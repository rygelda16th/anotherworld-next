#!/usr/bin/env python3
"""Gate E, third claim: the sound player's two halves.

 1. THE MIXER'S BYTES. Four voices at four different rates, with the volume table
    and the loops, mixed into the real ring - compared byte for byte against a host
    model of the reference's own arithmetic. `make check-mix` priced the inner loop
    and proved it for one voice against a ramp; this is that loop in its real
    setting, four voices deep, writing where the DMA will read.

 2. THE OUTPUT CLOCKING. zxnDMA streaming the ring to the DAC with auto-restart,
    its port A address sampled every 20 ms, and the rate FITTED from those samples
    rather than asserted. It must come out at 875 kHz / prescalar, and it must WRAP
    rather than run off the end.

Both rest on the three local ZEsarUX patches - prescalar, readback and
auto-restart - so these figures are reproducible only in this project's container.
Upstream, the prescalar is read and used as a boolean, a read of the DMA port
returns zero, and a block stops at its end whatever WR5 says.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zrcp import Zrcp  # noqa: E402

NEX, EXP = "build/sndtest.nex", "build/sndtest.exp"
RING_LEN = 2048
VOLUME = 48
RATE_NUM = 875_000

# active, frac, start, inc as (int, frac) - the same 16.8 increments check-mix
# used, from real rates in the trace at a 21,875 Hz output.
VOICES = [
    (1, 0x00, 0,   0x00, 0xF5),      # 10,559 Hz -> 0.958
    (1, 0x00, 64,  0x02, 0x45),      # 25,031 Hz -> 2.270
    (1, 0x00, 128, 0x00, 0x4D),      #  3,327 Hz -> 0.302
    (1, 0x00, 192, 0x01, 0x5A),      # 14,915 Hz -> 1.353
]


def scale(b):
    """clamp((int8)b * VOLUME / 64) - mixer.cpp:141, truncating towards zero."""
    v = b - 256 if b >= 128 else b
    m = min(abs(v) * VOLUME >> 6, 127)
    return (-m if v < 0 else m) & 0xFF


def host_mix(n):
    """What the ring must hold: the first active voice stores, the rest add."""
    ring = [None] * n
    for active, frac, start, inci, incf in VOICES:
        if not active:
            continue
        pos, f = start, frac
        for i in range(n):
            raw = pos & 0xFF                 # the sample is a ramp
            s = scale(raw)
            if ring[i] is None:
                ring[i] = s ^ 0x80           # store, biased to the DAC's centre
            else:
                d = s - 256 if s >= 128 else s
                v = ring[i] + d
                ring[i] = 255 if v > 255 else (0 if v < 0 else v)
            f += incf
            pos += inci + (f >> 8)
            f &= 0xFF
    return bytes(128 if v is None else v for v in ring)


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
    print(f"emulator: {z.cmd('get-version')}")
    z.cmd(f"smartload /work/{NEX}")
    time.sleep(4)
    z.cmd("set-memory-zone -1")
    if z.cmd(f"read-memory {sym['ready']} 1").strip().upper() != "5A":
        raise SystemExit("FAIL: the program never reached its wait loop")

    prescalar = int(z.cmd(f"read-memory {sym['prescalar_used']} 1").strip(), 16)
    want_rate = RATE_NUM / prescalar
    print(f"prescalar {prescalar} -> {want_rate:,.0f} bytes a second "
          f"(22,050 asked for, so {100*(want_rate/22050-1):+.1f}%)")

    def run(what, limit=400):
        z.cmd(f"write-memory {sym['done']} 0")
        z.cmd(f"write-memory {sym['what']} {what}")
        z.cmd(f"write-memory {sym['go']} 1")
        for _ in range(limit):
            if z.cmd(f"read-memory {sym['done']} 1").strip().upper() == "5A":
                return True
            time.sleep(0.05)
        return False

    # ---- claim 1: the mixer's bytes ---------------------------------------
    blob = bytearray()
    for active, frac, start, inci, incf in VOICES:
        blob += bytes([active, frac, start & 0xFF, start >> 8, incf,
                       inci & 0xFF, inci >> 8, 0])
    z.cmd(f"write-memory-raw {sym['poke_voices']} {blob.hex()}")

    for n in (16, 64, 200):
        z.cmd(f"write-memory {sym['mix_len']} {n}")
        if not run(1):
            raise SystemExit(f"FAIL: the mixer never finished at {n} samples")
        # the ring is in a banked page the program maps at $0000; the program
        # leaves it mapped, so it can be read there
        got = bytes.fromhex(z.cmd(f"read-memory 0 {n}").strip())
        want = host_mix(n)
        if got != want:
            k = next(i for i in range(n) if got[i] != want[i])
            print(f"\n{n} samples: {sum(1 for i in range(n) if got[i]!=want[i])} "
                  f"of {n} bytes differ")
            print(f"  first at {k}: machine {got[k]:#04x}, host {want[k]:#04x}")
            print(f"  machine {got[max(0,k-3):k+5].hex(' ')}")
            print(f"  host    {want[max(0,k-3):k+5].hex(' ')}")
            raise SystemExit("FAIL: the mixer's bytes are not the reference's")
        print(f"  {n:>4} samples, four voices: every byte matches the host")

    # ---- claim 2: the DMA's rate and its wrap -----------------------------
    n = 40
    z.cmd(f"write-memory {sym['dma_samples']} {n}")
    if not run(2, limit=1200):
        raise SystemExit("FAIL: the DMA run never finished")
    raw = bytes.fromhex(z.cmd(f"read-memory {sym['dma_log']} {n*2}").strip())
    pos = [int.from_bytes(raw[i:i + 2], "little") for i in range(0, n * 2, 2)]

    outside = [p for p in pos if p > RING_LEN]
    wraps = sum(1 for a, b in zip(pos, pos[1:]) if b < a)
    # unwrap and fit a rate over the whole run
    unwrapped, base = [], 0
    for a, b in zip(pos, pos[1:]):
        if b < a:
            base += RING_LEN
        unwrapped.append(base + b)
    span = unwrapped[-1] - (pos[0]) if unwrapped else 0
    secs = (len(pos) - 1) * 0.02
    rate = span / secs if secs else 0

    print(f"\nthe DMA over {n} samples 20 ms apart:")
    print(f"  port A moved {span:,} bytes in {secs:.2f} s -> {rate:,.0f} bytes/s")
    print(f"  wanted {want_rate:,.0f} from prescalar {prescalar}: "
          f"{100*(rate/want_rate-1):+.1f}%")
    print(f"  wraps seen {wraps}, addresses outside the ring {len(outside)}")

    if outside:
        raise SystemExit("FAIL: port A left the ring, so auto-restart is not "
                         "reloading the address")
    if wraps == 0:
        raise SystemExit("FAIL: no wrap in the whole run, so the ring is not "
                         "looping")
    if abs(rate / want_rate - 1) > 0.15:
        raise SystemExit(f"FAIL: the DMA is streaming at {rate:,.0f} bytes a "
                         f"second, not {want_rate:,.0f}")

    z.close()
    print(f"""
PASS: four voices mix byte-exact against the host, and the DMA empties the ring at
      {rate:,.0f} bytes a second with {wraps} wraps and nothing outside it.

      Both rest on the three local ZEsarUX patches. Upstream the prescalar is read
      and used as a boolean, a read of the DMA port returns zero, and a block stops
      at its end whatever WR5 says - so none of this is reproducible there.""")


if __name__ == "__main__":
    main()
