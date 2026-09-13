#!/usr/bin/env python3
"""Step 0: what one polygon span costs on the machine, decomposed.

Method is the project's own: the program increments a counter after each batch
of spans, we watch that counter while the CPU free-runs, and divide the
emulator's T-state counter by the spans completed. No breakpoints, nothing that
perturbs what is being measured.

(mode) selects what runs inside one build, so overhead and each fill mode are
separated without rebuilding - the shape src/dmatest.asm uses for DMA vs LDIR.
"""
import re, statistics, sys, time
sys.path.insert(0, "tools")
from zrcp import Zrcp

NEX, EXP = "build/span.nex", "build/span.exp"
SPANS     = 1000        # spans per pass, must match the asm
SPANLEN   = 22          # bytes per span, must match the asm
PASSES    = 6
SAMPLES   = 5
CLOCK     = 28_000_000
REFRESH   = CLOCK // 50
WORST     = 4004        # worst frame's span count, measured on the host

MODES = [
    (0, "whole span loop + unrolled stores", True),
    (1, "whole span loop, no fill (overhead)", True),
    (2, "fill only: unrolled stores",         False),
    (3, "fill only: PUSH",                    False),
    (4, "fill only: blend, SET 3,(HL)",       False),
    (5, "fill only: copy from page 0",        False),
    (6, "NULL - the harness loop alone",      False),
    (7, "wrapper only, no fill",              False),
]

def symbols(path):
    out = {}
    for line in open(path):
        name, _, val = line.partition(":")
        if "0x" in val:
            out[name.strip()] = int(val.split("0x")[1], 16)
    return out

