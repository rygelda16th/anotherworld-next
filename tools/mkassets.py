#!/usr/bin/env python3
"""Convert Another World's resources into the form the Next reads at run time.

Two conversions happen here, and only these two, because everything else the
engine needs is bytecode or polygon data that goes across untouched.

PALETTES. A palette resource is 2048 bytes: 1024 of VGA followed by 1024 of
EGA, and only the VGA half is ever used (Video::changePal reads
segPalettes + id*32 and rejects id >= 32, so it never reaches the second
kilobyte). That is 32 palettes of 16 colours, each colour two bytes laid out
0x0RGB big-endian - byte 0's low nibble is red, byte 1's high nibble green, its
low nibble blue. The comments in the original call this 565 and they are wrong;
the unpacking code masks nibbles.

The Next has two 256-entry Layer 2 palettes, selected by NextReg $43 bit 2, and
NextReg $70's low four bits add an offset to a pixel's top nibble. 2 x 256 is
512 entries, which is exactly 32 palettes of 16 - so every palette a part can
ask for stays resident and op_setPalette becomes two register writes with no
upload at all.

BITMAPS. The twelve full-screen images are 32,000 bytes of four-plane planar
data, 320x200 at 4 bits a pixel. They are deplaned here exactly as
Video::copyPage(const uint8_t *) does it, then resampled to 256x192.

The resampling is nearest-neighbour, and that is not laziness: the data is
palette-indexed, so averaging two neighbouring pixels would average their
*indices* and produce an unrelated colour. Nearest is the only correct choice
for indexed art, and doing it on the host makes it free at run time.

    python3 tools/mkassets.py data/ build/assets/
"""

import collections
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bytekiller import read_resource  # noqa: E402
from memlist import load  # noqa: E402

RT_POLY_ANIM = 2
RT_PALETTE = 3

SRC_W, SRC_H = 320, 200
DST_W, DST_H = 256, 192
PLANE = 8000                 # bytes per bitplane
PAL_ENTRIES = 16
PAL_BYTES = PAL_ENTRIES * 2  # one 16-colour palette
PALS_PER_RES = 32            # in the VGA kilobyte


def rgb444(pair):
    """One colour from its two bytes: 0x0RGB big-endian, four bits a channel."""
    return (pair[0] & 0x0F, (pair[1] & 0xF0) >> 4, pair[1] & 0x0F)


