#!/usr/bin/env python3
"""Build a Gate C test vector: real polygons, and the pixels they must produce.

Polygons are picked out of the host probe's trace rather than invented, so they
are shapes the game actually draws - but picked *for coverage* rather than taken
in order, because a run of consecutive frames is mostly the same few shapes.

What is covered, and why each matters:

  * all three fill modes: opaque (colour below 0x10), blend (exactly 0x10) and
    copy-from-page-0 (above 0x10). The last two are read-modify-write, so a
    rasteriser can be right about geometry and wrong about them.
  * clipping at each of the four edges independently, plus a polygon entirely
    off screen, which must draw nothing at all.
  * the degenerate single-point case, which fillPolygon handles by an early
    branch on bbw == 0 && bbh == 1 && numPoints == 4 rather than by walking.
  * a large polygon and a very small one, because the edge walk's fractional
    seeding shows up differently when h is 1 than when it is 100.
  * high vertex counts, since the walk consumes points two at a time from both
    ends and an odd assumption there only fails on long lists.

Emits an sjasmplus include of the polygon list and the reference's own 256x192
page as a binary, so the machine can be compared against it byte for byte.

    python3 tools/mkpolytest.py <trace.bin> build/polytest.inc build/expected.bin
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from refvideo import RefVideo8, read_trace  # noqa: E402

# Page 0 is filled with this before anything is drawn, so the copy-from-page-0
# mode has something recognisable to copy and a failure is visible rather than
# a plausible black.
PAGE0_SEED = 0x0B


def classify(p):
    """The coverage bucket a traced polygon falls into, or None."""
    R = RefVideo8
    colour, n = p["colour"], len(p["points"])
    bbw, bbh = R.sx(p["bbw"]), R.sy(p["bbh"])
    x, y = R.sx(p["px"]), R.sy(p["py"])
    x1, x2 = x - bbw // 2, x + bbw // 2
    y1, y2 = y - bbh // 2, y + bbh // 2

    if p["bbw"] == 0 and p["bbh"] == 1 and n == 4:
        return "point"
    if x1 > R.W - 1 or x2 < 0 or y1 > R.H - 1 or y2 < 0:
        return "offscreen"
    if bbw > 255 or bbh > 255:
        # Tested BEFORE the clipping buckets, because a box wider or taller than
        # the screen always clips and so was always claimed by one of them - which
        # is why this bucket came back empty the first time. A wide box is
        # legitimate data, the polygon is simply clipped, and the game produces
        # them up to 423 x 483. Nothing picked one until this existed, so the
        # 8-bit record format and the 8-bit box halving went unexercised for
        # exactly as long as they were wrong.
        return "wide"
    if x1 < 0:
        return "clip_left"
    if x2 > R.W - 1:
        return "clip_right"
    if y1 < 0:
        return "clip_top"
    if y2 > R.H - 1:
        return "clip_bottom"
    if colour == 0x10:
        return "blend"
    if colour > 0x10:
        return "copy"
    if n >= 20:
        return "many_points"
    if bbw * bbh >= 8000:
        return "large"
    if bbw <= 3 or bbh <= 3:
        return "tiny"
    return "opaque"


WANT = {
    "point": 3, "offscreen": 3, "clip_left": 4, "clip_right": 4,
    "clip_top": 4, "clip_bottom": 4, "blend": 6, "copy": 6,
    "many_points": 5, "large": 4, "tiny": 6, "opaque": 8, "wide": 4,
}


def main():
    trace = sys.argv[1]
    inc = sys.argv[2] if len(sys.argv) > 2 else "build/polytest.inc"
    exp = sys.argv[3] if len(sys.argv) > 3 else "build/expected.bin"

    picked, counts = [], {k: 0 for k in WANT}
    for kind, a in read_trace(trace):
        if kind != "poly":
            continue
        if len(a["points"]) > 48 or len(a["points"]) % 2:
            continue                      # the walk needs an even count
        b = classify(a)
        if b and counts[b] < WANT[b]:
            counts[b] += 1
            picked.append((b, a))
        if all(counts[k] >= WANT[k] for k in WANT):
            break

    print(f"{len(picked)} polygons picked for coverage:")
    for k in sorted(WANT):
        flag = "" if counts[k] >= WANT[k] else "   <-- trace had no more"
        print(f"  {k:<12}{counts[k]:>3} of {WANT[k]}{flag}")

    # Render them with the reference, in the same order the machine will.
    v = RefVideo8()
    for i in range(v.PAGE):
        v.pages[0][i] = PAGE0_SEED
    v.cur1 = 1
    for _, a in picked:
        v.fill_polygon_scaled(a["colour"], a["px"], a["py"],
                              a["bbw"], a["bbh"], a["points"])
    open(exp, "wb").write(bytes(v.pages[1]))
    painted = sum(1 for b in v.pages[1] if b)
    print(f"\nreference drew {painted:,} of {v.PAGE:,} pixels "
          f"({100*painted/v.PAGE:.1f}% of the page) -> {exp}")

    # And the same polygons as data for the machine, pre-scaled so the assembly
    # under test is the rasteriser alone. The vertex transform is a separate
    # routine with its own exhaustive check.
    R = RefVideo8
    with open(inc, "w") as fh:
        fh.write("; GENERATED by tools/mkpolytest.py - do not edit.\n")
        fh.write(f"; {len(picked)} polygons from a real trace, chosen for "
                 f"coverage, already scaled\n; into 256x192 space. Record: "
                 "colour (byte), ptx, pty, bbw, bbh (signed\n; words), npoints "
                 "(byte), then npoints pairs of (x, y) offsets within\n; the box, "
                 "as signed words.\n")
        fh.write(f"PAGE0_SEED      EQU ${PAGE0_SEED:02X}\n")
        fh.write(f"POLY_COUNT      EQU {len(picked)}\n\n")
        # An offset per record, so a program can start at record N without
        # walking to it. tools/checkpolycost.py draws WINDOWS of the vector to
        # decorrelate polygon count from span count, and walking to the window
        # put a cost proportional to the start index into every measurement -
        # a confound that looked like a huge per-polygon cost.
        off, offs = 0, []
        for _, a in picked:
            offs.append(off)
            # colour, ptx, pty, bbw, bbh, npoints, then npoints x (x, y).
            # Everything but the colour and the count is a WORD: the game's
            # post-zoom geometry reaches 423 x 483 after the 256x192 scale.
            off += 1 + 2 + 2 + 2 + 2 + 1 + 4 * len(a["points"])
        fh.write("poly_index:\n")
        for k in range(0, len(offs), 8):
            fh.write("        dw      " + ", ".join(str(v) for v in offs[k:k + 8]) + "\n")
        fh.write("\npoly_data:\n")
        for bucket, a in picked:
            pts = [(R.sx(x), R.sy(y)) for x, y in a["points"]]
            fh.write(f"        ; {bucket}: colour {a['colour']:#04x}, "
                     f"{len(pts)} points\n")
            fh.write(f"        db      {a['colour']}\n")
            fh.write(f"        dw      {R.sx(a['px'])}, {R.sy(a['py'])}\n")
            fh.write(f"        dw      {R.sx(a['bbw'])}, {R.sy(a['bbh'])}\n")
            fh.write(f"        db      {len(pts)}\n")
            for k in range(0, len(pts), 4):
                row = ", ".join(f"{x}, {y}" for x, y in pts[k:k + 4])
                fh.write(f"        dw      {row}\n")
        fh.write("poly_data_end:\n")
    print(f"wrote {inc}")

    # The same polygons in text, so tools/checkpoly.py can re-render any PREFIX
    # with the reference and bisect to the first one that diverges. Comparing
    # only the final page tells you that something is wrong, never which shape.
    txt = os.path.splitext(inc)[0] + ".txt"
    with open(txt, "w") as fh:
        fh.write(f"# bucket colour ptx pty bbw bbh n x0 y0 ...  "
                 f"(320x200 space, unscaled)\n")
        for bucket, a in picked:
            flat = " ".join(f"{x} {y}" for x, y in a["points"])
            fh.write(f"{bucket} {a['colour']} {a['px']} {a['py']} "
                     f"{a['bbw']} {a['bbh']} {len(a['points'])} {flat}\n")
    print(f"wrote {txt}")


if __name__ == "__main__":
    main()
