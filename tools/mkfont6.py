#!/usr/bin/env python3
"""The 6x8 font the Next's text needs, from the engine's 8x8 one.

WHY 6 WIDE. drawChar takes x in CHARACTER CELLS with x <= 39 (video.cpp:299), so the
original addresses 40 cells across 320 pixels - eight each. Our page is 256 wide, which is
32 cells of eight. Forty eight-pixel cells do not fit in 256 pixels, and the three ways out
are: scale the cell origin and let glyphs overlap, clip everything past cell 31, or narrow
the glyphs. Narrowing was chosen: 40 cells of six is 240 pixels, every cell reachable and
no letter touching its neighbour.

HOW. Eighty of the ninety-six glyphs already ink six columns or fewer, so they only need
shifting left. The other sixteen - % & = ? M Q W X Y _ m w | } ~ and one more - are seven or
eight wide, and rather than redraw them by hand this removes columns one at a time, always
the column whose removal changes the fewest pixels, until the glyph fits. That is mechanical
and reviewable: run with --show to see every altered glyph before and after, which is the
only way to judge whether an M is still an M.

    python3 tools/mkfont6.py preflight/hostprobe/probe/font.bin build/font6.bin [--show]
"""
import sys

W_TARGET = 6


# HAND-DRAWN WHERE THE MECHANICAL NARROWING READS BADLY.
#
# Removing the least-inked column is fine for the seven-wide glyphs whose extra column is
# nearly empty - '=' becomes six solid pixels, '&' loses one pixel from one row. It is NOT
# fine for the diagonal-heavy ones: 'M' came out as
#     #....#  /  #...##  /  ##.#.#  /  #.#..#
# which is asymmetric and does not read as an M. These five are drawn instead, and every
# other altered glyph is left mechanical and printed by --show so it can be judged.
HAND = {
    "M": ["#....#", "##..##", "#.##.#", "#....#", "#....#", "#....#", "......", "......"],
    "W": ["#....#", "#....#", "#....#", "#.##.#", "##..##", "#....#", "......", "......"],
    "m": ["......", "......", "##.##.", "#.#.#.", "#.#.#.", "#.#.#.", "......", "......"],
    "w": ["......", "......", "#...#.", "#.#.#.", "#.#.#.", ".#.#..", "......", "......"],
    "%": ["##...#", "##..#.", "...#..", "..#...", ".#..##", "#...##", "......", "......"],
}


def from_art(lines):
    out = []
    for line in lines:
        r = 0
        for i, ch in enumerate(line[:6]):
            if ch == "#":
                r |= 1 << (7 - i)
        out.append(r)
    return out


def rows_of(blob, g):
    return list(blob[g * 8:(g + 1) * 8])


def cols_used(rows):
    used = 0
    for r in rows:
        used |= r
    return used


def extent(rows):
    used = cols_used(rows)
    if not used:
        return 0, -1
    lo = 0
    while lo < 8 and not (used & (1 << (7 - lo))):
        lo += 1
    hi = 7
    while hi >= 0 and not (used & (1 << (7 - hi))):
        hi -= 1
    return lo, hi


def drop_column(rows, c):
    """Remove column c, shifting everything right of it one to the left."""
    out = []
    for r in rows:
        left = r & ~((1 << (8 - c)) - 1)             # columns < c, unchanged
        right = (r << 1) & ((1 << (8 - c)) - 1)      # columns > c, pulled left
        out.append((left | right) & 0xFF)
    return out


def ink(rows):
    return sum(bin(r).count("1") for r in rows)


def narrow(rows):
    """Remove the least costly column until the glyph is six wide."""
    removed = []
    while True:
        lo, hi = extent(rows)
        if hi < lo or hi - lo + 1 <= W_TARGET:
            return rows, removed
        best, best_cost = None, None
        for c in range(lo, hi + 1):
            cand = drop_column(rows, c)
            cost = ink(rows) - ink(cand)
            if best_cost is None or cost < best_cost:
                best, best_cost, best_c = cand, cost, c
        rows = best
        removed.append((best_c, best_cost))


def art(rows, w=8):
    return ["".join("#" if r & (1 << (7 - i)) else "." for i in range(w)) for r in rows]


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "preflight/hostprobe/probe/font.bin"
    out = sys.argv[2] if len(sys.argv) > 2 else "build/font6.bin"
    show = "--show" in sys.argv
    blob = open(src, "rb").read()
    if len(blob) != 768:
        raise SystemExit(f"{src} is {len(blob)} bytes, expected 768")

    result, altered, hand = bytearray(), [], []
    for g in range(96):
        rows = rows_of(blob, g)
        ch = chr(g + 32)
        if ch in HAND:
            before = rows_of(blob, g)
            rows = from_art(HAND[ch])
            hand.append((g + 32, before, rows))
        else:
            lo, hi = extent(rows)
            if hi >= lo:
                rows = [(r << lo) & 0xFF for r in rows]      # left-align first
                rows, removed = narrow(rows)
                if removed:
                    altered.append((g + 32, rows_of(blob, g), rows, removed))
        # keep only the top six columns; the low two bits are always clear now
        result += bytes(r & 0xFC for r in rows)
    open(out, "wb").write(bytes(result))

    print(f"wrote {out}: 96 glyphs, 6 columns each, {len(result)} bytes")
    print(f"  {96 - len(altered)} glyphs only needed shifting left")
    print(f"  {len(hand)} were hand-drawn: "
          + " ".join(f"'{chr(c)}'" for c, _, _ in hand))
    print(f"  {len(altered)} had a column removed: "
          + " ".join(f"'{chr(c)}'" for c, _, _, _ in altered))
    over = []
    for g in range(96):
        rows = list(result[g * 8:(g + 1) * 8])
        lo, hi = extent(rows)
        if hi >= lo and hi - lo + 1 > W_TARGET:
            over.append(g + 32)
    if over:
        raise SystemExit(f"FAIL: {len(over)} glyphs are still wider than six: {over}")
    print("  every glyph verified six columns or fewer")
    if show:
        for c, before, after in hand:
            print(f"\n  '{chr(c)}'  HAND-DRAWN")
            for a, b in zip(art(before), art(after, 6)):
                print(f"    {a}    {b}")
        for c, before, after, removed in altered:
            print(f"\n  '{chr(c)}'  removed column(s) "
                  + ", ".join(f"{col} (cost {cost})" for col, cost in removed))
            for a, b in zip(art(before), art(after, 6)):
                print(f"    {a}    {b}")


if __name__ == "__main__":
    main()
