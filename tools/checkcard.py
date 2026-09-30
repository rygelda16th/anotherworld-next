#!/usr/bin/env python3
"""checkcard.py - plan-pi-gus.md's CSpect gates for the Pi card (make check-card; it opens CSpect
windows, one at a time, never beside another CSpect).

The game (build/aw.nex, the shipped image) boots in CSpect with its Pi UART on a fake NextPi:
nextpi-gus's tools/fakepi.py, whose card is nextpi-gus's build/mac/ngus on a pty of its own. The
intro is started from outside (awprobe: AWPROBE_POKE start_part, AWPROBE_GO), and
tools/cspect/awsnd.cs logs the card's state block (card.inc's card_abi, read from page 11's
physical memory) once a second with the game's own counters.

A2 - the boot:
  1. a Pi with the card: the probe says GP42, the handoff reaches GUS1, no speed switch (CSpect is
     an emulator), the upload of GUSALL.GUS (227 blocks) from CSpect's SD card has every block good
     the first time, and the card's %M is the build's CRC (gusdata.inc) - as the machine read it,
     and as the card wrote it (the fake Pi's status log). The card is then on: its work runs in the
     interrupt every frame, the card counts good lines and no bad one, and the intro runs;
  2. a Pi without the card (--fresh): the game types GUSINST.TXT at SUP, the probe then finds the
     card it installed (the ARM build, byte for byte), and the same boot follows;
  3. no Pi at all: the probe gives up (CS_NOPI) and the intro runs on the Z80 path.

A3 - the sound on the card (--only 4,5):
  4. the whole intro with the card: every effect the machine asked for (awsnd's log of
     aw_play_sound) is on the next frame's F line, as a note or a stop on its channel's voice,
     the sound's own sample, the reference's pitch in Hz and the volume x 4; the music the card
     keeps - every A line the Next sent, less what its cuts dropped - is, row for row and at the
     same times, what the reference's player makes of the machine's own op_playMusic calls
     (nextpi-gus's awmus2gus.py's Sequencer: start, retime, stop, at the machine's ticks); each
     module's instruments' first four samples are zeroed (W) when it starts; the markers keep
     their times - the scripts that wait on 0xF4 ask for the same effects as the reference engine
     (A0's comparison); the card saw no bad line; and the intro runs at 100% or more of the
     original's speed (tools/cspect/speed.py's measure, from this run's pace log);
  5. the card killed mid-intro (fakepi.py --kill-after): the watchdog trips, the Z80 path's mixer
     takes over, and the intro runs on with no crash.

    python3 tools/checkcard.py [--only 1,2,3,4,5]
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
GUS = os.environ.get("NEXTPI_GUS", os.path.expanduser("~/src/nextpi-gus"))
CSPECT = os.environ.get("CSPECT_DIR", os.path.expanduser("~/src/cspect/CSpect"))
SD = os.path.join(os.path.dirname(CSPECT), "sd", "aw")
FAKEPI = os.path.join(GUS, "build", "fakepi")
FAILS = []
sys.path.insert(0, os.path.join(GUS, "tools"))
import gus_proto as g   # noqa: E402

CS = {0: "not tried", 1: "no Pi", 2: "no card", 3: "no GUS1", 4: "upload failed", 5: "no %M",
      6: "%M wrong", 7: "ON", 8: "lost"}
ABI_LEN = 48


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


def gusdata():
    inc = open(os.path.join(REPO, "build", "gusdata.inc")).read()

    def val(n):
        m = re.search(rf"^{n}\s+EQU (\$?)([0-9A-Fa-f]+)", inc, re.M)
        return int(m.group(2), 16 if m.group(1) else 10)
    return {"blocks": val("GUS_BLOCKS"), "len": val("GUS_LEN_LO") | (val("GUS_LEN_HI") << 16),
            "crc": val("GUS_CRC_LO") | (val("GUS_CRC_HI") << 16)}


def plugin(name, src):
    dll = os.path.join(CSPECT, name)
    subprocess.check_call(["mcs", "-target:library", "-r:" + os.path.join(CSPECT, "Plugin.dll"), "-out:" + dll, src],
                          stdout=subprocess.DEVNULL)
    return dll


def wait_no_mono(most=1800):
    t0 = time.time()
    while subprocess.run(["pgrep", "-f", "CSpect.exe"], capture_output=True).returncode == 0:
        if time.time() - t0 > most:
            raise SystemExit("another CSpect (mono) is still running after 30 min")
        print("        (another CSpect is running: waiting)", flush=True)
        time.sleep(15)


def parse_card(line):
    """`card <frame> <ticks> <hex> <watch...>` -> a dict of card_abi's fields."""
    p = line.split()
    b = bytes.fromhex(p[3])
    w = lambda o: b[o] | (b[o + 1] << 8)
    d = {"frame": int(p[1]), "ticks": int(p[2]), "st": b[0], "inst": b[1], "uperr": b[2], "speed": b[3],
         "upframes": w(4), "isrs": w(6), "passes": b[8], "err": b[9],
         "m": w(10) | (w(12) << 16), "bytes": w(14) | (w(16) << 16), "tn": w(18),
         "tv": [w(20 + 2 * i) for i in range(9)], "on_ticks": w(38), "on_now": w(40) | (b[42] << 16),
         "nfx": w(43), "nrows": w(45), "ncuts": b[47], "watch": [int(x) for x in p[4:]]}
    return d


