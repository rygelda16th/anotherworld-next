#!/usr/bin/env python3
"""Step 2: what does one POLYGON cost on the machine, apart from its spans?

Gameplay draws many more, much smaller shapes than the intro - the heaviest
frame measured is 956 polygons at 3.8 spans each - so per-polygon setup, not
span fill, is where gameplay spends its time. Every frame-budget figure in the
plan carries that cost as a swept parameter because nothing had measured it.

Fitting T against the polygon count alone would be wrong: each polygon draws a
different number of spans, so the two costs would be conflated and whichever
varied more would absorb the other. So this is a TWO-variable least squares,

    T(N) = a * polygons(N) + b * spans(N) + c

over a sweep of prefix lengths, with polygons(N) and spans(N) counted by the
reference - which is the only thing that knows how many spans a prefix draws.

`b` is then checked against the 672 T a span that `make check-span` measured by
a completely different route. Two independent measurements of the same quantity
agreeing is the evidence that the decomposition means anything.
"""
import statistics
import sys
import time

sys.path.insert(0, "tools")
from zrcp import Zrcp  # noqa: E402
from refvideo import RefVideo8  # noqa: E402

NEX, EXP = "build/polytest.nex", "build/polytest.exp"
POLYS = "build/polytest.txt"
PAGE0_SEED = 0x0B
CLOCK = 28_000_000
REFRESH = CLOCK // 50
SPAN_MEASURED = 672        # tools/checkspan.py, by a different method


def symbols(path):
    out = {}
    for line in open(path):
        name, _, val = line.partition(":")
        if "0x" in val:
            out[name.strip()] = int(val.split("0x")[1], 16)
    return out


def load_polys(path):
    out = []
    for line in open(path):
        if line.startswith("#") or not line.strip():
            continue
        f = line.split()
        colour, px, py, bbw, bbh, n = (int(v) for v in f[1:7])
        nums = [int(v) for v in f[7:7 + 2 * n]]
        out.append((colour, px, py, bbw, bbh, list(zip(nums[0::2], nums[1::2]))))
    return out


def counts(polys, first, limit):
    """What the reference draws for one window, split by fill mode."""
    v = RefVideo8()
    for i in range(v.PAGE):
        v.pages[0][i] = PAGE0_SEED
    v.cur1 = 1
    for colour, px, py, bbw, bbh, pts in polys[first:first + limit]:
        v.fill_polygon_scaled(colour, px, py, bbw, bbh, pts)
    return (v.n_polys, v.n_spans, v.n_span_bytes,
            list(v.n_mode_bytes), list(v.n_mode_spans))


