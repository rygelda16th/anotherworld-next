"""Is the machine's copy of part 2's cinematic segment the same as the card's?

The reader walks garbage from a record that is valid in RES1C.BIN, so either the data on the
machine is not the data on the card, or the reader is wrong. This settles which. Part 2's
cinematic goes onto the HEAP through aw_setup_part, not into the fixed polygon pages every
gate so far has used, so it is the first segment read from pages the allocator chose.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zrcp import Zrcp                                       # noqa: E402
from checksave import symbols, NEX, EXP                          # noqa: E402

FRAMES_DONE, NR_MMU7, DWIN = 0xC008, 0x57, 0xE000
SEG = "build/assets/RES1C.BIN"


def main():
    sym = symbols(EXP)
    want = open(SEG, "rb").read()
    z = Zrcp()

    def read(a, n):
        out = bytearray()
        while len(out) < n:
            k = min(2048, n - len(out))
            raw = z.cmd(f"read-memory {a + len(out)} {k}").strip()
            out += bytes(int(raw[i:i + 2], 16) for i in range(0, 2 * k, 2))
        return bytes(out)

    def w(a):
        b = read(a, 2)
        return b[0] | (b[1] << 8)

    z.cmd(f"smartload /work/{NEX}")
    time.sleep(3.2)
    z.cmd("set-memory-zone -1")
    z.cmd(f"write-memory {sym['go']} 1")
    for _ in range(6):
        z.cmd("send-keys-event 128 1 nomenu")
        time.sleep(0.1)
        z.cmd("send-keys-event 128 0 nomenu")
        time.sleep(0.4)
    last, still = w(FRAMES_DONE), 0
    for _ in range(40):
        time.sleep(1.0)
        f = w(FRAMES_DONE)
        still = still + 1 if f == last else 0
        last = f
        if still >= 4:
            break

    # MMU7 IS SHARED WITH THE MIXER, which is what made check-res and check-draw differ from
    # byte 2,048 exactly. Stop the interrupt's half of it before reading through the window.
    z.cmd(f"write-memory {sym['snd_off']} 1")
    time.sleep(0.2)
    base = read(sym["cin_base"], 1)[0]
    print(f"  stalled at frame {last}; cin_base = page {base}; "
          f"RES1C.BIN is {len(want):,} bytes = {(len(want) + 8191) // 8192} pages")

    bad = None
    for p in range((len(want) + 8191) // 8192):
        z.cmd(f"tbblue-set-register {NR_MMU7} {base + p}")
        n = min(8192, len(want) - p * 8192)
        got = read(DWIN, n)
        exp = want[p * 8192:p * 8192 + n]
        if got != exp:
            d = next(i for i in range(n) if got[i] != exp[i])
            bad = p * 8192 + d
            print(f"    page {base + p} (segment offset {p * 8192:#07x}): DIFFERS at "
                  f"{bad:#07x} - machine {got[d]:#04x}, card {exp[d]:#04x}")
            print(f"      machine: {got[d:d+12].hex(' ')}")
            print(f"      card   : {exp[d:d+12].hex(' ')}")
            break
        print(f"    page {base + p} (segment offset {p * 8192:#07x}): {n:,} bytes identical")
    if bad is None:
        print("  the whole segment matches the card - the data is right and the reader is not")
    z.close()


if __name__ == "__main__":
    main()
