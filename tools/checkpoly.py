#!/usr/bin/env python3
"""Gate C: is the machine's rasteriser pixel-exact against the reference?

Runs src/polytest.asm, which draws the 57 coverage polygons from
build/polytest.inc into Layer 2 page 1 and stops. Then reads all six 8K bands
of that page back over ZRCP and compares the 49,152 bytes against
build/expected.bin, which tools/refvideo.py produced from the same polygons.

No tolerance: the reference is the specification.

When it fails it says WHERE, because "5,000 bytes differ" is not a diagnosis.
It reports the first differing pixel, how the differences cluster by row and by
value, and writes three PNGs - ours, the reference, and a difference mask - since
a rasteriser fault usually has a recognisable shape.
"""

import os
import sys
import time
import zlib
import struct

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zrcp import Zrcp  # noqa: E402
from refvideo import RefVideo8, RefVideo320  # noqa: E402

# AW_WIDE=1: the 320x256 build (docs/plan-wide320.md W2). Its page is ten 8K strips of 32 columns,
# column-major (x * 256 + y), and is turned back into 320x200 rows before it is compared.
WIDE = bool(os.environ.get("AW_WIDE"))
NEX = "build/polytest320.nex" if WIDE else "build/polytest.nex"
EXP = "build/polytest320.exp" if WIDE else "build/polytest.exp"
EXPECTED = "build/expected320.bin" if WIDE else "build/expected.bin"
W, H = (320, 200) if WIDE else (256, 192)
BANDS = 10 if WIDE else 6
BAND_BYTES = 8192
PAGE0_SEED = 0x0B
L2_BASE_BANK = 12
DST_PAGE = 1
DST_P0 = (L2_BASE_BANK + DST_PAGE * (5 if WIDE else 3)) * 2      # first 8K page of the target
NR_MMU3 = 0x53
WIN = 0x6000

# A palette just for the diff images: the 16 game indices as distinguishable
# greys and hues, plus red for "differs". Not the game's palette - this is a
# debugging aid, not a screenshot.
VIEW = [(0, 0, 0), (40, 40, 60), (80, 60, 40), (60, 90, 60),
        (120, 60, 60), (60, 120, 130), (150, 120, 60), (170, 170, 170),
        (70, 70, 90), (110, 90, 70), (90, 130, 90), (160, 90, 90),
        (90, 160, 175), (200, 170, 90), (220, 220, 220), (255, 255, 255)]


def write_png(path, width, height, rgb_rows):
    raw = bytearray()
    for row in rgb_rows:
        raw.append(0)
        raw += row

    def chunk(tag, payload):
        return (struct.pack(">I", len(payload)) + tag + payload
                + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF))

    with open(path, "wb") as fh:
        fh.write(b"\x89PNG\r\n\x1a\n")
        fh.write(chunk(b"IHDR", struct.pack(">2I5B", width, height, 8, 2, 0, 0, 0)))
        fh.write(chunk(b"IDAT", zlib.compress(bytes(raw), 9)))
        fh.write(chunk(b"IEND", b""))


def as_rows(buf, diff=None):
    rows = []
    for y in range(H):
        row = bytearray()
        for x in range(W):
            i = y * W + x
            if diff is not None and i in diff:
                row += bytes((255, 0, 0))
            else:
                row += bytes(VIEW[buf[i] & 0x0F])
        rows.append(row)
    return rows


def symbols(path):
    out = {}
    for line in open(path):
        name, _, val = line.partition(":")
        if "0x" in val:
            out[name.strip()] = int(val.split("0x")[1], 16)
    return out


def load_polys(path):
    """The polygon list mkpolytest wrote, unscaled, in draw order."""
    out = []
    for line in open(path):
        if line.startswith("#") or not line.strip():
            continue
        f = line.split()
        colour, px, py, bbw, bbh, n = (int(v) for v in f[1:7])
        nums = [int(v) for v in f[7:7 + 2 * n]]
        pts = list(zip(nums[0::2], nums[1::2]))
        out.append((f[0], colour, px, py, bbw, bbh, pts))
    return out


