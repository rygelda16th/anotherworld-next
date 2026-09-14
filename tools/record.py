#!/usr/bin/env python3
"""I10's recorder: watch a HUMAN play, and produce what the gate asks for.

    make play        launches native ZEsarUX with the game, in a window
    make record      attaches to it and logs until you stop it (Ctrl-C)

The gate is "a full playthrough under the patched ZEsarUX, RECORDED, with the per-frame budget
re-measured on the real thing against the per-part table". Two of those three are not the
player's job and should not depend on anyone remembering to do them: if a playthrough happens
and nothing samples the machine, the gate is unsatisfied even if the ending is reached.

So this samples over ZRCP while someone plays, and reports at the end:

  which parts were reached, and in what order          - the playthrough itself
  frames, blits and polygons per part                  - what it cost
  polygons per frame against preflight's per-part table - THE BUDGET CLAIM

It never writes to the machine. Reading is safe at any moment; poking is not, and a recorder
that perturbs the thing it records is worse than no recorder.
"""
import os
import signal
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zrcp import Zrcp                                       # noqa: E402

FRAMES_DONE, FINISHED, BAD_OP, FAULT = 0xC008, 0xC00A, 0xC00C, 0xC00D
PART_TABLE = 0xDD48
LOG = os.environ.get("AW_LOG", "build/playlog.txt")
# Bounded instead of Ctrl-C, so the recorder itself can be tested without a person at the
# keyboard. Zero means "until interrupted", which is what a real playthrough uses.
RECORD_S = float(os.environ.get("AW_RECORD_S", "0"))
BUDGET_MS = float(os.environ.get("AW_BUDGET_MS", "80"))     # what the scripts ask for
POLY_RATE = float(os.environ.get("AW_POLY_RATE", "1385"))   # measured on the machine


def reference_table(path):
    out = {}
    for ln in open(path):
        if ln.startswith("#") or not ln.strip():
            continue
        f = [int(x) for x in ln.split()]
        out[f[0]] = dict(frames=f[1], mean=f[2], p95=f[3], max=f[4])
    return out


def main():
    sym = {}
    for p in ("build/aw.exp", "build/aw_vm_c.exp"):
        for ln in open(p):
            n, _, v = ln.partition(":")
            if "EQU" in v:
                try:
                    sym[n.strip()] = int(v.split("EQU")[1].strip().lstrip("$"), 16)
                except ValueError:
                    pass
    ref = reference_table("preflight/hostprobe/probe/parts_polys.txt")

    z = Zrcp()
    print(f"attached: {z.cmd('get-version')}")

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

    rows = read(PART_TABLE, 40)
    table = [rows[i * 4:i * 4 + 4] for i in range(10)]

    def which():
        page = read(sym["code_add"] + 1, 1)[0]
        if not page:
            return None
        pages = read(sym["res_page"], 256)
        rid = next((i for i in range(256) if pages[i] == page), None)
        return next((n for n, r in enumerate(table) if r[1] == rid), None)

    per_part = {}
    order, last = [], None
    stop = {"now": False}
    signal.signal(signal.SIGINT, lambda *_: stop.__setitem__("now", True))

    log = open(LOG, "w")
    log.write("# t  part  frames  polys  blits  loads  fault\n")
    print("recording - play the game; Ctrl-C when you are done\n")
    print(f"  {'t':>6} {'part':>5} {'frames':>7} {'polys/frame':>12} {'vs p95':>8}")

    t0 = time.time()
    pf, pp = w(FRAMES_DONE), w(sym["rd_pcount"])
    while not stop["now"]:
        if RECORD_S and time.time() - t0 > RECORD_S:
            break
        time.sleep(2.0)
        part, f, p = which(), w(FRAMES_DONE), w(sym["rd_pcount"])
        blits, loads = w(sym["_aw_blits"]), w(sym["n_load"])
        flt = read(FAULT, 1)[0]
        df, dp = f - pf, (p - pp) & 0xFFFF          # rd_pcount is 16-bit and wraps
        pf, pp = f, p
        log.write(f"{time.time() - t0:.1f} {part} {f} {p} {blits} {loads} {flt}\n")
        log.flush()
        if part != last:
            order.append(part)
            last = part
        if part is not None and df > 0:
            d = per_part.setdefault(part, dict(frames=0, polys=0, peak=0))
            d["frames"] += df
            d["polys"] += dp
            d["peak"] = max(d["peak"], dp // max(1, df))
            want = ref.get(part, {}).get("p95", 0)
            got = dp // df
            print(f"  {time.time() - t0:6.0f} {part:>5} {f:>7} {got:>12} "
                  f"{want:>8}{'   OVER' if want and got > want else ''}")
        if flt:
            print(f"\n  FAULT {flt:#04x}, bad_op {read(BAD_OP, 1)[0]:#04x} - stopping")
            break

    log.close()
    print(f"\n  log: {LOG}")
    print(f"  parts reached, in order: " + " -> ".join(str(p) for p in order))
    print(f"\n  {'part':>5} {'frames':>8} {'polys':>10} {'mean/frame':>11} "
          f"{'ref mean':>9} {'ref p95':>8} {'ms/frame at %.0f polys/s' % POLY_RATE:>24}")
    for part in sorted(k for k in per_part if k is not None):
        d = per_part[part]
        mean = d["polys"] // max(1, d["frames"])
        r = ref.get(part, {})
        ms = 1000.0 * mean / POLY_RATE
        print(f"  {part:>5} {d['frames']:>8,} {d['polys']:>10,} {mean:>11} "
              f"{r.get('mean', '-'):>9} {r.get('p95', '-'):>8} "
              f"{ms:>20.0f} ms{'  OVER' if ms > BUDGET_MS else ''}")
    print(f"\n  the scripts ask for {BUDGET_MS:.0f} ms a frame; anything marked OVER is a part "
          f"whose\n  average frame does not fit, which is the budget claim I10 asks to re-measure.")
    z.close()


if __name__ == "__main__":
    main()