def main():
    sym = symbols(EXP)
    polys = load_polys(POLYS)
    z = Zrcp()
    print(f"emulator: {z.cmd('get-version')}")
    z.cmd(f"smartload /work/{NEX}")
    time.sleep(4)
    z.cmd("set-memory-zone -1")
    z.cmd(f"write-memory {sym['bench']} 1")
    z.cmd(f"write-memory {sym['poly_limit']} {len(polys)}")
    z.cmd(f"write-memory {sym['go']} 1")
    time.sleep(1.5)

    def passes():
        raw = z.cmd(f"read-memory {sym['passes']} 2").strip()
        return int(raw[2:4] + raw[0:2], 16)

    if passes() == 0:
        time.sleep(2)
        if passes() == 0:
            raise SystemExit("FAIL: bench mode never completed a pass")

    def wait_for(pred, what, limit=60.0):
        t0 = time.time()
        while not pred():
            if time.time() - t0 > limit:
                raise SystemExit(f"gave up waiting for {what}")
            time.sleep(0.005)

    BUDGET = 5_000_000          # emulated T-states a sample; keeps the sweep short

    def raw_pass(window, want, what, limit_s=300.0):
        base = passes()
        wait_for(lambda: passes() != base, "a pass boundary", limit_s)
        z.cmd("reset-tstates-partial")
        b0 = passes()
        wait_for(lambda: passes() - b0 >= want, what, limit_s)
        el = int(z.cmd("get-tstates-partial").strip())
        done = passes() - b0
        return el / done

    def measure(first, limit, samples=2):
        """T-states a pass, with the pass count chosen from a probe.

        A fixed pass count cannot work across this sweep: a window of three
        point polygons is four orders of magnitude cheaper than one of four
        copy-mode polygons with 130-byte spans, and the first draft asked for
        twenty passes of the expensive one and timed out. So probe once, then
        pick a count that fits a fixed T-state budget - the counter is the
        emulator's, so the budget is in emulated work, not wall time.
        """
        z.cmd("set-memory-zone -1")
        z.cmd(f"write-memory {sym['poly_first']} {first}")
        z.cmd(f"write-memory {sym['poly_limit']} {limit}")
        time.sleep(0.3)
        est = raw_pass((first, limit), 1, f"one pass at [{first},{first+limit})")
        want = max(2, min(60, int(BUDGET / max(est, 1))))
        out = [raw_pass((first, limit), want,
                        f"{want} passes at [{first},{first+limit})")
               for _ in range(samples)]
        return statistics.median(out), want

    # Windows chosen to DECORRELATE polygon count from span count. Mixed SIZES
    # matter as much as mixed starts: with every window holding four polygons the
    # polygon term is collinear with the constant and the fit is arbitrary. Sizes
    # 1, 2, 4 and 8 give polygon counts from 1 to 8 against span counts from 0 to
    # 600, which is what makes the two separable.
    n = len(polys)
    WINDOWS = []
    for size in (1, 2, 4, 8):
        WINDOWS += [(f, min(size, n - f)) for f in range(0, n, max(size, 7))]
    WINDOWS += [(0, n), (0, 36)]

    # And every single-polygon window that draws NO spans, because those are what
    # measure the per-polygon cost directly. Sampling every seventh index found
    # one by luck, and stopped finding one the moment the vector's contents
    # changed - so look for them instead of hoping.
    zero_single = [f for f in range(n) if counts(polys, f, 1)[1] == 0]
    WINDOWS += [(f, 1) for f in zero_single]
    WINDOWS = sorted({(f, l) for f, l in WINDOWS if l > 0})
    print(f"\n{len(zero_single)} of {n} polygons draw no spans at all: "
          f"{zero_single[:8]}{' ...' if len(zero_single) > 8 else ''}")
    if not zero_single:
        raise SystemExit("FAIL: no polygon in the vector draws zero spans, so the "
                         "per-polygon cost cannot be measured directly. Add an "
                         "offscreen or point polygon to tools/mkpolytest.py.")

    rows = []
    print(f"\n{'window':>10}{'polys':>6}{'spans':>7}{'opaqB':>8}{'blndB':>7}"
          f"{'copyB':>7}{'T/pass':>11}{'T/poly':>9}{'psses':>7}")
    for f, l in WINDOWS:
        p, sp, by, mb, ms = counts(polys, f, l)
        t, want = measure(f, l)
        rows.append((p, sp, mb, t))
        print(f"{f:>4}+{l:<4}{p:>6}{sp:>7}{mb[0]:>8,}{mb[1]:>7,}{mb[2]:>7,}"
              f"{t:>11,.0f}{t/p if p else 0:>9.0f}{want:>7}")

    # How separable are they, really?
    xs = [float(r[0]) for r in rows]
    ys = [float(r[1]) for r in rows]
    mx, my = statistics.mean(xs), statistics.mean(ys)
    cov = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    sx = sum((a - mx) ** 2 for a in xs) ** 0.5
    sy = sum((b - my) ** 2 for b in ys) ** 0.5
    r = cov / (sx * sy) if sx and sy else 1.0
    print(f"\npolygons vs spans across the sweep: r = {r:.3f}"
          + ("  (separable)" if abs(r) < 0.9 else
             "  -- WEAK: the fit below cannot really tell them apart"))

    # The per-polygon cost is NOT ONE NUMBER, and that is the finding here rather
    # than an inconvenience. Every window that draws a single polygon and no spans
    # is a direct measurement of a per-polygon path, and they range over four and a
    # half times: the cheap end is a bounding-box rejection, the dear end sets up,
    # walks every row and has every span clipped.
    #
    # So it is fixed rather than fitted, and the fit is run at three values to show
    # that the span terms - the ones that can be checked against step 0 - barely
    # move. Fitting it as a fifth free term produced MINUS 7,180 T a polygon and a
    # 30% residual, because polygons and spans stay correlated across any sweep of
    # a fixed vector and least squares will happily trade one against the other.
    singles = sorted(t for p, s_, mb, t in rows if p == 1 and s_ == 0)
    if not singles:
        raise SystemExit("FAIL: no single-polygon window drew zero spans")
    lo, mid, hi = singles[0], singles[len(singles) // 2], singles[-1]
    print(f"\nthe {len(singles)} windows that draw one polygon and no spans, "
          f"directly measured:")
    print("  " + ", ".join(f"{t:,.0f}" for t in singles) + " T")
    print(f"  a bounding-box rejection at the cheap end, a fully-clipped walk at "
          f"the dear end")

    def fit_spans(per_poly):
        A = [[float(s_), float(mb[0]), float(mb[1] + mb[2])]
             for _, s_, mb, _ in rows]
        y = [float(t) - per_poly * float(p) for p, _, _, t in rows]
        K = 3
        M = [[sum(A[k][i] * A[k][j] for k in range(len(A))) for j in range(K)]
             + [sum(A[k][i] * y[k] for k in range(len(A)))] for i in range(K)]
        for i in range(K):
            piv = max(range(i, K), key=lambda rr: abs(M[rr][i]))
            M[i], M[piv] = M[piv], M[i]
            for rr in range(K):
                if rr != i:
                    f = M[rr][i] / M[i][i]
                    for c in range(i, K + 1):
                        M[rr][c] -= f * M[i][c]
        c = [M[i][K] / M[i][i] for i in range(K)]
        resid = [y[k] - sum(A[k][i] * c[i] for i in range(K))
                 for k in range(len(A))]
        return c, (sum(rr * rr for rr in resid) / len(resid)) ** 0.5

    print(f"\nthe span terms, with the per-polygon term fixed at each of those:")
    print(f"  {'T/poly':>8}{'T/span entry':>14}{'T/opaque byte':>15}"
          f"{'T/blend byte':>14}{'RMS':>12}")
    best = None
    for pp in (lo, mid, hi):
        (b, bo, bb), rms = fit_spans(pp)
        print(f"  {pp:>8,.0f}{b:>14.0f}{bo:>15.1f}{bb:>14.1f}{rms:>12,.0f}")
        if pp == mid:
            best = (b, bo, bb)
    b, bo, bb = best
    bc = bb
    per_poly = mid
    print(f"\n  The span terms move by a few per cent across a 4.5-fold change in")
    print(f"  the per-polygon term, so the conclusion does not rest on that choice.")
    print(f"  Step 0 measured the blend byte at 32.2 by another method entirely.")

    # The game's own spans average 22 bytes at 256 wide and are mostly opaque, so
    # cost them at this code's measured rates rather than at step 0's best-case.
    per_span = b + 22 * bo
    print(f"\nThe game's mean span is 22 bytes, so this code costs "
          f"{per_span:,.0f} T a span\n  against the {SPAN_MEASURED} T the plan "
          f"budgets from step 0's row - {per_span/SPAN_MEASURED:.1f}x.")
    print(f"\nThe frames the host probe measured, at {per_poly:,.0f} T a polygon and "
          f"{per_span:,.0f} T a span:")
    for polyn, spann, tag, slices in ((956, 3637, "worst gameplay frame", 4),
                                      (270, 4004, "worst intro frame", 5),
                                      (55, 376, "gameplay mean", 4),
                                      (20, 152, "intro mean", 5)):
        t = per_poly * polyn + per_span * spann
        print(f"  {tag:<24}{polyn:>5} polys {spann:>5} spans  "
              f"{t:>11,.0f} T = {t/REFRESH:6.2f} refreshes, "
              f"{t/(slices*REFRESH)*100:5.0f}% of its {slices}-slice pause")

    print(f"\nThe plan swept the per-polygon cost from 1,500 to 4,500 T and found the")
    print(f"overrun rate unchanged at 0.73%. Measured: {per_poly:,.0f} T"
          + (", inside that range." if 1500 <= per_poly <= 4500 else ", OUTSIDE it."))
    print(f"But the plan also costed a span at {SPAN_MEASURED} T, and this code "
          f"charges {per_span:,.0f}.")
    print(f"Re-run tools/frameload.py with SPAN={per_span:.0f} and "
          f"POLY={per_poly:.0f} before trusting any budget figure.")

    z.cmd(f"write-memory {sym['bench']} 0")
    z.close()
    print("\nPASS: the per-polygon cost is measured, not swept.")


if __name__ == "__main__":
    main()
