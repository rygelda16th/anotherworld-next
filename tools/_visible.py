"""Is there anything on the page the machine is actually DISPLAYING?

check-draw compares all four Layer 2 pages against the engine and passes, so the pages have
content. But it drives a fixed load and stops on a chosen blit. Nothing has ever asked the
simpler question about a NORMAL run: of the four pages, which one is on screen, and does it
have any non-zero pixel in it?

An earlier probe of mine reported "page 0, first 2K: 0 of 2,048 bytes are non-zero" and I read
that as "the intro starts black" and moved on. That was the same symptom a person later saw as
a black screen, so it is worth asking properly.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zrcp import Zrcp                                       # noqa: E402
from checksave import symbols, NEX                          # noqa: E402

NR_MMU7, DWIN, L2_BASE_BANK, BANDS = 0x57, 0xE000, 12, 6
FRAMES_DONE = 0xC008


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

    def nr(n):
        return int(z.cmd(f"tbblue-get-register {n}").strip().split()[0].rstrip("Hh"), 16)

    z.cmd(f"smartload /work/{NEX}")
    time.sleep(3.2)
    z.cmd("set-memory-zone -1")
    z.cmd(f"write-memory {sym['go']} 1")
    time.sleep(8.0)
    z.cmd(f"write-memory {sym['snd_off']} 1")       # MMU7 is the mixer's window too
    time.sleep(0.2)

    p1 = read(sym["pg_ptr1"], 1)[0]
    p2 = read(sym["pg_ptr2"], 1)[0]
    p3 = read(sym["pg_ptr3"], 1)[0]
    bank = nr(0x12)
    shown = (bank - L2_BASE_BANK) // 3
    print(f"  frames={w(FRAMES_DONE)} blits={w(sym['_aw_blits'])} "
          f"selects={w(sym['n_select'])}")
    print(f"  pg_ptr1(draw)={p1}  pg_ptr2(shown)={p2}  pg_ptr3={p3}   "
          f"NextReg $12={bank} -> Layer 2 page {shown}")
    print()
    for page in range(4):
        p0 = (L2_BASE_BANK + page * 3) * 2
        nz = 0
        vals = set()
        for band in range(BANDS):
            z.cmd(f"tbblue-set-register {NR_MMU7} {p0 + band}")
            b = read(DWIN, 8192)
            nz += sum(1 for x in b if x)
            vals.update(b)
        tag = ""
        if page == shown:
            tag += "  <-- ON SCREEN"
        if page == p1:
            tag += "  (the work page)"
        print(f"    Layer 2 page {page}: {nz:>7,} of 49,152 bytes non-zero, "
              f"{len(vals):>3} distinct{tag}")
    z.close()


if __name__ == "__main__":
    main()
