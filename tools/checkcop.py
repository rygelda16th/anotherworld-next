#!/usr/bin/env python3
"""Copper sound: does a copper list fed twice a frame play a clean signal? Measured in the audio.

src/coptest.asm drives the DAC from the copper - one MOVE a scanline - and feeds it a triangle
whose every step is +8 or -8. ZEsarUX is started with --aofile, which writes the audio it actually
produced: 312 samples a video frame (FRECUENCIA_CONSTANTE_NORMAL_SONIDO is 312*50), signed 8-bit,
MONO in the raw form - the WAV writer's two channels do not apply to it. Reading it as stereo halved
the period and passed half the samples as "steps"; the first run of this checker did exactly that. So this reads the emulator's own output back and counts the samples that break the
triangle: a dropped, repeated or stale sample shows as a step of any other size.

The claim is about ZEsarUX's copper and DAC. CSpect and real hardware are separate questions.
"""
import os
import sys
import time
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zrcp import Zrcp  # noqa: E402

NEX, EXP, RAW = "build/coptest.nex", "build/coptest.exp", "build/cop.raw"
SECONDS = 8


def symbols(path):
    out = {}
    for line in open(path):
        name, _, val = line.partition(":")
        if "0x" in val:
            out[name.strip()] = int(val.split("0x")[1], 16)
    return out


def read(z, addr, n):
    raw = z.cmd(f"read-memory {addr} {n}").strip()
    return bytes(int(raw[i:i + 2], 16) for i in range(0, 2 * n, 2))


def main():
    sym = symbols(EXP)
    z = Zrcp()
    print(f"emulator: {z.cmd('get-version')}")
    z.cmd(f"smartload /work/{NEX}")
    time.sleep(3.0)
    z.cmd("set-memory-zone -1")
    if read(z, sym["ready"], 1)[0] != 0x5A:
        raise SystemExit("FAIL: the harness never reached its idle loop")
    t0 = int.from_bytes(read(z, sym["ticks"], 2), "little")
    size0 = os.path.getsize(RAW) if os.path.exists(RAW) else 0
    time.sleep(SECONDS)
    t1 = int.from_bytes(read(z, sym["ticks"], 2), "little")
    feeds = int.from_bytes(read(z, sym["n_feed"], 2), "little")
    line = read(z, sym["last_line"], 1)[0]
    size1 = os.path.getsize(RAW)
    print(f"  {t1 - t0} frames in {SECONDS}s, {feeds} feeds so far, last interrupt at line (low byte) {line}")
    try:
        z.cmd("exit-emulator")
    except Exception:
        pass
    time.sleep(1.0)

    data = open(RAW, "rb").read()[size0:size1]
    left = [((b + 128) & 0xFF) for b in data]            # signed bytes, mono, to unsigned
    # the triangle is only there once the harness is running: take the last 90% of the capture
    left = left[len(left) // 10:]
    steps = Counter(left[i + 1] - left[i] for i in range(len(left) - 1))
    print(f"  {len(left)} samples; commonest steps: {steps.most_common(6)}")
    unit = max((abs(s) for s, _ in steps.most_common(3) if s), default=0)
    good = steps.get(unit, 0) + steps.get(-unit, 0)
    # a turning point repeats neither value nor direction here, so every other step is a glitch
    bad = len(left) - 1 - good
    # the period, from the rising zero crossings of the mean-removed signal
    mean = sum(left) / len(left)
    ups = [i for i in range(1, len(left)) if left[i - 1] < mean <= left[i]]
    period = (ups[-1] - ups[0]) / (len(ups) - 1) if len(ups) > 1 else 0
    print(f"  step unit {unit}; {good} good steps, {bad} glitches; period {period:.2f} samples "
          f"(the harness plays 62)")
    if unit == 0 or bad > len(left) // 1000 or abs(period - 62) > 0.5:
        raise SystemExit(f"FAIL: the copper did not play a clean triangle")
    print(f"PASS: the copper played the triangle clean - {good} steps, {bad} glitches, "
          f"period {period:.2f} samples")


if __name__ == "__main__":
    main()
