#!/usr/bin/env python3
"""Which draw first puts a wrong pixel on the page? (make bisect-draw)

The companion to check-draw. check-draw says the pages differ; this says which record did
it, which is the only useful form of the answer - one wrong record poisons everything
drawn after it, so the finished page can never name the culprit.

It found, on its first run: with NO draws the pages are IDENTICAL, so the fills and the
copies are right. With ONE draw, 2,756 bytes differ. And check-draw had already proved
that draw's operands identical to the engine's - off=2096, zoom=64, x=192, y=59,
colour=$FF. So the inputs agree, the destination page agrees, and the pixels do not.

One wrong record poisons everything drawn after it, so the finished page can never say
which one it was. Both sides stop after the same numbered draw and the page is compared;
binary search over that number finds the first divergence.
"""
import os, sys, time
sys.path.insert(0, "tools")
from zrcp import Zrcp
from refvideo import RefVideo8, replay, read_trace

CTL, W, H = 0xC000, 256, 192
PAGE = W * H
NR_MMU7, DWIN = 0x57, 0xE000

def symbols(*paths):
    out = {}
    for p in paths:
        for line in open(p):
            n, _, v = line.partition(":")
            if "0x" in v: out[n.strip()] = int(v.split("0x")[1], 16)
    return out

sym = symbols("build/aw.exp", "build/aw_vm_c.exp")
trace = "preflight/hostprobe/probe/trace.bin"
seed = next(int(l.split()[1]) & 0xFFFF
            for l in open("preflight/hostprobe/probe/ops.txt") if l.startswith("seed"))
total = sum(1 for k, _ in read_trace(trace) if k == "draw")
print(f"the trace holds {total} draw records, seed {seed}")

z = Zrcp()
def read(a, n):
    out = bytearray()
    while len(out) < n:
        k = min(2048, n - len(out))
        raw = z.cmd(f"read-memory {a + len(out)} {k}").strip()
        out += bytes(int(raw[i:i+2], 16) for i in range(0, 2 * k, 2))
    return bytes(out)

def machine(n):
    """Page 0 after the machine's first n draws."""
    z.cmd("smartload /work/build/aw.nex")
    time.sleep(3.2)
    z.cmd("set-memory-zone -1")
    hdr = seed.to_bytes(2,"little") + (2000).to_bytes(2,"little") + (60000).to_bytes(2,"little")
    z.cmd(f"write-memory-raw {CTL} {hdr.hex()}")
    z.cmd(f"write-memory-raw {sym['fname']} {(b'RES18.BIN'+bytes(1)).hex()}")
    z.cmd(f"write-memory-raw {sym['stop_draw']} {n.to_bytes(2,'little').hex()}")
    import os
    z.cmd(f"write-memory {sym['snd_off']} {os.environ.get('AW_SND_OFF', '0')}")
    z.cmd(f"write-memory {sym['go']} 1")
    for _ in range(600):
        if read(CTL + 10, 1)[0] == 0x5A: break
        time.sleep(0.05)
    got = int.from_bytes(read(sym["n_poly"], 2), "little")
    pages = []
    for pg in range(4):
        out = bytearray()
        for band in range(6):
            z.cmd(f"tbblue-set-register {NR_MMU7} {(12 + pg * 3) * 2 + band}")
            out += read(DWIN, 8192)
        pages.append(bytes(out[:PAGE]))
    return got, pages

def same(n):
    """ALL FOUR pages, not just page 0 - a copy that goes wrong leaves page 0 perfect and
    the fault somewhere the comparison was not looking."""
    got, mp = machine(n)
    ref, _ = replay(trace, cls=RefVideo8, stop_draws=n)
    ds = [sum(1 for i in range(PAGE) if mp[p][i] != bytes(ref.pages[p])[i])
          for p in range(4)]
    print(f"  after {n:>3} draws (machine dispatched {got}): "
          + ("all four identical" if not any(ds)
             else "  ".join(f"p{p}={d:,}" for p, d in enumerate(ds) if d)))
    return not any(ds), mp[0], bytes(ref.pages[0])

lo, hi = 0, min(total, 55)
ok, _, _ = same(hi)
if ok:
    print(f"\nno divergence in the first {hi} draws")
    z.close(); raise SystemExit(0)
ok, _, _ = same(lo)
if not ok:
    print("\nthey differ with NO draws at all - the fills or the copies, not a polygon")
    z.close(); raise SystemExit(0)
while hi - lo > 1:
    mid = (lo + hi) // 2
    ok, _, _ = same(mid)
    if ok: lo = mid
    else: hi = mid
print(f"\n  THE FIRST DIVERGENT DRAW IS {hi}")
_, mp, rp = same(hi)
diff = [i for i in range(PAGE) if mp[i] != rp[i]]
print(f"  {len(diff):,} bytes, first at row {diff[0]//W} x {diff[0]%W}: "
      f"ours {mp[diff[0]]:#04x} engine {rp[diff[0]]:#04x}")
rows = sorted({i // W for i in diff})
print(f"  rows {rows[0]}..{rows[-1]}, {len(rows)} of {H}")
z.close()
