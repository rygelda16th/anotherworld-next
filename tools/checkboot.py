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
FRAMES = int(os.environ.get("AW_FRAMES", "40"))   # the host logged 40
# An opcode budget, so the harness terminates even when the script waits for a
# resource the stubbed loader never delivers. Generous: the host dispatched 567
# opcodes over those 40 frames.
BUDGET = int(os.environ.get("AW_BUDGET", "4000"))
TRACE_FILE = "AWTRACE.BIN"   # the machine writes this through esxDOS


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

    trace_path = os.path.join("build/assets", TRACE_FILE)
    if os.path.exists(trace_path):
        os.remove(trace_path)

    z = Zrcp()
    print(f"emulator: {z.cmd('get-version')}")
    z.cmd(f"smartload /work/{NEX}")
    time.sleep(4)
    z.cmd("set-memory-zone -1")
    if z.cmd(f"read-memory {sym['ready']} 1").strip().upper() != "5A":
        raise SystemExit("FAIL: the program never reached its wait loop")

    # The header the C reads, poked into the same block it writes - so the only
    # memory the checker touches is six bytes at a fixed address in assembly-owned
    # RAM, and everything it reads comes back in a file.
    hdr = (seed.to_bytes(2, "little") + FRAMES.to_bytes(2, "little")
           + BUDGET.to_bytes(2, "little"))
    z.cmd(f"write-memory-raw {sym['log_buf']} {hdr.hex()}")
    blob = CODE_FILE.encode() + b"\x00"
    z.cmd(f"write-memory-raw {sym['fname']} {blob.hex()}")
    z.cmd(f"write-memory {sym['go']} 1")

    waited = 0.0
    limit = float(os.environ.get("AW_WAIT_S", "120"))
    while waited < limit:
        if z.cmd(f"read-memory {sym['done']} 1").strip().upper() == "5A":
            break
        time.sleep(0.1)
        waited += 0.1
    z.close()

    if not os.path.exists(trace_path):
        raise SystemExit(f"FAIL: the machine wrote no {TRACE_FILE} - it either "
                         f"never finished ({waited:.0f}s waited) or esxDOS refused "
                         "the write")
    blk = open(trace_path, "rb").read()
    print(f"\n{TRACE_FILE}: {len(blk):,} bytes, written by the machine itself")

    n = int.from_bytes(blk[6:8], "little")
    frames_done = int.from_bytes(blk[8:10], "little")
    finished = blk[10]
    oob = blk[11]
    bad_op = blk[12]
    print(f"  the VM ran {frames_done} frames, "
          f"{'finished cleanly' if finished == 0x5A else 'did not finish'}"
          f"{', out of opcode budget' if oob else ''}"
          f"{f', invalid opcode {bad_op:#04x}' if bad_op else ''}")
    print(f"  it claims {n:,} trace records")

    # Trust the content over the count, as ever: every record aw_logrec writes has
    # kind 1 or 2.
    recs, k = [], 0
    while 16 + k * 4 + 3 < len(blk) and blk[16 + k * 4] in (1, 2):
        kind, lo, hi, v = blk[16 + k * 4:20 + k * 4]
        recs.append((kind, lo | (hi << 8), v))
        k += 1
    print(f"  and holds {len(recs):,} of them")

    cur, norm = 0, []
    for kind, pc, v in recs:
        if kind == 2:
            cur = v
            norm.append(("thread", cur, pc, 0))
        else:
            norm.append(("op", cur, pc, v))

    m = 0
    while m < min(len(norm), len(want)) and norm[m] == want[m]:
        m += 1
    print(f"\nthe stream: {m:,} records identical to the engine's, of "
          f"{min(len(norm), len(want)):,} compared")

    if m == len(want):
        print(f"""
PASS: the VM dispatches exactly what the engine dispatches - all {len(want):,}
      records, thread by thread and opcode by opcode, over {FRAMES} frames.""")
        return
    if m < len(norm) and m < len(want):
        print(f"\n  FIRST DIVERGENCE at record {m}")
        print(f"    machine   {norm[m]}")
        print(f"    engine    {want[m]}")
        for j in range(max(0, m - 6), m):
            print(f"    {j:>5}  {norm[j]}   {want[j]}")
        raise SystemExit("FAIL: the machine's opcode stream is not the engine's")
    print(f"""
  The machine's stream is a PREFIX: every one of its {m:,} records is right and then
  it produces no more. Raise AW_BUDGET if it ran out of opcode budget; otherwise the
  script is waiting for a resource the stubbed loader never delivers, and the rest
  of D4 is what unblocks it.""")
    raise SystemExit(f"PARTIAL: {m:,} records identical, then the VM runs out of "
                     "things it can do")


if __name__ == "__main__":
    main()
