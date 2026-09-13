#!/usr/bin/env python3
"""How many mixer voices are live, and at what rates, over a whole run.

The host probe writes `sound.txt` for the entire run rather than for the traced
window, because voice concurrency is a property of minutes of play. Each line is
one event:

    sfx   <ms> <frame> <resId> <freqIndex> <vol> <chan> <len> <loopLen>
    note  <ms> <frame> <chan> <hz> <vol> <len> <loopLen>
    music <ms> <frame> <resId> <delay> <pos>
    load  <ms> <frame> <type> <size> <heapUsed>

A voice occupies its channel from the moment it starts until it is replaced on
that channel, stopped (volume or note zero), or - if it does not loop - until its
data runs out at its own playback rate. A looping voice runs until something
replaces it, which is why music keeps all four channels busy.

This matters because the mixer is not an occasional cost. If something is
playing almost all the time, the mixer is a permanent tax on the frame budget
and has to be counted as one.

    python3 tools/voices.py sound.txt
"""

import sys

# VirtualMachine::frequenceTable, staticres.cpp:61-67. A sound effect names an
# index into this; a music note carries its own Hz, already converted from the
# Amiga period by sfxplayer.cpp.
FREQ = [0x0CFF, 0x0DC3, 0x0E91, 0x0F6F, 0x1056, 0x114E, 0x1259, 0x136C,
        0x149F, 0x15D9, 0x1726, 0x1888, 0x19FD, 0x1B86, 0x1D21, 0x1EDE,
        0x20AB, 0x229C, 0x24B3, 0x26D7, 0x293F, 0x2BB2, 0x2E4C, 0x3110,
        0x33FB, 0x370D, 0x3A43, 0x3DDF, 0x4157, 0x4538, 0x4998, 0x4DAE,
        0x5240, 0x5764, 0x5C9A, 0x61C8, 0x6793, 0x6E19, 0x7485, 0x7BBD]

NEVER = float("inf")


def read(path):
    ev, music, loads = [], 0, []
    for line in open(path):
        f = line.split()
        if not f:
            continue
        if f[0] == "sfx":
            t, fi, vol, ch = int(f[1]), int(f[4]), int(f[5]), int(f[6])
            ln, loop = int(f[7]), int(f[8])
            ev.append((t, ch, FREQ[fi] if vol else 0, ln, loop, vol))
        elif f[0] == "note":
            t, ch, hz, vol = int(f[1]), int(f[3]), int(f[4]), int(f[5])
            ln, loop = int(f[6]), int(f[7])
            ev.append((t, ch, hz, ln, loop, vol))
        elif f[0] == "music":
            music += 1
        elif f[0] == "load":
            loads.append((int(f[3]), int(f[4]), int(f[5])))
    ev.sort()
    return ev, music, loads


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "sound.txt"
    ev, music, loads = read(path)
    if not ev:
        raise SystemExit(f"{path} holds no voice events")
    end = max(e[0] for e in ev)

    spans, live = [], {}
    for t, ch, hz, ln, loop, _ in ev:
        if ch in live:
            start, stop = live.pop(ch)
            spans.append((start, min(stop, t)))
        if hz:
            dur = NEVER if loop else ln / hz * 1000.0
            live[ch] = (t, t + dur)
    for start, stop in live.values():
        spans.append((start, min(stop, end)))
    spans = [(a, b) for a, b in spans if b > a]

    edges = sorted({x for a, b in spans for x in (a, b)} | {0.0, float(end)})
    occ = [0.0] * 5
    for i in range(len(edges) - 1):
        a, b = edges[i], edges[i + 1]
        n = sum(1 for s, e in spans if s <= a and e >= b)
        occ[min(n, 4)] += b - a
    total = sum(occ) or 1.0

    hz = [e[2] for e in ev if e[2]]
    print(f"{len(ev):,} voice events over {end/60000:.1f} minutes of virtual time")
    print(f"  {music} music commands, {sum(1 for e in ev if e[2] and e[4])} "
          f"looping voices of {len(hz)} starts")
    print(f"  playback rates {min(hz):,} to {max(hz):,} Hz, "
          f"median {sorted(hz)[len(hz)//2]:,}")
    vols = [e[5] for e in ev if e[2]]
    print(f"  volumes {min(vols)} to {max(vols)} of 63")
    print("\noccupancy:")
    for n in range(5):
        bar = "#" * int(60 * occ[n] / total)
        print(f"  {n} voices {100*occ[n]/total:5.1f}%  {bar}")
    mean = sum(n * occ[n] for n in range(5)) / total
    print(f"\n  silent {100*occ[0]/total:.1f}% of the time; mean {mean:.2f} voices")
    print(f"  a mixer sized for {max(n for n in range(5) if occ[n])} voices is "
          f"sized for {100*(total-occ[0])/total:.1f}% of the run")
    if loads:
        print(f"\n{len(loads)} resource loads, peak heap "
              f"{max(h for _, _, h in loads):,} bytes")


if __name__ == "__main__":
    main()
