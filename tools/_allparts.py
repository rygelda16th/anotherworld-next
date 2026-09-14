"""I10's "every part": boot into each of the ten and let it run.

"Playable to the end" is a claim about all ten parts, and until start_part existed the only way
to reach one was probe_part, which sets it up and stops before the VM runs. This boots each in
turn, taps fire so the cinematics advance, and reports what the machine does with it: the frame
rate it sustains, what it drew and loaded, how much of the heap it took, and whether it stopped.

It is not a playthrough - nothing here plays the game - but it is the measurement that says
which parts run at all, which is what a playthrough needs first.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zrcp import Zrcp                                       # noqa: E402
from checksave import symbols, NEX                          # noqa: E402

FRAMES_DONE, FINISHED, OUT_OF_BUDGET, BAD_OP, FAULT = (
    0xC008, 0xC00A, 0xC00B, 0xC00C, 0xC00D)
RES_FIRST_PAGE = 72
SECONDS = int(os.environ.get("AW_SECONDS", "14"))
NAMES = ["protection", "introduction", "gameplay", "gameplay", "gameplay",
         "battlechar", "gameplay", "gameplay", "password", "password"]


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

    print(f"  {'part':<5} {'what':<13} {'fps':>5} {'frames':>7} {'blits':>6} {'loads':>6} "
          f"{'pages':>6} {'bmp':>4} {'str':>4}  verdict")
    bad = []
    for part in range(10):
        z.cmd(f"smartload /work/{NEX}")
        time.sleep(3.2)
        z.cmd("set-memory-zone -1")
        z.cmd(f"write-memory {sym['start_part']} {part + 1}")
        z.cmd(f"write-memory {sym['go']} 1")

        t0, marks = time.time(), []
        for _ in range(SECONDS):
            z.cmd("send-keys-event 128 1 nomenu")
            time.sleep(0.08)
            z.cmd("send-keys-event 128 0 nomenu")
            time.sleep(0.8)
            marks.append((time.time() - t0, w(FRAMES_DONE)))

        frames = marks[-1][1]
        fps = frames / marks[-1][0]
        # stalled = no frame in the last third of the window
        third = marks[len(marks) * 2 // 3][1]
        stalled = frames == third
        flt, oob = read(FAULT, 1)[0], read(OUT_OF_BUDGET, 1)[0]
        full, err = read(sym["res_full"], 1)[0], read(sym["res_err"], 1)[0]
        pages = read(sym["next_page"], 1)[0] - RES_FIRST_PAGE

        why = []
        if flt:
            why.append(f"FAULT {flt:#04x} bad_op={read(BAD_OP, 1)[0]:#04x}")
        if oob:
            why.append("out of budget")
        if full:
            why.append("HEAP FULL")
        if err:
            why.append(f"load error {err:#04x}")
        if stalled:
            why.append(f"STALLED at {frames}")
        if not frames:
            why.append("never ran a frame")
        verdict = "; ".join(why) if why else "runs"
        if why:
            bad.append((part, verdict))

        print(f"  {part:<5} {NAMES[part]:<13} {fps:5.1f} {frames:7,} "
              f"{w(sym['_aw_blits']):6,} {w(sym['n_load']):6,} {pages:6} "
              f"{w(sym['n_bmp']):4} {w(sym['n_str']):4}  {verdict}")

    print()
    if bad:
        print(f"  {10 - len(bad)} of 10 parts run; these do not:")
        for part, why in bad:
            print(f"    part {part} ({NAMES[part]}): {why}")
    else:
        print("  all ten parts boot, load, draw and keep running")
    z.close()


if __name__ == "__main__":
    main()
