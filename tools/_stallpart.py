"""Part 5 stops at frame 1. Everything readable about why, in one run.

The same shape as the part 2 stall, so the same questions in the same order: is the interrupt
alive, is any opcode executing, where is the program counter, what is the reader doing, and
which draw is it on.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zrcp import Zrcp                                       # noqa: E402
from checksave import symbols, NEX, EXP                          # noqa: E402

PART = 5
FRAMES_DONE, RECORDS, FINISHED, OUT_OF_BUDGET, BAD_OP, FAULT, FAULT_PC = (
    0xC008, 0xC006, 0xC00A, 0xC00B, 0xC00C, 0xC00D, 0xC00E)
DRAW_BLOCK, VEC_TRAMP = 0xC390, 0xCECE


def main():
    sym = symbols(EXP)
    sym.update(symbols("build/aw_vm_c.exp"))
    z = Zrcp()

    def read(a, n):
        raw = z.cmd(f"read-memory {a} {n}").strip()
        return bytes(int(raw[i:i + 2], 16) for i in range(0, 2 * n, 2))

    def w(a):
        b = read(a, 2)
        return b[0] | (b[1] << 8)

    def pc():
        for tok in z.cmd("get-registers").split():
            if tok.startswith("PC="):
                return int(tok[3:], 16)
        return -1

    z.cmd(f"smartload /work/{NEX}")
    time.sleep(3.2)
    z.cmd("set-memory-zone -1")
    z.cmd(f"write-memory {sym['start_part']} {PART + 1}")
    z.cmd(f"write-memory {sym['go']} 1")
    for _ in range(6):
        z.cmd("send-keys-event 128 1 nomenu")
        time.sleep(0.1)
        z.cmd("send-keys-event 128 0 nomenu")
        time.sleep(0.4)
    time.sleep(3.0)

    print(f"  part {PART}: frames={w(FRAMES_DONE)} records={w(RECORDS)} "
          f"fin={read(FINISHED, 1)[0]:#04x} fault={read(FAULT, 1)[0]:#04x} "
          f"bad_op={read(BAD_OP, 1)[0]:#04x} oob={read(OUT_OF_BUDGET, 1)[0]:#04x} "
          f"fault_pc={w(FAULT_PC):#06x}")
    t0 = w(sym["ticks"])
    time.sleep(2.0)
    print(f"  ticks advanced {w(sym['ticks']) - t0} in 2s; "
          f"frames now {w(FRAMES_DONE)}, records {w(RECORDS)}")
    print(f"  res_full={read(sym['res_full'], 1)[0]:#04x} "
          f"res_err={read(sym['res_err'], 1)[0]:#04x} "
          f"next_page={read(sym['next_page'], 1)[0]} n_load={w(sym['n_load'])}")
    print(f"  cin_base={read(sym['cin_base'], 1)[0]} "
          f"vid2_base={read(sym['vid2_base'], 1)[0]} "
          f"code page={read(sym['code_add'] + 1, 1)[0]} "
          f"pc guard={w(0xC010):,}")

    hits = {}
    for _ in range(40):
        hits[pc()] = hits.get(pc(), 0) + 1
        time.sleep(0.05)
    print("  program counter:")
    for p, n in sorted(hits.items(), key=lambda kv: -kv[1])[:6]:
        tag = "  (the IM2 trampoline)" if p == VEC_TRAMP else ""
        print(f"    {n:>3}/40  {p:#06x}{tag}")

    d = read(DRAW_BLOCK, 12)
    print(f"  DRAW_BLOCK: off={d[0] | (d[1] << 8):#06x} zoom={d[2] | (d[3] << 8)} "
          f"at=({d[4] | (d[5] << 8)},{d[6] | (d[7] << 8)}) col={d[8]:#04x} video2={d[9]}")
    print(f"  reader: off={w(sym['rd_off']):#06x} pcount={w(sym['rd_pcount'])} "
          f"bad={w(sym['rd_bad'])} deep={w(sym['rd_deep'])} "
          f"stop={read(sym['rd_stop'], 1)[0]:#04x}")
    time.sleep(2.0)
    print(f"  two seconds on: pcount={w(sym['rd_pcount'])} bad={w(sym['rd_bad'])} "
          f"deep={w(sym['rd_deep'])} frames={w(FRAMES_DONE)} records={w(RECORDS)}")
    z.close()


if __name__ == "__main__":
    main()
