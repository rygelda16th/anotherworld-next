"""The stall is inside the polygon reader. Which draw, and how deep?

Every hot address sampled during the stall resolves to the reader or its zoom multiply, and
CTL_RECORDS stands still because aw_logrec fires BEFORE the opcode is dispatched - so a draw
that takes tens of seconds holds the count where it is. This reads the reader's own state
while it is in there.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zrcp import Zrcp                                       # noqa: E402
from checksave import symbols, NEX                          # noqa: E402

FRAMES_DONE, RECORDS = 0xC008, 0xC006
DRAW_BLOCK = 0xC390


def main():
    sym = symbols("build/aw.exp")
    z = Zrcp()

    def read(a, n):
        raw = z.cmd(f"read-memory {a} {n}").strip()
        return bytes(int(raw[i:i + 2], 16) for i in range(0, 2 * n, 2))

    def w(a):
        b = read(a, 2)
        return b[0] | (b[1] << 8)

    def sw(a):
        v = w(a)
        return v - 0x10000 if v >= 0x8000 else v

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
    print(f"  stalled at frame {last}, records={w(RECORDS)}")

    d = read(DRAW_BLOCK, 12)
    print(f"  DRAW_BLOCK: {' '.join(f'{b:02x}' for b in d)}")
    for label in range(3):
        print(f"  sample {label}: off={w(sym['rd_off']):#06x} col={read(sym['rd_col'], 1)[0]:#04x} "
              f"zoom={w(sym['rd_zoom']):<6} pt=({sw(sym['rd_ptx'])},{sw(sym['rd_pty'])}) "
              f"deep={read(sym['rd_deep'], 1)[0]:<4} bad={read(sym['rd_bad'], 1)[0]:#04x} "
              f"count={w(sym['rd_count'])} pcount={w(sym['rd_pcount'])} "
              f"plimit={w(sym['rd_plimit'])} stop={read(sym['rd_stop'], 1)[0]:#04x}")
        time.sleep(2.0)
    print(f"  n_poly-ish: selects={w(sym['n_select'])} blits={w(sym['n_load'])}")
    z.close()


if __name__ == "__main__":
    main()
