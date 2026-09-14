#!/usr/bin/env python3
"""Turn z88dk's map file into sjasmplus's --exp format.

This is the whole of the glue that lets sjasmplus stay the master assembler
while z88dk compiles the C. Every checker in this project and in wolf3d-next
reads symbol addresses out of an `.exp` file, and none of them should have to
know or care which tool produced a given symbol.

z88dk's -m map looks like this, one symbol a line:

    _door_ticks     = $925C ; addr, public, , doors_c, bss_compiler, doors.c:233
    CHAR_BELL       = $0007 ; const, local, , console_01_output_char_oterm, ...

sjasmplus --exp looks like this:

    draw_count: EQU 0x00008049

Only `addr, public` entries are wanted. `const` entries are compile-time
constants rather than locations, and `local` entries are not addressable from
outside their module, so emitting either would fill the file with thousands of
irrelevant names - a real z88dk map for a 5 KB program runs to about 650,000
bytes and some 30,000 lines.

SDCC prefixes every C identifier with an underscore, so `door_ticks` in the
source is `_door_ticks` in the map. Both spellings are emitted: the bare one
because that is what a person writing a checker will reach for, and the raw one
so a symbol that genuinely begins with an underscore is still findable.

    python3 tools/mkexp.py build/vm.map build/vm.exp
"""

import re
import sys

# _name = $XXXX ; addr, public, ...
LINE = re.compile(
    r"^\s*(?P<name>\S+)\s*=\s*\$(?P<addr>[0-9A-Fa-f]+)\s*;\s*"
    r"(?P<kind>\w+)\s*,\s*(?P<scope>\w+)")


def append_cc_top(map_path, exp_path):
    """Emit CC_TOP: the highest address the C occupies, which is NOT its image end.

    sjasmplus reports the size of the C's image, and the assembly asserted MUSIC_CODE against
    that - but the C's BSS lives ABOVE the image and is not in it. With a 3-byte margin the music
    and text code landed inside the C's variables, and the VM dispatched thirteen records and
    stopped; the assertion saw nothing wrong because the image did fit. This makes the real top
    visible so the assertion can compare against it and the build fails loudly instead.

    The highest symbol plus eight: a symbol's address is its start, and the map does not give
    sizes, so eight covers the largest single object the compiler places last.
    """
    hi, who = 0, ""
    for line in open(map_path, errors="replace"):
        m = LINE.match(line)
        if not m or m.group("kind") != "addr":
            continue
        a = int(m.group("addr"), 16)
        if 0x8000 <= a < 0xC000 and a > hi:
            hi, who = a, m.group("name")
    if hi:
        with open(exp_path, "a") as fh:
            fh.write(f"; the C's highest address is {who} at 0x{hi:04X} - its BSS, which is NOT\n")
            fh.write("; in the image sjasmplus measures. Plus eight, for the object's own size.\n")
            fh.write(f"CC_TOP: EQU 0x{hi + 8:04X}\n")
        print(f"  CC_TOP = 0x{hi + 8:04X}  (highest is {who} at 0x{hi:04X})")
    return hi


def convert(map_path, exp_path=None, want_kind="addr", want_scope="public"):
    """Returns the lines written. exp_path=None just returns them."""
    seen = {}
    order = []
    total = 0
    for line in open(map_path, errors="replace"):
        m = LINE.match(line)
        if not m:
            continue
        total += 1
        if m.group("kind") != want_kind or m.group("scope") != want_scope:
            continue
        name = m.group("name")
        addr = int(m.group("addr"), 16)
        for spelling in ({name, name.lstrip("_")} if name.startswith("_")
                         else {name}):
            if not spelling:
                continue
            # A duplicate name at a different address is worth knowing about
            # rather than silently taking the last one.
            if spelling in seen and seen[spelling] != addr:
                print(f"mkexp: {spelling} appears at both "
                      f"0x{seen[spelling]:04X} and 0x{addr:04X}, keeping the "
                      f"first", file=sys.stderr)
                continue
            if spelling not in seen:
                seen[spelling] = addr
                order.append(spelling)

    lines = [f"{n}: EQU 0x{seen[n]:08X}\n" for n in order]
    if exp_path:
        with open(exp_path, "w") as fh:
            fh.writelines(lines)
    return lines, total


def main():
    if len(sys.argv) < 2:
        raise SystemExit("usage: mkexp.py <in.map> [out.exp]")
    src = sys.argv[1]
    dst = sys.argv[2] if len(sys.argv) > 2 else src.rsplit(".", 1)[0] + ".exp"
    lines, total = convert(src, dst)
    top = append_cc_top(src, dst)
    print(f"{src}: {total:,} symbols read, {len(lines)} public addresses "
          f"written to {dst}")
    for line in lines[:12]:
        print("  " + line.rstrip())
    if len(lines) > 12:
        print(f"  ... and {len(lines) - 12} more")


if __name__ == "__main__":
    main()
