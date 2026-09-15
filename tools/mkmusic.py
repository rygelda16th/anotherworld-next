#!/usr/bin/env python3
"""The intro's music, rendered on the host, for the machine to play back instead of mixing it.

WHY. The intro at original speed needs the CPU the module's voices cost. Measured in CSpect, the
intro ran at 97.5% of the original with the music mixed live and at 100.3% with only the sound
effects mixed and a two-second catch-up. So the music is rendered here, once, and the machine
copies it into the copper list and mixes the effects on top.

WHAT IS RENDERED is the music as the ORIGINAL played it, not as the machine's live player would:

  - The event clock is the reference's. SfxPlayer's timer fires every `delay * 60 / 7050` ms
    (sfxplayer.cpp:43, :68) and the callback's return value is the next interval
    (sfxplayer.cpp:207-210), so a retime takes effect after the next event. The times of
    op_playMusic - the start, the retime at 45 s and the stop at 117 s - come from the reference
    engine's own run (sound.txt, written by preflight/hostprobe), because the bytecode decides
    them.
  - The notes are handlePattern's (sfxplayer.cpp:136-196): a row naming an instrument sets the
    channel's volume whatever else it does, 0xFFFD writes variable 0xF4, 0xFFFE stops the
    channel, anything else starts the instrument at 7159092 / (note * 2) Hz.
  - THE SOUND EFFECTS CUT THE MUSIC, and the other way round, because they share four channels
    (mixer.cpp:51-72). Every op_playSound in the reference's run takes its channel from the music
    at the moment it happened - so a looped note the original silenced at 42.6 s does not ring on
    here for thirteen seconds. The reverse cut - a music note stopping an effect - is the machine's
    to apply, since its effects are live, so it goes into the event table below.
  - The mixing is Mixer::mix's (mixer.cpp:99-145): linear interpolation, `b * volume / 64` per
    channel, clamped into a signed byte, biased to unsigned. The one departure is the end tests:
    the reference compares the position for EQUALITY with the last byte, which a step of more
    than one byte a sample can jump over, and then reads past the sample. This stops (or loops)
    at or past it instead.

The output rate is the copper's 312 lines x 50 Hz. The machine's tick is 312 samples, so the
rendered track and the machine's 20 ms clock stay locked together by construction.

THE FILE, build/assets/MUSIC.PCM:

    0     "AWMS"
    4     the op_playMusic it replaces: resource (byte), delay (word), position (byte)
    8     PCM length in samples, 24 bits, little-endian
    11    event count, a word
    13    three bytes of zero
    16    the events, six bytes each, in order: sample position (24 bits), type, value (word)
            type 0  variable 0xF4 = value (a 0xFFFD row)
            type 1  stop live channel `value` - a note or 0xFFFE took it; 0xFF is all four
            type 2  set live channel (value & 3)'s volume to value >> 8 (a row with an
                    instrument and no note)
    8192  unsigned 8-bit PCM at 15,600 Hz

The machine reads the first 8K as the table and streams the rest.

    python3 tools/mkmusic.py build/assets build/ref2614/sound.txt build/assets/MUSIC.PCM
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sfxmod import parse, be16    # noqa: E402

RATE = 312 * 50
TABLE_BYTES = 8192
MAX_EVENTS = (TABLE_BYTES - 16) // 6


def s8(b):
    return b - 256 if b >= 128 else b


def trunc_div64(x):
    # C's int division, which truncates towards zero
    return -((-x) >> 6) if x < 0 else x >> 6


def sample_at(ms):
    return (ms * RATE + 500) // 1000


def read_timeline(path):
    music, sfx, notes = [], [], []
    for line in open(path):
        p = line.split()
        if not p:
            continue
        if p[0] == "music":
            music.append((int(p[1]), int(p[3]), int(p[4]), int(p[5])))
        elif p[0] == "sfx":
            # gNow frame res freq vol chan len loop
            sfx.append((int(p[1]), int(p[6]) & 3, int(p[5])))
        elif p[0] == "note":
            notes.append(tuple(int(x) for x in (p[1], p[3], p[4], p[5], p[6], p[7])))
    return music, sfx, notes


class Channel:
    def __init__(self):
        self.active = False
        self.vol = 0

    def play(self, data, freq, vol):
        self.active = True
        self.data = data
        self.len = be16(data, 0) * 2
        self.loop_len = be16(data, 2) * 2
        self.loop_pos = self.len if self.loop_len else 0
        self.pos = 0
        self.inc = (freq << 8) // RATE
        self.vol = vol


def render(assets, timeline):
    music, sfx, notes = read_timeline(timeline)
    starts = [m for m in music if m[1] != 0]
    if len(starts) != 1:
        raise SystemExit(f"expected one module start in {timeline}, found {len(starts)}")
    t0, res, delay_arg, pos = starts[0]
    blob = open(os.path.join(assets, f"RES{res:02X}.BIN"), "rb").read()
    mod = parse(blob)
    delay_raw = delay_arg or mod["delay"]

    # prepareInstruments: each instrument's resource, with data+8..+11 zeroed (sfxplayer.cpp:89)
    inst = []
    for i in mod["instruments"]:
        if not i["res"]:
            inst.append(None)
            continue
        d = bytearray(open(os.path.join(assets, f"RES{i['res']:02X}.BIN"), "rb").read())
        d[8:12] = bytes(4)
        inst.append((bytes(d), i["volume"]))

    # Everything that happens, in time order. Music ops after the start and the effects; the
    # timer's events are generated as the clock passes them. At equal times the timer goes first:
    # Headless::sleep runs every event due by the end of the sleep before the VM continues.
    ops = [(t, 1, "retime" if d else "stop", d) for (t, r, d, _) in music if t > t0 and r == 0]
    ops += [(t, 2, "sfx", ch) for (t, ch, _) in sfx if t >= t0]
    ops.sort(key=lambda o: (o[0], o[1]))
    end_ms = max(o[0] for o in ops) if ops else t0

    chans = [Channel() for _ in range(4)]
    out = bytearray()
    events = []                  # (sample, type, value)
    got_notes = []
    cur_order, cur_pos = pos, 0
    delay_ms = delay_raw * 60 // 7050
    timer_next = t0 + (delay_ms or 1)
    timer_on = True

    def mix_until(sample):
        while len(out) < sample:
            acc = 0
            for ch in chans:
                if not ch.active:
                    continue
                p1 = ch.pos >> 8
                ilc = ch.pos & 0xFF
                ch.pos += ch.inc
                if ch.loop_len:
                    if p1 >= ch.loop_pos + ch.loop_len - 1:
                        p1 = min(p1, ch.loop_pos + ch.loop_len - 1)
                        p2 = ch.loop_pos
                        ch.pos = ch.loop_pos << 8
                    else:
                        p2 = p1 + 1
                else:
                    if p1 >= ch.len - 1:
                        ch.active = False
                        continue
                    p2 = p1 + 1
                b1 = s8(ch.data[8 + p1])
                b2 = s8(ch.data[8 + p2])
                b = (b1 * (0xFF - ilc) + b2 * ilc) >> 8
                acc += trunc_div64(b * ch.vol)
                acc = max(-128, min(127, acc))
            out.append((acc + 128) & 0xFF)

    def handle_events(now):
        nonlocal cur_order, cur_pos, timer_on
        order = mod["order"][cur_order]
        base = 0xC0 + cur_pos + order * 1024
        s = sample_at(now - t0)
        for c in range(4):
            n1, n2 = be16(blob, base + c * 4), be16(blob, base + c * 4 + 2)
            buf = None
            vol = None
            if n1 != 0xFFFD:
                idx = (n2 & 0xF000) >> 12
                if idx and inst[idx - 1]:
                    buf, vol = inst[idx - 1]
                    eff = (n2 & 0x0F00) >> 8
                    if eff == 5:
                        vol = min(0x3F, vol + (n2 & 0xFF))
                    elif eff == 6:
                        vol = max(0, vol - (n2 & 0xFF))
                    # setChannelVolume, on whatever the channel holds
                    chans[c].vol = vol
                    if n1 == 0:
                        events.append((s, 2, (vol << 8) | c))
            if n1 == 0xFFFD:
                events.append((s, 0, n2))
            elif n1 == 0xFFFE:
                got_notes.append((now, c, 0, 0, 0, 0))
                chans[c].active = False
                events.append((s, 1, c))
            elif n1 != 0 and buf is not None:
                freq = (7159092 // (n1 * 2)) & 0xFFFF
                chans[c].play(buf, freq, vol)
                got_notes.append((now, c, freq, vol, chans[c].len, chans[c].loop_len))
                events.append((s, 1, c))
        cur_pos += 16
        if cur_pos >= 1024:
            cur_pos = 0
            cur_order += 1
            if cur_order == mod["num_order"]:
                timer_on = False
                for ch in chans:
                    ch.active = False
                events.append((s, 1, 0xFF))
            # a module that ends leaves cur_order past numOrder; nothing reads it again

    for (t, _, kind, arg) in ops + [(end_ms + 1, 9, "end", 0)]:
        while timer_on and timer_next <= t and timer_next <= end_ms:
            mix_until(sample_at(timer_next - t0))
            handle_events(timer_next)
            timer_next += delay_ms or 1
        mix_until(sample_at(min(t, end_ms) - t0))
        if kind == "retime":
            delay_ms = arg * 60 // 7050      # the pending event keeps its time
        elif kind == "stop":
            timer_on = False                 # the timer only: notes ring on (sfxplayer.cpp:106-113)
        elif kind == "sfx":
            chans[arg].active = False        # the effect takes the channel
        if not timer_on and not any(ch.active for ch in chans):
            break

    # trailing silence is not worth streaming
    while out and out[-1] == 128 and len(out) > (events[-1][0] if events else 0):
        out.pop()

    # The reference engine's own notes, in the window the module played, must be exactly ours.
    window = [n for n in notes if n[0] >= t0]
    if [tuple(n) for n in window] != got_notes[:len(window)] or len(got_notes) != len(window):
        k = next((i for i, (a, b) in enumerate(zip(window, got_notes)) if tuple(a) != b),
                 min(len(window), len(got_notes)))
        raise SystemExit(f"note {k} differs from the reference: "
                         f"{window[k] if k < len(window) else None} vs "
                         f"{got_notes[k] if k < len(got_notes) else None}")
    return (res, delay_arg, pos), bytes(out), events, len(window)


def main():
    assets, timeline, dst = sys.argv[1:4]
    key, pcm, events, n_notes = render(assets, timeline)
    if any(t == 2 for _, t, _ in events):
        # st_apply in src/aw.asm handles types 0 and 1 only: the intro makes no type 2
        raise SystemExit("this module changes a live channel's volume, which the machine does not apply")
    if len(events) > MAX_EVENTS:
        raise SystemExit(f"{len(events)} events do not fit the {MAX_EVENTS} the table holds")
    head = bytearray(b"AWMS")
    head += bytes([key[0]]) + key[1].to_bytes(2, "little") + bytes([key[2]])
    head += len(pcm).to_bytes(3, "little") + len(events).to_bytes(2, "little") + bytes(3)
    for s, t, v in events:
        head += s.to_bytes(3, "little") + bytes([t]) + v.to_bytes(2, "little")
    head += bytes(TABLE_BYTES - len(head))
    with open(dst, "wb") as f:
        f.write(head)
        f.write(pcm)
    kinds = [sum(1 for e in events if e[1] == k) for k in range(3)]
    print(f"{dst}: resource {key[0]:#04x} delay {key[1]} position {key[2]}; "
          f"{len(pcm):,} samples, {len(pcm) / RATE:.1f} s; "
          f"{n_notes} notes match the reference engine's; "
          f"{kinds[0]} markers, {kinds[1]} channel stops, {kinds[2]} volume changes")


if __name__ == "__main__":
    main()
