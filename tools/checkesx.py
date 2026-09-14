#!/usr/bin/env python3
"""The esxDOS window invariant: is the ROM back over the bottom 16K during a DOS call?

RST $08 is a jump to $0008, and esxDOS only answers there because the divMMC pages
itself in when the processor FETCHES from that address - which it can only do while
the bottom 16K is ROM. vmhost.inc's code_add maps the bytecode segment over exactly
that range on every opcode fetch, so before this gate existed the first load after the
VM had fetched an opcode did not reach esxDOS at all: the RST landed in bytecode and
the machine ran off into data, unwinding the stack as it went.

WHY THIS GATE DOES NOT TEST THE LOAD. ZEsarUX answers RST $08 by address whatever the
paging says, so a load with the window in place succeeds there. That is exactly how
the fault survived twelve gates and was only found under CSpect, whose esxDOS plugin
checks that MMU0 reads back as ROM - which is what real hardware does. So what is
gated here is the register state itself, which both emulators agree on: MMU0 and MMU1
while a call is in progress, and MMU0 and MMU1 after it.

src/maptest.asm has known the rule since gate I1 - "the ROM back over the bottom 16K,
and bank 5 back at $4000, which is what the DOS needs". The loader never did it.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zrcp import Zrcp  # noqa: E402

NEX = "build/esxtest.nex"
EXP = "build/esxtest.exp"
NAME = "RES18.BIN"            # the intro's bytecode; any resource would do
SIG_LO, SIG_HI = 73, 74       # what src/esxtest.asm puts in MMU0/MMU1
ROM = 0xFF                    # what an MMU slot reads back as when it maps the ROM


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


def word(z, addr):
    b = read(z, addr, 2)
    return b[0], b[1]                       # (MMU0, MMU1), low byte first


def main():
    sym = symbols(EXP)
    z = Zrcp()
    print(f"emulator: {z.cmd('get-version')}")
    z.cmd(f"smartload /work/{NEX}")
    time.sleep(3.5)
    z.cmd("set-memory-zone -1")
    if read(z, sym["ready"], 1)[0] != 0x5A:
        raise SystemExit("FAIL: the harness never reached its wait loop")

    payload = NAME.encode() + b"\x00"
    z.cmd(f"write-memory-raw {sym['fname']} " + payload.hex())
    z.cmd(f"write-memory {sym['go']} 1")
    for _ in range(60):
        time.sleep(0.5)
        if read(z, sym["done"], 1)[0] == 0x5A:
            break
    else:
        raise SystemExit("FAIL: the harness never finished")

    before = word(z, sym["m_before"])
    during = word(z, sym["m_during"])
    after = word(z, sym["m_after"])
    load = word(z, sym["m_load"])
    err = read(z, sym["err"], 1)[0]
    got = int.from_bytes(read(z, sym["got"], 2), "little")

    print(f"  MMU0/MMU1 with the bytecode window in place  {before[0]},{before[1]}")
    print(f"  ...inside a DOS call                         {during[0]},{during[1]}")
    print(f"  ...and afterwards                            {after[0]},{after[1]}")
    print(f"  ...after a whole load_code                   {load[0]},{load[1]}")
    print(f"  the load itself: err={err} got={got}")

    bad = []
    if before != (SIG_LO, SIG_HI):
        bad.append(f"the harness could not page the bytecode window in: {before}")
    if during != (ROM, ROM):
        bad.append(f"a DOS call runs with {during} over the bottom 16K, not the ROM - "
                   f"RST $08 lands in whatever is paged there, not in esxDOS")
    if after != (SIG_LO, SIG_HI):
        bad.append(f"the window was not put back afterwards: {after}")
    if load != (SIG_LO, SIG_HI):
        bad.append(f"load_code did not put the window back: {load}")
    if err:
        bad.append(f"the load failed with esxDOS error {err}")
    if got == 0:
        bad.append("the load read nothing")

    if bad:
        for b in bad:
            print("  FAIL:", b)
        raise SystemExit(1)
    print(f"PASS: the ROM is back over the bottom 16K for the length of a DOS call, "
          f"and {got} bytes still arrive with the bytecode window paged in")


if __name__ == "__main__":
    main()
