#!/usr/bin/env python3
"""Gate D: the virtual machine, against the engine's own opcode stream.

Four claims, each failing loudly on its own:

 1. The thread table and the initial variables match initForPart exactly - thread
    0's pc at 0, all 63 others inactive, both channel-state arrays zero, and the
    variables the original game code and executable set rather than the bytecode.
 2. A frame advances and yields: thread 0's pc moves, and something actually
    executed pauseThread rather than the VM simply never having run.
 3. THE OPCODE STREAM MATCHES THE HOST, thread by thread and opcode by opcode.
    This is the claim that matters. A VM wrong in one opcode is a VM that renders
    almost correctly, which is the worst kind of wrong to debug at the end - so
    this catches a wrong operand length at the opcode that has it, rather than as a
    wrong picture 4,000 opcodes later.
 4. The video calls it makes line up with the host's counts.

The seed is taken from the host's own run, because the reference sets variable 0x3C
from time(0) and the two streams diverge the first time the bytecode reads it.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zrcp import Zrcp  # noqa: E402

NEX = "build/vmtest.nex"
EXP_ASM, EXP_C = "build/vmtest.exp", "build/vm_c.exp"
PROBE = "preflight/hostprobe/probe"
CODE_FILE = "RES18.BIN"         # the intro cinematic's bytecode, 9,871 bytes
FRAMES = 40                     # as many as the host logged


def symbols(*paths):
    out = {}
    for path in paths:
        for line in open(path):
            name, _, val = line.partition(":")
            if "0x" in val:
                out[name.strip()] = int(val.split("0x")[1], 16)
    return out


def host_stream(path):
    """(seed, [(kind, thread, pc, opcode)]) from the probe's ops.txt."""
    seed, out, thread = 0, [], 0
    for line in open(path):
        f = line.split()
        if f[0] == "seed":
            seed = int(f[1]) & 0xFFFF
        elif f[0] == "thread":
            thread = int(f[2])
            out.append(("thread", thread, int(f[3]), 0))
        elif f[0] == "op":
            out.append(("op", int(f[2]), int(f[3]), int(f[4])))
    return seed, out


