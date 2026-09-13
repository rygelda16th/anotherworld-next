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
z = Zrcp(); z.cmd("smartload /work/build/aw.nex"); time.sleep(3.0)
z.cmd("set-memory-zone -1")
def rd(a,n):
    raw = z.cmd(f"read-memory {a} {n}").strip()
    return bytes(int(raw[i:i+2],16) for i in range(0,2*n,2))
print("ticks:", int.from_bytes(rd(sym['ticks'],2),'little'))
print("voltab $DC00[0:16]:", rd(0xDC00,16).hex())
print("voltab $DC00[64:80]:", rd(0xDC40,16).hex())
print("voice0 $DD00[0:12]:", rd(0xDD00,12).hex())
print("sample $DE00[0:16]:", rd(0xDE00,16).hex())
print("ring   $D400[0:16]:", rd(0xD400,16).hex())
print("ring   $D480[0:16]:", rd(0xD480,16).hex())
for n in ("blocklen","mix_dst","ring_wr"):
    if n in sym:
        print(f"  {n} = {rd(sym[n], 2).hex()}")
z.close()