def to_rgb333(c):
    """4 bits a channel down to 3, rounding rather than truncating.

    Dropping the low bit (v >> 1) is the obvious move and it darkens
    everything slightly and unevenly; scaling 0..15 onto 0..7 keeps white white
    and black black, which matters because the game leans on both.
    """
    return tuple((v * 7 + 7) // 15 for v in c)


def nextreg44(c333):
    """The two bytes NextReg $44 wants with auto-increment on: RRRGGGBB, then
    the low bit of blue. The same shape wolf3d-next's palette loader uses."""
    r, g, b = c333
    return bytes(((r << 5) | (g << 2) | (b >> 1), b & 1))


def deplane(src):
    """32,000 bytes of four-plane data -> 320x200 bytes, one index per pixel.

    Ported from Video::copyPage(const uint8_t *): per source byte-column it
    walks the four planes most-significant bit first, taking them in the order
    3, 2, 1, 0 so each output byte carries two 4-bit pixels, high nibble first.
    """
    out = bytearray(SRC_W * SRC_H)
    o = 0
    s = 0
    for _ in range(SRC_H):
        for _ in range(SRC_W // 8):
            p = [src[s + PLANE * 3], src[s + PLANE * 2],
                 src[s + PLANE * 1], src[s + PLANE * 0]]
            for _j in range(4):
                acc = 0
                for i in range(8):
                    acc = (acc << 1) | (1 if p[i & 3] & 0x80 else 0)
                    p[i & 3] = (p[i & 3] << 1) & 0xFF
                out[o] = acc >> 4          # high nibble = first pixel
                out[o + 1] = acc & 0x0F    # low nibble = second
                o += 2
            s += 1
    return out


def resample(px):
    """320x200 indexed -> 256x192 indexed, nearest neighbour."""
    xmap = [(x * SRC_W) // DST_W for x in range(DST_W)]
    ymap = [(y * SRC_H) // DST_H for y in range(DST_H)]
    out = bytearray(DST_W * DST_H)
    for y in range(DST_H):
        row = ymap[y] * SRC_W
        base = y * DST_W
        for x in range(DST_W):
            out[base + x] = px[row + xmap[x]]
    return out


def main():
    data_dir = sys.argv[1] if len(sys.argv) > 1 else "data"
    out_dir = sys.argv[2] if len(sys.argv) > 2 else "build/assets"
    os.makedirs(out_dir, exist_ok=True)
    es, banks = load(data_dir)

    # ---- palettes --------------------------------------------------------
    pal_res = [e for e in es if e["type"] == RT_PALETTE]
    print(f"palette resources: {len(pal_res)}")
    distinct444, distinct333 = set(), set()
    for e in pal_res:
        raw = read_resource(e, banks[e["bank"]])
        if len(raw) != 2048:
            print(f"  !! res 0x{e['id']:02X} is {len(raw)} bytes, expected 2048")
        vga = raw[:1024]
        blob = bytearray()
        for p in range(PALS_PER_RES):
            for i in range(PAL_ENTRIES):
                off = p * PAL_BYTES + i * 2
                c = rgb444(vga[off:off + 2])
                distinct444.add(c)
                c3 = to_rgb333(c)
                distinct333.add(c3)
                blob += nextreg44(c3)
        path = os.path.join(out_dir, f"PAL{e['id']:02X}.BIN")
        open(path, "wb").write(blob)
        print(f"  res 0x{e['id']:02X} -> {os.path.basename(path)}  "
              f"{len(blob)} bytes = {PALS_PER_RES} palettes x {PAL_ENTRIES} "
              f"entries x 2")

    # Collisions WITHIN one 16-colour palette are what actually costs a scene a
    # distinguishable colour; the global figure below mostly reflects palettes
    # sharing colours with each other.
    hist = collections.Counter()
    worst = []
    for e in pal_res:
        vga = read_resource(e, banks[e["bank"]])[:1024]
        for p in range(PALS_PER_RES):
            before, after = set(), set()
            for i in range(PAL_ENTRIES):
                o = p * PAL_BYTES + i * 2
                c = rgb444(vga[o:o + 2])
                before.add(c)
                after.add(to_rgb333(c))
            hist[len(before) - len(after)] += 1
            if len(before) != len(after):
                worst.append((len(before) - len(after), e["id"], p, len(before)))
    n = sum(hist.values())
    print(f"\ncolours lost WITHIN a single palette ({n} palettes examined):")
    for k in sorted(hist):
        print(f"  {k} lost   {hist[k]:>4} palettes  {100*hist[k]/n:5.1f}%")
    worst.sort(reverse=True)
    if worst:
        k, rid, p, nb = worst[0]
        print(f"  worst: res 0x{rid:02X} palette {p}, {nb} distinct -> {nb-k}")
    print(f"  A smarter quantiser could nudge colliding entries to adjacent")
    print(f"  RGB333 values to keep them distinct, trading a little hue error")
    print(f"  for separation. Host-side, so free at run time - a fidelity call.")

    print(f"\nquantisation, RGB444 -> RGB333 across every palette:")
    print(f"  distinct colours before : {len(distinct444)}")
    print(f"  distinct colours after  : {len(distinct333)}")
    print(f"  collapsed into a neighbour : "
          f"{len(distinct444) - len(distinct333)}")
    print(f"  512 Layer 2 entries hold {PALS_PER_RES} palettes of "
          f"{PAL_ENTRIES}: every one a part can select stays resident")

    # ---- full-screen bitmaps --------------------------------------------
    anim = [e for e in es if e["type"] == RT_POLY_ANIM]
    print(f"\nfull-screen bitmaps: {len(anim)}")
    for e in anim:
        raw = read_resource(e, banks[e["bank"]])
        if len(raw) != PLANE * 4:
            print(f"  !! res 0x{e['id']:02X} is {len(raw)}, expected {PLANE*4}")
            continue
        px = deplane(raw)
        used = collections.Counter(px)
        small = resample(px)
        path = os.path.join(out_dir, f"BMP{e['id']:02X}.BIN")
        open(path, "wb").write(bytes(small))
        print(f"  res 0x{e['id']:02X} -> {os.path.basename(path)}  "
              f"{len(small):,} bytes  ({DST_W}x{DST_H}, "
              f"{len(used)} of 16 indices used)")

    print(f"\nwrote {len(pal_res)} palette and {len(anim)} bitmap blobs to "
          f"{out_dir}")
    print("Bytecode and polygon resources are not converted: they go to the "
          "machine as they are.")


if __name__ == "__main__":
    main()
