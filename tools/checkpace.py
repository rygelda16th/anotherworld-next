#!/usr/bin/env python3
"""Gate E, first two claims: the input mapping, and frame pacing.

Both are checked against a model of the reference computed here, not against a
picture. The input mapping has two quirks that only reading vm.cpp:586-638 gives
you - left and right BOTH assign, so pressing both gives left, and variable 0xE5
is assigned and then overwritten if up is held, which is not what 0xFB gets - and a
port that got either wrong would still feel like it worked.

Pacing is measured in refreshes from the machine's own 50 Hz tick, and the claim
that matters is the second one: a frame that overruns must LOSE time rather than
push everything after it back. The pause is a deadline, not a delay.
"""
import itertools
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zrcp import Zrcp  # noqa: E402

NEX, EXP = "build/petest.nex", "build/petest.exp"
DIR_LEFT, DIR_RIGHT, DIR_UP, DIR_DOWN = 1, 2, 4, 8


def reference_input(mask, button):
    """inp_updatePlayer, vm.cpp:586-638, in its own order."""
    lr = ud = m = 0
    if mask & DIR_RIGHT:
        lr = 1
        m |= 1
    if mask & DIR_LEFT:
        lr = -1
        m |= 2
    if mask & DIR_DOWN:
        ud = 1
        m |= 4
    e5 = ud
    if mask & DIR_UP:
        e5 = -1
    if mask & DIR_UP:
        ud = -1
        m |= 8
    fb, fc, fd = ud, lr, m
    fa = 0
    if button:
        fa = 1
        m |= 0x80
    return {"E5": e5, "FA": fa, "FB": fb, "FC": fc, "FD": fd, "FE": m}


def symbols(path):
    out = {}
    for line in open(path):
        name, _, val = line.partition(":")
        if "0x" in val:
            out[name.strip()] = int(val.split("0x")[1], 16)
    return out


def main():
    sym = symbols(EXP)
    z = Zrcp()
    print(f"emulator: {z.cmd('get-version')}")
    z.cmd(f"smartload /work/{NEX}")
    time.sleep(4)
    z.cmd("set-memory-zone -1")
    if z.cmd(f"read-memory {sym['ready']} 1").strip().upper() != "5A":
        raise SystemExit("FAIL: the program never reached its wait loop")

    def run(what, limit=200):
        z.cmd(f"write-memory {sym['done']} 0")
        z.cmd(f"write-memory {sym['what']} {what}")
        z.cmd(f"write-memory {sym['go']} 1")
        for _ in range(limit):
            if z.cmd(f"read-memory {sym['done']} 1").strip().upper() == "5A":
                return True
            time.sleep(0.05)
        return False

    def word(name, signed=True):
        raw = bytes.fromhex(z.cmd(f"read-memory {sym[name]} 2").strip())
        return int.from_bytes(raw, "little", signed=signed)

    # ---- the tick has to be running at all -------------------------------
    t0 = word("ticks", signed=False)
    time.sleep(0.5)
    t1 = word("ticks", signed=False)
    print(f"\nthe 50 Hz tick advanced {t1 - t0} in half a second "
          f"(expect about 25)")
    if t1 == t0:
        raise SystemExit("FAIL: the frame interrupt is not firing, so nothing "
                         "below means anything")

    # ---- claim 1: the input mapping, every combination -------------------
    bad = []
    for mask, button in itertools.product(range(16), (0, 1)):
        z.cmd(f"write-memory {sym['in_mask']} {mask}")
        z.cmd(f"write-memory {sym['in_button']} {button}")
        if not run(1):
            raise SystemExit("FAIL: the input mapping never finished")
        got = {n: word(f"var_{n}") for n in ("E5", "FA", "FB", "FC", "FD", "FE")}
        want = reference_input(mask, button)
        if got != want:
            bad.append((mask, button, got, want))
    print(f"\nthe input mapping over all {16 * 2} combinations: "
          + ("every variable matches the reference" if not bad
             else f"{len(bad)} WRONG"))
    for mask, button, got, want in bad[:6]:
        names = [k for k, b in (("left", 1), ("right", 2), ("up", 4), ("down", 8))
                 if mask & b]
        print(f"  mask {mask:#04x} ({'+'.join(names) or 'none'}) "
              f"button {button}:")
        for k in want:
            if got[k] != want[k]:
                print(f"    0x{k}: machine {got[k]}, reference {want[k]}")
    if bad:
        raise SystemExit("FAIL: the input mapping is not the reference's")

    # the two quirks, called out because they are what a port gets wrong
    lr = reference_input(DIR_LEFT | DIR_RIGHT, 0)
    up = reference_input(DIR_UP, 0)
    print(f"  left and right together give 0xFC = {lr['FC']} (left wins) and a "
          f"mask of {lr['FD']:#04x}")
    print(f"  up alone gives 0xE5 = {up['E5']} and 0xFB = {up['FB']} - the same "
          f"here, but they are computed by different paths")

    # ---- claim 2: pacing -------------------------------------------------
    print("\npacing, measured from the machine's own tick:")
    print(f"  {'asked':>6}{'work':>6}{'frames':>8}{'mean gap':>10}{'min':>6}"
          f"{'max':>6}   verdict")
    rows = []
    for slices, work in ((4, 0), (5, 0), (1, 0), (4, 2), (4, 6)):
        z.cmd(f"write-memory {sym['pace_n']} 12")
        z.cmd(f"write-memory {sym['pace_slices']} {slices}")
        z.cmd(f"write-memory {sym['pace_work']} {work}")
        if not run(2, limit=600):
            raise SystemExit(f"FAIL: pacing never finished at {slices} slices")
        raw = bytes.fromhex(z.cmd(f"read-memory {sym['pace_log']} 24").strip())
        ts = [int.from_bytes(raw[i:i + 2], "little") for i in range(0, 24, 2)]
        gaps = [b - a for a, b in zip(ts, ts[1:])]
        mean = sum(gaps) / len(gaps)
        ok = (abs(mean - slices) <= 0.5 if work <= slices
              else abs(mean - work) <= 1.0)
        verdict = ("paces to the request" if work <= slices
                   else "overran, and kept the overrun rather than drifting")
        rows.append((slices, work, mean, min(gaps), max(gaps), ok))
        print(f"  {slices:>6}{work:>6}{len(gaps):>8}{mean:>10.2f}{min(gaps):>6}"
              f"{max(gaps):>6}   {verdict}"
              + ("" if ok else "   <-- WRONG"))

    if any(not ok for *_, ok in rows):
        raise SystemExit("FAIL: pacing does not hold its deadline")

    print("""
  A frame asking for four refreshes and doing six refreshes of work comes out at
  six, not ten: the deadline advanced by four and had already passed, so the wait
  was skipped. That is the reference's own arithmetic - the pause is a deadline
  that a slow frame eats into, not a delay added on top of it.""")

    z.close()
    print("\nPASS: the input mapping is the reference's, every combination, and "
          "pacing\n      holds its deadline and loses time rather than drifting.")


if __name__ == "__main__":
    main()
