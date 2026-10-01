"""Does part 5's frame FINISH? "Slow" and "stalled" are different claims.

The reference draws 27,531 polygons in the worst frame of part 5 - twenty-nine times the worst
of any other part - and the machine draws them correctly, just not quickly. If it is slow, the
frame counter eventually moves. If it is stuck, it never does.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zrcp import Zrcp                                       # noqa: E402
from checksave import symbols, NEX, EXP                          # noqa: E402

PART, FRAMES_DONE, RECORDS = 5, 0xC008, 0xC006


def main():
    sym = symbols(EXP)
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
    z.cmd(f"write-memory {sym['start_part']} {PART + 1}")
    z.cmd(f"write-memory {sym['go']} 1")

    t0, last_f, last_p = time.time(), 0, 0
    for _ in range(30):
        time.sleep(4.0)
        f, p, r = w(FRAMES_DONE), w(sym["rd_pcount"]), w(RECORDS)
        print(f"    t={time.time() - t0:5.0f}s  frames={f:<5} (+{f - last_f}) "
              f"polygons={p:<8,} (+{p - last_p:,} = {(p - last_p) / 4:,.0f}/s)  records={r}")
        last_f, last_p = f, p
    print(f"\n  {last_f} frames in {time.time() - t0:.0f}s. "
          + ("the frames DO advance - part 5 is slow, not stuck"
             if last_f > 2 else "still on the same frame - it is stuck, not merely slow"))
    z.close()


if __name__ == "__main__":
    main()
