#!/usr/bin/env python3
"""Step 1: what one output sample of the mixer costs on the machine.

This is the plan's first step because sound is the largest unpriced cost in the
project. The host probe says something is playing 98.3% of the intro at a mean
of 2.83 voices, so the mixer is a permanent tax on the frame budget - and the
three candidate output rates had been costed by scaling wolf3d-next's
measurement of a mixer that does none of the three things this one has to do.

Method is the project's own, as in tools/checkspan.py: the program counts blocks
while the CPU free-runs, and the emulator's T-state counter is divided by the
samples completed. Cost is FITTED over several block lengths so the per-sample
figure does not carry the block setup. No breakpoints, nothing that perturbs
what is being measured.

Correctness first. A benchmark of wrong code measures nothing, so the volume
table, the sample ramp and an eight-sample mix are all verified against a host
computation of the reference's own arithmetic before any figure is believed.
"""
import statistics
import sys
import time

sys.path.insert(0, "tools")
from zrcp import Zrcp  # noqa: E402

NEX, EXP = "build/mixtest.nex", "build/mixtest.exp"
MIXLEN = 128            # must match the asm's default
VOLUME = 48             # must match the asm
CLOCK = 28_000_000
REFRESH = CLOCK // 50

# The rates the host trace actually shows, and the reference's own output rate.
RATES = [(11025, "half the reference"), (15625, "one per scanline"),
         (22050, "the reference's own rate")]

MODES = [
    (0, "NULL - the harness and block setup alone"),
    (1, "advance only, the floor under any mixer"),
    (2, "1 voice, table volume, store + bias"),
    (3, "1 voice, table volume, accumulate + saturate"),
    (4, "4 voices: 1 store + 3 accumulate"),
    (5, "1 voice accumulate, unrolled x4"),
    (6, "4 voices, unrolled x4"),
    (7, "1 voice, Z80N MUL D,E instead of the table"),
    (8, "a separate signed -> unsigned pass"),
    (9, "1 voice with linear interpolation"),
]

# Increments as the asm sets them: (frac, int). 16.8 fixed point.
INCS = [(0xF5, 0), (0x45, 2), (0x4D, 0), (0x5A, 1)]


