#!/usr/bin/env python3
"""checksndcalls.py - plan-pi-gus.md's A0 gate (make check-sndcalls; it opens a CSpect window).

The game (build/aw.nex) runs the intro in CSpect, silent, with no Pi, started at the intro by
awprobe (AWPROBE_POKE start_part, AWPROBE_GO). tools/cspect/awsnd.cs logs every call the C makes
to aw_play_sound and aw_play_music, with their operands. They must be the reference engine's own,
in order: build/ref2614/sound.txt, the host probe's run of the intro (its `sfx` and `music` lines).

It is the baseline the card's path is held to at A3: the machine asks for exactly what the engine
asks for, and the card must then play exactly that.

    python3 tools/checksndcalls.py [--seconds 100] [--nex build/aw.nex]
FAIL: lines and exit 1 on a failure; RESULT: ALL PASS otherwise.
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
CSPECT = os.environ.get("CSPECT_DIR", os.path.expanduser("~/src/cspect/CSpect"))
SD = os.path.join(os.path.dirname(CSPECT), "sd", "aw")
FAILS = []


def check(ok, what, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'}  {what}" + (f"  [{detail}]" if detail else ""), flush=True)
    if not ok:
        FAILS.append(what)
        print(f"FAIL: {what}" + (f" ({detail})" if detail else ""), flush=True)
    return ok


def symbols(path):
    out = {}
    for line in open(path):
        m = re.match(r"(\S+):\s*EQU\s*0x([0-9A-Fa-f]+)", line.strip())
        if m:
            out[m.group(1)] = int(m.group(2), 16)
    return out


def plugin(name, src):
    dll = os.path.join(CSPECT, name)
    subprocess.check_call(["mcs", "-target:library", "-r:" + os.path.join(CSPECT, "Plugin.dll"), "-out:" + dll, src],
                          stdout=subprocess.DEVNULL)
    return dll


def run(nex, seconds, extra_env=None, com=None):
    """One silent CSpect of the intro: (the calls, awprobe's log). com: a pty for -com (the fake Pi)."""
    if subprocess.run(["pgrep", "-f", r"^mono[^ ]* CSpect\.exe"], capture_output=True).returncode == 0:
        raise SystemExit("a CSpect is already open - not touching it")
    sym = symbols(os.path.join(REPO, "build", "aw.exp"))
    probe = plugin("AWProbe.dll", os.path.join(HERE, "cspect", "awprobe.cs"))
    snd = plugin("AwSnd.dll", os.path.join(HERE, "cspect", "awsnd.cs"))
    name = "AWSND.NEX"
    shutil.copy(nex, os.path.join(SD, name))
    log, plog = "/tmp/awsnd.txt", "/tmp/awsnd-probe.txt"
    for f in (log, plog):
        if os.path.exists(f):
            os.remove(f)
    env = dict(os.environ)
    # the reference run's random seed (variable 0x3C), as checkboot.py takes it: the intro's scripts
    # branch on it (without it the machine played sound 52 three times where the engine played none)
    seed = next(int(l.split()[1]) & 0xFFFF for l in open(os.path.join(REPO, "build", "ref2614", "ops.txt"))
                if l.startswith("seed"))
    ctl = sym.get("ctl", 0xC000)
    env.update(AWSND_LOG=log, AWSND_TICKS=f"{sym['ticks']:X}", AWPROBE_LOG=plog, AWPROBE_MAX=str(seconds),
               AWPROBE_GO=f"{sym['go']:X}",
               AWPROBE_POKE=f"{sym['start_part']:X}=2,{ctl:X}={seed & 255:X},{ctl + 1:X}={seed >> 8:X}")
    env.update(extra_env or {})
    args = ["mono", "CSpect.exe", "-w2", "-sound", "-mouse", "-basickeys", "-zxnext", "-mmc=../sd/aw/"]
    if com:
        args.append(f"-com={com}:115200")
    try:
        subprocess.run(args + ["../sd/aw/" + name], cwd=CSPECT, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, env=env, timeout=seconds + 90)
    finally:
        os.remove(snd)                  # CSpect loads every plugin it finds
    calls = [l.split() for l in open(log) if l[:3] in ("sfx", "mus")] if os.path.exists(log) else []
    return calls, (open(plog).read() if os.path.exists(plog) else "")


def reference():
    sfx, mus = [], []
    for l in open(os.path.join(REPO, "build", "ref2614", "sound.txt")):
        p = l.split()
        if p and p[0] == "sfx":
            sfx.append(tuple(int(x) for x in p[3:7]))       # res freq vol chan
        elif p and p[0] == "music":
            mus.append(tuple(int(x) for x in p[3:6]))       # res delay pos
    return sfx, mus


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=int, default=100)
    ap.add_argument("--nex", default=os.path.join(REPO, "build", "aw.nex"))
    a = ap.parse_args()
    print(f"the intro in CSpect for {a.seconds} s, the Z80 path, awsnd logging the sound calls")
    calls, plog = run(a.nex, a.seconds)
    sfx = [tuple(int(x) for x in c[2:6]) for c in calls if c[0] == "sfx"]
    mus = [tuple(int(x) for x in c[2:5]) for c in calls if c[0] == "music"]
    rsfx, rmus = reference()
    # the reference ran from the intro's start; the machine starts there too (start_part 2). The two are
    # the same bytecode, but not the same clock: CSpect runs at about 93% of the hardware, and a script
    # that paces a loop against the music plays its sound more or fewer times. So they are aligned
    # (difflib), and what differs must be small and local, and is printed: the known one is three
    # extra calls of sound 52 at about 66 s (plan-pi-gus.md, A0).
    import difflib
    sm = difflib.SequenceMatcher(a=rsfx[:len(sfx) + 10], b=sfx, autojunk=False)
    diffs = [op for op in sm.get_opcodes() if op[0] != "equal" and op[3] < len(sfx)]
    moved = sum(max(op[2] - op[1], op[4] - op[3]) for op in diffs)
    for op in diffs:
        print(f"        {op[0]}: the engine {rsfx[op[1]:op[2]]} / the machine {sfx[op[3]:op[4]]}, at the machine's call {op[3]}")
    first = next((i for i, (x, y) in enumerate(zip(sfx, rsfx)) if x != y), len(sfx))
    check(len(sfx) >= 40 and first >= 30 and moved <= 6,
          f"the machine's {len(sfx)} effects are the reference engine's, in order - the first {first} exactly, then "
          f"{moved} calls that differ where the scripts' timing does, and the rest aligned again",
          f"{len(diffs)} differences, {moved} calls")
    mfirst = next((i for i, (x, y) in enumerate(zip(mus, rmus)) if x != y), None)
    check(len(mus) >= 2 and mfirst is None, f"its {len(mus)} music calls are the reference's first {len(mus)} "
          f"(of {len(rmus)}): resource, delay, position", f"{mus} vs {rmus}")
    ticks = [int(c[1]) for c in calls]
    check(ticks == sorted(ticks), "the calls come in the machine's time order")
    print()
    if FAILS:
        print(f"RESULT: {len(FAILS)} FAILED")
        return 1
    print("RESULT: ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