def session(label, seconds, pi="card", kill_after=0, extra_env=None, seed=False, pace=False):
    """One CSpect run of the intro. pi: "card", "fresh" (no card installed) or None (no Pi).
    Returns (card rows, awsnd's sound calls, the fake Pi's files)."""
    print(f"\n{label}", flush=True)
    sym = symbols(os.path.join(REPO, "build", "aw.exp"))
    abi = 0x16000 + (sym["card_abi"] - 0xE000)          # page 11's physical address (bank 5: awsnd.cs)
    probe = plugin("AWProbe.dll", os.path.join(HERE, "cspect", "awprobe.cs"))
    snd = plugin("AwSnd.dll", os.path.join(HERE, "cspect", "awsnd.cs"))
    name = "AWCARD.NEX"
    shutil.copy(os.path.join(REPO, "build", "aw.nex"), os.path.join(SD, name))
    for f in ("GUSALL.GUS", "GUSINST.TXT"):
        shutil.copy(os.path.join(REPO, "build", "assets", f), os.path.join(SD, f))
    log, plog = "/tmp/awcard.txt", "/tmp/awcard-probe.txt"
    for f in (log, plog, os.path.join(FAKEPI, "PTY")):
        if os.path.exists(f):
            os.remove(f)
    fp = None
    args = ["mono", "CSpect.exe", "-w2", "-sound", "-mouse", "-basickeys", "-zxnext", "-mmc=../sd/aw/"]
    if pi:
        os.makedirs(FAKEPI, exist_ok=True)
        cmd = [sys.executable, os.path.join(GUS, "tools", "fakepi.py"), "--out", "null"]
        cmd += ["--fresh"] if pi == "fresh" else []
        cmd += ["--kill-after", str(kill_after)] if kill_after else []
        fp = subprocess.Popen(cmd, cwd=GUS, stdout=subprocess.DEVNULL, stderr=open(os.path.join(FAKEPI, "fakepi.err"), "w"))
        for _ in range(100):
            if os.path.exists(os.path.join(FAKEPI, "PTY")) and os.path.getsize(os.path.join(FAKEPI, "PTY")):
                break
            time.sleep(0.05)
        args.append("-com=" + open(os.path.join(FAKEPI, "PTY")).read().strip() + ":115200")
    env = dict(os.environ, PATH="/opt/homebrew/bin:" + os.environ.get("PATH", ""))
    env.update(AWSND_LOG=log, AWSND_TICKS=f"{sym['ticks']:X}", AWSND_CARD=f"{abi:X}:{ABI_LEN}",
               AWSND_WATCH=f"{sym['n_blit']:X},{sym['n_poly']:X},{sym['n_mix']:X}",
               AWPROBE_LOG=plog, AWPROBE_MAX=str(seconds), AWPROBE_GO=f"{sym['go']:X}",
               AWPROBE_POKE=f"{sym['start_part']:X}=2")
    if seed:
        # the reference run's random seed (variable 0x3C), as checksndcalls.py pokes it
        sd = next(int(l.split()[1]) & 0xFFFF for l in open(os.path.join(REPO, "build", "ref2614", "ops.txt"))
                  if l.startswith("seed"))
        ctl = sym.get("ctl", 0xC000)
        env["AWPROBE_POKE"] += f",{ctl:X}={sd & 255:X},{ctl + 1:X}={sd >> 8:X}"
    if pace:
        env["AWPROBE_PACE"] = f"{sym['ticks']:X}:{sym['n_blit']:X}:{sym['n_poly']:X}"
        if os.path.exists(plog + ".pace"):
            os.remove(plog + ".pace")
    if "res_page" in sym:
        env["AWSND_RESPAGE"] = f"{sym['res_page']:X}"
    if "aw_inval_res" in sym:
        env["AWSND_INVAL"] = f"{sym['aw_inval_res']:X}"
    env.update(extra_env or {})
    wait_no_mono()
    try:
        subprocess.run(args + ["../sd/aw/" + name], cwd=CSPECT, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, env=env, timeout=seconds + 120)
    finally:
        os.remove(snd)                  # CSpect loads every plugin it finds
        if fp:
            time.sleep(0.5)
            fp.terminate()
            fp.wait(5)
    lines = open(log).read().splitlines() if os.path.exists(log) else []
    rows = [parse_card(l) for l in lines if l.startswith("card ")]
    calls = [l.split() for l in lines if l[:3] in ("sfx", "mus", "inv")]
    for r in rows[::5]:
        print(f"    frame {r['frame']:5}  ticks {r['ticks']:5}  {CS.get(r['st'], r['st']):13} isrs {r['isrs']:5}  "
              f"up {r['upframes']} frames  %T {r['tn']} good {r['tv'][0]} bad {r['tv'][1]}  blits {r['watch'][0]}", flush=True)
    return rows, calls


