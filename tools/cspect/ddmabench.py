#!/usr/bin/env python3
"""plan-ddma.md D2: run preflight/ddma/bench.asm in CSpect 4.5.1.0 and price a 320x256 row.

The bench times each way of filling 4,096 or so pixels in raster lines (1,792 T-states at 28 MHz),
and counts what the 2D fills left in memory. awprobe reads `ready`, `results` and `checks` out of
the CPU's map (AWPROBE_PEEK). These are CSpect's numbers: how it charges the DMA's time is its own
model of the core, and the KS3 is the only measure of the real one.

    make measure-ddma                   CSPECT_DIR=<CSpect folder>, default ~/nextdev/cspect4/CSpect
"""
import os
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
from checkddma import CSPECT, SD, plugin, symbols  # noqa: E402

LINE = 1792
TESTS = [  # (name, pixels or bytes, span length, spans)
    ("nothing (the method's own cost)", 0, 0, 0),
    ("CPU, ld (hl),a / inc h: 64 spans of 64", 4096, 64, 64),
    ("plain zxnDMA fill, 8,192 bytes (today's)", 8192, 0, 0),
    ("zxnDDMA fill, 8,192 bytes (D1)", 8192, 0, 0),
    ("zxnDDMA 2D fill: 64 spans of 64", 4096, 64, 64),
    ("zxnDDMA 2D fill: 13 spans of 320", 4160, 320, 13),
    ("zxnDDMA 2D fill: 256 spans of 16", 4096, 16, 256),
    ("as 4, the whole programme every span", 4096, 64, 64),
    ("as 6, the whole programme every span", 4096, 16, 256),
    ("as 4, a 3,300 T wait after every span", 4096, 64, 64),
]


SCREEN_BYTES = 4096             # the ULA's first two thirds: character rows 0-15
DIGITS = [bytes(r) for r in (
    (0x3C, 0x66, 0x6E, 0x76, 0x66, 0x66, 0x3C, 0), (0x18, 0x38, 0x18, 0x18, 0x18, 0x18, 0x7E, 0),
    (0x3C, 0x66, 0x06, 0x0C, 0x30, 0x60, 0x7E, 0), (0x3C, 0x66, 0x06, 0x1C, 0x06, 0x66, 0x3C, 0),
    (0x0C, 0x1C, 0x3C, 0x6C, 0x7E, 0x0C, 0x0C, 0), (0x7E, 0x60, 0x7C, 0x06, 0x06, 0x66, 0x3C, 0),
    (0x3C, 0x60, 0x7C, 0x66, 0x66, 0x66, 0x3C, 0), (0x7E, 0x06, 0x0C, 0x18, 0x30, 0x30, 0x30, 0),
    (0x3C, 0x66, 0x66, 0x3C, 0x66, 0x66, 0x3C, 0), (0x3C, 0x66, 0x66, 0x3E, 0x06, 0x0C, 0x38, 0))]


def read_screen(scr, rows):
    """The ULA bitmap from $4000 as text: bench.asm's digits, a space for an empty cell."""
    out = []
    for r in range(rows):
        line = ""
        for c in range(32):
            cell = bytes(scr[((r & 0x18) << 8) + (k << 8) + ((r & 7) << 5) + c] for k in range(8))
            line += str(DIGITS.index(cell)) if cell in DIGITS else (" " if not any(cell) else "?")
        out.append(line.rstrip())
    return out


def main():
    sym = symbols(os.path.join(REPO, "build", "ddmabench.exp"))
    out = os.path.join(REPO, "build", "ddma")
    os.makedirs(out, exist_ok=True)
    plugin()
    name = "DDMABNCH.NEX"
    shutil.copy(os.path.join(REPO, "build", "ddmabench.nex"), os.path.join(SD, name))
    log = os.path.join(out, "bench.txt")
    if os.path.exists(log):
        os.remove(log)
    n = sym["checks"] + 24 - sym["ready"]
    env = dict(os.environ, AWPROBE_LOG=log, AWPROBE_MAX="12",
               AWPROBE_PEEK=f"{sym['ready']:X}:{n},4000:{SCREEN_BYTES}")
    try:
        subprocess.run(["mono", "CSpect.exe", "-w2", "-sound", "-mouse", "-basickeys", "-zxnext",
                        "-mmc=../sd/aw/", "../sd/aw/" + name], cwd=CSPECT, env=env,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=180)
    finally:
        os.remove(os.path.join(SD, name))
    rows = [l.split()[2:] for l in open(log) if l.startswith(f"# peek@{sym['ready']:04X}")]
    scr = [l.split()[2:] for l in open(log) if l.startswith("# peek@4000")]
    if not rows or rows[-1][0] != "5A":
        raise SystemExit("the bench did not finish\nRESULT: FAIL")
    b = bytes(int(x, 16) for x in rows[-1])
    word = lambda a: b[a - sym["ready"]] | (b[a - sym["ready"] + 1] << 8)
    lines = [word(sym["results"] + 2 * i) for i in range(len(TESTS))]
    base = lines[0]
    print(f"CSpect at {CSPECT}; a line is {LINE} T-states at 28 MHz; the method's own cost, {base} line(s), taken off\n")
    print(f"{'test':48} {'lines':>6} {'T-states':>9} {'T a pixel/byte':>15}")
    for (label, px, _, _), ln in zip(TESTS, lines):
        t = (ln - base) * LINE
        print(f"{label:48} {ln:6} {t:9} {t / px if px else 0:15.2f}")
    print("\nwhat the 2D fills left in memory (want = spans x length):")
    bad = 0
    for i, (label, px, length, spans) in enumerate(TESTS[4:]):
        good, tot = word(sym["checks"] + 4 * i), word(sym["checks"] + 4 * i + 2)
        want = length * spans
        ok = good == want and tot == want
        bad += not ok
        print(f"  {label:46} in the spans {good:5}, anywhere {tot:5}, want {want:5}  {'ok' if ok else 'WRONG'}")

    # what `show` put on the ULA screen, read back: the same numbers, one line a test
    screen = bytes(int(x, 16) for x in scr[-1])
    text = read_screen(screen, len(TESTS))
    want = []
    for t in range(len(TESTS)):
        w = f"{t} {lines[t]:05d}"
        if t >= 4:
            w += f" {word(sym['checks'] + 4 * (t - 4)):05d} {word(sym['checks'] + 4 * (t - 4) + 2):05d}"
        want.append(w)
    shown = text == want
    print("\non the screen (what the KS3 will show; test, lines, then for 4-9 the two counts):")
    for line in text:
        print("  " + line)
    if not shown:
        print("  NOT the numbers in memory: " + str(want))
    print("RESULT: " + ("PASS" if not bad and shown else "FAIL"))
    sys.exit(1 if bad or not shown else 0)


if __name__ == "__main__":
    main()
