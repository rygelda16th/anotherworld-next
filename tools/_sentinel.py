"""I9's load: did the second pass's reads write anything at all?

The earlier instrument recorded "the first byte that landed = 0x00" and I read that as proof the
read arrived. It was not: 0x00 was ALSO what was already there, so the check could not tell a
successful read from no read at all. This paints every destination with a byte the file never
contains and the VM never writes, and then counts what survives.

  all sentinel   -> the read wrote nothing
  all file       -> the read worked, and something after it is the culprit
  a mixture      -> it wrote a prefix, and the count says how much

The threads are frozen first, through aw_state/aw_state_req rather than through the C's loop, so
the loop keeps turning (the load needs its frame boundary) while nothing executes bytecode. That
is the freeze the three earlier attempts wanted and none of them found.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zrcp import Zrcp                                       # noqa: E402
from checksave import symbols, NEX, SAVE, HDR               # noqa: E402

NR_MMU2, PAGED_PAGE, SENT = 0x52, 10, 0xEE
FRAMES_DONE = 0xC008
# name, machine address symbol, length, offset in the file - the file's order, not memory's
BLOCKS = [("aw_vars", "_aw_vars", 512), ("aw_call_stack", "_aw_call_stack", 512),
          ("aw_pc", "_aw_pc", 256), ("aw_state", "_aw_state", 128)]


def main():
    sym = symbols("build/aw.exp")
    sym.update(symbols("build/aw_vm_c.exp"))
    blob = open(SAVE, "rb").read()
    off, want = HDR, {}
    for name, s, n in BLOCKS:
        want[name] = blob[off:off + n]
        off += n

    z = Zrcp()

    def read(a, n):
        out = bytearray()
        while len(out) < n:
            k = min(2048, n - len(out))
            raw = z.cmd(f"read-memory {a + len(out)} {k}").strip()
            out += bytes(int(raw[i:i + 2], 16) for i in range(0, 2 * k, 2))
        return bytes(out)

    def fill(a, n, b):
        for i in range(0, n, 128):
            k = min(128, n - i)
            z.cmd(f"write-memory-raw {a + i} {(bytes([b]) * k).hex()}")

    def word(a):
        v = read(a, 2)
        return v[0] | (v[1] << 8)

    z.cmd(f"smartload /work/{NEX}")
    time.sleep(3.2)
    z.cmd("set-memory-zone -1")
    z.cmd(f"write-memory-raw {0xC002} {(3000).to_bytes(2, 'little').hex()}")
    z.cmd(f"write-memory-raw {0xC004} {(60000).to_bytes(2, 'little').hex()}")
    z.cmd(f"write-memory {sym['go']} 1")
    time.sleep(2.0)

    # FREEZE THE THREADS, NOT THE LOOP. aw_host_frame tests aw_state[t] before anything else and
    # skips the thread; aw_check_requests copies aw_state_req over aw_state every frame, so both
    # halves of the 128 bytes have to hold. The loop keeps running, which is what the load needs.
    fill(sym["_aw_state"], 128, 1)
    time.sleep(0.4)
    a = read(sym["_aw_vars"], 32)
    f1 = word(FRAMES_DONE)
    time.sleep(0.4)
    b = read(sym["_aw_vars"], 32)
    f2 = word(FRAMES_DONE)
    print(f"threads frozen: the loop advanced {f2 - f1} frames and aw_vars "
          f"{'did not move' if a == b else 'STILL MOVED - the freeze does not hold'}")

    for name, s, n in BLOCKS[:3]:               # not aw_state: that is holding the freeze
        fill(sym[s], n, SENT)
    painted = read(sym["_aw_vars"], 512)
    print(f"painted: aw_vars is {painted.count(SENT)}/512 sentinel bytes before the load")

    z.cmd(f"write-memory {sym['save_req']} 2")
    done, t0 = False, time.time()
    for _ in range(400):
        time.sleep(0.25)
        z.cmd(f"tbblue-set-register {NR_MMU2} {PAGED_PAGE}")
        if read(sym["sv_done"], 1)[0] == 0x5A:
            done = True
            break
    print(f"sv_done after {time.time() - t0:.1f}s" if done
          else f"the load never finished; err={read(sym['err'], 1)[0]:#04x}")
    if not done:
        z.close()
        raise SystemExit("FAIL")

    print(f"\nthe recorder: sv_got={word(sym['sv_got'])} "
          f"sv_byte={read(sym['sv_byte'], 1)[0]:#04x} "
          f"sv_ferr={read(sym['sv_ferr'], 1)[0]:#04x} err={read(sym['err'], 1)[0]:#04x}")

    print("\nwhat is in each destination now:")
    for name, s, n in BLOCKS:
        got = read(sym[s], n)
        sent = got.count(SENT)
        same = sum(1 for i in range(n) if got[i] == want[name][i])
        first_bad = next((i for i in range(n) if got[i] != want[name][i]), None)
        print(f"  {name:<14} {sent:>4}/{n} still sentinel, {same:>4}/{n} match the file"
              + (f", first mismatch at byte {first_bad}" if first_bad is not None else ""))
        print(f"                 file {want[name][:12].hex(' ')}\n"
              f"                 mem  {got[:12].hex(' ')}")
    z.close()


if __name__ == "__main__":
    main()