def fakepi_file(name):
    p = os.path.join(FAKEPI, name)
    return open(p, errors="replace").read() if os.path.exists(p) else ""


def boot_checks(rows, want, installed=False):
    """The claims every session with the card shares."""
    if not check(bool(rows), "the plugin logged the card's state"):
        return None
    last = rows[-1]
    on = [r for r in rows if r["st"] == 7]
    check(last["st"] == 7 and on, "the boot: the probe, the handoff, the upload and %M - the card is ON",
          f"{CS.get(last['st'])}, uperr {last['uperr']}")
    if not on:
        return None
    first = on[0]
    check(first["uperr"] == 0 and first["passes"] == 0,
          f"GUSALL.GUS's {want['blocks']} blocks from CSpect's SD card, every one good the first time "
          f"({first['upframes']} frames at 115,200)", f"uperr {first['uperr']}, passes {first['passes']}")
    check(first["speed"] == 9, "no speed switch: gus_speed saw an emulator (9)", f"speed {first['speed']}")
    check(first["m"] == want["crc"], f"the card's %M as the machine read it is the build's CRC ({want['crc']:08X})",
          f"{first['m']:08X}")
    ms = []
    for l in fakepi_file("status.log").splitlines():
        p = l.split()
        if len(p) == 2 and p[1].startswith("%M"):
            t, vs = g.pparse(p[1])          # %M: address (2), length (2), CRC-32 (2)
            ms.append((g.unnum36(vs[0], vs[1]), g.unnum36(vs[2], vs[3]), g.uncrc2(vs[4], vs[5])))
    check(ms == [(0, want["len"], want["crc"])],
          f"and as the card wrote it: one %M, over the {want['len']:,} bytes from 0 (the fake Pi's status log)",
          " ".join(f"{a} {n} {m:08X}" for a, n, m in ms))
    isr = [r["isrs"] for r in on]
    frames = on[-1]["frame"] - on[0]["frame"]
    check(len(on) >= 5 and isr[-1] - isr[0] >= frames * 0.9,
          f"the interrupt's card work every frame after it: {isr[-1] - isr[0]} runs in {frames} CSpect frames")
    check(last["tn"] >= 5 and last["tv"][0] > 100 and last["tv"][1] == 0 and last["tv"][2] == 0,
          f"the card's %T: {last['tv'][0]} good lines, no bad line, no gap ({last['tn']} %T lines)", f"{last['tv']}")
    blits = [r["watch"][0] for r in on]
    check(blits[-1] > blits[0] + 20, f"and the intro runs meanwhile: {blits[-1] - blits[0]} blits since the card came on")
    if installed:
        started = [l for l in fakepi_file("fakepi.log").splitlines() if "card started for" in l]
        check(first["inst"] == 1 and started and "/NextPi/nextpi/nextpi-gus" in started[0] and "the ARM card" in started[0],
              "GUSINST.TXT typed at SUP installed the card, the ARM build byte for byte, in /NextPi/nextpi; "
              "the probe then found it", f"inst {first['inst']}; {started[:1]}")
    return on


