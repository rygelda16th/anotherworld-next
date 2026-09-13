#!/usr/bin/env python3
"""I4: does the machine draw the game's text the way the reference does?

drawString is driven DIRECTLY - a string id, colour and position poked in, the C never
entered - because the VM cannot reach any text on a deterministic path: text needs input,
and every gate's trace is input-free so the opcode streams stay reproducible. With autoplay
on the protection screen draws 2,378 glyphs in 400 frames, so text is reachable, just not
where anything else measures.

Both sides use the same 6x8 font and the same 40-cells-of-six geometry, so this is a real
comparison and not a tautology: the machine reads font6.bin out of a banked page and walks
the dictionary by bisection, while the reference indexes Python dicts. Only the pixels are
shared.
"""
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zrcp import Zrcp                       # noqa: E402
from refvideo import RefVideo8              # noqa: E402
from mkstrings import ENTRY, unescape       # noqa: E402

NEX = "build/aw.nex"
EXP_ASM, EXP_C = "build/aw.exp", "build/aw_vm_c.exp"
STR_BLOCK = 0xD330
W, H = 256, 192
PAGE = W * H
NR_MMU7, DWIN = 0x57, 0xE000

# Chosen to exercise the cases that break: a plain string, one with a newline, the longest
# one in the table, a lowercase-heavy one for the hand-drawn m and w, and cell 34 to prove
# the right-hand cells are reachable at all - which is the whole reason for a six-pixel cell.
CASES = [
    (0x001, 9, 0, 16),
    (0x002, 12, 2, 24),      # three newlines
    (0x264, 7, 0, 40),       # the longest, 174 characters
    (0x003, 15, 34, 64),     # far right: impossible with eight-pixel cells
    (0x006, 3, 20, 100),
]


def symbols(*paths):
    out = {}
    for path in paths:
        for line in open(path):
            name, _, val = line.partition(":")
            if "0x" in val:
                out[name.strip()] = int(val.split("0x")[1], 16)
    return out


def strings():
    text = open("preflight/hostprobe/probe/staticres.cpp", errors="replace").read()
    start = text.index("_stringsTableEng[]")
    body = text[start:text.index("};", start)]
    out = {}
    for m in ENTRY.finditer(body):
        sid = int(m.group(1), 16)
        out.setdefault(sid, unescape(m.group(2)))
    return out


def ref_draw_string(v, font, colour, cx, y, s):
    """drawString, video.cpp:267-297: a newline moves down eight and back to the start."""
    x0 = cx
    for ch in s:
        if ch == "\n":
            y += 8
            cx = x0
            continue
        v.draw_char(ord(ch), cx, y, colour, font)
        cx += 1


def main():
    sym = symbols(EXP_ASM, EXP_C)
    font = open("build/font6.bin", "rb").read()
    tbl = strings()
    z = Zrcp()
    print(f"emulator: {z.cmd('get-version')}")

    def read(a, n):
        out = bytearray()
        while len(out) < n:
            k = min(2048, n - len(out))
            raw = z.cmd(f"read-memory {a + len(out)} {k}").strip()
            out += bytes(int(raw[i:i + 2], 16) for i in range(0, 2 * k, 2))
        return bytes(out)

    bad, done = [], 0
    for sid, colour, cx, y in CASES:
        if sid not in tbl:
            bad.append(f"string {sid:#05x} is not in the reference's table")
            continue
        s = tbl[sid]

        z.cmd(f"smartload /work/{NEX}")
        time.sleep(3.2)
        z.cmd("set-memory-zone -1")
        blk = bytes([colour, cx, y, 0]) + sid.to_bytes(2, "little")
        z.cmd(f"write-memory-raw {STR_BLOCK} {blk.hex()}")
        z.cmd(f"write-memory {sym['pg_ptr1']} 0")
        z.cmd(f"write-memory {sym['probe_str']} 1")
        z.cmd(f"write-memory-raw {sym['fname']} {(b'RES18.BIN' + bytes(1)).hex()}")
        z.cmd(f"write-memory {sym['go']} 1")
        for _ in range(400):
            if read(sym["done"], 1)[0] == 0x5A:
                break
            time.sleep(0.05)
        got = bytearray()
        for band in range(6):
            z.cmd(f"tbblue-set-register {NR_MMU7} {24 + band}")
            got += read(DWIN, 8192)
        got = bytes(got[:PAGE])
        n_str = int.from_bytes(read(sym["n_str"], 2), "little")
        miss = int.from_bytes(read(sym["n_str_miss"], 2), "little")

        v = RefVideo8()
        v.cur1 = 0
        ref_draw_string(v, font, colour, cx, y, s)
        want = bytes(v.pages[0])

        ink_r = sum(1 for b in want if b)
        ink_m = sum(1 for b in got if b)
        show = s.replace("\n", "\\n")[:34]
        if got == want:
            print(f"  {sid:#05x} cell {cx:>2} row {y:>3} colour {colour:>2}  "
                  f"{ink_m:>5} pixels  IDENTICAL   \"{show}\"")
            done += 1
        else:
            d = [i for i in range(PAGE) if got[i] != want[i]]
            print(f"  {sid:#05x} cell {cx:>2} row {y:>3}  {len(d):,} bytes differ "
                  f"(machine {ink_m} pixels, reference {ink_r})  \"{show}\"")
            print(f"      first at row {d[0] // W} x {d[0] % W}: "
                  f"ours {got[d[0]]:#04x} reference {want[d[0]]:#04x}")
            bad.append(f"string {sid:#05x} differs in {len(d):,} bytes")
        if miss:
            bad.append(f"string {sid:#05x} was not found by the machine's bisection")
        if not n_str:
            bad.append(f"string {sid:#05x}: the machine drew nothing at all")
    z.close()

    if bad:
        print("\n  " + "\n  ".join(bad[:6]))
        raise SystemExit(f"FAIL: {len(bad)} problem(s) drawing text")
    print(f"""
PASS: all {done} strings pixel-identical to the reference - including one with three
      newlines, the longest in the table at 174 characters, and one at cell 34, which
      no eight-pixel cell could have reached. I4 is closed.""")


if __name__ == "__main__":
    main()
