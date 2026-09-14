"""I9's load: the one measurement, plus everything readable in the same breath.

Four attempts at this gate each guessed a mechanism and each cost a full run. This guesses
nothing. It replays the gate's own load sequence verbatim - request, 300ms, fault - and reads
CTL_FRAMES_DONE at four points around it, so the question "did the C's loop iterate after the
load wrote the arrays" is answered by the machine rather than by argument.

If the counter does not move, the VM is not the writer and the search moves elsewhere.
If it does, the freeze is the problem and the loop order is what wants reading.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zrcp import Zrcp                                       # noqa: E402
from checksave import compare, symbols, NEX, SAVE, HDR, VM_BYTES, PAGE_BYTES  # noqa: E402

NR_MMU2, PAGED_PAGE = 0x52, 10
FRAMES_DONE, FINISHED, OUT_OF_BUDGET, FAULT = 0xC008, 0xC00A, 0xC00B, 0xC00D


def main():
    sym = symbols("build/aw.exp")
    sym.update(symbols("build/aw_vm_c.exp"))
    blob = open(SAVE, "rb").read()
    print(f"the save on disk is {len(blob):,} bytes "
          f"(the layout wants {HDR + VM_BYTES + PAGE_BYTES:,})")

    z = Zrcp()

    def read(a, n):
        out = bytearray()
        while len(out) < n:
            k = min(2048, n - len(out))
            raw = z.cmd(f"read-memory {a + len(out)} {k}").strip()
            out += bytes(int(raw[i:i + 2], 16) for i in range(0, 2 * k, 2))
        return bytes(out)

    def word(a):
        b = read(a, 2)
        return b[0] | (b[1] << 8)

    def snap(tag):
        """The frame counter and the fields that moved, at one instant."""
        f = word(FRAMES_DONE)
        v = read(sym["_aw_vars"], 16)
        p = read(sym["pg_ptr1"], 1)[0]
        print(f"  {tag:<26} frames_done={f:<6} pg_ptr1={p:#04x} "
              f"aw_vars[0..7]={' '.join(f'{v[i] | (v[i+1] << 8):04x}' for i in range(0, 16, 2))}")
        return f

    z.cmd(f"smartload /work/{NEX}")
    time.sleep(3.2)
    z.cmd("set-memory-zone -1")
    z.cmd(f"write-memory-raw {0xC002} {(3000).to_bytes(2, 'little').hex()}")
    z.cmd(f"write-memory-raw {0xC004} {(60000).to_bytes(2, 'little').hex()}")
    z.cmd(f"write-memory {sym['go']} 1")
    time.sleep(2.0)

    print("\nthe gate's own sequence, instrumented:")
    f_run = snap("running, before request")
    z.cmd(f"write-memory {sym['save_req']} 2")
    time.sleep(0.3)
    f_req = snap("300ms after the request")
    z.cmd(f"write-memory {FAULT} 1")

    done, t0 = False, time.time()
    for _ in range(400):
        time.sleep(0.25)
        z.cmd(f"tbblue-set-register {NR_MMU2} {PAGED_PAGE}")
        if read(sym["sv_done"], 1)[0] == 0x5A:
            done = True
            break
    if not done:
        print(f"  the load never finished; err = {read(sym['err'], 1)[0]:#04x}")
        z.close()
        raise SystemExit("FAIL: no sv_done")
    print(f"  sv_done stamped after {time.time() - t0:.1f}s")

    f_done = snap("the instant sv_done lands")
    time.sleep(0.3)
    f_late = snap("300ms later")
    z.cmd(f"write-memory {sym['snd_off']} 1")
    time.sleep(0.3)
    f_off = snap("after snd_off")

    print(f"\n  CTL_FINISHED={read(FINISHED, 1)[0]:#04x}  "
          f"CTL_OUT_OF_BUDGET={read(OUT_OF_BUDGET, 1)[0]:#04x}  "
          f"CTL_FAULT={read(FAULT, 1)[0]:#04x}  save_req={read(sym['save_req'], 1)[0]:#04x}")

    moved_during = f_done - f_req
    moved_after = f_off - f_done
    print(f"\n  THE MEASUREMENT: the loop iterated {moved_during} time(s) between the fault poke "
          f"and sv_done,\n                   and {moved_after} time(s) after sv_done.")
    if moved_during == 0 and moved_after == 0:
        print("  => the VM's loop is NOT running. Whatever rewrites the arrays is not the VM.")
    else:
        print("  => the loop is still turning. The freeze is the problem, not the load.")

    print("\nwhich fields the gate would call wrong:")
    for b in compare(z, read, blob, sym, "the load"):
        print("  " + b)
    z.close()


if __name__ == "__main__":
    main()
