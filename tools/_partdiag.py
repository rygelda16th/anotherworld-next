"""check-part's probe cases load nothing and res_err is clean. Which is it?

The boot case passes and the probe cases do not, so the difference is what runs BEFORE
aw_setup_part: the fixed load. `.ready` tests err and jumps straight to .stop if it is set -
and err is the loader's byte, not the heap's, so a checker that only reads res_err sees a
clean failure with nothing loaded. This reads both, plus everything either one touches.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zrcp import Zrcp                                       # noqa: E402
from checksave import symbols, NEX                          # noqa: E402


def main():
    sym = symbols("build/aw.exp")
    z = Zrcp()

    def read(a, n):
        out = bytearray()
        while len(out) < n:
            k = min(2048, n - len(out))
            raw = z.cmd(f"read-memory {a + len(out)} {k}").strip()
            out += bytes(int(raw[i:i + 2], 16) for i in range(0, 2 * k, 2))
        return bytes(out)

    for index in (None, 1, 2):
        z.cmd(f"smartload /work/{NEX}")
        time.sleep(3.2)
        z.cmd("set-memory-zone -1")
        if index is not None:
            z.cmd(f"write-memory-raw {sym['fname']} {(b'RES18.BIN' + bytes(1)).hex()}")
            z.cmd(f"write-memory {sym['probe_part']} {index + 1}")
        z.cmd(f"write-memory {sym['go']} 1")
        if index is None:
            time.sleep(2.0)
        else:
            for _ in range(200):
                if read(sym["done"], 1)[0] == 0x5A:
                    break
                time.sleep(0.05)
        pages = read(sym["res_page"], 256)
        print(f"  {'boot' if index is None else f'part {index}':<8} "
              f"done={read(sym['done'], 1)[0]:#04x} "
              f"err={read(sym['err'], 1)[0]:#04x} "
              f"res_err={read(sym['res_err'], 1)[0]:#04x} "
              f"res_full={read(sym['res_full'], 1)[0]:#04x} "
              f"next_page={read(sym['next_page'], 1)[0]:<4} "
              f"n_load={int.from_bytes(read(sym['n_load'], 2), 'little'):<4} "
              f"resident={[hex(i) for i in range(256) if pages[i]][:8]}")
    z.close()


if __name__ == "__main__":
    main()
