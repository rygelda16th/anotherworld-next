"""Part 2 loads 45 resources against a 40-page reservation. Did it run out?

The stall is the polygon reader walking garbage, and the cheapest explanation for garbage in
the cinematic segment is that the segment is not all there. res_full says whether the heap
reservation was exceeded; next_page says how far it got; and res_page says where each of part
2's four resources actually landed.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zrcp import Zrcp                                       # noqa: E402
from checksave import symbols, NEX                          # noqa: E402

FRAMES_DONE = 0xC008
RES_FIRST = None


def main():
    sym = symbols("build/aw.exp")
    z = Zrcp()

    def read(a, n):
        raw = z.cmd(f"read-memory {a} {n}").strip()
        return bytes(int(raw[i:i + 2], 16) for i in range(0, 2 * n, 2))

    def w(a):
        b = read(a, 2)
        return b[0] | (b[1] << 8)

    z.cmd(f"smartload /work/{NEX}")
    time.sleep(3.2)
    z.cmd("set-memory-zone -1")
    z.cmd(f"write-memory {sym['go']} 1")
    for _ in range(6):
        z.cmd("send-keys-event 128 1 nomenu")
        time.sleep(0.1)
        z.cmd("send-keys-event 128 0 nomenu")
        time.sleep(0.4)

    last, still = w(FRAMES_DONE), 0
    for _ in range(40):
        time.sleep(1.0)
        f = w(FRAMES_DONE)
        still = still + 1 if f == last else 0
        last = f
        if still >= 4:
            break

    pages = read(sym["res_page"], 256)
    print(f"  stalled at frame {last}")
    print(f"  res_full={read(sym['res_full'], 1)[0]:#04x}  "
          f"res_err={read(sym['res_err'], 1)[0]:#04x}  "
          f"next_page={read(sym['next_page'], 1)[0]}  "
          f"n_load={w(sym['n_load'])}  n_inval={w(sym['n_inval'])}")
    print(f"  cin_base={read(sym['cin_base'], 1)[0]}  "
          f"vid2_base={read(sym['vid2_base'], 1)[0]}  "
          f"code page={read(sym['code_add'] + 1, 1)[0]}")
    for name, rid in (("palette", 0x1a), ("bytecode", 0x1b),
                      ("cinematic", 0x1c), ("video2", 0x11)):
        print(f"    part 2 {name:<10} {rid:#04x} -> page {pages[rid]}")
    resident = [i for i in range(0x92) if pages[i]]
    print(f"  {len(resident)} resources resident: "
          + " ".join(f"{i:#04x}@{pages[i]}" for i in resident[:24]))
    z.close()


if __name__ == "__main__":
    main()
