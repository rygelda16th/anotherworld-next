"""The stall, with raw addresses and the interrupt's own counter.

No opcodes execute and frames barely move, so the machine is stuck in assembly. Two shapes fit:
the main loop is waiting for a refresh that is not arriving, or the interrupt is arriving and
taking so long that nothing else runs. `ticks` tells those apart in one reading, and the voice
records say whether the mixer is the reason.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zrcp import Zrcp                                       # noqa: E402
from checksave import symbols, NEX, EXP                          # noqa: E402

FRAMES_DONE, RECORDS = 0xC008, 0xC006
VOICES, V_SIZE = 0xDD00, 18
V_FRAC, V_POS, V_INCF, V_INCI, V_VOL, V_END, V_LOOP, V_ACTIVE, V_PAGE, V_LEFT = (
    0, 1, 3, 4, 6, 7, 9, 11, 12, 13)


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
    print(f"  stalled at frame {last}")

    # IS THE INTERRUPT ALIVE? ticks is bumped once per frame interrupt, so ~50 a second.
    t0 = w(sym["ticks"])
    time.sleep(2.0)
    t1 = w(sym["ticks"])
    print(f"  ticks advanced {t1 - t0} in 2s (a live interrupt gives about 100)")

    hits = {}
    for _ in range(40):
        hits[pc()] = hits.get(pc(), 0) + 1
        time.sleep(0.1)
    print("  the program counter, raw:")
    for p, n in sorted(hits.items(), key=lambda kv: -kv[1])[:8]:
        print(f"    {n:>3}/40  {p:#06x}")

    print(f"  snd_off={read(sym['snd_off'], 1)[0]:#04x}  "
          f"mus_playing={read(sym['mus_playing'], 1)[0]:#04x}")
    v = read(VOICES, V_SIZE * 4)
    for c in range(4):
        r = v[c * V_SIZE:(c + 1) * V_SIZE]
        print(f"    voice {c}: active={r[V_ACTIVE]:#04x} page={r[V_PAGE]:<3} "
              f"pos={r[V_POS] | (r[V_POS+1] << 8):#06x} "
              f"inc={r[V_INCI] | (r[V_INCI+1] << 8):#06x}.{r[V_INCF]:02x} "
              f"end={r[V_END] | (r[V_END+1] << 8):#06x} "
              f"loop={r[V_LOOP] | (r[V_LOOP+1] << 8):#06x} "
              f"left={r[V_LEFT] | (r[V_LEFT+1] << 8)} vol={r[V_VOL]}")
    z.close()


if __name__ == "__main__":
    main()
