#!/usr/bin/env python3
"""Record the game's own audio under ZEsarUX and say whether it is sound: the intro, from boot.

ZEsarUX runs with --aofile, which writes what it actually played - 15,600 mono signed 8-bit samples
a second, one a scanline. This lets the VM go, waits, and reads the file back:

  - frames with sound: any of the frame's 312 samples away from the centre
  - stuck stretches: runs of one value long enough to be a feed that stopped rather than music

and writes a WAV beside it, so a person can listen to the same bytes the numbers came from.
"""
import os
import struct
import sys
import time
import wave

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zrcp import Zrcp  # noqa: E402

NEX, EXP = "build/aw.nex", "build/aw.exp"
RAW, WAV = "build/game.raw", "build/game.wav"
SECONDS = int(os.environ.get("REC_SECONDS", "25"))


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
    z.cmd(f"smartload /work/{NEX}")
    time.sleep(3.5)
    z.cmd("set-memory-zone -1")
    start = os.path.getsize(RAW)
    z.cmd(f"write-memory {sym['go']} 1")
    time.sleep(SECONDS)
    end = os.path.getsize(RAW)
    try:
        z.cmd("exit-emulator")
    except Exception:
        pass
    time.sleep(1)
    data = open(RAW, "rb").read()[start:end]
    u = bytes(((b + 128) & 0xFF) for b in data)
    with wave.open(WAV, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(1)
        w.setframerate(15600)
        w.writeframes(u)
    frames = [u[i:i + 312] for i in range(0, len(u) - 311, 312)]
    centre = max(set(u), key=u.count) if u else 128
    sound = sum(1 for f in frames if any(abs(b - centre) > 1 for b in f))
    longest, run = 0, 1
    for i in range(1, len(u)):
        run = run + 1 if u[i] == u[i - 1] else 1
        longest = max(longest, run)
    print(f"  {len(u)} samples, {len(frames)} frames; {sound} frames with sound "
          f"({100 * sound / max(1, len(frames)):.0f}%); longest run of one value {longest} samples; "
          f"centre {centre}")
    print(f"  wrote {WAV}")


if __name__ == "__main__":
    main()
