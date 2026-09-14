"""What does the DISPLAY hardware actually hold after the game boots?

No gate has ever asked. check-draw compares Layer 2's MEMORY, check-aw reads pal_now - a
variable - and the emulator runs headless, so sixteen gates proved the pixels correct without
one of them establishing that the pixels reach a screen. That is how the game shipped all day
without ever enabling Layer 2 at all.

This reads the registers that decide whether anything is visible, and reads the Layer 2 palette
back out of the hardware rather than trusting the copy in RAM.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zrcp import Zrcp                                       # noqa: E402
from checksave import symbols, NEX                          # noqa: E402

REGS = [
    (0x69, "Layer 2 enable + timing", "bit 7 = Layer 2 visible"),
    (0x70, "Layer 2 control", "bits 5-4 resolution (00 = 256x192 8bpp), 3-0 palette offset"),
    (0x12, "Layer 2 active bank", "the 16K bank being displayed"),
    (0x43, "palette control", "bit 2 = which L2 palette shows; bits 6-4 = write target"),
    (0x15, "sprite/layer priority", "layer order and sprite enable"),
]


def main():
    sym = symbols("build/aw.exp")
    z = Zrcp()

    def nr(n):
        # ZEsarUX answers like "80H" - hex with a suffix, not a bare number.
        t = z.cmd(f"tbblue-get-register {n}").strip().split()[0]
        return int(t.rstrip("Hh"), 16)

    z.cmd(f"smartload /work/{NEX}")
    time.sleep(3.2)
    z.cmd("set-memory-zone -1")
    z.cmd(f"write-memory {sym['go']} 1")
    time.sleep(4.0)

    print("  the display registers after boot:")
    for n, name, what in REGS:
        v = nr(n)
        print(f"    ${n:02X} {name:<26} = {v:#04x}  {v:08b}   {what}")

    on = nr(0x69) & 0x80
    print(f"\n  Layer 2 visible: {'YES' if on else 'NO - nothing it draws can be seen'}")

    # READ THE PALETTE BACK OUT OF THE HARDWARE, not out of our copy in RAM.
    z.cmd("tbblue-set-register 67 16")          # $43 = %00010000: write/read L2 first palette
    vals = []
    for i in range(16):
        z.cmd(f"tbblue-set-register 64 {i}")    # $40 = index
        vals.append(nr(0x41))                   # $41 = the 8-bit value
    print(f"  the hardware's first 16 Layer 2 palette entries:")
    print("    " + " ".join(f"{v:02x}" for v in vals))
    print(f"    {len(set(vals))} distinct values"
          + ("  - ALL THE SAME, so every pixel renders one colour" if len(set(vals)) < 2 else ""))
    z.close()


if __name__ == "__main__":
    main()
