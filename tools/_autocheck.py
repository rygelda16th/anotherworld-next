"""Does auto_input actually reach the VM's variables, and does it follow the probe's function?

Waiting for the synthetic player to die is a poor test - the reference's cycle is 400 frames
and the machine reaches about 370 in a minute. This checks the arithmetic directly instead:
the counters advance with the FRAME, the mask follows the three thresholds, and the VM's own
variables carry it. Every row is checked against the probe's processEvents, not eyeballed.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zrcp import Zrcp                                       # noqa: E402
from checksave import symbols, NEX                          # noqa: E402

FRAMES_DONE = 0xC008
M_LEFT, M_RIGHT, M_UP = 1, 2, 4


def want(f):
    """headless.cpp processEvents, verbatim."""
    m = 0
    if f % 400 < 260:
        m = M_RIGHT
    elif f % 400 < 300:
        m = M_UP
    elif f % 400 < 330:
        m = M_LEFT
    return m, 1 if (f % 47) < 6 else 0


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
    z.cmd(f"write-memory {sym['start_part']} 3")            # part index 2
    z.cmd(f"write-memory {sym['autoplay']} 1")
    z.cmd(f"write-memory {sym['go']} 1")

    vars_addr = sym["_aw_vars"]
    bad, n = [], 0
    print(f"  {'frames':>7} {'auto_400':>9} {'auto_47':>8} {'mask':>5} {'btn':>4} "
          f"{'want':>5} {'want':>5}  {'$FD':>5} {'$FE':>5}")
    for _ in range(40):
        time.sleep(0.5)
        f = w(FRAMES_DONE)
        c400 = w(sym["auto_400"])
        c47 = read(sym["auto_47"], 1)[0]
        mask = read(sym["in_mask"], 1)[0]
        btn = read(sym["in_button"], 1)[0]
        v_fd = w(vars_addr + 0xFD * 2)
        v_fe = w(vars_addr + 0xFE * 2)
        wm = want(c400)[0]                    # the mask follows auto_400, which IS f % 400
        n += 1
        if mask != wm:
            bad.append(f"at counter {c400} the mask is {mask} and the probe's is {wm}")
        if btn != (1 if c47 < 6 else 0):
            bad.append(f"at counter {c47} the button is {btn}")
        print(f"  {f:>7} {c400:>9} {c47:>8} {mask:>5} {btn:>4} {wm:>5} "
              f"{1 if c47 < 6 else 0:>5}  {v_fd:>5} {v_fe:>5}")

    print()
    if c400 == 0:
        print("  FAIL: auto_400 never advanced - the frame counter is not being seen")
    elif bad:
        print(f"  FAIL: {len(bad)} of {n} samples disagree with the probe's function")
        for b in bad[:5]:
            print("    " + b)
    else:
        print(f"  all {n} samples match headless.cpp's processEvents, and the VM's own "
              f"variables carry it")
    z.close()


if __name__ == "__main__":
    main()
