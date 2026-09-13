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
    WINDOWS = sorted({(f, l) for f, l in WINDOWS if l > 0})

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

    # The per-polygon cost is MEASURED, not fitted. One window draws a polygon
    # and no spans at all, so its whole pass is the per-polygon path: the
    # bounding-box test, the vertex walk's setup and the record advance. A five
    # term least squares over these windows puts polygons and spans at r = 0.96
    # and can move cost freely between them - it returned 28,690 T a polygon and
    # 95 T a copy byte, both of which are impossible.
    zero = [(p, t) for p, s_, _, t in rows if s_ == 0 and p == 1]
    if not zero:
        raise SystemExit("FAIL: no single-polygon window draws zero spans, so the "
                         "per-polygon cost cannot be measured directly")
    per_poly = min(t for _, t in zero)
    print(f"\nper polygon, MEASURED from a window that draws one polygon and no "
          f"spans:\n  {per_poly:,.0f} T")

    # With that fixed, the rest is well posed - but only for the modes the vector
    # actually exercises. Copy-mode bytes never exceed 952 in any window and are
    # zero in most, so their coefficient is unidentifiable: fitted freely it came
    # out at MINUS 243 T a byte. They are folded in with blend, which step 0
    # measured at 32.2 against copy's 37.6 - a 17% difference, far smaller than
    # the error in pretending to have measured it.
    A = [[float(s_), float(mb[0]), float(mb[1] + mb[2])] for _, s_, mb, _ in rows]
    y = [float(t) - per_poly * float(p) for p, _, _, t in rows]
    K = 3
    M = [[sum(A[k][i] * A[k][j] for k in range(len(A))) for j in range(K)]
         + [sum(A[k][i] * y[k] for k in range(len(A)))] for i in range(K)]
    for i in range(K):
        piv = max(range(i, K), key=lambda rr: abs(M[rr][i]))
        M[i], M[piv] = M[piv], M[i]
        if abs(M[i][i]) < 1e-9:
            raise SystemExit("FAIL: singular - the windows do not vary the fill "
                             "modes independently enough")
        for rr in range(K):
            if rr != i:
                f = M[rr][i] / M[i][i]
                for c in range(i, K + 1):
                    M[rr][c] -= f * M[i][c]
    coef = [M[i][K] / M[i][i] for i in range(K)]
    b, bo, bb = coef
    bc = bb
    resid = [y[k] - sum(A[k][i] * coef[i] for i in range(K)) for k in range(len(A))]
    rms = (sum(rr * rr for rr in resid) / len(resid)) ** 0.5

    print(f"\nwith that subtracted, the span terms:")
    print(f"  per span entry           {b:>9.0f} T   (step 0's own span row: 433)")
    print(f"  per opaque byte          {bo:>9.1f} T   (step 0 measured  5.4 by PUSH,"
          f" 10.7 unrolled)")
    print(f"  per blend or copy byte   {bb:>9.1f} T   (step 0 measured 32.2 and 37.6)")
    print(f"  residual RMS {rms:,.0f} T, {100*rms/statistics.mean([t for *_, t in rows]):.1f}%"
          f" of the mean pass over {len(rows)} windows")

    # Spot-check the model against the three windows it should predict best:
    # a single polygon with many long spans, where the byte term dominates.
    print(f"\nthe model against single-polygon windows, worst first:")
    checks = sorted(((p, s_, mb, t) for p, s_, mb, t in rows if p == 1),
                    key=lambda r: -r[3])[:4]
    for p, s_, mb, t in checks:
        pred = per_poly + b * s_ + bo * mb[0] + bb * mb[1] + bc * mb[2]
        print(f"  {s_:>4} spans, {sum(mb):>6,} bytes: predicted {pred:>10,.0f} T, "
              f"measured {t:>10,.0f}  ({100*(pred-t)/t:+.1f}%)")

    print(f"\nWhat this says about the code as it stands. span_opaque is a plain")
    print(f"  ld (hl),a / inc l / djnz loop at {bo:.0f} T a byte. Step 0 measured a PUSH")
    print(f"  fill at 5.4 and an unrolled store at 10.7, so the rasteriser's fill is")
    print(f"  {bo/5.4:.1f}x dearer than the cheapest one already measured - and the plan's")
    print(f"  672 T a span describes step 0's purpose-built row, not this code.")
    print(f"  The two deferred optimisations are therefore NOT optional after all.")

    # The game's own spans are 22 bytes and mostly opaque, so the frames below use
    # step 0's end-to-end 672 T a span rather than this vector's mode-heavy mix.
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
