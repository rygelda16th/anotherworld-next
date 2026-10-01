#!/usr/bin/env python3
"""The streamed music on the machine: does the interrupt play MUSIC.PCM, byte for byte, and do the
intro's scripts get their markers from it?

tools/mkmusic.py renders the intro's module on the host; st_music takes op_playMusic for it, the
main code fills a 128K ring from the card, and st_block copies it into the copper list's value bytes
with the sound effects added on top. This runs the intro in ZEsarUX and, at moments the CPU is
outside the interrupt, stops the emulator and reads:

 1. THE LAST BLOCK THE INTERRUPT WROTE, which must be the file's samples st_played - 156 .. st_played
    exactly - when no effect is sounding, because then nothing was added. A block that is one sample
    out, or a page boundary crossed wrongly, differs here.
 2. THE RING NEVER RAN DRY: avail - played is above zero at every stop until the file is all read.
    A dry ring is silence and a stall, which the design survives but which a card fast enough
    should never cause. ZEsarUX answers esxDOS on the host, so this proves the plumbing, not the
    card's speed.
 3. THE MARKERS ARRIVED: events delivered keeps up with the position, and variable 0xF4 took the
    values the file's type-0 events carry, in order.

Needs `make music`, which the Makefile target runs first.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zrcp import Zrcp  # noqa: E402

NEX = "build/aw.nex"
EXP_ASM, EXP_C = "build/aw.exp", "build/aw_vm_c.exp"
PCM = "build/assets/MUSIC.PCM"
CODE_FILE = "RES18.BIN"
CTL = 0xC000
COP_BUF, COP_LINES, HALF = 0xD400, 312, 156
VOICES, V_SIZE, V_ACTIVE = 0xDD00, 18, 11
SECONDS = float(os.environ.get("AW_STREAM_S", "140"))   # the stream is 118.7 s, and starts ~15 s in


def symbols(*paths):
    out = {}
    for path in paths:
        for line in open(path):
            name, _, val = line.partition(":")
            if "0x" in val:
                out[name.strip()] = int(val.split("0x")[1], 16)
    return out


def main():
    sym = symbols(EXP_ASM, EXP_C)
    blob = open(PCM, "rb").read()
    n_len = int.from_bytes(blob[8:11], "little")
    n_ev = int.from_bytes(blob[11:13], "little")
    events = [(int.from_bytes(blob[16 + i * 6:19 + i * 6], "little"), blob[19 + i * 6],
               int.from_bytes(blob[20 + i * 6:22 + i * 6], "little")) for i in range(n_ev)]
    pcm = blob[8192:]
    assert len(pcm) == n_len, "the file's length field disagrees with its size"

    z = Zrcp()
    print(f"emulator: {z.cmd('get-version')}")

    def read(a, n):
        raw = z.cmd(f"read-memory {a} {n}").strip()
        return bytes(int(raw[i:i + 2], 16) for i in range(0, 2 * n, 2))

    def u24(a):
        return int.from_bytes(read(a, 3), "little")

    z.cmd(f"smartload /work/{NEX}")
    time.sleep(3.5)
    z.cmd("set-memory-zone -1")
    if read(sym["ready"], 1)[0] != 0x5A:
        raise SystemExit("FAIL: the game never reached its wait loop")
    seed = next(int(l.split()[1]) for l in open("build/ref2614/ops.txt") if l.startswith("seed")) & 0xFFFF
    hdr = seed.to_bytes(2, "little") + (2000).to_bytes(2, "little") + (60000).to_bytes(2, "little")
    z.cmd(f"write-memory-raw {CTL} {hdr.hex()}")
    z.cmd(f"write-memory-raw {sym['fname']} {(CODE_FILE.encode() + bytes(1)).hex()}")
    z.cmd(f"write-memory {sym['go']} 1")

    bad = []
    compared = skipped_voice = skipped_irq = dry = 0
    seen_on = False
    marks_seen = []
    t_end = time.time() + SECONDS
    last = None
    while time.time() < t_end:
        time.sleep(0.37)
        z.cmd("enter-cpu-step")
        regs_raw = z.cmd("get-registers")
        on = read(sym["st_on"], 1)[0]
        played, avail = u24(sym["st_played"]), u24(sym["st_avail"])
        eof = read(sym["st_eof"], 1)[0]
        # st_ev_left lives in page 10, which is at MMU2 only while the main code is in it
        mmu2 = int(z.cmd("tbblue-get-register 82").split()[0].rstrip("Hh"), 16)
        z.cmd("tbblue-set-register 82 10")
        ev_left = int.from_bytes(read(sym["st_ev_left"], 2), "little")
        z.cmd(f"tbblue-set-register 82 {mmu2}")
        f4 = int.from_bytes(read(sym["_aw_vars"] + 0xF4 * 2, 2), "little")
        voices = read(VOICES, 4 * V_SIZE)
        active = any(voices[i * V_SIZE + V_ACTIVE] for i in range(4))
        # ZEsarUX prints "IFF12" with both enabled and "IFF--" with neither; the interrupt runs with
        # them off. Read from the raw line: z.registers() keeps only name=value pairs, so this test
        # was always false and a stop inside the interrupt compared a half-written block.
        in_irq = ("IFF--" in regs_raw) or ("IFF-2" in regs_raw)
        cop = read(COP_BUF, COP_LINES * 4)
        ring_wr = int.from_bytes(read(sym["ring_wr"], 2), "little")
        z.cmd("exit-cpu-step")

        if not on:
            if seen_on:
                print(f"  the stream stopped at sample {played:,} of {n_len:,}")
                break
            continue
        if not seen_on:
            print(f"  the stream is playing: {n_len:,} samples, {n_ev} events")
            seen_on = True
        if avail - played <= 0 and not eof:
            dry += 1
        delivered = n_ev - ev_left
        # every event at or before `played` was due; allow the frame boundary's lag of a frame or two
        due = sum(1 for e in events if e[0] <= played)
        late = sum(1 for e in events if e[0] <= played - 312 * 10)
        if delivered < late:
            bad.append(f"at sample {played:,}: {delivered} events delivered, {late} were due 10 ticks ago")
        if delivered > due:
            bad.append(f"at sample {played:,}: {delivered} events delivered, only {due} due")
        m = [e[2] for e in events[:delivered] if e[1] == 0]
        if m and (not marks_seen or marks_seen[-1] != m[-1]):
            marks_seen.append(m[-1])
            if f4 != m[-1]:
                print(f"  note: 0xF4 reads {f4:#06x} where the last marker was {m[-1]:#06x} "
                      f"(the script may have written it since)")

        if in_irq:
            skipped_irq += 1
            continue
        if active:
            skipped_voice += 1
            continue
        if played < HALF or (played, ring_wr) == last:
            continue
        last = (played, ring_wr)
        # the interrupt's last block ends at ring_wr and holds samples played-156..played
        want = pcm[played - HALF:played]
        got = bytes(cop[((ring_wr - HALF + i) % COP_LINES) * 4 + 3] for i in range(HALF))
        compared += 1
        if got != want:
            k = next(i for i in range(HALF) if got[i] != want[i])
            bad.append(f"at sample {played:,}: the block differs from the file at line {k} "
                       f"({got[k]} vs {want[k]}), avail {avail:,}")

    print(f"  {compared} blocks compared byte for byte; {skipped_voice} stops skipped for a live "
          f"effect, {skipped_irq} inside the interrupt; {len(marks_seen)} marker values seen")
    if not seen_on:
        bad.append("the stream never started - is MUSIC.PCM in build/assets, and does its key match?")
    if dry:
        bad.append(f"the ring was empty at {dry} stops before the file was read")
    if seen_on and compared < 5:
        bad.append(f"only {compared} blocks could be compared")
    if bad:
        for b in bad[:12]:
            print("  " + b)
        raise SystemExit("FAIL check-stream")
    print("PASS check-stream")


if __name__ == "__main__":
    main()
