#!/usr/bin/env python3
"""How fast does the intro run, against the original engine? Measured in CSpect, in emulated time.

The machine's own 50 Hz tick counter is read at every blit by awprobe (AWPROBE_PACE), so the
host running CSpect below real speed does not enter into it. The original's time for the same
blits is what its scripts ask for: pause_slices x 20 ms each (vm.cpp:285-297 sleeps exactly
that, less the time the frame took, which on a PC is nothing). frames.txt from the host probe
holds pause_slices per blit.

    python3 tools/cspect/speed.py build/aw.nex --blits 700

Runs one CSpect, silent (-sound MUTES CSpect 3), and kills it after. Refuses to start if a
CSpect is already open, because that one is somebody's.
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
CSPECT = os.environ.get("CSPECT_DIR", os.path.expanduser("~/src/cspect/CSpect"))
SD = os.path.join(os.path.dirname(CSPECT), "sd", "aw")
DLL = os.path.join(CSPECT, "AWProbe.dll")
SRC = os.path.join(HERE, "awprobe.cs")


def symbols(path):
    out = {}
    for line in open(path):
        m = re.match(r"(\S+):\s*EQU\s*0x([0-9A-Fa-f]+)", line.strip())
        if m:
            out[m.group(1)] = int(m.group(2), 16)
    return out


def ensure_plugin():
    if not os.path.exists(DLL) or os.path.getmtime(DLL) < os.path.getmtime(SRC):
        subprocess.check_call(["mcs", "-target:library", "-r:" + os.path.join(CSPECT, "Plugin.dll"),
                               "-out:" + DLL, SRC])


def cspect_running():
    return subprocess.run(["pgrep", "-f", "CSpect.exe"], capture_output=True).returncode == 0


def run(nex, exp, blits, timeout, extra_env):
    if cspect_running():
        raise SystemExit("a CSpect is already open - not touching it")
    ensure_plugin()
    sym = symbols(exp)
    name = "AWSPEED.NEX"
    shutil.copy(nex, os.path.join(SD, name))
    log = "/tmp/awspeed.txt"
    for f in (log, log + ".pace"):
        if os.path.exists(f):
            os.remove(f)
    env = dict(os.environ)
    env.update(AWPROBE_LOG=log, AWPROBE_MAX="100000", AWPROBE_GO=f"{sym['go']:X}",
               AWPROBE_PACE=f"{sym['ticks']:X}:{sym['n_blit']:X}:{sym['n_poly']:X}")
    if "st_played" in sym:
        env.update(AWPROBE_STREAM=f"{sym['st_played']:X}:{sym['st_avail']:X}")
    env.update(extra_env)
    proc = subprocess.Popen(["mono", "CSpect.exe", "-w2", "-sound", "-mouse", "-basickeys", "-zxnext",
                             "-mmc=../sd/aw/", "../sd/aw/" + name], cwd=CSPECT,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
    start = time.time()
    try:
        last = 0
        while time.time() - start < timeout:
            time.sleep(2)
            if os.path.exists(log + ".pace"):
                lines = open(log + ".pace").read().split("\n")
                rows = [l for l in lines if l and not l.startswith("#")]
                if rows:
                    last = int(rows[-1].split()[0])
                if last >= blits + 400:            # the machine is ~355 blits ahead; see compare
                    break
            if proc.poll() is not None:
                break
    finally:
        proc.kill()
        proc.wait()
        subprocess.run(["pkill", "-9", "-f", "CSpect.exe -w2 -sound -mouse -basickeys -zxnext -mmc=../sd/aw/ ../sd/aw/AWSPEED.NEX"])
        os.remove(os.path.join(SD, name))
    return log + ".pace"


def compare(pace, frames, first, blits):
    rows = [l.split() for l in open(frames) if not l.startswith("#")]
    eng = [int(r[6]) for r in rows]
    m, polys = {}, {}
    for l in open(pace):
        if l.startswith("#") or not l.strip():
            continue
        f = l.split()
        b, t = int(f[0]), int(f[1])
        m.setdefault(b, t)
        polys.setdefault(b, int(f[3]))
    # THE MACHINE'S BLIT NUMBERS ARE NOT THE REFERENCE'S. The shipped image blits about 350 times,
    # drawing nothing, before the intro's first picture - the reference draws its first at blit 5 -
    # so blit N here was never the reference's blit N, and every figure this tool printed before the
    # offset was a comparison of different pictures. Align on the first picture: the reference's
    # first blit with polygons, and the machine's first blit after which n_poly has moved.
    ref_first = next(i for i, r in enumerate(rows) if int(r[2]) > 0)
    base = polys[min(polys)]
    mach_first = min(b for b in polys if polys[b] > base + 1)
    offset = mach_first - ref_first
    print(f"aligned: the reference's first picture is its blit {ref_first}, the machine's is its blit "
          f"{mach_first}; machine blit = reference blit + {offset}")
    m = {b - offset: t for b, t in m.items() if b - offset >= 0}
    have = sorted(m)
    last = max(b for b in have if b <= blits)

    def at(b):
        while b not in m:
            b += 1
        return m[b]

    print(f"{'blits':>12} {'original s':>11} {'ours s':>8} {'speed':>7}")
    te = tm = 0.0
    for a in range(first, last, 100):
        b = min(a + 100, last)
        e = sum(eng[a + 1:b + 1]) * 0.02         # the pauses before blits a+1..b, which is a..b
        mm = (at(b) - at(a)) * 0.02
        te += e
        tm += mm
        print(f"{a:>5}-{b:<6} {e:11.2f} {mm:8.2f} {100 * e / mm if mm else 0:6.0f}%")
    print(f"TOTAL {first}-{last}: original {te:.1f} s, ours {tm:.1f} s, speed {100 * te / tm:.1f}% of the original")
    return te, tm


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("nex", nargs="?", default=os.path.join(REPO, "build/aw.nex"))
    ap.add_argument("--exp", default=os.path.join(REPO, "build/aw.exp"))
    ap.add_argument("--frames", default=os.path.join(REPO, "build/ref2614/frames.txt"))
    ap.add_argument("--blits", type=int, default=700)
    ap.add_argument("--first", type=int, default=5)
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--pace", help="analyse an existing pace log instead of running")
    a = ap.parse_args()
    pace = a.pace or run(a.nex, a.exp, a.blits, a.timeout, {})
    compare(pace, a.frames, a.first, a.blits)


if __name__ == "__main__":
    main()
