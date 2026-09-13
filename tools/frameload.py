#!/usr/bin/env python3
"""Score every frame against the pause the script itself asked for.

The host probe writes `frames.txt`, one line per VM frame: the part, the
opcodes dispatched, the polygons filled, the spans drawn, the page fills and
copies, and - the column that matters most - `vmVariables[0xFF]`, the pause in
twentieths of a second that the bytecode requested for that frame.

Without that last column the worst frame looks alarming and the mean looks
idle, because both are being compared against a 20 ms refresh that the game
never asks for. The scripts ask for 80 ms three quarters of the time. So the
question is not "does the worst frame fit one refresh", it is "how many frames
overrun their own deadline", and that is what this prints.

Costs are all measured now - `make check-span` for the fill modes and
`make check-polycost` for the per-polygon and per-span figures. Two models are
reported, because which applies is a decision about how much optimising gets done
rather than a fact about the game: the rasteriser as it stands, and the same with
the two optimisations step 0 measured and this project deferred.

    python3 tools/frameload.py frames.txt
"""

import sys

REFRESH = 560_000        # T-states in one 20 ms refresh at 28 MHz
OPCODE = 400             # C dispatch, measured in Phase B
COPY = 49_152 * 2        # a whole 256x192 page, PUSH/POP pairs; upper bound
FILL = int(49_152 * 1.5)

# Two cost models, both measured, because which one applies is a decision about
# how much optimising gets done rather than a fact about the game.
#
#   "as built"  - what src/polytest.asm charges today, from make check-polycost:
#                 2,974 T a polygon measured directly, and a 22-byte opaque span
#                 at 1,570 T entry + 22 x 21.3 T a byte. The fill is a plain
#                 ld (hl),a / inc l / djnz loop.
#   "optimised" - the same with the two optimisations step 0 already measured:
#                 accumulators held in registers across a trapezoid (433 T entry)
#                 and a PUSH fill (5.4 T a byte). Both are measured techniques,
#                 not guesses, and check-polycost showed they are needed.
#
# The plan's earlier figures used 672 T a span, which is step 0's purpose-built
# span row rather than the rasteriser - a three-fold understatement.
MODELS = {
    "as built":  (2974, 1570 + 22 * 21.3),
    "optimised": (2974, 433 + 22 * 5.4),
}


def pctile(v, q):
    v = sorted(v)
    return v[min(len(v) - 1, int(q * len(v)))]


def load(path):
    rows = []
    for line in open(path):
        if line.startswith("#") or not line.strip():
            continue
        rows.append([int(v) for v in line.split()])
    return rows


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "frames.txt"
    rows = load(path)
    if not rows:
        raise SystemExit(f"{path} is empty")
    if len(rows[0]) < 7:
        raise SystemExit(f"{path} has {len(rows[0])} columns, expected 7 - "
                         "it predates the pause_slices column")

    byparts = {}
    for r in rows:
        byparts.setdefault(r[0], []).append(r)

    print(f"{len(rows):,} frames from {path}\n")
    pace = {}
    for _, _, _, _, _, _, p in rows:
        pace[p] = pace.get(p, 0) + 1
    print("the pause the scripts asked for:")
    for p in sorted(pace):
        print(f"  {p} slices ({p*20:>3} ms) {pace[p]:>8,}  "
              f"{100*pace[p]/len(rows):5.1f}%")

    print(f"\n{'model':>10} {'T/poly':>7} {'T/span':>7} | {'p50':>6} {'p90':>6} "
          f"{'p99':>6} {'max':>6} | {'missed':>7} {'>2x':>6} | {'mean load':>9}")
    for name, (pp, sp) in MODELS.items():
        cost, load_, miss, bad = [], [], 0, 0
        for _, ops, polys, spans, fill, copy, p in rows:
            t = spans * sp + polys * pp + ops * OPCODE + copy * COPY + fill * FILL
            budget = max(p, 1) * REFRESH
            cost.append(t / REFRESH)
            load_.append(t / budget)
            miss += t > budget
            bad += t > 2 * budget
        print(f"{name:>10} {pp:>7.0f} {sp:>7.0f} | {pctile(cost,.50):>6.2f} "
              f"{pctile(cost,.90):>6.2f} {pctile(cost,.99):>6.2f} {max(cost):>6.2f} | "
              f"{100*miss/len(rows):>6.2f}% {100*bad/len(rows):>5.2f}% | "
              f"{sum(load_)/len(load_):>8.1%}")

    print("\ncost is in 20 ms refreshes; 'missed' counts frames that overrun the "
          "pause\nthe script asked for; 'mean load' is the mean fraction of that "
          "pause used.")

    if len(byparts) > 1:
        print("\nby part:")
        for name, (pp, sp) in MODELS.items():
            for part in sorted(byparts):
                rs = byparts[part]
                c = [(s * sp + pl * pp + o * OPCODE + cp * COPY + fl * FILL)
                     / (max(p, 1) * REFRESH)
                     for _, o, pl, s, fl, cp, p in rs]
                print(f"  {name:<10} part {part:<3} {len(rs):>7,} frames   mean load "
                      f"{sum(c)/len(c):>6.1%}   worst {max(c):>6.2f}x its deadline")


if __name__ == "__main__":
    main()
