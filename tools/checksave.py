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
NR_MMU2, PAGED_PAGE = 0x52, 10          # where page 10 goes when its own code is read
N_RES, ORDER = [0], []                  # filled in by compare(), quoted by the PASS text


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

    # Boot the game proper - no NAME poked, so the boot path sets up START_PART - and poke a
    # frame count, because this gate wants a BOUNDED run it can reason about. The image ships
    # CTL_FRAMES zero, which now means no bound at all rather than no frames.
    z.cmd(f"smartload /work/{NEX}")
    time.sleep(3.2)
    z.cmd("set-memory-zone -1")
    z.cmd(f"write-memory-raw {0xC002} {(3000).to_bytes(2, 'little').hex()}")   # CTL_FRAMES
    z.cmd(f"write-memory-raw {0xC004} {(60000).to_bytes(2, 'little').hex()}")  # CTL_BUDGET
    arm(z, sym)
    z.cmd(f"write-memory {sym['go']} 1")
    time.sleep(2.0)
    request(z, read, sym, 1)

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

    # request() already stopped the VM. snd_off stops the interrupt's mixer too, which would
    # otherwise keep advancing V_POS in the voice records the file captured.
    z.cmd(f"write-memory {sym['snd_off']} 1")
    time.sleep(0.3)

    bad += compare(z, read, blob, sym, "the save")

    # ---- I9's SECOND HALF: read it back and see whether the machine becomes the file --------
    #
    # The plan asks for save mid-part, reload, and a machine that matches a run which never
    # saved. This is the round trip that has to hold first: after a load, every field the save
    # captured must be back. It is the same comparison, against the same file, on a machine that
    # reached its state by READING rather than by running - which is the only way to tell a
    # restore that works from a state dump that merely looks right.
    z.cmd(f"smartload /work/{NEX}")
    time.sleep(3.2)
    z.cmd("set-memory-zone -1")
    z.cmd(f"write-memory-raw {0xC002} {(3000).to_bytes(2, 'little').hex()}")
    z.cmd(f"write-memory-raw {0xC004} {(60000).to_bytes(2, 'little').hex()}")
    arm(z, sym)
    z.cmd(f"write-memory {sym['go']} 1")
    time.sleep(2.0)
    # FREEZE WITH CTL_FAULT, NOT THE BUDGET. The C's loop runs aw_frame_sync, then the part block,
    # then breaks on budget-or-fault, and only AFTER that runs the frame's threads. The budget is
    # only spent by opcodes, so zeroing it does not stop the frame the load happens in - and that
    # frame's threads then moved pg_ptr1, aw_vars, the call stack and the voices before anything
    # could be read. A fault breaks on the very next check, so the load's frame does no thread
    # work at all and the machine stands still on exactly what the file put there.
    # NOTHING BUT THE REQUEST. Poking anything that stops the VM alongside it is a race with the
    # frame boundary - a fault breaks the loop at the check right after aw_frame_sync, so
    # depending on where the two pokes fall the load either runs or never gets read at all, and
    # this gate saw both. It is also unnecessary: measured directly, with nothing poked after the
    # request, the restored fields were identical twelve frames later. A state whose threads the
    # save caught inactive leaves the VM quiescent, which is the state a load lands in.
    request(z, read, sym, 2)                                                # 2 = load

    # sv_done lives in page 10, so reading it means mapping page 10 where it was assembled
    done = False
    for _ in range(400):
        time.sleep(0.25)
        z.cmd(f"tbblue-set-register {NR_MMU2} {PAGED_PAGE}")
        if read(sym["sv_done"], 1)[0] == 0x5A:
            done = True
            break
    if not done:
        err = read(sym["err"], 1)[0]
        bad.append(f"the load never finished; err = {err:#04x}"
                   + (" - esxDOS refused the open" if err else " - sv_load never ran"))
    else:
        z.cmd(f"write-memory {sym['snd_off']} 1")
        time.sleep(0.3)
        before = len(bad)
        bad += compare(z, read, blob, sym, "the load")
        if len(bad) == before:
            print("  the round trip holds: every field the save captured came back")
    z.close()

    if bad:
        print("\n  " + "\n  ".join(bad[:6]))
        raise SystemExit(f"FAIL: {len(bad)} thing(s) wrong across the save and the load")
    print(f"""
  the load order holds {N_RES[0]} ids: {' '.join(f'{r:#04x}' for r in ORDER)}

PASS: a {len(blob):,}-byte save and a load that puts it all back. Every field matches the
      machine it was taken from AND the machine that read it back - the VM's variables, call
      stack, thread pcs and channel flags byte for byte; the palette and page state; the player
      down to its pattern position; all four voice records; the heap's load order, in heap order
      and every id resident; and all {BANDS} bands of the four Layer 2 pages.

      The part index and the load order are DERIVED at save time rather than kept, which is why
      this cost no resident memory - and on the way back the resources are reloaded IN THAT
      ORDER, so the heap reconstructs identically and the restored windows point where they did.

      STILL OWED: the plan also asks that the opcode stream from the reload match a run that
      never saved. A round trip that holds is necessary and not sufficient - a state that
      matches can still resume wrongly.""")