def scale(b):
    """clamp((int8)b * VOLUME / 64), the reference's own volume arithmetic.

    mixer.cpp:141 is `(int)b * ch->volume / 0x40`, and C division truncates
    TOWARDS ZERO, so a negative sample rounds the other way from an arithmetic
    shift. The machine does magnitude-then-sign for exactly this reason - the
    same shape, and the same trap, as the vertex scale.
    """
    v = b - 256 if b >= 128 else b
    m = abs(v) * VOLUME >> 6
    m = min(m, 127)
    return (-m if v < 0 else m) & 0xFF


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
    z.cmd(f"smartload /work/{NEX}")
    time.sleep(4)
    z.cmd("set-memory-zone -1")

    if z.cmd(f"read-memory {sym['ready']} 1").strip() != "5A":
        raise SystemExit("FAIL: the program never reached the timed loop")

    def hold(on):
        z.cmd("set-memory-zone -1")
        z.cmd(f"write-memory {sym['hold']} {1 if on else 0}")
        time.sleep(0.1)

    def rd(addr, n):
        raw = z.cmd(f"read-memory {addr} {n}").strip()
        return bytes(int(raw[i:i + 2], 16) for i in range(0, len(raw), 2))

    # ---- correctness -----------------------------------------------------
    hold(True)
    tab = rd(sym["voltab"], 256)
    want = bytes(scale(b) for b in range(256))
    bad = [b for b in range(256) if tab[b] != want[b]]
    print(f"\nvolume table, {VOLUME} of 63: "
          f"{'OK, all 256 entries' if not bad else f'{len(bad)} WRONG'}")
    if bad:
        b = bad[0]
        print(f"  first at {b}: machine {tab[b]:#04x}, host {want[b]:#04x}")
        raise SystemExit("FAIL: the volume table is not the reference's arithmetic")

    ramp = rd(sym["sampbuf"], 256)
    if ramp != bytes(range(256)):
        raise SystemExit("FAIL: the sample ramp is wrong")
    print("sample ramp:                 OK")

    # The eight-sample mix the program runs before the timed loop. Walk the
    # same 16.8 accumulator the machine walks and scale through the same table.
    frac, pos, out = 0, 0, []
    incf, inci = INCS[0]
    for _ in range(8):
        out.append(scale(ramp[pos & 0xFF]) ^ 0x80)
        frac += incf
        pos += inci + (frac >> 8)
        frac &= 0xFF
    got = rd(sym["mixbuf"], 8)
    ok = bytes(out) == got
    print(f"eight-sample mix:            {'OK' if ok else 'MISMATCH'}")
    if not ok:
        print(f"  machine {got.hex(' ')}")
        print(f"  host    {bytes(out).hex(' ')}")
        raise SystemExit("FAIL: the machine's mix is not the reference's")
    hold(False)

    # ---- timing ----------------------------------------------------------
    def passes():
        raw = z.cmd(f"read-memory {sym['passes']} 2").strip()
        return int(raw[2:4] + raw[0:2], 16)

    def wait_for(pred, what, limit=40.0):
        t0 = time.time()
        while not pred():
            if time.time() - t0 > limit:
                raise SystemExit(f"gave up waiting for {what}")
            time.sleep(0.005)

    def measure(mode, length, blocks=12, samples=5):
        z.cmd("set-memory-zone -1")
        z.cmd(f"write-memory {sym['blocklen']} {length}")
        z.cmd(f"write-memory {sym['mode']} {mode}")
        time.sleep(0.4)
        out = []
        for _ in range(samples):
            base = passes()
            wait_for(lambda: passes() != base, "a block boundary")
            z.cmd("reset-tstates-partial")
            b0 = passes()
            wait_for(lambda: passes() - b0 >= blocks, f"{blocks} blocks")
            el = int(z.cmd("get-tstates-partial").strip())
            done = passes() - b0
            out.append(el / done)          # T per BLOCK, not per sample
        med = statistics.median(out)
        return med, (max(out) - min(out)) / med * 100

    # Fit T-per-block against block length. The intercept is the setup that a
    # real player pays once a block; the slope is the per-sample cost, which is
    # the number the whole phase turns on.
    LENS = [16, 32, 64, 128, 252]
    LENS_U4 = [16, 32, 64, 128, 240]        # the unrolled pair needs a multiple of 4
    print(f"\nT-states per BLOCK, fitted over block length:")
    print("  " + "mode".ljust(46) + "".join(f"{n:>8}" for n in LENS))
    fit = {}
    for m, label in MODES:
        lens = LENS_U4 if m in (5, 6) else LENS
        pts = []
        for n in lens:
            v, _ = measure(m, n, blocks=8, samples=3)
            pts.append((n, v))
        k = len(pts)
        sx = sum(a for a, _ in pts)
        sy = sum(b for _, b in pts)
        sxx = sum(a * a for a, _ in pts)
        sxy = sum(a * b for a, b in pts)
        slope = (k * sxy - sx * sy) / (k * sxx - sx * sx)
        inter = (sy - slope * sx) / k
        fit[m] = (slope, inter)
        print(f"  {m} {label:<44}" + "".join(f"{v:>8.0f}" for _, v in pts)
              + f"   -> {slope:6.2f} T/sample + {inter:5.0f}")

    null_s, null_i = fit[0]
    print(f"\nthe harness itself is {null_s:.2f} T/sample + {null_i:.0f} T a block, "
          "subtracted below")

    def per_sample(m):
        return fit[m][0] - null_s

    print("\nT-states per output sample, harness subtracted:")
    for m, label in MODES:
        if m == 0:
            continue
        print(f"  {label:<46}{per_sample(m):>8.2f}")

    adv = per_sample(1)
    v1 = per_sample(2)
    v1a = per_sample(3)
    v4 = per_sample(4)
    v4u = per_sample(6)
    mul = per_sample(7)
    interp = per_sample(9)

    print(f"\n  the advance is {100*adv/v1:.0f}% of a storing voice, which is why it is "
          "branchless")
    print(f"  saturating costs {v1a - v1:.1f} T over storing")
    print(f"  MUL D,E costs {mul - v1:+.1f} T against the table's 16,384 bytes")
    print(f"  interpolation costs {interp - v1:+.1f} T, {100*(interp-v1)/v1:.0f}% more")
    print(f"  unrolling x4 saves {v4 - v4u:.1f} T a sample on four voices")
    best4 = min(v4, v4u)
    print(f"  additivity check: 1 store + 3 saturating = "
          f"{v1 + 3*v1a:.0f} T vs {v4:.0f} measured, "
          f"{abs(v1 + 3*v1a - v4)/v4*100:.1f}% apart")

    print(f"\nWhat four voices cost at each candidate output rate "
          f"({best4:.0f} T a sample):")
    print("  " + "rate".ljust(10) + "note".ljust(26) + "T/second".rjust(12)
          + "% of 28 MHz".rjust(14) + "  verdict")
    for rate, note in RATES:
        t = best4 * rate
        pc = 100 * t / CLOCK
        # The rasteriser's own mean load, measured on the host at 24.8%.
        total = pc + 24.8
        verdict = ("comfortable" if total < 50 else
                   "tight but workable" if total < 70 else "too much")
        print(f"  {rate:<10,}{note:<26}{t:>12,.0f}{pc:>13.1f}%  "
              f"+ 24.8% renderer = {total:.0f}%, {verdict}")

    print(f"\nAgainst the plan's estimates of 22%, 16% and 11%: "
          f"{100*best4*22050/CLOCK:.0f}%, {100*best4*15625/CLOCK:.0f}%, "
          f"{100*best4*11025/CLOCK:.0f}%.")

    # The decision rule the plan wrote down in advance.
    worst = 100 * best4 * 22050 / CLOCK
    print(f"\nThe plan's threshold was 35% of the machine for four voices at "
          f"22,050 Hz.\n  Measured: {worst:.1f}% -> "
          + ("the ring-and-tick design stands, and the reference's own rate is "
             "affordable." if worst <= 35 else
             "at the reference's rate the design must give up fidelity on "
             "purpose; a lower rate is the first lever."))

    z.cmd(f"write-memory {sym['mode']} 0")
    z.close()
    print("\nPASS: the mixer is priced, and its arithmetic matches the reference.")


if __name__ == "__main__":
    main()
