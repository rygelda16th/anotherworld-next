#!/usr/bin/env python3
"""The music module format, decoded - the reference I5 has to be gated against.

NOTHING in this project parses a module. check-snd proves the MIXER's arithmetic against a
synthetic ramp, and the plan had I5 down as wiring; it is not. sfxplayer.cpp reads a format
that has no counterpart here, and before a line of Z80 is written there has to be something
that says what the right answer is.

THE LAYOUT, from loadSfxModule and prepareInstruments (sfxplayer.cpp), big-endian throughout:

    0x00  delay, a word. The default event delay if op_playMusic passes zero.
    0x02  fifteen instruments, four bytes each: a resource number and a volume, both words.
          A resource number of zero means the slot is unused.
    0x3E  numOrder, a word: how many entries of the order table are played.
    0x40  the order table, 0x80 bytes. Each entry selects a 1024-byte pattern block.
    0xC0  the pattern blocks themselves.

A pattern block is 1024 bytes: 64 rows of four channels of four bytes. Each channel's four
bytes are two big-endian words, note_1 and note_2 - and note_1 of 0xFFFD is the marker
handlePattern tests first, while the instrument is the top nibble of note_2.

    python3 tools/sfxmod.py build/assets/RES07.BIN
"""
import sys

# 7159092 * 256 / (2 * rate), at the copper's 312 lines * 50 Hz = 15,600 Hz. It was 41891, at the
# DMA's 21,875 Hz, until the copper took the DAC over. = NOTE_NUM in src/aw.asm.
NOTE_NUM = 58741
RATE = 312 * 50


def be16(b, o):
    return (b[o] << 8) | b[o + 1]


def parse(blob):
    m = {
        "delay": be16(blob, 0),
        "num_order": be16(blob, 0x3E),
        "order": list(blob[0x40:0xC0]),
        "instruments": [],
    }
    for i in range(15):
        o = 2 + i * 4
        m["instruments"].append({"res": be16(blob, o), "volume": be16(blob, o + 2)})
    m["patterns_at"] = 0xC0
    used = sorted(set(m["order"][:m["num_order"]]))
    m["blocks_used"] = used
    m["bytes_needed"] = 0xC0 + (max(used) + 1) * 1024 if used else 0xC0
    return m


def rows(blob, block, n=4):
    """The first n rows of a pattern block: four channels of note_1, note_2."""
    base = 0xC0 + block * 1024
    out = []
    for r in range(n):
        chans = []
        for ch in range(4):
            o = base + r * 16 + ch * 4
            chans.append((be16(blob, o), be16(blob, o + 2)))
        out.append(chans)
    return out


def walk(blob, pos=0, ticks=1):
    """handleEvents, sfxplayer.cpp, as a model: what the order and position become, and how
    many notes and channel-stops the rows contain.

    The machine has to agree with this or its music is in the wrong place, which is the one
    sound fault a listener cannot fail to notice."""
    m = parse(blob)
    cur_order, cur_pos = pos, 0
    events = notes = stops = marks = 0
    playing = True
    for _ in range(ticks):
        if not playing:
            break
        events += 1
        order = m["order"][cur_order]
        base = 0xC0 + cur_pos + order * 1024
        for ch in range(4):
            o = base + ch * 4
            n1, n2 = be16(blob, o), be16(blob, o + 2)
            if n1 == 0xFFFD:
                marks += 1
            elif n1 == 0xFFFE:
                stops += 1
            elif n1 != 0:
                notes += 1
        cur_pos += 16
        if cur_pos >= 1024:
            cur_pos = 0
            cur_order += 1
            if cur_order == m["num_order"]:
                playing = False
    return {"order": cur_order, "pos": cur_pos, "events": events,
            "notes": notes, "stops": stops, "marks": marks, "playing": playing}


