"""The save half, instrumented at every step, to find where the extra frame comes from.

The load half stops dead on the same stopper. The save half ends up one frame of thread work
past the snapshot - pg_ptr1 flipped and one VM variable moved - and those are written only by
opcodes, so a thread ran after the file was closed. This says exactly when.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zrcp import Zrcp                                       # noqa: E402
from checksave import symbols, NEX, SAVE, HDR, VM_BYTES, PAGE_BYTES   # noqa: E402

FRAMES_DONE, FINISHED, FAULT = 0xC008, 0xC00A, 0xC00D


def main():
    sym = symbols("build/aw.exp")
    sym.update(symbols("build/aw_vm_c.exp"))
    if os.path.exists(SAVE):
        os.unlink(SAVE)
    z = Zrcp()

    def read(a, n):
        out = bytearray()
        while len(out) < n:
            k = min(2048, n - len(out))
            raw = z.cmd(f"read-memory {a + len(out)} {k}").strip()
            out += bytes(int(raw[i:i + 2], 16) for i in range(0, 2 * k, 2))
        return bytes(out)

    def snap(tag):
        f = read(FRAMES_DONE, 2)
        v = read(sym["_aw_vars"], 8)
        print(f"  {tag:<34} frames={f[0] | (f[1] << 8):<6} pg_ptr1={read(sym['pg_ptr1'], 1)[0]:#04x} "
              f"fault={read(FAULT, 1)[0]:#04x} fin={read(FINISHED, 1)[0]:#04x} "
              f"vars[0..3]={' '.join(f'{v[i] | (v[i+1] << 8):04x}' for i in range(0, 8, 2))}")

    z.cmd(f"smartload /work/{NEX}")
    time.sleep(3.2)
    z.cmd("set-memory-zone -1")
    z.cmd(f"write-memory-raw {0xC002} {(3000).to_bytes(2, 'little').hex()}")
    z.cmd(f"write-memory-raw {0xC004} {(60000).to_bytes(2, 'little').hex()}")
    z.cmd(f"write-memory {sym['go']} 1")
    time.sleep(2.0)

    snap("running, before the request")
    z.cmd(f"write-memory {sym['save_req']} 1")
    t0, polls = time.time(), 0
    for polls in range(300):
        if read(sym["save_req"], 1)[0] == 0:
            break
        time.sleep(0.01)
    print(f"  save_req cleared after {polls} poll(s), {time.time() - t0:.3f}s")
    snap("the instant save_req cleared")
    z.cmd(f"write-memory {FAULT} 1")
    snap("just after the fault was poked")

    want = HDR + VM_BYTES + PAGE_BYTES
    for _ in range(300):
        time.sleep(0.2)
        if os.path.exists(SAVE) and os.path.getsize(SAVE) >= want:
            break
    print(f"  the file appeared after {time.time() - t0:.1f}s")
    snap("the instant the file is complete")
    time.sleep(0.5)
    snap("500ms later")
    z.cmd(f"write-memory {sym['snd_off']} 1")
    time.sleep(0.3)
    snap("after snd_off")

    blob = open(SAVE, "rb").read()
    print(f"\n  the file says pg_ptr1={blob[7]:#04x}, "
          f"aw_vars[0..3]=" + ' '.join(f"{blob[HDR+i] | (blob[HDR+i+1] << 8):04x}" for i in range(0, 8, 2)))
    z.close()


if __name__ == "__main__":
    main()
