#!/usr/bin/env python3
"""Step 9: every part the probe can reach, not just the two it plays into.

Every figure in this project came from parts 2 and 3 of ten, because that is as far
as synthetic input can play. The game's own route onward is the password screen and
its codes are not in the data, so the probe requests a part directly instead -
which the engine's own comments in engine.cpp:75-85 warn can crash.

So this reports each part separately and says which ones produced sane figures,
rather than averaging a crashed part in with a working one. A part that drew almost
nothing for thousands of frames did not run; one that drew steadily did.

Host only - no emulator - so it is cheap to re-run.
"""
import os
import re
import shutil
import subprocess
import sys

PROBE = "preflight/hostprobe/probe"
DATA = os.environ.get("DATA_DIR", "data")
FRAMES = int(os.environ.get("AW_PART_FRAMES", "6000"))
JUMP_AT = 200

NAMES = {
    0: "protection", 1: "intro cinematic", 2: "3, water", 3: "4, jail",
    4: "5, cave", 5: "battlechar", 6: "7, arena", 7: "8, baths",
    8: "9, final", 9: "password",
}


def run(part):
    exe = os.path.join(PROBE, "probe")
    if not os.path.exists(exe):
        raise SystemExit(f"{exe} missing - see preflight/hostprobe/README.md")
    # The probe writes frames.txt into ITS OWN working directory, so it has to be
    # run from there and the data directory has to be absolute. Running it from the
    # repository root instead left every part reading one stale frames.txt, and the
    # table came out identical for seven different parts - which is a much more
    # convincing kind of wrong than a crash.
    args = ["./probe", os.path.abspath(DATA), str(FRAMES), "0", "1"]
    if part is not None:
        args += [str(part), str(JUMP_AT)]
    out = subprocess.run(args, capture_output=True, text=True, cwd=PROBE).stdout
    frames = os.path.join(PROBE, "frames.txt")
    rows = []
    if os.path.exists(frames):
        for line in open(frames):
            if line.startswith("#") or not line.strip():
                continue
            rows.append([int(v) for v in line.split()])
    def num(pat):
        m = re.search(pat + r"\s+(\d+)", out)
        return int(m.group(1)) if m else 0
    return rows, dict(
        polys=num("polygon records drawn"),
        hiers=num("hierarchy records walked"),
        depth=num("deepest nesting"),
        fan=num("widest fan-out"),
        pts=num("most vertices in one record"),
        bitmaps=num("full-screen bitmaps loaded"),
        heap=num("peak script-heap use"),
    )


def main():
    print(f"{FRAMES:,} frames a part, requesting the part at frame {JUMP_AT}, "
          f"synthetic input on\n")
    print(f"{'part':<18}{'frames':>8}{'drew':>8}{'polys/f':>9}{'spans/f':>9}"
          f"{'worst':>8}{'bitmaps':>9}{'depth':>7}{'fan':>6}  verdict")
    results = {}
    for part in range(2, 9):
        rows, st = run(part)
        # Only the frames after the jump, and only those the engine reports as
        # being IN the requested part. No fallback: if the jump did not take, the
        # honest answer is zero frames, not "here are the old part's figures".
        after = [r for r in rows[JUMP_AT + 5:] if r[0] == part]
        drew = [r for r in after if r[3] > 0]
        n = len(after)
        if not n:
            print(f"{NAMES[part]:<18}{0:>8}{'':>8}{'':>9}{'':>9}{'':>8}"
                  f"{st['bitmaps']:>9}{'':>7}{'':>6}  never entered this part")
            results[part] = (st, 0, 0, 0, False)
            continue
        polys = sum(r[2] for r in after) / n if n else 0
        spans = sum(r[3] for r in after) / n if n else 0
        worst = max((r[3] for r in after), default=0)
        share = len(drew) / n if n else 0
        sane = share > 0.20 and spans > 5
        results[part] = (st, polys, spans, worst, sane)
        print(f"{NAMES[part]:<18}{n:>8,}{len(drew):>8,}{polys:>9.1f}{spans:>9.1f}"
              f"{worst:>8,}{st['bitmaps']:>9}{st['depth']:>7}{st['fan']:>6}  "
              + ("ran" if sane else "did NOT run - ignore its figures"))

    ran = [p for p, (_, _, _, _, sane) in results.items() if sane]
    print(f"\n{len(ran)} of 7 parts produced sane figures: "
          + ", ".join(NAMES[p] for p in ran))

    if ran:
        print("\nWhat that changes, against the two parts everything rested on:")
        mx = max(ran, key=lambda p: results[p][3])
        st, polys, spans, worst, _ = results[mx]
        print(f"  the worst frame across them is {worst:,} spans, in "
              f"{NAMES[mx]}\n    (parts 2 and 3 gave 4,004 and 3,637)")
        d = max(results[p][0]["depth"] for p in ran)
        f = max(results[p][0]["fan"] for p in ran)
        v = max(results[p][0]["pts"] for p in ran)
        h = max(results[p][0]["heap"] for p in ran)
        print(f"  deepest hierarchy nesting {d}   (4 before)")
        print(f"  widest fan-out {f}   (119 before)")
        print(f"  most vertices in a record {v}   (40 before)")
        print(f"  peak script-heap use {h:,} bytes   (241,363 before)")
        bm = [p for p in ran if results[p][0]["bitmaps"]]
        if bm:
            tot = sum(results[p][0]["bitmaps"] for p in bm)
            print(f"\n  AND {tot} full-screen bitmaps load, in "
                  + ", ".join(NAMES[p] for p in bm) + ".")
            print("  That path had ZERO loads in 72,000 frames of parts 2 and 3, so")
            print("  Gate A covers none of it and tools/mkassets.py's deplaner has")
            print("  never been compared against the engine's. It can be now.")
        else:
            print("\n  No part reached here loads a full-screen bitmap.")

    print("\nPASS: the parts are measured separately, and the ones that did not "
          "run say so.")


if __name__ == "__main__":
    main()