# ---- A3 -----------------------------------------------------------------------------------

def next_lines():
    """Every line the Next sent the card (the fake Pi's next.bin), parsed: (type, items)."""
    data = open(os.path.join(FAKEPI, "next.bin"), "rb").read().decode("latin-1")
    out = []
    for ln in data.split("\n"):
        if not ln.startswith("#"):
            continue
        try:
            t, _, payload = g.parse(ln)
        except g.BadLine:
            out.append(("bad", []))
            continue
        out.append((t, payload))
    return out


def card_streams(lines):
    """(the effects on F lines, the music the card keeps, the W writes, the cuts, the all-offs)."""
    fx, music, writes, cuts, alloffs = [], [], [], [], []
    last = None

    def unwrap(st):
        nonlocal last
        if last is not None:
            while st < last - (1 << 17):
                st += 1 << 18
        last = st
        return st
    for t, payload in lines:
        if t in ("F", "A"):
            vs = g.unitems(payload)
            stamp = unwrap(vs[0])
            for off, ev in g.decode_events(vs[1:], t == "F"):
                if ev[0] == "cut":
                    ct = stamp + off - ev[1]
                    cuts.append((stamp, ev[1]))
                    music = [m for m in music if m[0] < ct]
                elif t == "A":
                    music.append((stamp + off, ev))
                elif ev[0] == "alloff":
                    alloffs.append(stamp + off)
                else:
                    fx.append((stamp + off, ev))
        elif t == "W":
            vs = g.unitems(payload[:9])
            writes.append((g.unnum36(vs[0], vs[1]), vs[2], payload[9:]))
    return fx, music, writes, cuts, alloffs


def expected_fx(calls, gus_of):
    """awsnd's sfx calls as the card should get them: the last call a frame on each channel, a
    note or a stop on the next frame's F line - less those a stop of every voice (op_updateMemList(0),
    a part's setup) came after in the same frame: the mailbox is emptied. And the all-offs."""
    sys.path.insert(0, HERE)
    hz = __import__("mksndfreq").table(open(os.path.join(REPO, "preflight/hostprobe/probe/staticres.cpp")).read())
    last, alloffs = {}, []
    for c in calls:
        tick = int(c[1])
        if c[0] == "inval":
            for k in [k for k in last if k[0] == tick]:
                del last[k]
            alloffs.append(gus_of(tick + 1))
        elif c[0] == "sfx":
            res, freq, vol, chan = (int(x) for x in c[2:6])
            if len(c) > 6 and c[6] == "0":
                continue                    # not loaded: the game ignores it (vm.cpp:698), the card too
            last[(tick, chan & 3)] = (res, freq, vol)
    out = []
    for (tick, ch) in sorted(last):
        res, freq, vol = last[(tick, ch)]
        ev = ("stop", ch) if vol == 0 else ("note", ch, res, min(vol, 63) * 4, hz[min(freq, 39)], 8, 0)
        out.append((gus_of(tick + 1), ev))
    return out, sorted(set(alloffs))


def expected_music(calls, gus_of, until):
    """What the reference's player makes of the machine's op_playMusic calls, row by row, to `until`."""
    sys.path.insert(0, os.path.join(REPO, "tools"))
    import awmus2gus as am
    import memlist
    import bytekiller
    import sfxmod
    import json
    up = json.load(open(os.path.join(GUS, "build", "upload", "aw", "upload.json")))
    by_id = {x["id"]: x for x in up["sounds"]}
    es, banks = memlist.load(os.path.join(REPO, "data"))
    rows, seq, zeros = [], None, []
    ops = [(int(c[1]), int(c[2]), int(c[3]), int(c[4])) if c[0] == "music" else (int(c[1]), "stop", 0, 0)
           for c in calls if c[0] in ("music", "inval")]
    for tick, res, delay, pos in ops + [(None, None, None, None)]:
        t = gus_of(tick) if tick is not None else until
        while seq is not None and seq.on and seq.timer_next <= t:
            rows.append(seq.row())
        if tick is None:
            break
        if res == "stop":                   # player->stop(): op_updateMemList(0), a part's setup
            if seq is not None:
                seq.on = False
        elif res:
            e = next(x for x in es if x["id"] == res)
            blob = bytekiller.read_resource(e, banks[e["bank"]])
            mod = sfxmod.parse(blob)
            inst = []
            for i in mod["instruments"]:
                if not i["res"]:
                    inst.append(None)
                    continue
                sm = by_id[i["res"]]
                inst.append((i["res"], i["volume"], sm["samples"] - sm["loop_len"], sm["loop_len"]))
                zeros.append((t, sm["address"]))
            ms = (delay or mod["delay"]) * 60 // 7050
            seq = am.Sequencer(blob, mod, inst, pos, 0, t + (ms or 1), ms)
        elif seq is not None and delay:
            seq.delay_ms = delay * 60 // 7050
        elif seq is not None:
            seq.on = False
    out = []
    for now, evs, _ in rows:
        items = [v for e in evs for v in e]
        out += [(now + off, ev) for off, ev in g.decode_events(items, False)]
    return out, zeros


