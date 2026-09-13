import sys, time
sys.path.insert(0, "tools")
from zrcp import Zrcp
z = Zrcp()
print("VER:", z.cmd("get-version"))
for c in ("write-memory-raw 32768 aabbcc",
          "write-memory 32768 170 187 204",
          "write-memory-raw 32768 ddeeff"):
    print(f"--- {c!r}")
    print("   ->", repr(z.cmd(c)[:160]))
    print("   read:", z.cmd("read-memory 32768 3"))
