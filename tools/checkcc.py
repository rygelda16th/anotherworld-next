#!/usr/bin/env python3
"""Gate B: does compiled C call assembly at a fixed address, and come back?

Reads the C's globals through the .exp that tools/mkexp.py produced from
z88dk's map, and the assembly's through sjasmplus's own .exp. That both work
from the same helper is the point: no checker should need to know which tool
produced a symbol.

Four things are proved, in order, so a failure says which half broke:
  1. the assembly reached its handover to the C at all
  2. the C is running (its own counter advances)
  3. C -> assembly carried the argument intact (0x5AA5 arrives at `poked`)
  4. assembly -> C carried the result back (0x1111 + 0x1111 = 0x2222)
"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zrcp import Zrcp

NEX = "build/ctest.nex"
ASM_EXP = "build/ctest.exp"      # sjasmplus wrote this (assembly symbols)
C_EXP = "build/ctest_c.exp"      # tools/mkexp.py wrote this (C symbols)


def symbols(path):
    out = {}
    for line in open(path):
        name, _, val = line.partition(":")
        if "0x" in val:
            out[name.strip()] = int(val.split("0x")[1], 16)
    return out


def main():
    for p in (ASM_EXP, C_EXP):
        if not os.path.exists(p):
            raise SystemExit(f"FAIL: {p} is missing - run `make cc asm` first")
    asm = symbols(ASM_EXP)
    csym = symbols(C_EXP)
    need_asm = ["asm_ran", "poked", "poke_count"]
    need_c = ["cc_ticks", "cc_returned"]
    missing = [n for n in need_asm if n not in asm] + \
              [n for n in need_c if n not in csym]
    if missing:
        print("symbols present from assembly:", sorted(asm)[:10])
        print("symbols present from C:", sorted(csym)[:10])
        raise SystemExit(f"FAIL: these symbols were not found: {missing}")

    z = Zrcp()
    print(f"emulator: {z.cmd('get-version')}")
    z.cmd(f"smartload /work/{NEX}")
    time.sleep(4)
    z.cmd("set-memory-zone -1")

    def byte(a):
        return int(z.cmd(f"read-memory {a} 1").strip(), 16)

    def word(a):
        raw = z.cmd(f"read-memory {a} 2").strip()
        return int(raw[2:4] + raw[0:2], 16)

    ran = byte(asm["asm_ran"])
    print(f"\n1. assembly reached the handover : 0x{ran:02X} "
          f"({'OK' if ran == 0xA5 else 'FAIL - 0xEE means the C returned'})")
    if ran != 0xA5:
        raise SystemExit("FAIL: the assembly never handed over, or the C returned")

    t0 = word(csym["cc_ticks"])
    time.sleep(1.0)
    t1 = word(csym["cc_ticks"])
    print(f"2. the C is running             : cc_ticks {t0} -> {t1} "
          f"({'OK' if t1 != t0 else 'FAIL - not advancing'})")
    if t1 == t0:
        raise SystemExit("FAIL: cc_ticks never advanced, so the C is not running")

    pk, pc = word(asm["poked"]), byte(asm["poke_count"])
    print(f"3. C -> assembly, argument      : poked 0x{pk:04X} "
          f"after {pc} calls ({'OK' if pk == 0x5AA5 else 'FAIL, want 0x5AA5'})")
    rv = word(csym["cc_returned"])
    print(f"4. assembly -> C, return value  : 0x{rv:04X} "
          f"({'OK' if rv == 0x2222 else 'FAIL, want 0x2222'})")
    z.close()
    if pk != 0x5AA5 or rv != 0x2222:
        raise SystemExit("FAIL: the calling convention is not what was assumed")
    print("\nPASS: sjasmplus and z88dk are bound, both directions, at fixed "
          "addresses.")


if __name__ == "__main__":
    main()
