"""I10's first measurement: how far does the shipped game actually get, left alone?

Nothing is poked but `go`. Every second this reads the counters and works out which part is
running - code_add + 1 is the page the current bytecode landed at, res_page says which resource
is at that page, and part_table's second column names each part's bytecode - so the sequence of
parts is readable without the VM being asked anything.

It answers the only question I10 opens with: does the game advance on its own, and where does
it stop when it does not?
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zrcp import Zrcp                                       # noqa: E402
from checksave import symbols, NEX                          # noqa: E402

FRAMES_DONE, FINISHED, OUT_OF_BUDGET, BAD_OP, FAULT, FAULT_PC = (
    0xC008, 0xC00A, 0xC00B, 0xC00C, 0xC00D, 0xC00E)
PART_TABLE = 0xDD80
SECONDS = int(os.environ.get("AW_SECONDS", "120"))


def main():
    sym = symbols("build/aw.exp")
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

    z.cmd(f"smartload /work/{NEX}")
    time.sleep(3.2)
    z.cmd("set-memory-zone -1")
    z.cmd(f"write-memory {sym['go']} 1")

    table = read(PART_TABLE, 40)
    rows = [table[i * 4:i * 4 + 4] for i in range(10)]

    def which_part():
        page = read(sym["code_add"] + 1, 1)[0]
        pages = read(sym["res_page"], 256)
        rid = next((i for i in range(256) if pages[i] == page and page), None)
        if rid is None:
            return None, page
        return next((n for n, r in enumerate(rows) if r[1] == rid), None), page

    seen, last, t0 = [], None, time.time()
    for _ in range(SECONDS):
        time.sleep(1.0)
        part, page = which_part()
        f, flt = w(FRAMES_DONE), read(FAULT, 1)[0]
        if part != last:
            seen.append((round(time.time() - t0), part, page, f))
            print(f"  t={time.time() - t0:5.1f}s  PART {part} (bytecode at page {page})  "
                  f"frames={f}")
            last = part
        if flt or read(FINISHED, 1)[0] == 0x5A:
            print(f"  t={time.time() - t0:5.1f}s  STOPPED: fault={flt:#04x} "
                  f"bad_op={read(BAD_OP, 1)[0]:#04x} pc={w(FAULT_PC):#06x} "
                  f"out_of_budget={read(OUT_OF_BUDGET, 1)[0]:#04x} frames={f}")
            break

    f = w(FRAMES_DONE)
    print(f"\n  {f:,} frames in {time.time() - t0:.0f}s "
          f"({f / max(1, time.time() - t0):.1f}/s), blits={w(sym['_aw_blits'])}, "
          f"loads={w(sym['n_load'])}, invalidations={w(sym['n_inval'])}, "
          f"bitmaps={w(sym['n_bmp'])}, strings={w(sym['n_str'])}")
    print("  parts in order: " + " -> ".join(str(p) for _, p, _, _ in seen))
    z.close()


if __name__ == "__main__":
    main()
