import sys, time, collections
sys.path.insert(0, "tools")
from zrcp import Zrcp
from refvideo import RefVideo8, replay
CTL, PAGE, NR_MMU7, DWIN = 0xC000, 256*192, 0x57, 0xE000
def symbols(*paths):
    out={}
    for p in paths:
        for line in open(p):
            n,_,v=line.partition(":")
            if "0x" in v: out[n.strip()]=int(v.split("0x")[1],16)
    return out
sym=symbols("build/aw.exp","build/aw_vm_c.exp")
seed=next(int(l.split()[1])&0xFFFF for l in open("preflight/hostprobe/probe/ops.txt") if l.startswith("seed"))
z=Zrcp()
def read(a,n):
    o=bytearray()
    while len(o)<n:
        k=min(2048,n-len(o)); raw=z.cmd(f"read-memory {a+len(o)} {k}").strip()
        o+=bytes(int(raw[i:i+2],16) for i in range(0,2*k,2))
    return bytes(o)
z.cmd("smartload /work/build/aw.nex"); time.sleep(3.2); z.cmd("set-memory-zone -1")
hdr=seed.to_bytes(2,"little")+(2000).to_bytes(2,"little")+(60000).to_bytes(2,"little")
z.cmd(f"write-memory-raw {CTL} {hdr.hex()}")
z.cmd(f"write-memory-raw {sym['fname']} {(b'RES18.BIN'+bytes(1)).hex()}")
z.cmd(f"write-memory-raw {sym['stop_draw']} 0000")
z.cmd(f"write-memory {sym['go']} 1")
for _ in range(400):
    if read(CTL+10,1)[0]==0x5A: break
    time.sleep(0.05)
out=bytearray()
for band in range(6):
    z.cmd(f"tbblue-set-register {NR_MMU7} {24+band}")
    out+=read(DWIN,8192)
p0=bytes(out[:PAGE])
c=collections.Counter(p0)
print("machine page 0 just before draw 1:", dict(c.most_common(6)))
ref,_=replay("preflight/hostprobe/probe/trace.bin",cls=RefVideo8,stop_draws=0)
print("reference page 0 at the same point:", dict(collections.Counter(bytes(ref.pages[0])).most_common(6)))
print("  dst_p0=",read(sym['dst_p0'],1)[0]," pg_ptr1=",read(sym['pg_ptr1'],1)[0],
      " src_p0=",read(sym['src_p0'],1)[0]," cur_band=",read(sym['cur_band'],1)[0])
z.close()