def a3_intro():
    want = gusdata()
    rows, calls = session("A3.1 the whole intro with the card: effects, music, markers, speed", 230, seed=True, pace=True)
    on = boot_checks(rows, want)
    if not on:
        return
    first = on[0]
    gus_of = lambda tick: first["on_now"] + 20 * (tick - first["on_ticks"])
    lines = next_lines()
    check(not any(t == "bad" for t, _ in lines), f"every one of the {len(lines):,} lines the Next sent is a valid GUS1 line")
    fx, music, writes, cuts, alloffs = card_streams(lines)
    t_on = gus_of(first["on_ticks"])
    calls_on = [c for c in calls if gus_of(int(c[1])) >= t_on]
    # the effects
    efx, eao = expected_fx(calls_on, gus_of)
    check(alloffs == eao, f"every voice off on the F line after each op_updateMemList(0) or part setup ({len(eao)})",
          f"{alloffs[:5]} vs {eao[:5]}")
    same = fx == efx
    i = next((i for i, (a, b) in enumerate(zip(fx, efx)) if a != b), min(len(fx), len(efx)))
    check(same and len(fx) >= 40, f"the {len(fx)} effects on the F lines are the machine's {len(efx)} aw_play_sound calls: "
          "the next frame's line, the channel's voice, the sound, its pitch in Hz, its volume x 4",
          f"first difference at {i}: card {fx[i] if i < len(fx) else None} vs {efx[i] if i < len(efx) else None}")
    # the music
    last_a = max((t for t, _ in music), default=0)
    em, zeros = expected_music(calls_on, gus_of, last_a)
    em = [m for m in em if m[0] <= last_a]
    j = next((j for j, (a, b) in enumerate(zip(music, em)) if a != b), min(len(music), len(em)))
    nnotes = sum(1 for _, e in music if e[0] == "note")
    check(music == em and nnotes > 300,
          f"the music the card keeps is the reference player's for the machine's op_playMusic calls: "
          f"{len(music)} events ({nnotes} notes), row for row at the same times, after {len(cuts)} cut(s)",
          f"first difference at {j}: card {music[j] if j < len(music) else None} vs model {em[j] if j < len(em) else None}")
    zw = sorted((a, n, d) for a, n, d in writes)
    want_z = sorted({a for _, a in zeros})
    check([a for a, n, d in zw] == want_z and all(n == 4 and set(d) <= {"A"} for a, n, d in zw),
          f"W: four zero bytes at each of the {len(want_z)} instruments' first samples, as the module started",
          f"{[(hex(a), n) for a, n, d in zw][:6]}")
    # the markers: the scripts that wait on them asked for what the reference engine did
    sys.path.insert(0, HERE)
    import checksndcalls as cs
    import difflib
    rsfx, rmus = cs.reference()
    sfx = [tuple(int(x) for x in c[2:6]) for c in calls if c[0] == "sfx"]
    mus = [tuple(int(x) for x in c[2:5]) for c in calls if c[0] == "music"]
    sm = difflib.SequenceMatcher(a=rsfx[:len(sfx) + 10], b=sfx, autojunk=False)
    moved = sum(max(op[2] - op[1], op[4] - op[3]) for op in sm.get_opcodes() if op[0] != "equal" and op[3] < len(sfx))
    firstd = next((i for i, (x, y) in enumerate(zip(sfx, rsfx)) if x != y), len(sfx))
    check(len(sfx) >= 40 and firstd >= 30 and moved <= 6 and mus == rmus[:len(mus)] and len(mus) >= 2,
          f"the markers keep their times: the machine's {len(sfx)} effects are the reference engine's (the first "
          f"{firstd} exactly, {moved} differing where A0 found the scripts' own timing), its {len(mus)} music calls too")
    last = rows[-1]
    tv = last["tv"]
    check(tv[1] == 0 and tv[2] == 0, f"the card's last %T: no bad line, no gap; {tv[3]} late, {tv[4]} steps "
          "(the Next's loads with interrupts off)", f"{tv}")
    # the speed, from this run's pace log
    import importlib.util
    spec = importlib.util.spec_from_file_location("speed", os.path.join(HERE, "cspect", "speed.py"))
    sp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sp)
    try:
        te, tm = sp.compare("/tmp/awcard-probe.txt.pace", os.path.join(REPO, "build", "ref2614", "frames.txt"), 5, 2613)
        check(te / tm >= 1.0, f"the intro at {100 * te / tm:.1f}% of the original's speed (at least 100%)")
    except Exception as e:      # noqa: BLE001
        check(False, "the intro's speed, from the pace log", repr(e))


