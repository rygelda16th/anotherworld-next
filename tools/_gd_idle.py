#!/usr/bin/env python3
"""Does the machine survive doing NOTHING? Boot vmtest, never set go, watch PC."""
import sys, time
sys.path.insert(0, "tools")
from zrcp import Zrcp
z = Zrcp()
z.cmd("smartload /work/build/vmtest.nex")
time.sleep(3.5)
z.cmd("set-memory-zone -1")
for t in range(12):
    r = z.registers()
    print(f"  t={t*1.0:>4.1f}s  PC={r.get('PC',0):#06x} SP={r.get('SP',0):#06x} "
          f"MMU={z.cmd('tbblue-get-register 80').strip()[:2]}")
    time.sleep(1.0)
z.close()
