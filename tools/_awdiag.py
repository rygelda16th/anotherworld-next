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
CTL = 0xC000
z = Zrcp()
z.cmd("smartload /work/build/aw.nex"); time.sleep(3.5)
z.cmd("set-memory-zone -1")
def rd(a, n):
    raw = z.cmd(f"read-memory {a} {n}").strip()
    return bytes(int(raw[i:i+2],16) for i in range(0,2*n,2))
print("ready:", rd(sym['ready'],1).hex(), " PC before go:", f"{z.registers().get('PC',0):#06x}")
hdr = (42307).to_bytes(2,'little') + (45).to_bytes(2,'little') + (20000).to_bytes(2,'little')
z.cmd(f"write-memory-raw {CTL} {hdr.hex()}")
z.cmd(f"write-memory-raw {sym['fname']} {(b'RES18.BIN'+bytes(1)).hex()}")
z.cmd(f"write-memory {sym['go']} 1")
for t in range(10):
    time.sleep(0.4)
    r = z.registers()
    b = rd(CTL, 24)
    print(f"  t={t*0.4:>4.1f} PC={r.get('PC',0):#06x} SP={r.get('SP',0):#06x} "
          f"ticks={int.from_bytes(rd(sym['ticks'],2),'little'):>5} "
          f"err={rd(sym['err'],1).hex()} got={int.from_bytes(rd(sym['got'],2),'little'):>6} "
          f"recs={int.from_bytes(b[6:8],'little'):>4} fin={b[10]:#04x} flt={b[13]} "
          f"IFF={'on' if 'IFF1' in z.cmd('get-registers') else '?'}")
print("regs:", z.cmd("get-registers").strip())
z.close()