def a3_kill():
    lines = sum(1 for _ in open(os.path.join(REPO, "build", "assets", "GUSALL.GUS")))
    n = lines + 3 + 1200                # H, the upload, M, then about 20 s of play
    rows, calls = session(f"A3.2 the card killed mid-intro (after {n:,} lines)", 75, kill_after=n)
    if not check(bool(rows), "the plugin logged the card's state"):
        return
    on = [r for r in rows if r["st"] == 7]
    lost = [r for r in rows if r["st"] == 8]
    check(bool(on) and bool(lost), "the card came on, then went: the watchdog tripped (CS_LOST)",
          f"on {len(on)} s, lost {len(lost)} s, err {lost[0]['err'] if lost else None}")
    if not lost:
        return
    a, b = lost[0], rows[-1]
    check(b["watch"][2] > a["watch"][2] + 100, f"the Z80 path's mixer took over: {b['watch'][2] - a['watch'][2]} mixes since",
          f"n_mix {a['watch'][2]} -> {b['watch'][2]}")
    check(b["ticks"] > a["ticks"] + 250 and b["watch"][0] > a["watch"][0] + 20,
          f"and the intro ran on, no crash: {b['ticks'] - a['ticks']} ticks and {b['watch'][0] - a['watch'][0]} blits after",
          f"ticks {a['ticks']} -> {b['ticks']}, blits {a['watch'][0]} -> {b['watch'][0]}")
    tail = [c for c in calls if int(c[1]) > a["ticks"]]
    check(len([c for c in tail if c[0] == "sfx"]) > 0, f"and it still plays effects: {len(tail)} sound calls after")


def a2_card():
    rows, _ = session("A2.1 a Pi with the card: the boot, the upload, %M, then the intro", 45)
    boot_checks(rows, gusdata())


def a2_fresh():
    rows, _ = session("A2.2 a Pi without the card: GUSINST.TXT, then the boot", 70, pi="fresh")
    boot_checks(rows, gusdata(), installed=True)


def a2_nopi():
    rows, _ = session("A2.3 no Pi: the probe gives up, the Z80 path", 20, pi=None)
    if not check(bool(rows), "the plugin logged the card's state"):
        return
    last = rows[-1]
    check(all(r["st"] in (0, 1) for r in rows) and last["st"] == 1 and last["isrs"] == 0,
          "the probe found no SUP> (CS_NOPI) and the card never ran", f"{CS.get(last['st'])}, isrs {last['isrs']}")
    b = [r["watch"][0] for r in rows]
    check(b[-1] > b[0] + 20, f"the intro runs on the Z80 path: {b[-1]} blits")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="1,2,3,4,5")
    a = ap.parse_args()
    if not os.path.isdir(CSPECT):
        print(f"no CSpect at {CSPECT}: skipped\nRESULT: SKIPPED")
        return 0
    if not os.path.exists(os.path.join(GUS, "build", "mac", "ngus")):
        subprocess.check_call(["make", "-C", GUS, "build/mac/ngus"])
    only = set(a.only.split(","))
    if "1" in only:
        a2_card()
    if "2" in only:
        a2_fresh()
    if "3" in only:
        a2_nopi()
    if "4" in only:
        a3_intro()
    if "5" in only:
        a3_kill()
    print()
    if FAILS:
        print(f"RESULT: {len(FAILS)} FAILED")
        return 1
    print("RESULT: ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
