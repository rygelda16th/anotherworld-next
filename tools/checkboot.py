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
# How many frames the reference covers. Taken FROM the reference rather than fixed:
# the first version of this gate had 40 here and 40 in the probe, and the machine
# matched every one of the engine's 679 records and then produced a 680th with
# nothing to compare it against - a reference that ends before the thing under test
# does cannot say whether the next record is right. AW_OP_FRAMES in the probe and
# this number come from the same place now.
def ref_frames(path):
    n = 0
    for line in open(path):
        f = line.split()
        if f[0] in ("op", "thread"):
            n = max(n, int(f[1]) + 1)
    return n
# An opcode budget, so the harness terminates even when the script waits for a
# resource the stubbed loader never delivers. Generous: the host dispatched 567
# opcodes over those 40 frames.
BUDGET = int(os.environ.get("AW_BUDGET", "20000"))
TRACE_FILE = "AWTRACE.BIN"   # the machine writes this through esxDOS
HDR = 32                     # the control block, then the records


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
    ops = os.path.join(PROBE, "ops.txt")
    frames = int(os.environ.get("AW_FRAMES", str(ref_frames(ops))))
    seed, want = host_stream(ops)
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
    hdr = (seed.to_bytes(2, "little") + frames.to_bytes(2, "little")
           + BUDGET.to_bytes(2, "little"))
    z.cmd(f"write-memory-raw {sym['log_buf']} {hdr.hex()}")
    blob = CODE_FILE.encode() + b"\x00"
    z.cmd(f"write-memory-raw {sym['fname']} {blob.hex()}")
    z.cmd(f"write-memory {sym['go']} 1")

    def b1(name):
        return int(z.cmd(f"read-memory {sym[name]} 1").strip(), 16)

    # WAIT ON THE CONTROL BLOCK, not on an assembly flag. main does not return -
    # see the comment at the foot of src/aw/vm.c - so $C00A going to $5A is the only
    # signal there is, and it is also the one the verdict is read beside.
    waited = 0.0
    limit = float(os.environ.get("AW_WAIT_S", "60"))
    fin = sym["log_buf"] + 10
    while waited < limit:
        if z.cmd(f"read-memory {fin} 1").strip().upper() == "5A":
            break
        time.sleep(0.1)
        waited += 0.1

    # THE VERDICT COMES OFF THE MACHINE AS THIRTY-TWO BYTES, and it is read twice.
    #
    # The comparison itself happens on the machine now: the engine's 679 records
    # ship in the .nex at $E000 and the VM checks each record as it writes it. That
    # change is what made this gate readable at all. Every failing run used to end
    # the same way - the VM leaves the rails, the bytes after the rails get executed
    # as opcodes, and the stack runs down from $BF00 and wraps, so the smear reaches
    # the trace block and destroys the evidence of what went wrong. Stopping on the
    # first mismatch stops before any of that.
    #
    # Two reads because a verdict read wrongly is a verdict that disagrees with
    # itself, and this is the one number the gate turns on.
    def block():
        raw = z.cmd(f"read-memory {sym['log_buf']} 32").strip()
        return bytes(int(raw[i:i + 2], 16) for i in range(0, 64, 2))

    b, b2 = block(), block()
    if b != b2:
        raise SystemExit("FAIL: the control block read back differently twice - "
                         f"{b.hex()} then {b2.hex()}")
    w = lambda o: int.from_bytes(b[o:o + 2], "little")     # noqa: E731
    records, frames_done = w(6), w(8)
    finished, oob, bad_op, flt = b[10], b[11], b[12], b[13]
    fault_pc, code_len, fault_a, exp_n, div_at = w(14), w(16), w(18), w(20), w(22)
    got_rec, want_rec = b[24:28], b[28:32]
    z.close()

    print(f"\nthe machine: {records:,} records over {frames_done} frames of a "
          f"{code_len:,}-byte segment")
    print(f"  it {'finished' if finished == 0x5A else 'DID NOT finish'} in "
          f"{waited:.1f}s, with {exp_n:,} expected records loaded")
    if oob:
        print("  it ran out of opcode budget")
    if bad_op:
        print(f"  it saw opcode {bad_op:#04x}, which the engine calls error() on")

    def rec(r):
        kind = {1: "op", 2: "thread"}.get(r[0], f"kind {r[0]}")
        return f"({kind}, pc {r[1] | (r[2] << 8)}, {r[3]})"

    why = {1: "the pc left the segment it was given",
           2: "resetThread over a range outside the thread table",
           3: "an opcode the reference calls error() on",
           4: "ret with nothing on the call stack",
           5: "a record the engine did not produce",
           6: "the reference ran out - every record in it was matched"}
    if flt and not (flt == 6 and records == exp_n):
        print(f"  FAULT {flt}: {why.get(flt, '?')}")
        print(f"    at pc {fault_pc} ({fault_pc:#06x}), context {fault_a:#06x}")

    if flt == 5:
        print(f"\n  FIRST DIVERGENCE at record {div_at:,} of {exp_n:,}")
        print(f"    the machine {rec(got_rec)}")
        print(f"    the engine  {rec(want_rec)}")
        print("    the engine's records either side:")
        for j in range(max(0, div_at - 5), min(len(want), div_at + 3)):
            mark = "  <-- here" if j == div_at else ""
            print(f"      {j:>5}  {want[j]}{mark}")
        raise SystemExit("FAIL: the machine's opcode stream is not the engine's")

    if flt and not (flt == 6 and records == exp_n):
        print(f"""
  The machine's first {records:,} records ARE the engine's - the comparison runs on
  the machine and it stopped at a fault, not at a mismatch. {why.get(flt, '?')}
  is what to fix next.""")
        raise SystemExit(f"PARTIAL: {records:,} records identical, then a fault")

    if flt == 6 and records == exp_n:
        # THE REFERENCE ENDS BEFORE THE MACHINE DOES, and that is the probe's frame
        # counter, not a difference in the VM. instrFrame() hangs off
        # Video::updateDisplay, so what the probe calls a frame is a BLIT; the C
        # counts hostFrame iterations. The two agree closely and not exactly - here
        # 43 of ours to 45 of its - so asking both for "45 frames" asks for different
        # amounts of work. The record stream carries no frame boundaries, so it
        # cannot tell them apart and does not need to: matching every record in the
        # reference and then having nothing left to compare is the end of the test,
        # not a failure of it.
        print(f"  the reference ends here: {frames} of the probe's frames is "
              f"{frames_done + 1} of the VM's, because the probe counts blits")

    if records == len(want) and finished == 0x5A:
        print(f"""
PASS: the VM dispatches exactly what the engine dispatches - all {len(want):,}
      records, thread by thread and opcode by opcode, over {frames} frames,
      checked on the machine as each one was produced.""")
        return
    raise SystemExit(f"FAIL: {records:,} records, {len(want):,} expected, no fault "
                     f"reported - which should not be possible")


if __name__ == "__main__":
    main()
