#!/usr/bin/env python3
"""I2's gate: does the game's own picture match the engine's?

This is the claim I2 exists for. Everything before it proves the callbacks are reached
and that pixels change; this proves the pixels are the RIGHT ones, produced by the VM
dispatching real bytecode rather than by a draw list a checker poked.

THE ALIGNMENT IS A BLIT, and that took a while to see. The VM's frames and the probe's
frames are different quantities - instrFrame hangs off Video::updateDisplay, so what
ops.txt calls a frame is a blit - and 45 of the probe's is 44 of the VM's. But a blit is
the one instant where both sides agree what the frame IS. So the machine is told to stop
after its Kth blit, the reference replays the engine's trace and stops after its Kth, and
the four pages are compared.

When it fails it says where, because "N pixels differ" is not a diagnosis: which page,
the first differing pixel in scanline terms, how the differences cluster by row, and the
most common (ours, theirs) value pairs.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zrcp import Zrcp            # noqa: E402
from refvideo import RefVideo8, replay   # noqa: E402

NEX = "build/aw.nex"
EXP_ASM, EXP_C = "build/aw.exp", "build/aw_vm_c.exp"
PROBE = "preflight/hostprobe/probe"
CODE_FILE = "RES18.BIN"

# WHICH PART. I9a asks for this gate to be re-run against gameplay, and part 2 draws 1,947
# polygons in thirty frames against the intro's 542, with twelve fills against three.
#
# THE TWO SIDES DO NOT START FROM THE SAME PICTURE, which is the obstacle here and is not a
# missing fixture. The probe reaches a later part by JUMPING into it, so its pages carry what
# part 1 left behind; a machine booting through start_part begins with whatever boot left. So
# the reference is replayed from the trace's START - part 1's blits included - and the machine's
# blit K is aligned with trace blit K + SKIP, where SKIP is the number of blits before the part
# change. That is read out of the trace, not assumed.
#
# It is only sound once the picture no longer depends on what preceded it. MEASURED, by replaying
# the same trace from two different starting pictures and finding where they agree: page 0 and
# page 3 differ in all 49,152 bytes at one, two and three blits, and ALL FOUR PAGES ARE IDENTICAL
# AT FIVE. The part change is at blit 3, so any machine blit from 2 onward is past it, and the
# default of 8 is comfortably clear.
AW_PART = os.environ.get("AW_PART", "")
TRACE_FILE = f"trace_part{AW_PART}.bin" if AW_PART else "trace.bin"


def blits_before_part_change(path):
    """How many blits the trace spends in the part it started in."""
    from refvideo import read_trace
    n, seen = 0, 0
    for kind, _ in read_trace(path):
        if kind == "part":
            seen += 1
            if seen == 2:
                return n
        elif kind == "blit":
            n += 1
    return 0
CTL = 0xC000
W, H = 256, 192
PAGE = W * H
BANDS, BAND = 6, 8192
L2_BASE_BANK = 12
NR_MMU7 = 0x57
DWIN = 0xE000
BLITS = int(os.environ.get("AW_BLITS", "8"))


def symbols(*paths):
    out = {}
    for path in paths:
        for line in open(path):
            name, _, val = line.partition(":")
            if "0x" in val:
                out[name.strip()] = int(val.split("0x")[1], 16)
    return out


def host_seed(path):
    for line in open(path):
        f = line.split()
        if f and f[0] == "seed":
            return int(f[1]) & 0xFFFF
    raise SystemExit("no seed in ops.txt")


def read(z, addr, n):
    out = bytearray()
    while len(out) < n:
        k = min(2048, n - len(out))
        raw = z.cmd(f"read-memory {addr + len(out)} {k}").strip()
        out += bytes(int(raw[i:i + 2], 16) for i in range(0, 2 * k, 2))
    return bytes(out)


def machine_page(z, page):
    """One whole Layer 2 page off the machine, through the band window."""
    p0 = (L2_BASE_BANK + page * 3) * 2
    out = bytearray()
    for band in range(BANDS):
        z.cmd(f"tbblue-set-register {NR_MMU7} {p0 + band}")
        out += read(z, DWIN, BAND)
    return bytes(out[:PAGE])


def describe(name, got, want):
    diff = [i for i in range(PAGE) if got[i] != want[i]]
    if not diff:
        return True
    import collections
    print(f"\n  {name}: {len(diff):,} of {PAGE:,} bytes differ "
          f"({100 * len(diff) / PAGE:.2f}%)")
    f = diff[0]
    print(f"    first at row {f // W}, x {f % W}: ours {got[f]:#04x}, "
          f"engine {want[f]:#04x}")
    rows = sorted({i // W for i in diff})
    print(f"    rows {rows[0]}..{rows[-1]} ({len(rows)} of {H}), "
          f"bands {sorted({r // 32 for r in rows})}")
    pairs = collections.Counter((got[i], want[i]) for i in diff)
    print("    commonest (ours, engine): "
          + ", ".join(f"{a:#04x}/{b:#04x} x{n:,}" for (a, b), n in pairs.most_common(4)))
    return False


def main():
    sym = symbols(EXP_ASM, EXP_C)
    seed = host_seed(os.path.join(PROBE, "ops.txt"))
    trace = os.path.join(PROBE, TRACE_FILE)

    # THE REFERENCE REPLAYS THE PART ALONE, and getting this wrong is what made the first
    # version of this gate fail. A trace that JUMPED into part 2 opens with the part the engine
    # was already in, and replaying from its start performs drawing the machine never does - the
    # machine boots straight into part 2 and draws only part 2. Comparing the two then fails for
    # that reason and no other, which is exactly what it did: identical at blits 3, 4 and 5,
    # page 2 wholly different at 6, page 1 wholly different at 7, page 2 at 0.97% by 8.
    #
    # I misread that as the machine arriving "cold" where the engine arrived "warm", and poked
    # the reference's page pointers in to fix it. They came back 2/2/1 - the machine's own
    # defaults - so there was nothing to warm and the theory was wrong.
    #
    # start_at_part=2 skips to the part change, and the question worth asking was then asked
    # properly: replaying PART 2'S RECORDS ALONE from two different starting pictures, all four
    # pages are independent of what came before after ONE blit. Part 2 clears everything it
    # needs. So there is no offset and no warming - the machine's blit K is the part's blit K.
    ref, blits = replay(trace, cls=RefVideo8, stop_after=BLITS,
                        start_at_part=2 if AW_PART else None)
    if blits < BLITS:
        raise SystemExit(f"the trace only holds {blits} blits after the part change, fewer "
                         f"than the {BLITS} asked for - lower AW_BLITS or lengthen the trace")
    print(f"part: {AW_PART or 'the intro'}, trace {TRACE_FILE}")
    print(f"the engine's trace: replayed to blit {blits}, seed {seed}")

    z = Zrcp()
    print(f"emulator: {z.cmd('get-version')}")
    z.cmd(f"smartload /work/{NEX}")
    time.sleep(3.5)
    z.cmd("set-memory-zone -1")
    if read(z, sym["ready"], 1)[0] != 0x5A:
        raise SystemExit("FAIL: the game never reached its wait loop")

    hdr = (seed.to_bytes(2, "little") + (2000).to_bytes(2, "little")
           + (60000).to_bytes(2, "little"))
    z.cmd(f"write-memory-raw {CTL} {hdr.hex()}")
    if AW_PART:
        # THE PART PATH, not the fixed load. A gameplay part needs its own palette and its own
        # polygon segment, and the fixed path carries the intro's - it pokes a bytecode name and
        # then loads fixed poly and palette files beside it.
        z.cmd(f"write-memory {sym['start_part']} {int(AW_PART) + 1}")

        # NOTHING IS POKED INTO THE PAGE POINTERS, and it was worth proving rather than
        # assuming. The engine carries cur1/cur2/cur3 through a part change - initForPart is
        # VM-level and does not touch them - so it looked as though it would arrive in part 2
        # holding something the machine's cold 2/2/1 would not match. Replayed to the part
        # change, they are 2, 2 and 1. The same. There is nothing to warm.
    else:
        z.cmd(f"write-memory-raw {sym['fname']} {(CODE_FILE.encode() + bytes(1)).hex()}")
    z.cmd(f"write-memory-raw {sym['stop_blit']} "
          f"{BLITS.to_bytes(2, 'little').hex()}")
    z.cmd(f"write-memory {sym['go']} 1")

    fin = CTL + 10
    waited = 0.0
    while waited < 120.0:
        if read(z, fin, 1)[0] == 0x5A:
            break
        time.sleep(0.1)
        waited += 0.1
    c = {n: int.from_bytes(read(z, sym[n], 2), "little")
         for n in ("n_blit", "n_poly", "n_select", "n_fill", "n_copy", "n_pal",
                   "n_video2", "rd_bad", "rd_deep", "rd_count")}
    n_blit, n_poly = c["n_blit"], c["n_poly"]
    print(f"the machine: stopped after {n_blit} blits, {waited:.1f}s")
    print("  " + ", ".join(f"{k[2:] if k.startswith('n_') else k}={v}"
                           for k, v in c.items()))
    print(f"  copy last resolved: src p0={read(z, sym['cp_src'], 1)[0]}, "
          f"dst p0={read(z, sym['cp_dst'], 1)[0]} "
          f"(page 0 is p0={(12 + 0 * 3) * 2}, page 1 is {(12 + 1 * 3) * 2}, "
          f"page 2 is {(12 + 2 * 3) * 2})")
    print(f"  pages: drawing into {read(z, sym['pg_ptr1'], 1)[0]}, "
          f"displaying {read(z, sym['pg_ptr2'], 1)[0]}, "
          f"other {read(z, sym['pg_ptr3'], 1)[0]}")
    # The engine's own counts to the same blit, so the two are comparable at a glance.
    import collections
    from refvideo import read_trace
    eng, b = collections.Counter(), 0
    for kind, a in read_trace(trace):
        if kind == "blit":
            b += 1
            if b >= BLITS:
                break
        eng[kind] += 1
    print("  the engine to the same blit: "
          + ", ".join(f"{k}={v}" for k, v in sorted(eng.items())))
    if n_blit != BLITS:
        raise SystemExit(f"FAIL: it stopped after {n_blit} blits, not {BLITS} - the "
                         f"comparison would not be aligned")

    # THE OPERANDS, which nothing has ever compared. Gate D proves the opcode stream and
    # says nothing about what the C computed from it; check-readmachine proves the reader
    # given a poked draw list. This is the seam between them.
    N = min(n_poly, 8)
    raw = read(z, 0xC4A0, N * 10)
    mach = []
    for i in range(N):
        e = raw[i * 10:i * 10 + 10]
        mach.append(dict(page=e[0],
                         off=int.from_bytes(e[1:3], "little"),
                         zoom=int.from_bytes(e[3:5], "little"),
                         x=int.from_bytes(e[5:7], "little", signed=True),
                         y=int.from_bytes(e[7:9], "little", signed=True),
                         colour=e[9]))
    eng = []
    for kind, a in read_trace(trace):
        if kind == "draw":
            eng.append(a)
            if len(eng) >= N:
                break
    print(f"\n  the {N} first draws, machine against engine:")
    first = None
    for i in range(min(len(mach), len(eng))):
        m, e = mach[i], eng[i]
        same = all(m[k] == e.get(k, m[k]) for k in ("off", "zoom", "x", "y"))
        flag = "" if same else "   <-- DIFFERS"
        if not same and first is None:
            first = i
        if i < 8 or not same:
            print(f"    {i:>2} machine off={m['off']:>6} zoom={m['zoom']:>4} "
                  f"x={m['x']:>5} y={m['y']:>5} col={m['colour']:#04x}{flag}")
            print(f"       engine  off={e.get('off'):>6} zoom={e.get('zoom'):>4} "
                  f"x={e.get('x'):>5} y={e.get('y'):>5} col={e.get('colour')}")
    if first is None:
        print("    every one of those draws had the engine's operands")
    else:
        print(f"    FIRST DIFFERING OPERANDS at draw {first}")

    # QUIESCE THE MIXER FIRST. machine_page maps a band into MMU7 and reads it as four ZRCP
    # calls, and MMU7 is shared three ways: the Layer 2 draw band, the loader's staging window
    # and - from I5 - the mixer's sample window, which the interrupt borrows and restores fifty
    # times a second. That is right on the machine and fatal to a reader holding the slot
    # across round trips; it showed as bands 0, 1, 4 and 5 differing from the engine while
    # 2 and 3 were perfect. The run has finished by here, so nothing is drawing.
    z.cmd(f"write-memory {sym['snd_off']} 1")
    time.sleep(0.1)
    pages = [machine_page(z, p) for p in range(4)]
    z.close()

    ok = True
    for p in range(4):
        want = bytes(ref.pages[p])
        if len(want) != PAGE:
            raise SystemExit(f"the reference's page {p} is {len(want)} bytes")
        if describe(f"page {p}", pages[p], want):
            print(f"  page {p}: IDENTICAL  ({PAGE:,} bytes)")
        else:
            ok = False

    if not ok:
        raise SystemExit("FAIL: the game's picture is not the engine's")
    print(f"""
PASS: all four pages identical to the engine's, {4 * PAGE:,} bytes, after {BLITS}
      blits of the intro - drawn by the virtual machine dispatching real bytecode,
      not by a poked draw list. I2 is closed.""")


if __name__ == "__main__":
    main()
