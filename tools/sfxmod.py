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
