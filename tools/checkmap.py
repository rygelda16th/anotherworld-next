#!/usr/bin/env python3
"""I1: can the integrated program's eight slots coexist?

Chain 2 rests on this and nothing had tested it. The plan's arithmetic says the whole
game is 502,527 bytes, half of a 1MB machine, so capacity was never the risk - slot
contention is. No harness has ever needed more than two windows at once; the game
needs five plus its resident code.

The experiment puts a distinct signature in eight banked pages, maps the proposed
arrangement all at once, reads every signature back, then does the one thing known to
break it - an esxDOS call, which wants the ROM at $0000 and bank 5 at $4000 - and
reads them all back again.

The new claim under test is $4000-$7FFF. src/vmtest.asm records that region as "NOT
AVAILABLE", but it records it for the duration of a DOS call. Outside one it is
sixteen kilobytes the project has never used, and the second window has to go
somewhere.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zrcp import Zrcp  # noqa: E402

NEX = "build/maptest.nex"
EXP = "build/maptest.exp"
SIG = 64                      # SIG_PAGE in src/maptest.asm

# Which page each sampled address should be showing, and the slot it proves.
EXPECT = [
    ("$0000", SIG + 0, "MMU0  bytecode window, low"),
    ("$1FFF", SIG + 0, "MMU0  bytecode window, low, top byte"),
    ("$2000", SIG + 1, "MMU1  bytecode window, high"),
    ("$3FFF", SIG + 1, "MMU1  bytecode window, high, top byte"),
    ("$4000", SIG + 2, "MMU2  polygon window, low"),
    ("$5FFF", SIG + 2, "MMU2  polygon window, low, top byte"),
    ("$6000", SIG + 3, "MMU3  polygon window, high"),
    ("$7FFF", SIG + 3, "MMU3  polygon window, high, top byte"),
    ("$C000", SIG + 6, "MMU6  the Layer 2 band being drawn"),
    ("$DFFF", SIG + 6, "MMU6  the Layer 2 band, top byte"),
    ("$E000", SIG + 7, "MMU7  sample window / loader staging"),
    ("$FFFF", SIG + 7, "MMU7  sample window, top byte"),
]


def symbols(path):
    out = {}
    for line in open(path):
        name, _, val = line.partition(":")
        if "0x" in val:
            out[name.strip()] = int(val.split("0x")[1], 16)
    return out


def read(z, addr, n):
    raw = z.cmd(f"read-memory {addr} {n}").strip()
    return bytes(int(raw[i:i + 2], 16) for i in range(0, 2 * n, 2))


def main():
    sym = symbols(EXP)
    z = Zrcp()
    print(f"emulator: {z.cmd('get-version')}")
    z.cmd(f"smartload /work/{NEX}")
    time.sleep(3.5)
    z.cmd("set-memory-zone -1")
    if read(z, sym["ready"], 1)[0] != 0x5A:
        raise SystemExit("FAIL: the program never reached its wait loop")
    z.cmd(f"write-memory {sym['go']} 1")
    for _ in range(120):
        if read(z, sym["done"], 1)[0] == 0x5A:
            break
        time.sleep(0.1)
    else:
        raise SystemExit("FAIL: it never finished - which for this test means the "
                         "arrangement itself hung the machine")

    w4000, w5b00, w7fff = (read(z, sym[n], 1)[0]
                           for n in ("r_4000w", "r_5b00w", "r_7fffw"))
    dos, doserr = read(z, sym["r_dos"], 1)[0], read(z, sym["r_doserr"], 1)[0]
    before = read(z, sym["r_before"], 12)
    after = read(z, sym["r_after"], 12)
    z.close()

    bad = []

    print("\n$4000-$7FFF with our own page in it - is it plain RAM we own?")
    for name, got, want in (("$4000", w4000, 0xA5), ("$5B00", w5b00, 0xA5),
                            ("$7FFF", w7fff, 0x5A)):
        ok = got == want
        print(f"  wrote {want:#04x} to {name}, read back {got:#04x}   "
              + ("ok" if ok else "WRONG"))
        if not ok:
            bad.append(f"{name} did not hold what was written to it")
    if not bad:
        print("  so the region IS ours outside a DOS call, which is the new claim")

    for label, block in (("all eight slots mapped at once", before),
                         ("and again AFTER an esxDOS call", after)):
        print(f"\n{label}:")
        for (addr, want, what), got in zip(EXPECT, block):
            ok = got == want
            print(f"  {addr}  page {got:>3}  want {want:>3}  {what}"
                  + ("" if ok else "   WRONG"))
            if not ok:
                bad.append(f"{addr} showed page {got}, wanted {want} ({label})")

    print("\nthe esxDOS call itself: "
          + ("opened and closed a file with the windows stood down"
             if dos == 1 else f"FAILED, error {doserr:#04x}"))
    if dos != 1:
        bad.append("the DOS call failed with the proposed arrangement")

    if bad:
        print("\n  " + "\n  ".join(bad))
        raise SystemExit(f"FAIL: {len(bad)} problem(s) - the slot map in the plan "
                         "does not hold, and I1 has to be redesigned before "
                         "anything is built on it")
    print("""
PASS: all five windows and the resident code coexist, $4000-$7FFF is usable as the
      second window outside a DOS call, and every window survives being stood down
      for esxDOS and put back. I1's arrangement holds.""")


if __name__ == "__main__":
    main()
