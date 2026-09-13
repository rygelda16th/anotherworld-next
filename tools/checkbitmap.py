#!/usr/bin/env python3
"""The full-screen bitmap path: is our deplaner the engine's deplaner?

This is the one part of the asset pipeline that had never been compared against
anything. `Video::copyPage(const uint8_t *)` (video.cpp:523-549) turns a
four-plane, 32,000-byte resource into a 320x200 page, and `tools/mkassets.py` has a
port of it that has shipped since Phase A - but the path never ran: zero
`RT_POLY_ANIM` loads in 72,000 frames of parts 2 and 3, so Gate A's byte-exactness
covers none of it.

Step 9 found where they are. Seventy of them load in the arena, and the probe now
dumps the engine's own page 0 straight after each load, so the comparison is against
the engine rather than against a second transcription of it.

Host only - no emulator, no machine.
"""
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from memlist import load  # noqa: E402
from bytekiller import read_resource  # noqa: E402
from mkassets import deplane  # noqa: E402

PROBE = "preflight/hostprobe/probe"
DATA = os.environ.get("DATA_DIR", "data")
W, H = 320, 200


def main():
    dumps = sorted(glob.glob(os.path.join(PROBE, "bmp_engine_*.bin")))
    if not dumps:
        raise SystemExit(
            "no bmp_engine_*.bin in " + PROBE + " - run the probe over a part that "
            "loads them:\n  cd " + PROBE + " && ./probe <data> 3000 0 1 6 200")

    entries, banks = load(DATA)
    print(f"{len(dumps)} engine page dumps to compare\n")
    bad = 0
    for path in dumps:
        rid = int(os.path.basename(path).split("_")[2].split(".")[0], 16)
        engine = open(path, "rb").read()
        if len(engine) != W * H // 2:
            print(f"  resource {rid:#04x}: dump is {len(engine)} bytes, expected "
                  f"{W*H//2}")
            bad += 1
            continue

        raw = read_resource(entries[rid], banks[entries[rid]["bank"]])
        ours = deplane(raw)              # one index a pixel, 64,000 of them

        # the engine holds two pixels a byte, high nibble first
        theirs = bytearray(W * H)
        for i, b in enumerate(engine):
            theirs[i * 2] = b >> 4
            theirs[i * 2 + 1] = b & 0x0F

        if bytes(ours) == bytes(theirs):
            used = len(set(ours))
            print(f"  resource {rid:#04x}: IDENTICAL, all {W*H:,} pixels "
                  f"({used} of 16 indices used)")
        else:
            diff = [i for i in range(W * H) if ours[i] != theirs[i]]
            k = diff[0]
            print(f"  resource {rid:#04x}: {len(diff):,} of {W*H:,} pixels differ")
            print(f"    first at pixel {k} (row {k//W}, x {k%W}): "
                  f"ours {ours[k]}, engine {theirs[k]}")
            rows = sorted({i // W for i in diff})
            print(f"    rows {rows[0]}..{rows[-1]} of {H}")
            bad += 1

    if bad:
        raise SystemExit(f"\nFAIL: {bad} of {len(dumps)} disagree - the asset "
                         "pipeline's deplaner is not the engine's")
    print(f"""
PASS: the deplaner in tools/mkassets.py is the engine's, pixel for pixel, over
      {len(dumps)} real resources. That path had shipped since Phase A without ever
      being compared against anything, because no part the probe could reach loaded
      one.""")


if __name__ == "__main__":
    main()
