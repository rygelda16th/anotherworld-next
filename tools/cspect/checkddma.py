#!/usr/bin/env python3
"""The fills by the zxnDDMA, in the one emulator that has one (make check-ddma; docs/plan-ddma.md D1).

Core 3.03.00's zxnDDMA fills without reading (src/aw.asm, ddma_fill); everywhere else the game fills
as it always did. ZEsarUX has no zxnDDMA, so every ZRCP gate sees only the second of those. CSpect
4.5.1.0 models it ("DMA+"), so this runs the intro there - on Xvfb, no window - twice from the same
image: once as built, once with ddma_have poked to 0 before the ENTER wait is released, which is the
plain path and nothing else. awprobe dumps the visible screen at the same blit counts in both.

It passes if the probe found the zxnDDMA at boot (ddma_have 1), if fills went the new way in the first
run (n_ddma moved after the start) and none did in the second, and if every screen both runs dumped
at the same count is the same, byte for byte. What a real core does with the same bytes, and how
long it takes, only the machine can say.

    make check-ddma                     the 320x256 build; AW_SCREEN=256 for build/aw256.nex
    AW_NEX=<.nex> AW_EXP=<.exp>         a copy of either, while a gate rebuilds the originals
    CSPECT_DIR=<CSpect folder>          default ~/nextdev/cspect4/CSpect
"""
import os
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
CSPECT = os.environ.get("CSPECT_DIR") or os.path.expanduser("~/nextdev/cspect4/CSpect")
SD = os.path.join(os.path.dirname(CSPECT), "sd", "aw")
OUT = os.path.join(REPO, "build", "ddma")
BLITS = [40, 80, 120, 160, 200, 260, 320, 380, 440, 500, 560, 620, 680]


def symbols(path):
    out = {}
    for line in open(path):
        m = re.match(r"(\S+):\s*EQU\s*0x([0-9A-Fa-f]+)", line.strip())
        if m:
            out[m.group(1)] = int(m.group(2), 16)
    return out


def plugin():
    dll = os.path.join(CSPECT, "AWProbe.dll")
    subprocess.check_call(["mcs", "-target:library", "-r:" + os.path.join(CSPECT, "Plugin.dll"),
                           "-out:" + dll, os.path.join(HERE, "awprobe.cs")], stdout=subprocess.DEVNULL)


