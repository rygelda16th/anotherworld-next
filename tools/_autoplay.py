"""Does the machine play the game when given the probe's own synthetic player?

Every gameplay measurement in this project is the host probe's, and the probe only reaches
gameplay because headless.cpp drives it with a fixed function of the frame number. auto_input
reproduces that function on the machine. If it works, the signature is deaths: the synthetic
player walks into things and dies, and a death RESTARTS THE PART - so n_inval climbs, which a
tapped fire button never makes happen.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zrcp import Zrcp                                       # noqa: E402
from checksave import symbols, NEX, EXP                          # noqa: E402

PART = 2
FRAMES_DONE, FAULT, BAD_OP, FINISHED = 0xC008, 0xC00D, 0xC00C, 0xC00A
PART_TABLE = 0xDD48


def main():
    sym = symbols(EXP)
    sym.update(symbols("build/aw_vm_c.exp"))
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

    for auto in (0, 1):
        z.cmd(f"smartload /work/{NEX}")
        time.sleep(3.2)
        z.cmd("set-memory-zone -1")
        z.cmd(f"write-memory {sym['start_part']} {PART + 1}")
        z.cmd(f"write-memory {sym['autoplay']} {auto}")
        z.cmd(f"write-memory {sym['go']} 1")
        t0 = time.time()
        while time.time() - t0 < 60:
            if not auto:                        # the old way: tap fire
                z.cmd("send-keys-event 128 1 nomenu")
                time.sleep(0.08)
                z.cmd("send-keys-event 128 0 nomenu")
            time.sleep(1.0)
        rows = read(PART_TABLE, 40)
        page = read(sym["code_add"] + 1, 1)[0]
        pages = read(sym["res_page"], 256)
        rid = next((i for i in range(256) if pages[i] == page and page), None)
        part = next((n for n in range(10) if rows[n * 4 + 1] == rid), None)
        print(f"  {'autoplay' if auto else 'fire taps':<10} "
              f"frames={w(FRAMES_DONE):<6} blits={w(sym['_aw_blits']):<6} "
              f"loads={w(sym['n_load']):<5} INVALIDATIONS={w(sym['n_inval']):<4} "
              f"part now {part}  fault={read(FAULT, 1)[0]:#04x} "
              f"bad_op={read(BAD_OP, 1)[0]:#04x}")
    z.close()


if __name__ == "__main__":
    main()