def render(polys, limit, seed):
    """The reference's page 1 after drawing the first `limit` polygons."""
    v = RefVideo320() if WIDE else RefVideo8()
    for i in range(v.PAGE):
        v.pages[0][i] = seed
    v.cur1 = 1
    for _, colour, px, py, bbw, bbh, pts in polys[:limit]:
        v.fill_polygon_scaled(colour, px, py, bbw, bbh, pts)
    return bytes(v.pages[1])


def run_machine(z, sym, limit, settle=4.0):
    """Boot the program with a polygon limit and read the target page back."""
    z.cmd(f"smartload /work/{NEX}")
    time.sleep(settle)
    z.cmd("set-memory-zone -1")
    z.cmd(f"write-memory {sym['poly_limit']} {limit}")
    z.cmd(f"write-memory {sym['go']} 1")
    for _ in range(60):
        if z.cmd(f"read-memory {sym['done']} 1").strip() == "5A":
            break
        time.sleep(0.25)
    else:
        raise SystemExit(f"FAIL: never finished with a limit of {limit}")
    got = bytearray()
    for band in range(BANDS):
        z.cmd(f"tbblue-set-register {NR_MMU3} {DST_P0 + band}")
        addr, chunk = WIN, bytearray()
        while len(chunk) < BAND_BYTES:
            n = min(2048, BAND_BYTES - len(chunk))
            raw = z.cmd(f"read-memory {addr} {n}").strip()
            chunk += bytes(int(raw[i:i + 2], 16) for i in range(0, len(raw), 2))
            addr += n
        got += chunk[:BAND_BYTES]
    if WIDE:
        return bytes(got[x * 256 + y] for y in range(H) for x in range(W))
    return bytes(got)


def check_calc_step(z, sym):
    """The calc_step unit test's results, which nothing was reading.

    The program runs 576 cases before it draws anything and leaves the answers in
    cs_results. That has been true for a while and NO checker read them back, so
    the "exhaustive at 648 of 648" claim rested on a run nobody repeated. An
    unchecked test is not a test.

    It matters more since the widening: calc_step's product went from 8x16 to
    16x16, assembled out of four MUL D,E and three shifted accumulations, which is
    exactly the kind of code that is plausible and wrong.
    """
    cases = []
    for line in open("build/csteps.txt"):
        f = line.split()
        cases.append((int(f[0]), int(f[1]), int(f[2]), int(f[3]),
                      int(f[4]), int(f[5])))
    if z.cmd(f"read-memory {sym['cs_done']} 1").strip().upper() != "C5":
        raise SystemExit("FAIL: the calc_step self-test never finished")

    base = sym["cs_results"]
    n = len(cases)
    raw = bytearray()
    addr = base
    left = n * 6
    while left:
        k = min(2048, left)
        h = z.cmd(f"read-memory {addr} {k}").strip()
        raw += bytes(int(h[i:i + 2], 16) for i in range(0, len(h), 2))
        addr += k
        left -= k

    bad = []
    for i, (p1x, p1y, p2x, p2y, step, dy) in enumerate(cases):
        o = i * 6
        gstep = int.from_bytes(raw[o:o + 4], "little")
        gdy = int.from_bytes(raw[o + 4:o + 6], "little")
        if gstep != step or gdy != (dy & 0xFFFF):
            bad.append((i, (p1x, p1y, p2x, p2y), gstep, step, gdy, dy))
    print(f"calc_step: {n - len(bad)} of {n} cases exact"
          + ("" if not bad else f"   {len(bad)} WRONG"))
    if bad:
        for i, pts, gs, ws, gd, wd in bad[:6]:
            print(f"  case {i} p1=({pts[0]},{pts[1]}) p2=({pts[2]},{pts[3]}): "
                  f"step {gs:#010x} want {ws:#010x}, dy {gd} want {wd}")
        wide = sum(1 for b in bad if max(b[1]) > 255)
        print(f"  {wide} of {len(bad)} involve a coordinate above 255, so the "
              f"widened multiply is {'implicated' if wide else 'not implicated'}")
        raise SystemExit("FAIL: calc_step does not match the reference")