def session(label, nex, sym, off, most=900):
    """One silent CSpect run of the intro. Returns (log lines, {blit count: screen bytes})."""
    print(f"\n{label}", flush=True)
    name = "AWDDMA.NEX"
    shutil.copy(nex, os.path.join(SD, name))
    log = os.path.join(OUT, f"{'off' if off else 'on'}.txt")
    for f in os.listdir(OUT):
        if f.startswith(os.path.basename(log)):
            os.remove(os.path.join(OUT, f))
    pokes = f"{sym['start_part']:X}=2"                  # part index 1, the intro
    if off:                                             # and undo ddma_probe's two patches
        pokes += f",{sym['ddma_have']:X}=0"
        pokes += f",{sym['dm_pre']:X}=83,{sym['dm_pre'] + 1:X}=83"
        pk = sym['dma_mem.plain']
        pokes += f",{sym['dma_mem.fill'] + 1:X}={pk & 0xFF:X},{sym['dma_mem.fill'] + 2:X}={pk >> 8:X}"
    env = dict(os.environ, AWPROBE_LOG=log, AWPROBE_MAX="100000", AWPROBE_GO=f"{sym['go']:X}",
               AWPROBE_POKE=pokes, AWPROBE_BLIT=f"{sym['n_blit']:X}:" + ",".join(map(str, BLITS)),
               AWPROBE_DDMA=f"{sym['ddma_have']:X}:{sym['n_ddma']:X}")
    proc = subprocess.Popen(["mono", "CSpect.exe", "-w2", "-sound", "-mouse", "-basickeys", "-zxnext",
                             "-mmc=../sd/aw/", "../sd/aw/" + name], cwd=CSPECT,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
    t0 = time.time()
    try:
        while time.time() - t0 < most and proc.poll() is None:
            time.sleep(2)
            dumps = [f for f in os.listdir(OUT) if f.startswith(os.path.basename(log) + ".1")]
            if any(int(f.split(".")[-2]) - 100000 >= BLITS[-1] for f in dumps):
                time.sleep(3)                           # one more report line after the last dump
                break
    finally:
        proc.kill()
        proc.wait()
        os.remove(os.path.join(SD, name))
    lines = open(log).read().split("\n") if os.path.exists(log) else []
    shots = {}
    for f in os.listdir(OUT):
        m = re.match(re.escape(os.path.basename(log)) + r"\.1(\d{5})\.ppm$", f)
        if m:
            shots[int(m.group(1))] = open(os.path.join(OUT, f), "rb").read()
    print(f"  {len(shots)} screens, {time.time() - t0:.0f} s", flush=True)
    return lines, shots


def ddma(lines, tag=None):
    """(have, n) from the last `# ddma` line, or the one marked TAG."""
    rows = [l for l in lines if l.startswith("# ddma") and (tag is None or l.endswith(tag))]
    if not rows:
        return None, None
    m = re.match(r"# ddma have=(\d+) n=(\d+)", rows[-1])
    return int(m.group(1)), int(m.group(2))


def main():
    wide = os.environ.get("AW_SCREEN", "320") != "256"
    nex, exp = (("build/aw.nex", "build/aw.exp") if wide else ("build/aw256.nex", "build/aw256.exp"))
    if os.environ.get("AW_NEX"):                    # a copy, while a gate rebuilds the originals
        nex, exp = os.environ["AW_NEX"], os.environ["AW_EXP"]
    nex, exp = os.path.join(REPO, nex), os.path.join(REPO, exp)
    if not os.path.isdir(CSPECT):
        print(f"no CSpect at {CSPECT}: skipped\nRESULT: SKIPPED")
        return
    sym = symbols(exp)
    shutil.rmtree(OUT, ignore_errors=True)
    os.makedirs(OUT)
    plugin()
    print(f"{'320x256' if wide else '256x192'}: {os.path.relpath(nex, REPO)} in {CSPECT}")
    on_lines, on = session("1. as built: the zxnDDMA's fill where the probe finds it", nex, sym, off=False)
    off_lines, off = session("2. ddma_have poked to 0: the plain zxnDMA's fill", nex, sym, off=True)

    bad = []
    have, n = ddma(on_lines)
    _, n_go = ddma(on_lines, "at go")
    print(f"\nrun 1: ddma_have {have}, n_ddma {n_go} at the start and {n} at the end")
    if have != 1:
        bad.append(f"the probe did not find the zxnDDMA (ddma_have {have})")
    if n is None or n_go is None or n <= n_go:
        bad.append("no fill went by the zxnDDMA after the start")
    have2, n2 = ddma(off_lines)
    _, n2_go = ddma(off_lines, "at go")
    print(f"run 2: ddma_have {have2}, n_ddma {n2_go} at the start and {n2} at the end")
    if have2 != 0 or n2 is None or n2 != n2_go:
        bad.append("with ddma_have 0, fills still went by the zxnDDMA")

    both = sorted(set(on) & set(off))
    same = [b for b in both if on[b] == off[b]]
    print(f"screens at the same blit count in both runs: {len(both)} of {len(BLITS)} asked for; "
          f"{len(same)} the same: {both}")
    for b in both:
        if on[b] != off[b]:
            bad.append(f"blit {b}: the screens differ")
    if len(both) < len(BLITS) // 2:
        bad.append(f"only {len(both)} screens to compare")
    if bad:
        for b in bad:
            print("  " + b)
        print(f"FAIL: {len(bad)} problem(s)\nRESULT: FAIL")
        sys.exit(1)
    print("PASS: the zxnDDMA's fills draw what the plain zxnDMA's do\nRESULT: PASS")


if __name__ == "__main__":
    main()
