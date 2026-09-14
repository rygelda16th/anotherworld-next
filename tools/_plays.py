"""Does the shipped image play? Nothing is poked but `go`.

Every gate so far has had to poke a frame count and an opcode budget in before the VM would
move, because the image ships the control block zeroed and zero meant "no frames" and "no
opcodes". This boots exactly what a Next would load off the SD card and watches the counters.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zrcp import Zrcp                                       # noqa: E402
from checksave import symbols, NEX                          # noqa: E402

FRAMES_DONE, FINISHED, OUT_OF_BUDGET, BAD_OP, FAULT = 0xC008, 0xC00A, 0xC00B, 0xC00C, 0xC00D
FAULT_PC, FAULT_A = 0xC00E, 0xC010
NR_MMU7, DWIN, L2_BASE_BANK = 0x57, 0xE000, 12


def main():
    sym = symbols("build/aw.exp")
    sym.update(symbols("build/aw_vm_c.exp"))
    z = Zrcp()

    def read(a, n):
        out = bytearray()
        while len(out) < n:
            k = min(2048, n - len(out))
            raw = z.cmd(f"read-memory {a + len(out)} {k}").strip()
            out += bytes(int(raw[i:i + 2], 16) for i in range(0, 2 * k, 2))
        return bytes(out)

    def w(a):
        b = read(a, 2)
        return b[0] | (b[1] << 8)

    z.cmd(f"smartload /work/{NEX}")
    time.sleep(3.2)
    z.cmd("set-memory-zone -1")
    z.cmd(f"write-memory {sym['go']} 1")                    # AND NOTHING ELSE

    t0, last = time.time(), 0
    for i in range(10):
        time.sleep(1.0)
        f = w(FRAMES_DONE)
        print(f"  t={time.time() - t0:4.1f}s  frames_done={f:<6} (+{f - last:<5}) "
              f"blits={w(sym['_aw_blits']) if '_aw_blits' in sym else '?':<6} "
              f"loads={w(sym['n_load']):<4} bitmaps={w(sym['n_bmp']):<4} "
              f"strings={w(sym['n_str'])}")
        last = f

    fin, oob = read(FINISHED, 1)[0], read(OUT_OF_BUDGET, 1)[0]
    flt, bad = read(FAULT, 1)[0], read(BAD_OP, 1)[0]
    print(f"\n  CTL_FINISHED={fin:#04x}  CTL_OUT_OF_BUDGET={oob:#04x}  "
          f"CTL_FAULT={flt:#04x}  CTL_BAD_OP={bad:#04x}  "
          f"fault_pc={w(FAULT_PC):#06x} fault_a={w(FAULT_A):#06x}")

    # is anything actually on the screen? count non-zero pixels in the visible page's first band
    z.cmd(f"write-memory {sym['snd_off']} 1")
    time.sleep(0.2)
    z.cmd(f"tbblue-set-register {NR_MMU7} {L2_BASE_BANK * 2}")
    band = read(DWIN, 2048)
    print(f"  page 0, first 2K: {sum(1 for b in band if b):,} of 2,048 bytes are non-zero, "
          f"{len(set(band))} distinct values")

    if fin == 0x5A:
        print("\n  the loop ENDED - the game is not running")
    elif last > 0:
        print(f"\n  the game is running: {last} frames and still going, no fault")
    z.close()


if __name__ == "__main__":
    main()
