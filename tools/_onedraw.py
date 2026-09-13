import sys, time
sys.path.insert(0, "tools")
from zrcp import Zrcp
from refvideo import RefVideo8

OFF, ZOOM, X, Y, COL = 2096, 64, 192, 59, 0xFF
W, PAGE = 256, 256 * 192
def symbols(*paths):
    out = {}
    for p in paths:
        for line in open(p):
            n, _, v = line.partition(":")
            if "0x" in v: out[n.strip()] = int(v.split("0x")[1], 16)
    return out
sym = symbols("build/aw.exp", "build/aw_vm_c.exp")

import os
FILL = int(os.environ.get("AW_FILL", "-1"))     # -1 = leave page 0 blank
ref = RefVideo8(); ref.cur1 = 0
if FILL >= 0:
    ref.fill_page(0, FILL)
ref.cur1 = 0
ref.read_and_draw_polygon(open("build/assets/RES19.BIN","rb").read(), OFF, COL, ZOOM, X, Y)
want = bytes(ref.pages[0])

z = Zrcp()
def read(a, n):
    out = bytearray()
    while len(out) < n:
        k = min(2048, n - len(out))
        raw = z.cmd(f"read-memory {a+len(out)} {k}").strip()
        out += bytes(int(raw[i:i+2],16) for i in range(0,2*k,2))
    return bytes(out)
z.cmd("smartload /work/build/aw.nex"); time.sleep(3.2)
z.cmd("set-memory-zone -1")
blk = (OFF.to_bytes(2,"little") + ZOOM.to_bytes(2,"little")
       + X.to_bytes(2,"little",signed=True) + Y.to_bytes(2,"little",signed=True)
       + bytes([COL, 0]))
z.cmd(f"write-memory-raw 50064 {blk.hex()}")          # DRAW_BLOCK = $C390
z.cmd(f"write-memory {sym['pg_ptr1']} 0")
z.cmd(f"write-memory {sym['probe_draw']} 1")
z.cmd(f"write-memory {sym['probe_fill']} {0 if FILL < 0 else FILL + 1}")
z.cmd(f"write-memory-raw {sym['fname']} {(b'RES18.BIN'+bytes(1)).hex()}")
z.cmd(f"write-memory {sym['go']} 1")
for _ in range(400):
    if read(sym["done"], 1)[0] == 0x5A: break
    time.sleep(0.05)
got = bytearray()
for band in range(6):
    z.cmd(f"tbblue-set-register 87 {24+band}")
    got += read(0xE000, 8192)
got = bytes(got[:PAGE])
d = [i for i in range(PAGE) if got[i] != want[i]]
print(f"one record through the reader, no VM, page 0 "
      f"{'blank' if FILL < 0 else f'filled with {FILL}'}: off={OFF} zoom={ZOOM} x={X} y={Y} col={COL:#04x}")
print(f"  n_poly={int.from_bytes(read(sym['n_poly'],2),'little')}, "
      f"rd_bad={int.from_bytes(read(sym['rd_bad'],2),'little')}, "
      f"rd_deep={int.from_bytes(read(sym['rd_deep'],2),'little')}")
if not d:
    print("  IDENTICAL to the reference -> the READER is right on this record, so the")
    print("  fault is in how aw_draw_poly sets it up when the VM drives it")
else:
    print(f"  {len(d):,} bytes differ, first at row {d[0]//W} x {d[0]%W}: "
          f"ours {got[d[0]]:#04x} reference {want[d[0]]:#04x}")
    print("  -> the READER itself gets this record wrong, with no VM involved")
z.close()