def main():
    sym = symbols(EXP)
    z = Zrcp()
    print(f"emulator: {z.cmd('get-version')}")
    print(f"machine:  {z.cmd('get-current-machine')}\n")
    z.cmd(f"smartload /work/{NEX}")
    time.sleep(4)
    z.cmd("set-memory-zone -1")

    if z.cmd(f"read-memory {sym['ready']} 1").strip() != "5A":
        raise SystemExit("FAIL: the program never reached the timed loop")
    print(f"NextReg $07 turbo:  {z.nextreg(7)}   (33H = 28 MHz)")
    print(f"NextReg $70 L2 cfg: {z.nextreg(0x70)}   (0 = 256x192 8bpp)")
    print(f"NextReg $53 MMU3:   {z.nextreg(0x53)}   (24 = Layer 2 page 0, lines 0-31)")

    # Correctness before timing: the static probe, then the loop's own output.
    # Held, so slot 3 is page 0 for the length of the read rather than whatever
    # band the loop is on.
    def hold(on):
        z.cmd("set-memory-zone -1")
        z.cmd(f"write-memory {sym['hold']} {1 if on else 0}")
        time.sleep(0.1)

    hold(True)
    probe = z.cmd(f"read-memory {0x6000 + 7*256 + 100} {SPANLEN}").strip()
    want = "2A" * SPANLEN
    hold(False)
    print(f"\nstatic probe at y=7 x=100: {'OK' if probe.upper()==want else 'MISMATCH'}")
    if probe.upper() != want:
        raise SystemExit(f"FAIL: Layer 2 addressing wrong\n  got  {probe}\n  want {want}")

    def passes():
        raw = z.cmd(f"read-memory {sym['passes']} 2").strip()
        return int(raw[2:4] + raw[0:2], 16)

    def tstates():
        return int(z.cmd("get-tstates-partial").strip())

    def wait_for(pred, what, limit=30.0):
        t0 = time.time()
        while not pred():
            if time.time() - t0 > limit:
                raise SystemExit(f"gave up waiting for {what}")
            time.sleep(0.005)

    # mode 0 must actually paint the span the loop computes
    z.cmd(f"write-memory {sym['mode']} 0")
    time.sleep(1.0)
    hold(True)
    row = z.cmd(f"read-memory {0x6000 + 3*256 + 40} {SPANLEN}").strip()
    hold(False)
    print(f"span loop output at x=40:  {'OK' if row.upper()==want else 'MISMATCH'}  ({row[:12]}...)")
    if row.upper() != want:
        raise SystemExit("FAIL: the span loop is not painting what it claims")

    def measure(mode, length=None, passes=12, samples=5):
        z.cmd("set-memory-zone -1")
        if length is not None:
            z.cmd(f"write-memory {sym['bench_len']} {length}")
        z.cmd(f"write-memory {sym['mode']} {mode}")
        time.sleep(0.4)
        out = []
        for _ in range(samples):
            base = passes_n()
            wait_for(lambda: passes_n() != base, "a pass boundary")
            z.cmd("reset-tstates-partial")
            b0 = passes_n()
            wait_for(lambda: passes_n() - b0 >= passes, f"{passes} passes")
            el, done = tstates(), passes_n() - b0
            out.append(el / (done * SPANS))
        return statistics.median(out), (max(out)-min(out))/statistics.median(out)*100

    passes_n = passes
    raw = {}
    print("\nraw, T-states per span (includes the harness loop):")
    for m, label, _ in MODES:
        raw[m], sp = measure(m, SPANLEN, passes=(40 if m>=6 else 12))
        print(f"  mode {m}  {label:<40}{raw[m]:>8.1f}" + (f"   spread {sp:.1f}%" if sp>3 else ""))

    harness, wrapper = raw[6], raw[7]
    overhead  = raw[1] - harness
    full      = raw[0] - harness
    print(f"\nharness loop itself            {harness:>8.1f} T   (subtracted below)")
    print(f"fill wrapper itself            {wrapper-harness:>8.1f} T   (subtracted from fills)")
    print(f"\nspan_row, all of it except the fill : {overhead:>7.1f} T")
    print(f"span_row + unrolled store fill      : {full:>7.1f} T")
    fill_store = raw[2] - wrapper
    print(f"  of which the fill                 : {fill_store:>7.1f} T")
    print(f"  consistency (overhead+fill vs full): {overhead+fill_store:>7.1f} vs {full:.1f} T"
          f"  -> {abs(overhead+fill_store-full)/full*100:.1f}% apart")

    # Sweep length to separate entry cost from cost per byte.
    LENS = [2, 8, 16, 32, 64, 128, 252]   # even: PUSH writes 2 bytes at a time
    print(f"\nfill cost by length (wrapper subtracted), T:")
    print("  " + "len".ljust(10) + "".join(f"{n:>9}" for n in LENS))
    fits = {}
    for m, label, _ in MODES[2:6]:
        row, pts = [], []
        for n in LENS:
            v, _ = measure(m, n, passes=8, samples=3)
            c = v - wrapper
            row.append(c); pts.append((n, c))
        # least squares slope/intercept
        k = len(pts); sx = sum(a for a,_ in pts); sy = sum(b for _,b in pts)
        sxx = sum(a*a for a,_ in pts); sxy = sum(a*b for a,b in pts)
        slope = (k*sxy - sx*sy)/(k*sxx - sx*sx); inter = (sy - slope*sx)/k
        fits[m] = (slope, inter)
        nm = label.replace("fill only: ","")
        print(f"  {nm:<10}" + "".join(f"{v:>9.0f}" for v in row)
              + f"   -> {slope:.2f} T/byte + {inter:.0f} T entry")

    print(f"\nWhat that means for a {SPANLEN}-byte span (the measured mean):")
    best_m, best_c = None, None
    for m, label, _ in MODES[2:6]:
        s, i0 = fits[m]
        c = s*SPANLEN + i0
        nm = label.replace("fill only: ","")
        print(f"  {nm:<28}{c:>7.0f} T")
        if label.startswith("fill only: unrolled") or label.startswith("fill only: PUSH"):
            if best_c is None or c < best_c: best_m, best_c = nm, c
    print(f"  cheapest opaque fill: {best_m} at {best_c:.0f} T")

    # crossover between stores and PUSH
    ss, si = fits[2]; ps, pi = fits[3]
    if abs(ss-ps) > 1e-6:
        x = (pi - si)/(ss - ps)
        print(f"  stores vs PUSH cross at {x:.0f} bytes"
              + (" (PUSH wins above that)" if ps < ss else " (stores win above that)"))

    per_span = overhead + best_c
    print(f"\nPER SPAN, end to end: {overhead:.0f} T overhead + {best_c:.0f} T fill = {per_span:.0f} T")
    for n, tag in ((4004, "worst frame measured"), (152, "intro mean"), (8, "gameplay mean")):
        tot = per_span * n
        print(f"  {tag:<22}{n:>6} spans  {tot:>12,.0f} T  {tot/REFRESH:>6.2f} refreshes")
    print(f"\nAW pauses 1-5 slices a frame: budget {REFRESH:,} to {5*REFRESH:,} T.")
    z.close()

if __name__ == "__main__":
    main()