def voices(blob, sample_of, pos=0, ticks=1, split=32):
    """What the four voices should look like after a walk. The model for I5's voice setup.

    sample_of(res) must return that resource's own bytes, because a sample's shape is in its
    first four bytes: sampleLen at 0 and loopLen at 2, both big-endian words doubled, with the
    data starting at byte 8. The reference plays 0..sampleLen and then jumps to loopPos =
    sampleLen for loopLen, which is the same as playing 0..sampleLen+loopLen once and looping
    back to sampleLen.
    """
    m = parse(blob)
    chans = [dict(active=0, inc=0, total=0, loop=0, vol=0) for _ in range(4)]
    cur_order, cur_pos, playing = pos, 0, True
    for _ in range(ticks):
        if not playing:
            break
        order = m["order"][cur_order]
        base = 0xC0 + cur_pos + order * 1024
        for ch in range(4):
            o = base + ch * 4
            n1, n2 = be16(blob, o), be16(blob, o + 2)
            if n1 == 0xFFFE:
                chans[ch]["active"] = 0
                continue
            if n1 in (0, 0xFFFD):
                continue
            # A NOTE ONLY PLAYS IF THIS ROW NAMES AN INSTRUMENT. handlePattern's pat is a
            # local memset to zero each call, so pat.sampleBuffer is set only inside the
            # `if (sample != 0)` block and the play is guarded by `sampleBuffer != 0`. A zero
            # instrument nibble means the row is ignored - there is no carry-over.
            idx = (n2 & 0xF000) >> 12
            if not idx:
                continue
            ins = m["instruments"][idx - 1]
            if not ins["res"]:
                continue
            data = sample_of(ins["res"])
            if data is None:
                continue
            # prepareInstruments zeroes data+8..data+11 on every instrument it loads
            # (sfxplayer.cpp:89), so a module note opens on four samples of silence. It does
            # not change any field compared here, but the mixer gate will need it.
            slen = be16(data, 0) * 2
            llen = be16(data, 2) * 2
            vol = ins["volume"] & 0xFF
            eff = (n2 & 0x0F00) >> 8
            amt = n2 & 0xFF
            if eff == 5:
                vol = min(0x3F, vol + amt)
            elif eff == 6:
                vol = max(0, vol - amt)
            chans[ch]["total"] = 8 + slen + llen
            chans[ch]["loop"] = (8 + slen) if llen and (8 + slen) < 0x2000 else 0
            chans[ch]["vol"] = vol
            chans[ch]["inc"] = NOTE_NUM // n1
            chans[ch]["active"] = 1
        cur_pos += 16
        if cur_pos >= 1024:
            cur_pos = 0
            cur_order += 1
            if cur_order == m["num_order"]:
                playing = False
    return chans


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "build/assets/RES07.BIN"
    blob = open(path, "rb").read()
    m = parse(blob)
    print(f"{path}: {len(blob):,} bytes")
    print(f"  default delay {m['delay']} -> {m['delay'] * 60 // 7050} ms an event "
          f"(the reference's delay * 60 / 7050)")
    print(f"  numOrder {m['num_order']}, order table uses blocks {m['blocks_used']}")
    print(f"  needs {m['bytes_needed']:,} bytes for its patterns; the file has "
          f"{len(blob):,}"
          + ("  OK" if m["bytes_needed"] <= len(blob) else "  !! TRUNCATED"))
    live = [(i + 1, ins) for i, ins in enumerate(m["instruments"]) if ins["res"]]
    print(f"  {len(live)} instruments in use:")
    for n, ins in live:
        print(f"    {n:>2}: resource {ins['res']:#04x}, volume {ins['volume']}")
    print(f"  order table, first 24 of {m['num_order']}: "
          f"{m['order'][:24]}")
    print("  first four rows of the first block played:")
    first = m["order"][0]
    for r, chans in enumerate(rows(blob, first)):
        cells = []
        for n1, n2 in chans:
            if n1 == 0xFFFD:
                cells.append("  MARK  ")
            elif n1 == 0 and n2 == 0:
                cells.append("   --   ")
            else:
                cells.append(f"{n1:04X}/{n2 >> 12:X}{n2 & 0xFFF:03X}")
        print(f"    row {r}: " + "  ".join(cells))
    return m


if __name__ == "__main__":
    main()


def sound(data, freq_idx, vol, incs):
    """snd_playSound, vm.cpp:692 - what one op_playSound should leave in a voice.

    The shape comes from the sample's own first four bytes, exactly as the module path reads
    them: sampleLen at 0 and loopLen at 2, both big-endian words doubled, data from byte 8
    (vm.cpp:708-713). `loop` is an OFFSET from the page the sample starts in, which is what
    V_LOOP holds minus SAMP_WIN, and it is zero when the loop point is past the window - the
    same convention voices() uses.

    Two things differ from a module note and nothing else does. The pitch is a table lookup
    rather than a divide - frequenceTable[freq] through the mixer's (freq << 8) / rate, which
    `incs` has already reduced - and prepareInstruments' four zero bytes at data+8 are NOT
    applied, because that belongs to loading a module (sfxplayer.cpp:89) and not to playing a
    plain sound.

    Volume zero is not a quiet note: it stops the channel and does nothing else
    (vm.cpp:702-704).
    """
    if vol == 0:
        return dict(active=0, inc=0, total=0, loop=0, vol=0)
    slen = be16(data, 0) * 2
    llen = be16(data, 2) * 2
    return dict(active=1,
                inc=incs[freq_idx],
                total=8 + slen + llen,
                loop=(8 + slen) if llen and (8 + slen) < 0x2000 else 0,
                vol=min(vol, 0x3F))


def mix_ring(data, inc, volume, nblocks, blocklen, ring_len=2048, start=8):
    """The ring the mixer must hold after `nblocks` blocks of one voice, from a REAL sample.

    This is the piece check-snd cannot reach. Its model computes every sample as `pos & 0xFF` -
    a synthetic ramp, one resident page, no stepping and no loop - so the mixer has only ever
    been proven on a sample it never has to walk out of. A real one does: the game's largest is
    22,690 bytes, which is three 8K pages, and `voice_run` cuts each block at the window's edge
    while `voice_advance` steps `V_PAGE` and rewinds `V_POS`.

    So the model here is deliberately NOT a transcription of that splitting - it is the meaning
    the splitting has to add up to. One flat offset into the sample, stepped in 8.8, each byte
    through the volume table and biased to the DAC's centre; where the machine crosses a page is
    the machine's business and the whole point of the comparison.

    `volume` is 48 for the loud table and 24 for the quiet one (VOLUME and VOLUME_QUIET in
    src/aw.asm), and the scale is scale_byte's, which check-mix gates: mixer.cpp:141's
    clamp((int8)b * VOLUME / 64), truncating towards zero.
    """
    def scale(b):
        v = b - 256 if b >= 128 else b
        m = min(abs(v) * volume >> 6, 127)
        return (-m if v < 0 else m) & 0xFF

    ring = bytearray(b"\x80" * ring_len)
    pos, w = start << 8, 0
    for _ in range(nblocks * blocklen):
        off = pos >> 8
        if off >= len(data):
            break                       # the voice would have stopped; no case here reaches it
        ring[w] = scale(data[off]) ^ 0x80
        w = (w + 1) % ring_len
        pos += inc
    return bytes(ring)
