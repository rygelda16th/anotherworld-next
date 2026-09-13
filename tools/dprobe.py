import sys, time
sys.path.insert(0,"tools")
from zrcp import Zrcp
def syms(*ps):
    o={}
    for p in ps:
        for l in open(p):
            n,_,v=l.partition(":")
            if "0x" in v: o[n.strip()]=int(v.split("0x")[1],16)
    return o
s=syms("build/vmtest.exp","build/vm_c.exp")
want=[]
for l in open("preflight/hostprobe/probe/ops.txt"):
    f=l.split()
    if f[0]=="thread": want.append(("thread",int(f[2]),int(f[3]),0))
    elif f[0]=="op": want.append(("op",int(f[2]),int(f[3]),int(f[4])))
print("host records:", len(want))
for budget in (200, 800, 2000):
    z=Zrcp()
    z.cmd("smartload /work/build/vmtest.nex"); time.sleep(3.5)
    z.cmd("set-memory-zone -1")
    z.cmd("write-memory-raw %d %s" % (s["fname"], (b"RES18.BIN"+bytes([0])).hex()))
    for nm,v in (("aw_seed",34032),("aw_frames",40),("aw_budget",budget)):
        z.cmd("write-memory %d %d" % (s[nm], v & 0xFF))
        z.cmd("write-memory %d %d" % (s[nm]+1, v >> 8))
    z.cmd("write-memory %d 1" % s["go"])
    ok=False
    for _ in range(600):
        if z.cmd("read-memory %d 1" % s["done"]).strip().upper()=="5A": ok=True; break
        time.sleep(0.05)
    def w(n): return int.from_bytes(bytes.fromhex(z.cmd("read-memory %d 2" % s[n]).strip()),"little")
    def b1(n): return int(z.cmd("read-memory %d 1" % s[n]).strip(),16)
    nrec=w("aw_records")
    raw=bytes.fromhex(z.cmd("read-memory %d %d" % (s["log_buf"], min(nrec+4,2048)*4)).strip())
    n=0
    while n*4+3 < len(raw) and raw[n*4] in (1,2): n+=1
    cur=0; got=[]
    for k in range(n):
        kind,lo,hi,v = raw[k*4:k*4+4]
        pc=lo|(hi<<8)
        if kind==2: cur=v; got.append(("thread",cur,pc,0))
        else: got.append(("op",cur,pc,v))
    m=0
    while m<min(len(got),len(want)) and got[m]==want[m]: m+=1
    print("budget=%-5d done=%-5s finished=%s oob=%s frames=%-3d records=%-4d written=%-4d matched=%-4d bad_op=%s"
          % (budget, ok, b1("aw_finished"), b1("aw_out_of_budget"), w("aw_frames_done"),
             nrec, n, m, b1("aw_bad_op")))
    if m < min(len(got),len(want)):
        print("      first difference: machine %s   engine %s" % (got[m], want[m]))
    z.close()
