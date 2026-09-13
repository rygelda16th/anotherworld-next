#!/usr/bin/env python3
"""I1: the integrated program - everything live at once, and nothing broken by it.

Eight harnesses proved the parts one at a time. This is the first program that runs
more than one of them together, and the gate is that none of them notices the others:

 1. THE OPCODE STREAM IS STILL THE ENGINE'S. Gate D, re-run inside the game, with the
    frame interrupt firing fifty times a second, the zxnDMA streaming a ring to the
    DAC, and the mixer refilling that ring from inside the interrupt. If any of that
    disturbs the VM - a clobbered shadow register, a window paged out from under it -
    the stream diverges and says where.
 2. THE FRAME INTERRUPT IS LIVE, and the VM ran at its pace: one tick a frame.
 3. THE MIXER RAN. The ring is not silence, and the DMA's own position has moved.
 4. IT SURVIVES BEING LEFT ALONE. vm.c's main never returns, so after the last frame
    the interrupt keeps ticking and mixing forever; a soak proves the arrangement is
    stable rather than merely surviving 0.9 seconds.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zrcp import Zrcp  # noqa: E402

NEX = "build/aw.nex"
EXP_ASM, EXP_C = "build/aw.exp", "build/aw_vm_c.exp"
PROBE = "preflight/hostprobe/probe"
CODE_FILE = "RES18.BIN"
CTL = 0xC000
RING, RING_LEN = 0xD400, 2048
BUDGET = int(os.environ.get("AW_BUDGET", "20000"))
SOAK_S = float(os.environ.get("AW_SOAK_S", "5"))


def symbols(*paths):
    out = {}
    for path in paths:
        for line in open(path):
            name, _, val = line.partition(":")
            if "0x" in val:
                out[name.strip()] = int(val.split("0x")[1], 16)
    return out


def host_stream(path):
    seed, out, thread, frames = 0, [], 0, 0
    for line in open(path):
        f = line.split()
        if f[0] == "seed":
            seed = int(f[1]) & 0xFFFF
        elif f[0] == "thread":
            thread = int(f[2])
            frames = max(frames, int(f[1]) + 1)
            out.append(("thread", thread, int(f[3]), 0))
        elif f[0] == "op":
            frames = max(frames, int(f[1]) + 1)
            out.append(("op", int(f[2]), int(f[3]), int(f[4])))
    return seed, out, frames


def read(z, addr, n):
    raw = z.cmd(f"read-memory {addr} {n}").strip()
    return bytes(int(raw[i:i + 2], 16) for i in range(0, 2 * n, 2))


def main():
    sym = symbols(EXP_ASM, EXP_C)
    seed, want, frames = host_stream(os.path.join(PROBE, "ops.txt"))
    print(f"host stream: {len(want):,} records over {frames} of the probe's frames, "
          f"seed {seed}")

    z = Zrcp()
    print(f"emulator: {z.cmd('get-version')}")
    z.cmd(f"smartload /work/{NEX}")
    time.sleep(3.5)
    z.cmd("set-memory-zone -1")
    if read(z, sym["ready"], 1)[0] != 0x5A:
        raise SystemExit("FAIL: the game never reached its wait loop")

    # It is already ticking and already mixing, before the VM has been let go.
    t0 = int.from_bytes(read(z, sym["ticks"], 2), "little")
    time.sleep(0.5)
    t1 = int.from_bytes(read(z, sym["ticks"], 2), "little")
    ring_boot = read(z, RING, 64)

    hdr = (seed.to_bytes(2, "little") + frames.to_bytes(2, "little")
           + BUDGET.to_bytes(2, "little"))
    z.cmd(f"write-memory-raw {CTL} {hdr.hex()}")
    blob = (CODE_FILE.encode() + bytes(1)).hex()
    z.cmd(f"write-memory-raw {sym['fname']} {blob}")
    z.cmd(f"write-memory {sym['go']} 1")

    fin = CTL + 10
    waited, limit = 0.0, 60.0
    while waited < limit:
        if read(z, fin, 1)[0] == 0x5A:
            break
        time.sleep(0.1)
        waited += 0.1

    def block():
        return read(z, CTL, 32)

    b, b2 = block(), block()
    if b != b2:
        raise SystemExit(f"FAIL: the control block read differently twice: "
                         f"{b.hex()} then {b2.hex()}")
    w = lambda o: int.from_bytes(b[o:o + 2], "little")      # noqa: E731
    records, frames_done = w(6), w(8)
    finished, oob, bad_op, flt = b[10], b[11], b[12], b[13]
    exp_n, div_at = w(20), w(22)
    got_rec, want_rec = b[24:28], b[28:32]
    ticks_end = int.from_bytes(read(z, sym["ticks"], 2), "little")
    ring_run = read(z, RING, 64)
    counts = {n: int.from_bytes(read(z, sym[n], 2), "little")
              for n in ("n_poly", "n_select", "n_fill", "n_copy", "n_blit", "n_pal")}
    n_cmp = min(256, len(want))
    rec_raw = read(z, CTL + 0x20, n_cmp * 4)

    # DID ANYTHING ACTUALLY GET DRAWN? The reader being wired is not the reader working,
    # and a page full of one value is what a fill leaves behind. Sample the page the VM
    # last drew into, across all six of its bands, and count distinct values. This is a
    # weak check on purpose - I2's real gate is the page compared against the engine -
    # but it separates "the callbacks are reached" from "pixels changed", which the call
    # counters cannot.
    pg1 = read(z, sym["pg_ptr1"], 1)[0] & 3
    p0 = (12 + pg1 * 3) * 2
    seen, samples = set(), 0
    for band in range(6):
        z.cmd(f"tbblue-set-register {0x57} {p0 + band}")
        chunk = read(z, 0xE000, 512)
        seen.update(chunk)
        samples += len(chunk)
    n_video2 = int.from_bytes(read(z, sym["n_video2"], 2), "little")
    cp_unimpl = read(z, sym["cp_unimpl"], 1)[0]
    # The palette: did the file arrive, and did a blit apply one? pal=2 in the counters
    # only says op_setPalette was reached, which is not the same as sixteen colours
    # reaching Layer 2.
    pal_file = read(z, 0xCD00, 64)
    pal_now = read(z, sym["pal_now"], 1)[0]
    pal_req = read(z, sym["pal_req"], 1)[0]

    print(f"\nbefore the VM was let go: {t1 - t0} ticks in half a second "
          f"(50 a second is {25} in half)")
    print(f"the VM: {records:,} records over {frames_done + 1} frames in {waited:.1f}s, "
          f"{'finished' if finished == 0x5A else 'DID NOT finish'}")
    print(f"  video calls counted: " + ", ".join(f"{k[2:]}={v}" for k, v in counts.items()))
    print(f"  ticks at the end: {ticks_end}")

    bad = []
    # A LIVENESS check, not a rate check. The emulator with --vo null does not track
    # wall clock closely and the two ZRCP reads around the sleep cost time of their
    # own, so the first run of this measured 19 ticks where 25 was nominal. Whether
    # the interrupt fires at exactly 50 Hz is the display's business and E1 gated the
    # pacing arithmetic already; what this has to catch is an interrupt that is not
    # running at all.
    if (t1 - t0) < 5:
        bad.append(f"the frame interrupt ticked only {t1 - t0} times in half a "
                   f"second - it is not running")
    if ring_boot.count(128) == len(ring_boot):
        bad.append("the ring was still silence after half a second - the mixer "
                   "never ran")
    if ring_run.count(128) == len(ring_run):
        bad.append("the ring is silence after the run - the mixer stopped")
    if ticks_end < frames_done:
        bad.append(f"only {ticks_end} ticks for {frames_done} frames - the VM was "
                   f"not paced by the interrupt")

    if flt == 5:
        print(f"\n  FIRST DIVERGENCE at record {div_at:,} of {exp_n:,}")
        print(f"    the game   {tuple(got_rec)}")
        print(f"    the engine {tuple(want_rec)}")
        raise SystemExit("FAIL: running everything at once changed the opcode stream")
    if flt and not (flt == 6 and records == exp_n):
        why = {1: "the pc left the segment", 2: "resetThread out of range",
               3: "an invalid opcode", 4: "ret with an empty stack"}
        raise SystemExit(f"FAIL: fault {flt} - {why.get(flt, '?')} - after "
                         f"{records:,} records")
    # AT LEAST the reference's length, not exactly it. With the engine's stream no longer
    # inside the .nex there is nothing to stop the VM at record 763, so it runs the frames
    # it was asked for and dispatches whatever they contain - 801 here for 45 frames. What
    # matters is that it got at least as far as the reference and that the records it
    # produced are the engine's, which the prefix comparison below establishes.
    if records < len(want):
        bad.append(f"only {records:,} records, the engine's stream has {len(want):,}")

    # THE STREAM IS STILL CHECKED, but from the trace buffer over ZRCP rather than
    # against a copy inside the .nex. The in-.nex comparison was how I1 was gated and it
    # passed - 763 of 763 - but the rasteriser needs 1,024 reciprocals resident and the
    # resident 16K will not hold the assembly, the C and 2KB of table together, so the
    # engine's stream gave up its 3,052 bytes to the reciprocals. The buffer holds 256
    # records; those are compared here, and I2's page comparison is the stronger claim
    # that replaces the rest.
    cur, norm = 0, []
    for k in range(n_cmp):
        kind, lo, hi, v = rec_raw[k * 4:k * 4 + 4]
        pc = lo | (hi << 8)
        if kind == 2:
            cur = v
            norm.append(("thread", cur, pc, 0))
        elif kind == 1:
            norm.append(("op", cur, pc, v))
        else:
            bad.append(f"record {k} has kind {kind}, which aw_logrec never writes")
            break
    m = 0
    while m < len(norm) and norm[m] == want[m]:
        m += 1
    print(f"  the first {m:,} of {len(norm):,} trace records are the engine's, "
          f"read back over ZRCP")
    print(f"  page {pg1} holds {len(seen)} distinct values over {samples:,} sampled "
          f"bytes: {sorted(seen)[:12]}")
    if n_video2:
        print(f"  {n_video2} draws wanted the video2 segment, which is not loaded yet")
    if cp_unimpl:
        print(f"  a scrolled page copy was asked for and skipped")
    print(f"  palettes loaded: {len(set(pal_file))} distinct bytes in the first 64; "
          f"applied palette {pal_now if pal_now != 0xFF else 'none'}, "
          f"{'none' if pal_req == 0xFF else pal_req} still requested")
    if len(set(pal_file)) < 3:
        bad.append(f"PAL17.BIN did not load: the first 64 bytes hold "
                   f"{sorted(set(pal_file))}")
    if counts["n_pal"] and pal_now == 0xFF:
        bad.append(f"op_setPalette was reached {counts['n_pal']} times and no palette "
                   f"ever reached Layer 2 - the blit is not applying the request")
    if len(seen) < 2:
        bad.append(f"the page the VM drew into holds one value ({sorted(seen)}) - the "
                   f"reader is reached {counts['n_poly']} times and draws nothing")
    if m < len(norm):
        bad.append(f"record {m} differs: the game {norm[m]}, the engine {want[m]}")

    # 4. Left alone: the interrupt and the DMA carry on without the frame loop.
    print(f"\nsoak: left alone for {SOAK_S:.0f}s with the interrupt and the DMA live")
    s0 = int.from_bytes(read(z, sym["ticks"], 2), "little")
    time.sleep(SOAK_S)
    s1 = int.from_bytes(read(z, sym["ticks"], 2), "little")
    b3 = block()
    z.close()
    expect = SOAK_S * 50
    print(f"  ticks advanced {s1 - s0}, expected about {expect:.0f}")
    if not 0.7 * expect <= (s1 - s0) <= 1.3 * expect:
        bad.append(f"the interrupt advanced {s1 - s0} ticks in {SOAK_S:.0f}s, "
                   f"wanted about {expect:.0f} - it is not stable when left alone")
    if b3 != b:
        bad.append("the control block changed during the soak - something is still "
                   "writing to it after the frame loop ended")

    if bad:
        print("\n  " + "\n  ".join(bad))
        raise SystemExit(f"FAIL: {len(bad)} problem(s) with everything running at once")
    print(f"""
PASS: one program, everything live. {records:,} records dispatched, the first {m:,}
      checked record for record against the engine's own, with the
      frame interrupt pacing the VM at 50 Hz, the zxnDMA streaming the ring to the DAC,
      and the mixer refilling it from inside the interrupt - and it holds for
      {SOAK_S:.0f} seconds of being left alone afterwards.""")


if __name__ == "__main__":
    main()
