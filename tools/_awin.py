import sys, time
sys.path.insert(0, "tools")
from zrcp import Zrcp
def symbols(*paths):
    out = {}
    for p in paths:
        for line in open(p):
            n, _, v = line.partition(":")
            if "0x" in v: out[n.strip()] = int(v.split("0x")[1], 16)
    return out
sym = symbols("build/aw.exp", "build/aw_vm_c.exp")
va = sym.get("_aw_vars") or sym.get("aw_vars")
print("aw_vars at", hex(va))
z = Zrcp(); z.cmd("smartload /work/build/aw.nex"); time.sleep(3.2)
z.cmd("set-memory-zone -1")
def rd(a,n):
    raw = z.cmd(f"read-memory {a} {n}").strip()
    return bytes(int(raw[i:i+2],16) for i in range(0,2*n,2))
hdr = (0).to_bytes(2,'little')+(600).to_bytes(2,'little')+(60000).to_bytes(2,'little')
z.cmd(f"write-memory-raw 0xC000 {hdr.hex()}")
z.cmd(f"write-memory-raw {sym['fname']} {(b'RES18.BIN'+bytes(1)).hex()}")
z.cmd(f"write-memory {sym['go']} 1")
for _ in range(100):
    if int.from_bytes(rd(0xC014,2),'little') != 0: break
    time.sleep(0.02)
z.cmd("write-memory-raw 0xC014 0000")
z.cmd("send-keys-event 128 1 nomenu")
for t in range(8):
    time.sleep(0.4)
    b = rd(0xC000, 24)
    print(f"  t={t*0.4:>4.1f} frames_done={int.from_bytes(b[8:10],'little'):>4} "
          f"fin={b[10]:#04x} flt={b[13]} recs={int.from_bytes(b[6:8],'little'):>4} "
          f"IN=${rd(0xC380,12).hex()} varFA={int.from_bytes(rd(va+0xFA*2,2),'little')} "
          f"varFE={int.from_bytes(rd(va+0xFE*2,2),'little')}")
z.cmd("send-keys-event 128 0 nomenu")
z.close()
