"""I10's real question: left playing, how far through the game does it get?

Every previous run either tapped fire (which advances a cinematic and does nothing else) or
watched a single part. auto_input now reproduces the probe's own synthetic player on the
machine, so the game can be LEFT PLAYING and asked where it ends up.

This is not the gate - the gate is a playthrough to the ending - but it is the measurement that
says whether one is reachable by playing at all, and it has never been taken.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zrcp import Zrcp                                       # noqa: E402
from checksave import symbols, NEX, EXP                          # noqa: E402

FRAMES_DONE, FINISHED, BAD_OP, FAULT = 0xC008, 0xC00A, 0xC00C, 0xC00D
PART_TABLE = 0xDD48
SECONDS = int(os.environ.get("AW_SECONDS", "300"))
START = 1                       # the intro; the bypass's own starting part


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

    z.cmd(f"smartload /work/{NEX}")
    time.sleep(3.2)
    z.cmd("set-memory-zone -1")
    z.cmd(f"write-memory {sym['start_part']} {START + 1}")
    z.cmd(f"write-memory {sym['autoplay']} 1")
    z.cmd(f"write-memory {sym['go']} 1")

    rows = read(PART_TABLE, 40)
    table = [rows[i * 4:i * 4 + 4] for i in range(10)]

    def which():
        page = read(sym["code_add"] + 1, 1)[0]
        if not page:
            return None
        pages = read(sym["res_page"], 256)
        rid = next((i for i in range(256) if pages[i] == page), None)
        return next((n for n, r in enumerate(table) if r[1] == rid), None)

    seen, last, t0 = [], None, time.time()
    for _ in range(SECONDS):
        time.sleep(1.0)
        part = which()
        if part != last:
            seen.append(part)
            print(f"  t={time.time() - t0:6.1f}s  PART {part}   frames={w(FRAMES_DONE):<6} "
                  f"blits={w(sym['_aw_blits']):<6} loads={w(sym['n_load']):<4} "
                  f"invalidations={w(sym['n_inval'])}")
            last = part
        f = read(FAULT, 1)[0]
        if f or read(FINISHED, 1)[0] == 0x5A:
            print(f"  t={time.time() - t0:6.1f}s  STOPPED fault={f:#04x} "
                  f"bad_op={read(BAD_OP, 1)[0]:#04x}")
            break

    print(f"\n  {w(FRAMES_DONE):,} frames in {time.time() - t0:.0f}s, "
          f"{w(sym['_aw_blits']):,} blits, {w(sym['n_load'])} loads, "
          f"{w(sym['n_inval'])} invalidations")
    print("  parts, in order: " + " -> ".join(str(p) for p in seen))
    z.close()


if __name__ == "__main__":
    main()
