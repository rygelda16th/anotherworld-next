import sys, time
sys.path.insert(0, "tools")
from zrcp import Zrcp
def symbols(*paths):
    out={}
    for p in paths:
        for line in open(p):
            n,_,v=line.partition(":")
            if "0x" in v: out[n.strip()]=int(v.split("0x")[1],16)
    return out
sym=symbols("build/aw.exp","build/aw_vm_c.exp")
CTL=0xC000
z=Zrcp()
def rd(a,n):
    o=bytearray()
    while len(o)<n:
        k=min(2048,n-len(o)); raw=z.cmd(f"read-memory {a+len(o)} {k}").strip()
        o+=bytes(int(raw[i:i+2],16) for i in range(0,2*k,2))
    return bytes(o)
z.cmd("smartload /work/build/aw.nex"); time.sleep(3.2); z.cmd("set-memory-zone -1")
seed=next(int(l.split()[1])&0xFFFF for l in open("preflight/hostprobe/probe/ops.txt") if l.startswith("seed"))
z.cmd(f"write-memory-raw {CTL} {(seed.to_bytes(2,'little')+(45).to_bytes(2,'little')+(60000).to_bytes(2,'little')).hex()}")
z.cmd(f"write-memory-raw {sym['fname']} {(b'RES18.BIN'+bytes(1)).hex()}")
z.cmd(f"write-memory {sym['go']} 1")
for _ in range(400):
    if rd(CTL+10,1)[0]==0x5A: break
    time.sleep(0.05)
b=rd(CTL,32)
w=lambda o:int.from_bytes(b[o:o+2],'little')
print(f"  records {w(6)} frames {w(8)} fault {b[13]} fault_pc {w(14)} ctx {w(18):#06x}")
print(f"  n_mus {int.from_bytes(rd(sym['n_mus'],2),'little')} "
      f"miss {int.from_bytes(rd(sym['n_mus_miss'],2),'little')} "
      f"mus_res {rd(sym['mus_res'],1)[0]:#04x} page {rd(sym['mus_page'],1)[0]} "
      f"playing {rd(sym['mus_playing'],1)[0]}")
print(f"  n_load {int.from_bytes(rd(sym['n_load'],2),'little')} "
      f"next_page {rd(sym['next_page'],1)[0]} res_err {rd(sym['res_err'],1)[0]:#04x}")
print(f"  MMU: {z.cmd('get-registers').strip().split('MMU=')[-1]}")
print(f"  SP now {z.registers().get('SP'):#06x}")
z.close()