def arm(z, sym):
    """Set sv_stop, so the save or load faults the VM the instant it returns.

    BOTH HALVES WANT THE SAME THING: the frame that does the file work must be the LAST frame,
    with no thread work after it, because the VM touches pg_ptr1 and aw_vars every frame and a
    snapshot compared against a machine that has moved on differs for that reason alone.

    EVERY WAY OF ARRANGING THAT FROM OUT HERE IS A RACE, and this gate lost it four times. The
    C's loop runs aw_frame_sync, then the part block, then breaks on budget-or-fault, and only
    AFTER that runs the frame's threads. So a stopper poked BEFORE the request can break the
    loop before any frame_sync reads the request, and the file work never happens; and one poked
    AFTER can arrive too late, because a save through ZEsarUX's esxDOS finishes in well under a
    tenth of a second - less than one ZRCP round trip. An instrumented run measured exactly that:
    the file held vars[3] = 0x10 and the machine had run on to 0x0c by the time it stopped.

    sv_stop ends it by moving the stopper inside, where there is nothing to race: see sv_entry.

    It is armed HERE, before `go`, and not later - mapping page 10 at MMU2 is only safe while the
    VM is not running, because MMU2 is the polygon segment window the rest of the time.
    """
    z.cmd(f"tbblue-set-register {NR_MMU2} {PAGED_PAGE}")
    z.cmd(f"write-memory {sym['sv_stop']} 1")


def request(z, read, sym, mode):
    """Ask for a save (1) or a load (2) and wait for the VM to stop itself."""
    z.cmd(f"write-memory {sym['save_req']} {mode}")
    for _ in range(400):
        if read(0xC00A, 1)[0] == 0x5A:                                      # CTL_FINISHED
            return
        time.sleep(0.05)
    raise SystemExit("FAIL: the VM never stopped - the request was never taken, or sv_stop "
                     "is not set")


def compare(z, read, blob, sym, label):
    """Every field of the file against the machine. Used for the save and again after the load."""
    bad = []
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
    fields = [(7, "pg_ptr1"), (16, "mus_res"), (17, "mus_playing"), (19, "mus_cur_order")]
    if label == "the save":
        fields.append((5, "pal_now"))
        fields.append((6, "pal_req"))
    else:
        # AFTER A LOAD THE SAVED pal_now IS IN pal_req, and pal_now is untouched: apply_palette maps
        # MMU2, which is where the load's own code runs, so the load asks aw_blit to apply it -
        # the reference's paletteIdRequested arrangement exactly. The VM is stopped the moment the
        # load returns, so no blit ever consumes the request.
        #
        # This used to compare the file's pal_now with the machine's pal_now, which after a load
        # is whatever palette the fresh run had reached two seconds in. It agreed only while the
        # run's timing happened to put a palette change on the right side of that mark, and it
        # stopped agreeing the day page copies got faster: 0x17 in the file, 0x13 on the machine.
        fields.append((5, "pal_req"))
    for off, name in fields:
        if blob[off] != live[name]:
            bad.append(f"{name} is {blob[off]:#04x} in the file, {live[name]:#04x} on the machine")

    # the mixer's four voice records, verbatim
    if blob[32:32 + 72] != read(0xDD00, 72):
        bad.append("the four voice records differ from the machine's")

    # the heap's load order, and that it is not empty - part 0 loads three resources at least
    n_res = blob[15]
    order = list(blob[128:128 + n_res])
    N_RES[0], ORDER[:] = n_res, order
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
    return [f"{label}: {b}" for b in bad]


if __name__ == "__main__":
    main()
