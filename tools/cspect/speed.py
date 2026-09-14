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
                if last >= blits + 1:
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
    eng = [int(l.split()[6]) for l in open(frames) if not l.startswith("#")]
    m = {}
    for l in open(pace):
        if l.startswith("#") or not l.strip():
            continue
        b, t, _, _ = map(int, l.split())
        m.setdefault(b, t)
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
        e = sum(eng[a:b]) * 0.02
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
    ap.add_argument("--frames", default=os.path.join(REPO, "build/ref700/frames.txt"))
    ap.add_argument("--blits", type=int, default=700)
    ap.add_argument("--first", type=int, default=5)
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--pace", help="analyse an existing pace log instead of running")
    a = ap.parse_args()
    pace = a.pace or run(a.nex, a.exp, a.blits, a.timeout, {})
    compare(pace, a.frames, a.first, a.blits)


if __name__ == "__main__":
    main()
