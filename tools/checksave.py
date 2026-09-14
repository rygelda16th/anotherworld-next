"""I9, first half. The save, on the machine, against the machine's own state.

Five objects serialise in the reference, in this order (engine.cpp:136-138): the VM
(vm.cpp:736), the resources (resource.cpp:358), the video (video.cpp:624), the player
(sfxplayer.cpp:212) and the mixer (mixer.cpp:156). Our layout is not theirs - nothing reads our
saves but us - so what this checks is that every one of the five is present and correct: each
field in the file is compared against the same field read live off the machine.

Two things in the file are DERIVED rather than kept, and both are checked against the machine:
the part index, matched from code_add + 1 through part_table, and the heap's load order, walked
out of res_page. Neither costs a byte of resident memory, which is why the save could be written
at all - the resident block has twenty-two bytes left and the C cannot grow by one.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zrcp import Zrcp                   # noqa: E402

NEX, ASSETS = "build/aw.nex", "build/assets"
SAVE = os.path.join(ASSETS, "AWSAVE.BIN")
L2_BASE_BANK, BANDS, BAND, DWIN, NR_MMU7 = 12, 24, 8192, 0xE000, 0x57
HDR, VM_BYTES, PAGE_BYTES = 256, 512 + 512 + 256 + 128, BANDS * BAND
START_PART = 0


def symbols(path):
    d = {}
    for ln in open(path):
        if ":" in ln and "EQU" in ln:
            n, v = ln.split(":", 1)
            try:
                d[n.strip()] = int(v.split("EQU")[1].strip().lstrip("$"), 16)
            except ValueError:
                pass
    return d


def main():
    sym = symbols("build/aw.exp")
    sym.update(symbols("build/aw_vm_c.exp"))
    if os.path.exists(SAVE):
        os.unlink(SAVE)                 # so a stale file cannot pass for a new one

    z = Zrcp()
    print(f"emulator: {z.cmd('get-version')}")

    def read(a, n):
        out = bytearray()
        while len(out) < n:
            k = min(2048, n - len(out))
            raw = z.cmd(f"read-memory {a + len(out)} {k}").strip()
            out += bytes(int(raw[i:i + 2], 16) for i in range(0, 2 * k, 2))
        return bytes(out)

    # Boot the game proper - no NAME poked, so the boot path sets up START_PART - but DO poke a
    # frame count, because the C's loop is bounded by CTL_FRAMES and the image leaves it zero.
    # That the shipped game therefore runs zero frames is a real gap, recorded under I9: closing
    # it costs the C 36 bytes and the memory map has 23. It is not this gate's business, which is
    # whether a save is correct once frames are running.
    z.cmd(f"smartload /work/{NEX}")
    time.sleep(3.2)
    z.cmd("set-memory-zone -1")
    z.cmd(f"write-memory-raw {0xC002} {(3000).to_bytes(2, 'little').hex()}")   # CTL_FRAMES
    z.cmd(f"write-memory-raw {0xC004} {(60000).to_bytes(2, 'little').hex()}")  # CTL_BUDGET
    z.cmd(f"write-memory {sym['go']} 1")
    time.sleep(2.0)
    # AND EXHAUST THE BUDGET IN THE SAME BREATH. The C's loop runs aw_frame_sync, then the part
    # block, then breaks on budget-or-fault - and only AFTER that does it run the frame's threads.
    # So a budget of zero makes the frame that performs the save the LAST frame, with no thread
    # work after it, and the machine stands still on exactly the state the save captured. Without
    # this the VM ran on between the save and the reading, and the two fields it touches every
    # frame - pg_ptr1 and aw_vars - differed for that reason alone rather than any fault.
    z.cmd(f"write-memory-raw {0xC004} {(0).to_bytes(2, 'little').hex()}")   # CTL_BUDGET
    z.cmd(f"write-memory {sym['save_req']} 1")

    for _ in range(300):                # the pages alone are 196,608 bytes through esxDOS
        time.sleep(0.2)
        if os.path.exists(SAVE) and os.path.getsize(SAVE) >= HDR + VM_BYTES + PAGE_BYTES:
            break
    time.sleep(0.5)

    bad = []
    if not os.path.exists(SAVE):
        raise SystemExit("FAIL: no save file appeared - aw_save never ran, or esxDOS refused "
                         f"the open (FA_WRITE is $0C, not $0E). err = "
                         f"{read(sym['err'], 1)[0]:#04x}")
    blob = open(SAVE, "rb").read()
    want_len = HDR + VM_BYTES + PAGE_BYTES
    print(f"  the file is {len(blob):,} bytes; the layout wants {want_len:,}")
    if blob[:4] != b"AWS1":
        bad.append(f"the magic is {blob[:4]!r}, not b'AWS1'")
    if len(blob) != want_len:
        bad.append(f"the file is {len(blob):,} bytes, not {want_len:,}")

    # FREEZE THE MACHINE BEFORE COMPARING. A save is a SNAPSHOT and the game keeps running, so
    # every field would differ by the time it was read - which is exactly what the first run of
    # this reported: pg_ptr1, aw_vars, the thread pcs and all six bands of page 0. Poking
    # CTL_FRAMES to zero ends the C's loop, which stops aw_frame_sync and with it music_tick;
    # snd_off stops the interrupt's mixer, which would otherwise keep advancing V_POS.
    z.cmd(f"write-memory-raw {0xC002} {(0).to_bytes(2, 'little').hex()}")
    z.cmd(f"write-memory {sym['snd_off']} 1")
    time.sleep(0.3)

    # ---- the header, field by field, against the machine ----------------------------------
    live = {
        "part": None,                   # derived; checked against START_PART below
        "pal_now": read(sym["pal_now"], 1)[0],
        "pal_req": read(sym["pal_req"], 1)[0],
        "pg_ptr1": read(sym["pg_ptr1"], 1)[0],
        "mus_res": read(sym["mus_res"], 1)[0],
        "mus_playing": read(sym["mus_playing"], 1)[0],
        "mus_cur_order": read(sym["mus_cur_order"], 1)[0],
    }
    if blob[4] != START_PART:
        bad.append(f"the part index is {blob[4]}, and the game boots into {START_PART}")
    for off, name in ((5, "pal_now"), (6, "pal_req"), (7, "pg_ptr1"),
                      (16, "mus_res"), (17, "mus_playing"), (19, "mus_cur_order")):
        if blob[off] != live[name]:
            bad.append(f"{name} is {blob[off]:#04x} in the file, {live[name]:#04x} on the machine")

    # the mixer's four voice records, verbatim
    if blob[32:32 + 72] != read(0xDD00, 72):
        bad.append("the four voice records differ from the machine's")

    # the heap's load order, and that it is not empty - part 0 loads three resources at least
    n_res = blob[15]
    order = list(blob[128:128 + n_res])
    pages = read(sym["res_page"], 256)
    if n_res < 3:
        bad.append(f"the load order holds {n_res} ids; part 0 loads at least three")
    for rid in order:
        if not pages[rid]:
            bad.append(f"the order names {rid:#04x}, which res_page says is not resident")
    if order and sorted(order, key=lambda r: pages[r]) != order:
        bad.append("the load order is not in heap order")

    # ---- the VM's arrays, byte for byte ---------------------------------------------------
    o = HDR
    for name, addr, n in (("aw_vars", sym["_aw_vars"], 512),
                          ("aw_call_stack", sym["_aw_call_stack"], 512),
                          ("aw_pc + aw_pc_req", sym["_aw_pc"], 256),
                          ("aw_state + aw_state_req", sym["_aw_state"], 128)):
        if blob[o:o + n] != read(addr, n):
            d = next((i for i in range(n) if blob[o + i] != read(addr + i, 1)[0]), 0)
            bad.append(f"{name} differs from the machine at byte {d}")
        o += n

    # ---- the four Layer 2 pages ----------------------------------------------------------
    p0 = L2_BASE_BANK * 2
    diff_bands = []
    for band in range(BANDS):
        z.cmd(f"tbblue-set-register {NR_MMU7} {p0 + band}")
        if blob[o:o + BAND] != read(DWIN, BAND):
            diff_bands.append(band)
        o += BAND
    if diff_bands:
        bad.append(f"bands {diff_bands[:6]} of the four pages differ from the machine's")
    z.close()

    if bad:
        print("\n  " + "\n  ".join(bad[:6]))
        raise SystemExit(f"FAIL: {len(bad)} thing(s) wrong with the save")
    print(f"""
  the load order holds {n_res} ids: {' '.join(f'{r:#04x}' for r in order)}

PASS: the save is {len(blob):,} bytes and every field in it matches the machine it was taken
      from - the VM's variables, call stack, thread pcs and channel flags byte for byte; the
      palette and page state; the player down to its pattern position; all four voice records;
      the heap's load order, in heap order and every id resident; and all {BANDS} bands of the
      four Layer 2 pages. The part index and the load order are DERIVED at save time rather
      than kept, which is why this cost no resident memory.

      This is the first half of I9. Nothing reads the save back yet - that, and a stream
      comparison across a reload, is the other half.""")


if __name__ == "__main__":
    main()