def main():
    want = open(EXPECTED, "rb").read()
    if len(want) != W * H:
        raise SystemExit(f"{EXPECTED} is {len(want)} bytes, expected {W*H}")
    sym = symbols(EXP)

    polys = load_polys("build/polytest320.txt" if WIDE else "build/polytest.txt")
    z = Zrcp()
    print(f"emulator: {z.cmd('get-version')}")
    # The unit test runs before the draw, so check it before believing any pixel.
    z.cmd(f"smartload /work/{NEX}")
    time.sleep(4)
    z.cmd("set-memory-zone -1")
    check_calc_step(z, sym)

    got = run_machine(z, sym, len(polys), settle=5.0)
    print(f"the machine drew all {len(polys)} polygons\n")

    if got == want:
        print(f"\nPASS: all {W*H:,} pixels identical to the reference.")
        return

    diff = [i for i in range(W * H) if got[i] != want[i]]
    print(f"\n{len(diff):,} of {W*H:,} pixels differ "
          f"({100*len(diff)/(W*H):.2f}%)")
    f = diff[0]
    print(f"  first at pixel {f}: row {f//W}, x {f%W} - "
          f"ours {got[f]:#04x}, reference {want[f]:#04x}")
    rows = sorted({i // W for i in diff})
    print(f"  rows affected: {len(rows)} of {H}  ({rows[0]}..{rows[-1]})")
    cols = sorted({i % W for i in diff})
    print(f"  columns affected: {len(cols)} of {W}  ({cols[0]}..{cols[-1]})")
    import collections
    pairs = collections.Counter((got[i], want[i]) for i in diff)
    print("  most common (ours, reference) pairs:")
    for (a, b), n in pairs.most_common(6):
        print(f"    {a:#04x} vs {b:#04x}   {n:,}")
    # A cluster entirely inside one band points at the MMU window rather than
    # the walk, which is worth separating early.
    bands = sorted({(i // W) // 32 for i in diff})
    print(f"  bands affected: {bands} of {list(range(BANDS))}")

    # Bisect to the FIRST polygon that diverges. One wrong shape at index 3
    # pollutes everything drawn after it, so the last image cannot say which.
    print("\n  bisecting for the first polygon that diverges...")
    lo, hi = 0, len(polys)          # lo always matches, hi always differs
    while hi - lo > 1:
        mid = (lo + hi) // 2
        g = run_machine(z, sym, mid)
        ok = g == render(polys, mid, PAGE0_SEED)
        print(f"    first {mid:>3} polygons: {'match' if ok else 'DIFFER'}")
        if ok:
            lo = mid
        else:
            hi = mid
    bad = polys[hi - 1]
    kind, colour, px, py, bbw, bbh, pts = bad
    print(f"\n  FIRST BAD POLYGON is index {hi-1}: bucket '{kind}'")
    print(f"    colour {colour:#04x}  centre ({px}, {py})  box {bbw}x{bbh}  "
          f"{len(pts)} points")
    print(f"    scaled: centre ({RefVideo8.sx(px)}, {RefVideo8.sy(py)})  "
          f"box {RefVideo8.sx(bbw)}x{RefVideo8.sy(bbh)}")
    print(f"    points: {pts[:8]}{' ...' if len(pts) > 8 else ''}")
    z.close()

    os.makedirs("build/diff", exist_ok=True)
    write_png("build/diff/ours.png", W, H, as_rows(got))
    write_png("build/diff/reference.png", W, H, as_rows(want))
    write_png("build/diff/diff.png", W, H, as_rows(want, set(diff)))
    print("\n  wrote build/diff/ours.png, reference.png and diff.png")
    raise SystemExit("FAIL: the machine does not match the reference")


if __name__ == "__main__":
    main()
