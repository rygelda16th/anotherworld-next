#!/usr/bin/env python3
"""Gate C4 on the machine: does the Z80N reader draw what the reference reader does?

The reference reader is already proved against the engine call for call by
tools/checkreader.py. This takes the same inputs - a raw polygon segment and a list
of top-level draws, each one exactly what a bit-7 or bit-6 opcode computes - poked
into the machine, and compares the page it produces against the reference's, byte
for byte.

The segment goes into banked pages and is read through a two-page 16K window at
$0000, which is C6: a segment is addressed by a flat 16-bit offset and the largest
in the game is 65,230 bytes, so it cannot be mapped linearly into a 64K space that
also holds code.

Draws are chosen for zoom coverage, not taken in order: 97.4% of the intro's
polygons are at zoom 0x40, the identity, and a vector that did not go looking for
the rest would leave the zoom multiply untested.
"""
import os
import sys
import time
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zrcp import Zrcp  # noqa: E402
from refvideo import RefVideo8, RefVideo320, read_trace  # noqa: E402

# AW_WIDE=1: the 320x256 build (docs/plan-wide320.md W2): no scale, ten 8K column strips.
WIDE = bool(os.environ.get("AW_WIDE"))
REF = RefVideo320 if WIDE else RefVideo8

NEX, EXP = ("build/polytest320.nex", "build/polytest320.exp") if WIDE else ("build/polytest.nex", "build/polytest.exp")
PROBE = "preflight/hostprobe/probe"
W, H = (320, 200) if WIDE else (256, 192)
BANDS, BAND_BYTES = (10 if WIDE else 6), 8192
PAGE0_SEED = 0x0B
L2_BASE_BANK, DST_PAGE = 12, 1
DST_P0 = (L2_BASE_BANK + DST_PAGE * (5 if WIDE else 3)) * 2
NR_MMU3, NR_MMU0 = 0x53, 0x50
# Stage the poke through the READER'S OWN window at $0000, not through $C000.
# $C000 is where the program's generated tables and the draw list live, so paging
# a segment page in there wrote the draw list into the segment and paged the
# interpolation table out from under calc_step - which showed up as the machine
# finding 65 malformed records where the reference finds none.
WIN, SEG_STAGE = 0x6000, 0x0000
SEG_BASE = 48               # 8K page: clear of the 48K image and of Layer 2
CHUNK = 512
MAX_DRAWS = 64


def symbols(path):
    out = {}
    for line in open(path):
        name, _, val = line.partition(":")
        if "0x" in val:
            out[name.strip()] = int(val.split("0x")[1], 16)
    return out


def pick_draws(trace, limit):
    """Top-level draws chosen so the zoom multiply is actually exercised."""
    by_zoom, order = {}, []
    for kind, a in read_trace(trace):
        if kind == "part" and a["index"] != 0:
            break                       # one segment at a time
        if kind != "draw" or a["video2"]:
            continue
        by_zoom.setdefault(a["zoom"], []).append(a)
        order.append(a)
    picked, seen = [], Counter()
    # every distinct zoom first, then fill up in trace order
    for z in sorted(by_zoom):
        picked.append(by_zoom[z][0])
        seen[z] += 1
        if len(picked) >= limit:
            break
    for a in order:
        if len(picked) >= limit:
            break
        if seen[a["zoom"]] < 3:
            picked.append(a)
            seen[a["zoom"]] += 1
    return picked