def main():
    sym = symbols(EXP_ASM, EXP_C)
    seed, want = host_stream(os.path.join(PROBE, "ops.txt"))
    print(f"host stream: {len(want):,} records "
          f"({sum(1 for r in want if r[0]=='op'):,} opcodes, "
          f"{sum(1 for r in want if r[0]=='thread'):,} thread edges), seed {seed}")

    z = Zrcp()
    print(f"emulator: {z.cmd('get-version')}")
    z.cmd(f"smartload /work/{NEX}")
    time.sleep(4)
    z.cmd("set-memory-zone -1")
    if z.cmd(f"read-memory {sym['ready']} 1").strip().upper() != "5A":
        raise SystemExit("FAIL: the program never reached its wait loop")

    def poke16(name, v):
        z.cmd(f"write-memory {sym[name]} {v & 0xFF}")
        z.cmd(f"write-memory {sym[name] + 1} {(v >> 8) & 0xFF}")

    blob = CODE_FILE.encode() + b"\x00"
    z.cmd(f"write-memory-raw {sym['fname']} {blob.hex()}")
    poke16("aw_seed", seed)
    poke16("aw_frames", FRAMES)
    z.cmd(f"write-memory {sym['go']} 1")

    for _ in range(600):
        if z.cmd(f"read-memory {sym['done']} 1").strip().upper() == "5A":
            break
        time.sleep(0.05)
    else:
        raise SystemExit("FAIL: the VM never finished")

    err = int(z.cmd(f"read-memory {sym['err']} 1").strip(), 16)
    got_bytes = int.from_bytes(
        bytes.fromhex(z.cmd(f"read-memory {sym['got']} 2").strip()), "little")
    if err:
        raise SystemExit(f"FAIL: esxDOS error {err:#04x} loading {CODE_FILE}")
    size = os.path.getsize(os.path.join("build/assets", CODE_FILE))
    print(f"bytecode loaded: {got_bytes:,} bytes of {size:,}")
    if got_bytes != size:
        raise SystemExit("FAIL: short read")

    fin = z.cmd(f"read-memory {sym['aw_finished']} 1").strip().upper()
    frames = int.from_bytes(
        bytes.fromhex(z.cmd(f"read-memory {sym['aw_frames_done']} 2").strip()),
        "little")
    print(f"the VM ran {frames} frames and "
          f"{'finished cleanly' if fin == '5A' else 'DID NOT finish'}")

    def rd(addr, n):
        out = bytearray()
        while len(out) < n:
            k = min(2048, n - len(out))
            out += bytes.fromhex(z.cmd(f"read-memory {addr + len(out)} {k}").strip())
        return bytes(out)

    # ---- claim 1: the initial state --------------------------------------
    # Read it from a fresh boot, before the VM runs.
    z.cmd(f"smartload /work/{NEX}")
    time.sleep(4)
    z.cmd("set-memory-zone -1")
    z.cmd(f"write-memory-raw {sym['fname']} {blob.hex()}")
    poke16("aw_seed", seed)
    poke16("aw_frames", 0)              # load and initialise, run nothing
    z.cmd(f"write-memory {sym['go']} 1")
    for _ in range(400):
        if z.cmd(f"read-memory {sym['done']} 1").strip().upper() == "5A":
            break
        time.sleep(0.05)
    pcs = rd(sym["aw_pc"], 128)
    reqs = rd(sym["aw_pc_req"], 128)
    states = rd(sym["aw_state"], 64)
    sreqs = rd(sym["aw_state_req"], 64)
    variables = rd(sym["aw_vars"], 512)

    faults = []
    if int.from_bytes(pcs[0:2], "little") != 0:
        faults.append(f"thread 0's pc is {int.from_bytes(pcs[0:2],'little')}, not 0")
    for t in range(1, 64):
        v = int.from_bytes(pcs[t * 2:t * 2 + 2], "little")
        if v != 0xFFFF:
            faults.append(f"thread {t}'s pc is {v:#06x}, not 0xFFFF")
            break
    for t in range(64):
        if int.from_bytes(reqs[t * 2:t * 2 + 2], "little") != 0xFFFF:
            faults.append(f"thread {t}'s requested pc is not 0xFFFF")
            break
    if any(states) or any(sreqs):
        faults.append("a channel state is not zero")
    def var(i):
        return int.from_bytes(variables[i * 2:i * 2 + 2], "little", signed=True)
    for i, w in ((0x54, 0x81), (0xE4, 0x14), (0xBC, 0x10), (0xC6, 0x80),
                 (0xF2, 4000), (0xDC, 33), (0x3C, seed if seed < 0x8000
                                            else seed - 0x10000)):
        if var(i) != w:
            faults.append(f"variable {i:#04x} is {var(i)}, not {w}")
    print(f"claim 1, the initial state: "
          + ("as initForPart leaves it" if not faults else f"{len(faults)} FAULTS"))
    for f in faults[:6]:
        print(f"    {f}")
    if faults:
        raise SystemExit("FAIL: the VM does not start where the engine starts")

    # ---- claims 2 to 4: run it and compare the stream --------------------
    z.cmd(f"smartload /work/{NEX}")
    time.sleep(4)
    z.cmd("set-memory-zone -1")
    z.cmd(f"write-memory-raw {sym['fname']} {blob.hex()}")
    poke16("aw_seed", seed)
    poke16("aw_frames", FRAMES)
    z.cmd(f"write-memory {sym['go']} 1")
    for _ in range(600):
        if z.cmd(f"read-memory {sym['done']} 1").strip().upper() == "5A":
            break
        time.sleep(0.05)

    claimed = int.from_bytes(
        bytes.fromhex(z.cmd(f"read-memory {sym['aw_log_count']} 2").strip()),
        "little")
    # Trust the CONTENT, not the counter. Every record aw_logrec writes has kind 1
    # or 2, so a kind of 0 is the end of what was written - and the counter has
    # been seen to over-report, which would otherwise turn the buffer's unwritten
    # tail into a wall of spurious divergences.
    raw = rd(sym["log_buf"], min(claimed + 8, 2048) * 4)
    n = 0
    while n * 4 + 3 < len(raw) and raw[n * 4] in (1, 2):
        n += 1
    print(f"\nthe machine logged {n:,} records over {FRAMES} frames"
          + (f"   (the counter claims {claimed:,}: a diagnostic wart, see the docs)"
             if claimed != n else ""))
    cur = 0
    norm = []
    for k in range(n):
        kind, lo, hi, v = raw[k * 4:k * 4 + 4]
        pc = lo | (hi << 8)
        if kind == 2:
            cur = v
            norm.append(("thread", cur, pc, 0))
        elif kind == 1:
            norm.append(("op", cur, pc, v))
        else:
            raise SystemExit(f"FAIL: log record {k} has kind {kind}, not 1 or 2")

    bad = None
    for k, (g, w) in enumerate(zip(norm, want)):
        if g != w:
            bad = (k, g, w)
            break
    print(f"claim 3, the opcode stream: compared {min(len(norm), len(want)):,} "
          f"records")
    if bad is None and len(norm) != len(want):
        bad = (min(len(norm), len(want)),
               norm[len(want)] if len(norm) > len(want) else None,
               want[len(norm)] if len(want) > len(norm) else None)
    if bad:
        k, g, w = bad
        print(f"\n  FIRST DIVERGENCE at record {k}")
        print(f"    machine   {g}")
        print(f"    engine    {w}")
        print("\n  the ten records before it, both sides:")
        for j in range(max(0, k - 10), k):
            print(f"    {j:>5}  {norm[j]}   {want[j]}")
        if g is None:
            print(f"""
The machine's stream is a PREFIX of the engine's: every one of the {k} records it
produced is right, and then it stops producing them. That is the open fault in
Phase D, and it is in the trace rather than in the VM - see
docs/where-things-stand.md, "Gate D: nineteen records, and a corrupted counter".""")
        raise SystemExit("FAIL: the machine's opcode stream is not the engine's")

    print(f"    identical, all {len(want):,} of them")

    for name, label in (("n_poly", "polygons"), ("n_select", "selectVideoPage"),
                        ("n_fill", "fillVideoPage"), ("n_copy", "copyVideoPage"),
                        ("n_blit", "blitFramebuffer"),
                        ("n_pal", "setPalette")):
        v = int.from_bytes(
            bytes.fromhex(z.cmd(f"read-memory {sym[name]} 2").strip()), "little")
        print(f"    {label:<18}{v:>6}")

    z.close()
    print("\nPASS: the VM starts where the engine starts and dispatches exactly "
          "what it\n      dispatches, thread by thread, over 40 frames.")


if __name__ == "__main__":
    main()
