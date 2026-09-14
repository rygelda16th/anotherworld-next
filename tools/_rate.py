"""How fast does part 2 actually run, and is it running at all?

The first playthrough probe reported 46 frames in 138 seconds and read 256 bytes of res_page
every second to work out which part was live. Two candidates for that rate and they need
separating: the machine is slow, or the probe is standing on it. This reads TWO BYTES per
sample and taps fire only at the start, to skip the intro.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zrcp import Zrcp                                       # noqa: E402
from checksave import symbols, NEX                          # noqa: E402

FRAMES_DONE, FINISHED, OUT_OF_BUDGET, BAD_OP, FAULT, FAULT_PC = (
    0xC008, 0xC00A, 0xC00B, 0xC00C, 0xC00D, 0xC00E)


def main():
    sym = symbols("build/aw.exp")
    sym.update(symbols("build/aw_vm_c.exp"))
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

    for _ in range(6):                  # skip the intro cinematic
        z.cmd("send-keys-event 128 1 nomenu")
        time.sleep(0.1)
        z.cmd("send-keys-event 128 0 nomenu")
        time.sleep(0.4)

    print("  sampling frames_done alone, every 3s, with no other traffic:")
    last, t_last = w(FRAMES_DONE), time.time()
    for i in range(20):
        time.sleep(3.0)
        f, now = w(FRAMES_DONE), time.time()
        print(f"    t={now - t_last:5.1f}s step  frames={f:<6} (+{f - last:<4}) "
              f"= {(f - last) / (now - t_last):5.2f}/s")
        last, t_last = f, now

    print(f"\n  blits={w(sym['_aw_blits'])} selects={w(sym['n_select'])} "
          f"loads={w(sym['n_load'])} invalidations={w(sym['n_inval'])} "
          f"bitmaps={w(sym['n_bmp'])} strings={w(sym['n_str'])} "
          f"missing strings={w(sym['n_str_miss'])}")
    print(f"  CTL_FINISHED={read(FINISHED, 1)[0]:#04x} "
          f"OUT_OF_BUDGET={read(OUT_OF_BUDGET, 1)[0]:#04x} "
          f"FAULT={read(FAULT, 1)[0]:#04x} BAD_OP={read(BAD_OP, 1)[0]:#04x} "
          f"pc={w(FAULT_PC):#06x}")
    z.close()


if __name__ == "__main__":
    main()
