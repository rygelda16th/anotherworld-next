"""Part 2 reaches frame 39 and stops. Where is the Z80?

Frames creeping up one every twenty to forty seconds is not an idle VM - an idle VM still
turns its loop once a refresh. Something inside a frame is taking tens of seconds. This samples
the program counter and maps it to the nearest symbol, which says where without any theory.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zrcp import Zrcp                                       # noqa: E402
from checksave import symbols, NEX, EXP                          # noqa: E402

FRAMES_DONE, RECORDS, BUDGET = 0xC008, 0xC006, 0xC004


def main():
    sym = symbols(EXP)
    sym.update(symbols("build/aw_vm_c.exp"))
    # nearest-preceding-symbol lookup, for anything in the resident/C region
    table = sorted((v, k) for k, v in sym.items() if 0x4000 <= v <= 0xFFFF)

    def name_of(pc):
        lo, best = None, "?"
        for addr, nm in table:
            if addr <= pc:
                lo, best = addr, nm
            else:
                break
        return f"{best}+{pc - lo}" if lo is not None else "?"

    z = Zrcp()

    def read(a, n):
        raw = z.cmd(f"read-memory {a} {n}").strip()
        return bytes(int(raw[i:i + 2], 16) for i in range(0, 2 * n, 2))

    def w(a):
        b = read(a, 2)
        return b[0] | (b[1] << 8)

    def pc():
        r = z.cmd("get-registers")
        for tok in r.split():
            if tok.startswith("PC="):
                return int(tok[3:], 16)
        return -1

    z.cmd(f"smartload /work/{NEX}")
    time.sleep(3.2)
    z.cmd("set-memory-zone -1")
    z.cmd(f"write-memory {sym['go']} 1")
    for _ in range(6):
        z.cmd("send-keys-event 128 1 nomenu")
        time.sleep(0.1)
        z.cmd("send-keys-event 128 0 nomenu")
        time.sleep(0.4)

    print("  waiting for the stall...")
    last, still = w(FRAMES_DONE), 0
    for _ in range(40):
        time.sleep(1.0)
        f = w(FRAMES_DONE)
        still = still + 1 if f == last else 0
        last = f
        if still >= 4:
            break
    print(f"  stalled at frame {last}. sampling the program counter:")

    hits = {}
    for _ in range(30):
        p = pc()
        hits[name_of(p)] = hits.get(name_of(p), 0) + 1
        time.sleep(0.2)
    for nm, n in sorted(hits.items(), key=lambda kv: -kv[1])[:10]:
        print(f"    {n:>3}/30  {nm}")

    print(f"\n  frames={w(FRAMES_DONE)} records={w(RECORDS)} budget={w(BUDGET)}")
    time.sleep(4.0)
    print(f"  four seconds later: frames={w(FRAMES_DONE)} records={w(RECORDS)}")

    # which threads are alive, and where
    pcs = read(sym["_aw_pc"], 128)
    st = read(sym["_aw_state"], 64)
    live = [(t, pcs[t * 2] | (pcs[t * 2 + 1] << 8)) for t in range(64)
            if (pcs[t * 2] | (pcs[t * 2 + 1] << 8)) != 0xFFFF and not st[t]]
    print(f"  {len(live)} runnable thread(s): " +
          " ".join(f"#{t}@{p:#06x}" for t, p in live[:12]))
    z.close()


if __name__ == "__main__":
    main()
