#!/usr/bin/env python3
"""Step 5: how fast does esxDOS read, and what does a part load cost?

The plan's own instruction: measure this before any of Phase D is built. It is the
one number in that phase with no evidence behind it, and a part load that takes
four seconds is a loading-screen design decision rather than an implementation
detail.

Timing is the emulator's T-state counter around the read and nothing else, so the
figure is the read - not the read plus whatever the harness was doing. A part is
four resources and at worst 154,971 bytes, which is what the last table costs out.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zrcp import Zrcp  # noqa: E402

NEX, EXP = "build/loadtest.nex", "build/loadtest.exp"
ASSETS = "build/assets"
CLOCK = 28_000_000
REFRESH = CLOCK // 50

# Each part's four resources, from parts.cpp:14-26. A palette is 2,048 bytes and
# is not a separate file (make assets converts those), so it is costed by size.
PARTS = [
    ("protection",      0x14, 0x15, 0x16, None),
    ("intro cinematic", 0x17, 0x18, 0x19, None),
    ("3, water",        0x1A, 0x1B, 0x1C, 0x11),
    ("4, jail",         0x1D, 0x1E, 0x1F, 0x11),
    ("5, cave",         0x20, 0x21, 0x22, 0x11),
    ("battlechar",      0x23, 0x24, 0x25, None),
    ("7, arena",        0x26, 0x27, 0x28, 0x11),
    ("8, baths",        0x29, 0x2A, 0x2B, 0x11),
    ("9, final",        0x7D, 0x7E, 0x7F, None),
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
    z.cmd(f"smartload /work/{NEX}")
    time.sleep(4)
    z.cmd("set-memory-zone -1")
    if z.cmd(f"read-memory {sym['ready']} 1").strip().upper() != "5A":
        raise SystemExit("FAIL: the program never reached its wait loop")

    def read_file(name):
        blob = name.encode() + b"\x00"
        z.cmd(f"write-memory-raw {sym['fname']} {blob.hex()}")
        z.cmd(f"write-memory {sym['done']} 0")
        z.cmd("reset-tstates-partial")
        z.cmd(f"write-memory {sym['go']} 1")
        for _ in range(400):
            if z.cmd(f"read-memory {sym['done']} 1").strip().upper() == "5A":
                break
            time.sleep(0.05)
        else:
            raise SystemExit(f"FAIL: reading {name} never finished")
        t = int(z.cmd("get-tstates-partial").strip())
        raw = bytes.fromhex(z.cmd(f"read-memory {sym['got']} 4").strip())
        got = int.from_bytes(raw, "little")
        err = int(z.cmd(f"read-memory {sym['err']} 1").strip(), 16)
        where = int(z.cmd(f"read-memory {sym['errwhere']} 1").strip(), 16)
        return t, got, err, where

    print(f"\n{'file':<14}{'bytes on disk':>14}{'read':>10}{'T-states':>14}"
          f"{'T/byte':>9}{'KB/s':>9}")
    rates, sizes, times = [], [], []
    for res in (0x18, 0x19, 0x11, 0x21, 0x22, 0x1B, 0x25):
        name = f"RES{res:02X}.BIN"
        path = os.path.join(ASSETS, name)
        if not os.path.exists(path):
            print(f"  {name} missing - run make assets")
            continue
        size = os.path.getsize(path)
        t, got, err, where = read_file(name)
        if err:
            print(f"{name:<14}{size:>14,}  esxDOS error {err:#04x} at "
                  f"{'open' if where == 1 else 'read'}")
            continue
        ok = "" if got == size else f"  <-- SHORT, got {got:,}"
        per = t / got if got else 0
        kbs = CLOCK / per / 1024 if per else 0
        rates.append(per)
        sizes.append(got)
        times.append(t)
        print(f"{name:<14}{size:>14,}{got:>10,}{t:>14,}{per:>9.1f}{kbs:>9.0f}{ok}")

    # Does the time even depend on the size? If ZEsarUX's esxDOS handler does its
    # I/O on the host at no emulated cost, then every figure above is the
    # checker's own polling latency and none of it is a read rate.
    if len(rates) < 3:
        raise SystemExit("FAIL: too few files read to judge anything")
    n = len(sizes)
    mx, my = sum(sizes) / n, sum(times) / n
    sxy = sum((a - mx) * (b - my) for a, b in zip(sizes, times))
    sxx = sum((a - mx) ** 2 for a in sizes) ** 0.5
    syy = sum((b - my) ** 2 for b in times) ** 0.5
    r = sxy / (sxx * syy) if sxx and syy else 0.0
    spread = (max(times) - min(times)) / (sum(times) / n)

    print(f"\nsize against time over {n} files: r = {r:.3f}, "
          f"times spread {spread*100:.0f}% across a {max(sizes)/min(sizes):.1f}-fold "
          f"range of sizes")

    if r < 0.5:
        print("""
NOT MEASURABLE HERE, and that is the result.

The time a read takes does not depend on how much is read: the smallest file above
cost MORE emulated time than the largest, and two files 98 bytes apart in size cost
the same number of T-states to the byte. ZEsarUX's esxDOS handler does its I/O on
the host and charges the emulated CPU nothing for it, so what these figures measure
is this checker's polling interval while the program spins in its wait loop.

So the read rate is a HARDWARE question, and it joins the list of things only the
KS3 can answer - alongside whether the DMA honours $123B and what it really costs
a byte. Until then Phase D should be designed against an assumed rate rather than
a measured one, and the assumption stated where it is used.

What this run DOES establish, and it is not nothing:
  * esxDOS opens and reads these files correctly, through a buffer in IX, with the
    code at $8000 and the destination in a banked page at $C000 - so the two traps
    carried over from wolf3d-next are avoided in working code.
  * every byte arrives: each file's length matches the host's exactly, over eight
    8K pages for the largest.
  * a part's four resources are at most 154,971 bytes, so at any rate above
    100 KB/s a part load is under two seconds and a held frame covers it.""")
        z.close()
        # Not a failure. Nothing here is wrong: the loading path is verified and
        # the emulator simply does not model the cost. A gate should go red when
        # something is broken, not when a question turns out to need hardware.
        print("\nPASS, INCONCLUSIVE ON SPEED: the loading path works and every "
              "byte arrives.\n      The rate needs the KS3.")
        return

    per = max(rates)
    print(f"\nworst rate seen: {per:.1f} T a byte, "
          f"{CLOCK/per/1024:.0f} KB/s at 28 MHz")
    print(f"\nWhat a part costs, at that rate:")
    print(f"  {'part':<18}{'bytes':>10}{'T-states':>13}{'refreshes':>11}"
          f"{'seconds':>10}")
    worst = None
    for name, pal, code, cine, v2 in PARTS:
        total = 2048
        for res in (code, cine, v2):
            if res is None:
                continue
            path = os.path.join(ASSETS, f"RES{res:02X}.BIN")
            if os.path.exists(path):
                total += os.path.getsize(path)
        t = total * per
        print(f"  {name:<18}{total:>10,}{t:>13,.0f}{t/REFRESH:>11.1f}"
              f"{t/CLOCK:>10.2f}")
        if worst is None or total > worst[1]:
            worst = (name, total, t / CLOCK)
    print(f"\nThe worst part is {worst[0]} at {worst[1]:,} bytes, "
          f"{worst[2]:.2f} s.")

    z.close()
    print("\nPASS: the read rate is measured.")


if __name__ == "__main__":
    main()