def main():
    sym = symbols(EXP)
    seg = open(os.path.join(PROBE, "seg_cine_0.bin"), "rb").read()
    draws = pick_draws(os.path.join(PROBE, "trace.bin"), MAX_DRAWS)
    zooms = sorted({d["zoom"] for d in draws})
    print(f"segment: {len(seg):,} bytes, {(len(seg)+8191)//8192} pages of 8K")
    print(f"draws:   {len(draws)} chosen, {len(zooms)} distinct zooms "
          f"{zooms[:8]}{' ...' if len(zooms) > 8 else ''}")
    print(f"         {sum(1 for d in draws if d['zoom'] != 64)} of them at a zoom "
          f"other than the identity")

    # ---- what the reference produces ------------------------------------
    ref = REF()
    for i in range(ref.PAGE):
        ref.pages[0][i] = PAGE0_SEED
    ref.cur1 = 1
    for d in draws:
        ref.read_and_draw_polygon(seg, d["off"], d["colour"], d["zoom"],
                                  d["x"], d["y"])
    want = bytes(ref.pages[1])
    print(f"reference: {ref.n_polys:,} polygons, {ref.n_spans:,} spans, "
          f"deepest nesting {getattr(ref, 'n_reader_depth', 0)}, "
          f"{getattr(ref, 'n_reader_bad', 0)} malformed records")

    def render(n, plimit=0):
        """The reference's page 1 after n draws, at most plimit polygons."""
        r = REF()
        r.reader_limit = plimit
        for k in range(r.PAGE):
            r.pages[0][k] = PAGE0_SEED
        r.cur1 = 1
        for d in draws[:n]:
            r.read_and_draw_polygon(seg, d["off"], d["colour"], d["zoom"],
                                    d["x"], d["y"])
        return bytes(r.pages[1]), r

    z = Zrcp()
    print(f"\nemulator: {z.cmd('get-version')}")

    def run(n, plimit=0xFFFF):
        """Boot, poke the segment and the first n draws, read the page back."""
        z.cmd(f"smartload /work/{NEX}")
        time.sleep(4)
        z.cmd("set-memory-zone -1")
        npages = (len(seg) + 8191) // 8192
        for p in range(npages):
            z.cmd(f"tbblue-set-register {NR_MMU0} {SEG_BASE + p}")
            block = seg[p * 8192:(p + 1) * 8192]
            for o in range(0, len(block), CHUNK):
                z.cmd(f"write-memory-raw {SEG_STAGE + o} "
                      f"{block[o:o+CHUNK].hex()}")
        blob = bytearray()
        for d in draws[:n]:
            blob += int(d["off"]).to_bytes(2, "little")
            blob += bytes([d["colour"] & 0xFF])
            blob += int(d["zoom"]).to_bytes(2, "little")
            blob += int(d["x"] & 0xFFFF).to_bytes(2, "little")
            blob += int(d["y"] & 0xFFFF).to_bytes(2, "little")
        for o in range(0, len(blob), CHUNK):
            z.cmd(f"write-memory-raw {sym['rd_list'] + o} {blob[o:o+CHUNK].hex()}")
        z.cmd(f"write-memory {sym['seg_base']} {SEG_BASE}")
        z.cmd(f"write-memory {sym['read_mode']} 1")
        z.cmd(f"write-memory {sym['rd_count']} {n & 0xFF}")
        z.cmd(f"write-memory {sym['rd_count'] + 1} {n >> 8}")
        z.cmd(f"write-memory {sym['rd_plimit']} {plimit & 0xFF}")
        z.cmd(f"write-memory {sym['rd_plimit'] + 1} {plimit >> 8}")
        z.cmd(f"write-memory {sym['go']} 1")
        for _ in range(240):
            if z.cmd(f"read-memory {sym['done']} 1").strip().upper() == "5A":
                break
            time.sleep(0.25)
        else:
            raise SystemExit(f"FAIL: the reader never finished at n={n}")
        bad = int.from_bytes(bytes.fromhex(
            z.cmd(f"read-memory {sym['rd_bad']} 2").strip()), "little")
        deep = int.from_bytes(bytes.fromhex(
            z.cmd(f"read-memory {sym['rd_deep']} 2").strip()), "little")
        page = bytearray()
        for band in range(BANDS):
            z.cmd(f"tbblue-set-register {NR_MMU3} {DST_P0 + band}")
            addr, chunk = WIN, bytearray()
            while len(chunk) < BAND_BYTES:
                k = min(2048, BAND_BYTES - len(chunk))
                raw = z.cmd(f"read-memory {addr} {k}").strip()
                chunk += bytes.fromhex(raw)
                addr += k
            page += chunk[:BAND_BYTES]
        if WIDE:
            page = bytes(page[x * 256 + y] for y in range(H) for x in range(W))
        return bytes(page), bad, deep

    got, bad, deep = run(len(draws))
    print(f"the machine ran all {len(draws)} draws; records refused: "
          f"{bad} malformed, {deep} too deeply nested")

    # Verify the poked segment at SCATTERED offsets, not just at its start.
    # Checking the first bytes only proves the first write landed, and a poke that
    # goes wrong later is indistinguishable from a reader that misreads - which
    # cost a long detour hunting rounding faults in arithmetic that was right.
    import random
    rng = random.Random(1)
    probes = [0, 0x910, 0x924, len(seg) - 16] + \
             [rng.randrange(0, len(seg) - 16) for _ in range(12)]
    wrong = []
    for off in probes:
        z.cmd(f"tbblue-set-register {NR_MMU0} {SEG_BASE + (off >> 13)}")
        back = bytes.fromhex(z.cmd(f"read-memory {off & 0x1FFF} 16").strip())
        if back != seg[off:off + 16]:
            wrong.append((off, back, seg[off:off + 16]))
    print(f"segment verified at {len(probes)} scattered offsets: "
          + ("all correct" if not wrong else f"{len(wrong)} WRONG"))
    for off, gb, wb in wrong[:4]:
        print(f"  at {off:#07x}: machine {gb.hex(' ')}")
        print(f"                 host    {wb.hex(' ')}")
    if wrong:
        raise SystemExit("FAIL: the segment did not land correctly")

    if got == want:
        print(f"\nPASS: all {W*H:,} pixels identical to the reference, over "
              f"{len(draws)} draws\n      and {ref.n_polys:,} polygons the reader "
              f"found for itself.")
        z.close()
        return

    diff = [i for i in range(W * H) if got[i] != want[i]]
    print(f"\n{len(diff):,} of {W*H:,} pixels differ ({100*len(diff)/(W*H):.2f}%)")
    f0 = diff[0]
    print(f"  first at row {f0//W}, x {f0%W}: ours {got[f0]:#04x}, "
          f"reference {want[f0]:#04x}")

    # Bisect to the first draw that diverges. Comparing the finished page says
    # only that something is wrong; this says which draw, at which offset, at
    # which zoom - the same reason Gate C bisects on the polygon count.
    # Bisect on the POLYGON count across the whole run, not the draw count: one
    # draw makes up to 256 polygons and a page comparison after it says only that
    # one of them is wrong.
    total = ref.n_polys
    print(f"\n  bisecting over {total:,} polygons for the first that diverges...")
    lo, hi = 0, total
    while hi - lo > 1:
        mid = (lo + hi) // 2
        g, b, _ = run(len(draws), mid)
        ok = g == render(len(draws), mid)[0]
        print(f"    first {mid:>4} polygons: {'match' if ok else 'DIFFER'}")
        if ok:
            lo = mid
        else:
            hi = mid
    print(f"\n  FIRST BAD POLYGON is number {hi}")

    # Where, exactly. With only that polygon drawn the difference is small enough
    # to read, and a shape the Gate C vector does not contain can only be caught
    # here.
    g1, _, _ = run(len(draws), hi)
    w1, _ = render(len(draws), hi)
    d1 = [i for i in range(W * H) if g1[i] != w1[i]]
    print(f"    drawing only those {hi}: {len(d1):,} pixels differ")
    for i in d1[:10]:
        print(f"      row {i//W:>3} x {i%W:>3}: machine {g1[i]:#04x}  "
              f"reference {w1[i]:#04x}")
    if d1:
        rows = sorted({i // W for i in d1})
        cols = sorted({i % W for i in d1})
        print(f"    rows {rows[0]}..{rows[-1]}, columns {cols[0]}..{cols[-1]}")

    # which draw was it in, and what did the reference make of it
    seen = 0
    for k, d in enumerate(draws):
        _, rr2 = render(k + 1)
        if rr2.n_polys >= hi:
            print(f"    it is in draw {k}: offset {d['off']:#06x} colour "
                  f"{d['colour']:#04x} zoom {d['zoom']} at ({d['x']},{d['y']})")
            break

    d = draws[hi - 1]
    _, r = render(hi)
    _, rprev = render(hi - 1)

    # And then that polygon itself, field for field. With the limit set to its
    # number the machine stops with it in rd_record, so it can be compared
    # against the reference's own call - which says which field is wrong rather
    # than which pixels are.
    class Rec(REF):
        def __init__(self):
            super().__init__()
            self.calls = []

        def _draw_polygon(self, colour, ptx, pty, bbw, bbh, points):
            self.calls.append((colour, self.sx(ptx), self.sy(pty),
                               self.sx(bbw), self.sy(bbh),
                               [(self.sx(x), self.sy(y)) for x, y in points]))

    # The inputs, before any geometry: which record did the reader reach, with what
    # colour and centre? A wrong field in a built record and a wrong record
    # entirely look identical from the pixels.
    class Inp(REF):
        def __init__(self):
            super().__init__()
            self.inputs = []

        def read_and_draw_polygon(self, buf, off, colour, zoom, ptx, pty,
                                  depth=1):
            if off < len(buf) and buf[off] >= 0xC0:
                self.inputs.append((off, colour & 0xFF, ptx, pty))
            return super().read_and_draw_polygon(buf, off, colour, zoom,
                                                 ptx, pty, depth)

        def _draw_polygon(self, *a):
            pass

    ii = Inp()
    for d in draws[:2]:
        ii.read_and_draw_polygon(seg, d["off"], d["colour"], d["zoom"],
                                 d["x"], d["y"])
    run(2)
    raw = bytes.fromhex(z.cmd(f"read-memory {sym['rd_log']} {8*12}").strip())
    print("\n  leaves the reader reached, inputs as read:")
    print(f"    {'#':>3}  {'machine  off col   ptx   pty':<30}"
          f"{'reference  off col   ptx   pty'}")
    for k in range(min(10, len(ii.inputs))):
        o = k * 8
        m = (int.from_bytes(raw[o:o+2], 'little'), raw[o+2],
             int.from_bytes(raw[o+3:o+5], 'little', signed=True),
             int.from_bytes(raw[o+5:o+7], 'little', signed=True))
        w = ii.inputs[k]
        flag = "" if m == w else "   <-- DIFFERS"
        print(f"    {k+1:>3}  {m[0]:#07x} {m[1]:>3} {m[2]:>5} {m[3]:>5}"
              f"          {w[0]:#07x} {w[1]:>3} {w[2]:>5} {w[3]:>5}{flag}")

    rr = Rec()
    for d in draws:
        rr.read_and_draw_polygon(seg, d["off"], d["colour"], d["zoom"],
                                 d["x"], d["y"])
        if len(rr.calls) >= hi:
            break
    if len(rr.calls) >= hi:
        # The limit is hi - 1, NOT hi. The record is built in full and only then
        # tested against the limit, so a limit of N leaves polygon N+1 sitting in
        # rd_record. Setting it to hi compared polygon hi+1's fields against
        # polygon hi's and reported five wrong fields in code that was right.
        run(len(draws), hi - 1)
        raw = bytes.fromhex(z.cmd(f"read-memory {sym['rd_record']} 80").strip())
        want_c = rr.calls[hi - 1]
        gn = raw[9]
        got_f = (raw[0],
                 int.from_bytes(raw[1:3], "little", signed=True),
                 int.from_bytes(raw[3:5], "little", signed=True),
                 int.from_bytes(raw[5:7], "little", signed=True),
                 int.from_bytes(raw[7:9], "little", signed=True), gn)
        print(f"\n  polygon {hi}, field for field "
              f"(built with the limit at {hi-1}, so not drawn):")
        for name, g, w in zip(("colour", "ptx", "pty", "bbw", "bbh", "npoints"),
                              got_f,
                              (want_c[0], want_c[1], want_c[2], want_c[3],
                               want_c[4], len(want_c[5]))):
            print(f"    {name:<8} machine {g:>6}   reference {w:>6}"
                  + ("" if g == w else "   <-- WRONG"))
        gp = [(int.from_bytes(raw[10 + k * 4:12 + k * 4], "little", signed=True),
               int.from_bytes(raw[12 + k * 4:14 + k * 4], "little", signed=True))
              for k in range(min(gn, 16))]
        for k, (g, w) in enumerate(zip(gp, want_c[5])):
            if g != w:
                print(f"    point {k}: machine {g}, reference {w}   <-- WRONG")
                break
        else:
            print(f"    the first {len(gp)} points all match")

    print(f"\n  FIRST BAD DRAW is index {hi-1}:")
    print(f"    offset {d['off']:#06x}  colour {d['colour']:#04x}  "
          f"zoom {d['zoom']} ({d['zoom']/64:.3f}x)  at ({d['x']}, {d['y']})")
    print(f"    the reference makes {r.n_polys - rprev.n_polys} polygons of it, "
          f"nesting {getattr(r, 'n_reader_depth', 0)}")
    print(f"    its first segment bytes: {seg[d['off']:d['off']+12].hex(' ')}")
    z.close()
    raise SystemExit("FAIL: the machine's reader does not match the reference")


if __name__ == "__main__":
    main()
