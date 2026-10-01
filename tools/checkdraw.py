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
from refvideo import RefVideo8, RefVideo320, replay   # noqa: E402

# THE SCREEN: 320x256 unless AW_SCREEN=256 asks for the earlier 256x192 build (docs/plan-wide320.md W3): build/aw.nex (aw256.nex for 256x192), pages of ten 8K column
# strips turned back into 320x200 rows, against RefVideo320 with the engine's own 8x8 font.
WIDE = os.environ.get("AW_SCREEN", "320") != "256"
REF = RefVideo320 if WIDE else RefVideo8

NEX = "build/aw.nex" if WIDE else "build/aw256.nex"
EXP_ASM, EXP_C = ("build/aw.exp" if WIDE else "build/aw256.exp"), "build/aw_vm_c.exp"
# AW_PROBE_DIR points the gate at a different probe run - a longer trace, say - without
# touching the committed one. The default is the committed run.
PROBE = os.environ.get("AW_PROBE_DIR") or "preflight/hostprobe/probe"
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
W, H = (320, 200) if WIDE else (256, 192)
PAGE = W * H
BANDS, BAND = (10 if WIDE else 6), 8192
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
    p0 = (L2_BASE_BANK + page * (5 if WIDE else 3)) * 2
    out = bytearray()
    for band in range(BANDS):
        z.cmd(f"tbblue-set-register {NR_MMU7} {p0 + band}")
        out += read(z, DWIN, BAND)
    if WIDE:
        return bytes(out[x * 256 + y] for y in range(H) for x in range(W))
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
    # THE MACHINE'S FONT, not the probe's. The machine draws six-pixel glyphs from font6.bin, five
    # of them redrawn by hand (tools/mkfont6.py); replay's default is the original 8x8 font.bin,
    # whose first six columns differ for exactly those glyphs. check-text already compares this way.
    # No trace reached text until the intro gate went past frame 1,122.
    ref, blits = replay(trace, cls=REF, stop_after=BLITS,
                        start_at_part=2 if AW_PART else None,
                        font=open("preflight/hostprobe/probe/font.bin" if WIDE else "build/font6.bin", "rb").read())
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

    # AW_TEXTPAGE=1: read TEXT_PAGE (page 1: the font, the strings, the palettes) before the VM runs
    # and again when it stops, and say which ranges changed. Palettes at $EE00 are loaded as parts
    # change; nothing else in that page is ever meant to.
    text_before = None
    if os.environ.get("AW_TEXTPAGE"):
        z.cmd(f"tbblue-set-register {NR_MMU7} 1")
        text_before = read(z, DWIN, 8192)

    # THE FRAME CAP HAS TO REACH THE BLIT. It was a flat 2,000, which no gate noticed until the intro
    # gate asked for blit 2,100 and the VM stopped, as told, at 2,002.
    hdr = (seed.to_bytes(2, "little") + max(2000, BLITS + 200).to_bytes(2, "little")
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
    # AW_AUTOPLAY=1 runs the machine's synthetic player, for a reference the probe recorded with
    # its own autoplay on - gameplay that nobody plays stands still and draws nothing worth testing.
    if os.environ.get("AW_AUTOPLAY"):
        z.cmd(f"write-memory {sym['autoplay']} 1")
    z.cmd(f"write-memory-raw {sym['stop_blit']} "
          f"{BLITS.to_bytes(2, 'little').hex()}")
    z.cmd(f"write-memory {sym['go']} 1")

    fin = CTL + 10
    waited = 0.0
    while waited < max(120.0, BLITS * 1.0):   # a long intro run takes longer than 45 blits
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
    if text_before is not None:
        z.cmd(f"tbblue-set-register {NR_MMU7} 1")
        text_after = read(z, DWIN, 8192)
        diff = [i for i in range(8192) if text_before[i] != text_after[i]]
        runs, start = [], None
        for i in range(8193):
            inside = i < 8192 and text_before[i] != text_after[i]
            if inside and start is None:
                start = i
            if not inside and start is not None:
                runs.append((start, i)); start = None
        print(f"  TEXT_PAGE: {len(diff)} bytes changed since boot, in {len(runs)} runs: "
              + ", ".join(f"${0xE000 + a:04X}-${0xE000 + b - 1:04X}" for a, b in runs[:12]))
        if runs:
            a = runs[0][0]
            print(f"    before ${0xE000 + a:04X}: {text_before[a:a + 32].hex(' ')}")
            print(f"    after  ${0xE000 + a:04X}: {text_after[a:a + 32].hex(' ')}")
            import collections
            vals = collections.Counter(text_after[i] for i in diff if i < 0xE00)
            print(f"    commonest new values below $EE00: {vals.most_common(8)}")
    if n_blit != BLITS:
        # SAY WHY. A machine that stops early has left its reason in the control block, and
        # "stopped after 217" alone sent a run hunting in the wrong place.
        ctl = read(z, CTL, 0x18)
        w = lambda o: int.from_bytes(ctl[o:o + 2], "little")
        print(f"  control block: frames {w(2)}, budget {w(4)}, records {w(6)}, frames done {w(8)}, "
              f"finished {ctl[0x0A]:#04x}, out of budget {ctl[0x0B]}, bad op {ctl[0x0C]}, "
              f"fault {ctl[0x0D]}, fault pc {w(0x0E):#06x}, code len {w(0x10)}, fault a {w(0x12):#06x}, "
              f"div at {w(0x16)}")
        print(f"  waited {waited:.1f}s; ticks {int.from_bytes(read(z, sym['ticks'], 2), 'little')}")
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
    mach_ptrs = [int(z.cmd(f"read-memory {sym[n]} 1").strip(), 16)
                 for n in ("pg_ptr1", "pg_ptr2", "pg_ptr3")]
    z.close()

    if AW_PART:
        # THE POINTERS, EVERY RUN, not only on failure. $FF resolves through pg_ptr3 and a blit
        # of $FF swaps the pair, so a divergence here can appear, do its damage through one fill,
        # and RE-SYNCHRONISE before the comparison ever looks - which is why sampling them only
        # when the pixels disagree found them already back in step.
        #
        # The reference's cur1 is NOT comparable: neither trace contains a single `select`
        # record, so the replay never learns a work page and takes each polygon's destination
        # from the poly record instead. cur2 and cur3 are real.
        print(f"  pointers: machine pg_ptr2={mach_ptrs[1]} pg_ptr3={mach_ptrs[2]}   "
              f"reference cur2={ref.cur2} cur3={ref.cur3}"
              + ("   <-- DIVERGED" if (mach_ptrs[1], mach_ptrs[2]) != (ref.cur2, ref.cur3)
                 else ""))

    ok = True
    for p in range(4):
        want = bytes(ref.pages[p])
        if len(want) != PAGE:
            raise SystemExit(f"the reference's page {p} is {len(want)} bytes")
        if describe(f"page {p}", pages[p], want):
            print(f"  page {p}: IDENTICAL  ({PAGE:,} bytes)")
        else:
            ok = False

    # WHEN IT FAILS, ASK WHETHER IT IS MERELY OUT OF STEP. The machine cannot be stopped before
    # its third blit - it performs blits while the part is set up that the reference's records
    # for that part do not contain - so the machine's blit K need not be the part's blit K. That
    # is an OFFSET and an offset is measurable: replay the reference to the neighbouring counts
    # and see whether any matches byte for byte. A gate that reports "wrong" when it means "out
    # of step by one" sends the next session hunting a rasteriser bug that is not there, which is
    # a mistake this gate has already made twice today.
    if not ok and AW_PART:
        # THE POINTERS, WHICH THIS GATE HAS NEVER COMPARED. $FF resolves through pg_ptr3 and
        # $FE through pg_ptr2, and a blit of $FF SWAPS them - so one blit more or fewer inverts
        # the pair for the rest of the run, and every later fill or copy through $FF lands on
        # the other page. That is exactly the shape of a whole page differing while the other
        # three match, and of the wrong page alternating between one comparison and the next.
        # Pixels cannot say it; these three bytes can.


        print(f"\n  the page pointers at this blit:")
        print(f"    machine   pg_ptr1={mach_ptrs[0]} pg_ptr2={mach_ptrs[1]} "
              f"pg_ptr3={mach_ptrs[2]}")
        print(f"    reference cur1={ref.cur1} cur2={ref.cur2} cur3={ref.cur3}")
        if (mach_ptrs[1], mach_ptrs[2]) == (ref.cur3, ref.cur2):
            print("    THE PAIR IS INVERTED - one $FF blit more or fewer than the engine")
        print("\n  out of step, or wrong? the reference replayed either side:")
        for delta in (-3, -2, -1, 1, 2, 3):
            n = BLITS + delta
            if n < 1:
                continue
            alt, got_n = replay(trace, cls=REF, stop_after=n, start_at_part=2)
            if got_n < n:
                continue
            same = [q for q in range(4) if bytes(alt.pages[q]) == pages[q]]
            verdict = ("ALL FOUR IDENTICAL - out of step by "
                       f"{delta:+d}, not wrong") if len(same) == 4 else f"pages agreeing: {same}"
            print(f"    reference blit {n:>2} (machine {BLITS}{delta:+d}): {verdict}")
            if len(same) == 4:
                break

    if not ok:
        raise SystemExit("FAIL: the game's picture is not the engine's")
    print(f"""
PASS: all four pages identical to the engine's, {4 * PAGE:,} bytes, after {BLITS}
      blits of the intro - drawn by the virtual machine dispatching real bytecode,
      not by a poked draw list. I2 is closed.""")


if __name__ == "__main__":
    main()
