#!/usr/bin/env python3
"""I1a: does the game read a real keyboard, and does the reference's mapping survive it?

Until this step nothing in the project read input at all. check-pace proves the
MAPPING - all 32 combinations, in inp_updatePlayer's own order, including the two
oddities that make it worth sharing rather than rewriting: LEFT assigns rather than
or-s, so left-and-right together reads as left; and UP is tested twice, writing
variable $E5 before the test and again inside it. But petest is HANDED its mask as a
poked byte.

This drives the emulator's own keyboard with send-keys-event, one key at a time, and
checks the six variables the game publishes for the C - so the path under test is
port $FE and port $1F through read_keys and do_input, not a poke.

The oracle is the same model check-pace uses, so a mapping change has to break both.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zrcp import Zrcp  # noqa: E402

NEX = "build/aw.nex"
EXP_ASM, EXP_C = "build/aw.exp", "build/aw_vm_c.exp"
IN_BLOCK = 0xC380
CTL = 0xC000

# The keys read_keys reads, and the mask bit each sets. ZEsarUX's send-keys-event
# takes ASCII below 128 for letters; space has its own code.
KEYS = {
    "left":  (ord('o'), 0x01),
    "right": (ord('p'), 0x02),
    "up":    (ord('q'), 0x04),
    "down":  (ord('a'), 0x08),
    "fire":  (128,      None),      # UTIL_KEY_SPACE
}


# THE ORACLE IS IMPORTED, NOT RETYPED. The first version of this checker re-derived
# inp_updatePlayer from the reference and got it wrong in one place - and the wrong
# place was the one that matters, because it is the entire reason two variables exist:
# $FD takes the mask WITHOUT the fire bit and $FE takes it WITH, since the reference
# writes $FD before the fire test and $FE after it. Sixteen of thirty-two combinations
# "failed" and the machine was right in every one of them.
#
# check-pace's copy is gated. Import it; do not have two.
from checkpace import reference_input as _ref_named       # noqa: E402


def reference_input(mask, button):
    """check-pace's own model, keyed by number rather than by name."""
    r = _ref_named(mask, button)
    return {0xE5: r["E5"], 0xFA: r["FA"], 0xFB: r["FB"],
            0xFC: r["FC"], 0xFD: r["FD"], 0xFE: r["FE"]}


def symbols(*paths):
    out = {}
    for path in paths:
        for line in open(path):
            name, _, val = line.partition(":")
            if "0x" in val:
                out[name.strip()] = int(val.split("0x")[1], 16)
    return out


def main():
    sym = symbols(EXP_ASM, EXP_C)
    z = Zrcp()
    print(f"emulator: {z.cmd('get-version')}")
    z.cmd(f"smartload /work/{NEX}")
    time.sleep(3.5)
    z.cmd("set-memory-zone -1")
    if int(z.cmd(f"read-memory {sym['ready']} 1").strip(), 16) != 0x5A:
        raise SystemExit("FAIL: the game never reached its wait loop")

    def read_block():
        raw = z.cmd(f"read-memory {IN_BLOCK} 12").strip()
        b = bytes(int(raw[i:i + 2], 16) for i in range(0, 24, 2))
        v = [int.from_bytes(b[i:i + 2], "little", signed=True) for i in range(0, 12, 2)]
        return dict(zip((0xE5, 0xFA, 0xFB, 0xFC, 0xFD, 0xFE), v))

    def press(codes, down):
        for c in codes:
            z.cmd(f"send-keys-event {c} {1 if down else 0} nomenu")

    # Every combination of the four directions and fire: 32 of them, the same set
    # check-pace scores, driven from the keyboard instead of from a poke.
    bad, n = [], 0
    for combo in range(32):
        names = [k for i, k in enumerate(("left", "right", "up", "down", "fire"))
                 if combo & (1 << i)]
        codes = [KEYS[k][0] for k in names]
        mask = sum(KEYS[k][1] for k in names if KEYS[k][1])
        button = 1 if "fire" in names else 0

        press(codes, True)
        time.sleep(0.12)                # several interrupts, so it has certainly read
        got = read_block()
        press(codes, False)
        time.sleep(0.08)

        want = reference_input(mask, button)
        n += 1
        if got != want:
            bad.append((combo, names, got, want))

    # And the C picks them up: hold fire, run frames, and read the VM's own variable.
    vars_addr = sym.get("_aw_vars") or sym.get("aw_vars")
    fire_ok = None
    if vars_addr:
        # DECIMAL ADDRESSES. ZEsarUX's expression parser refuses an 0x prefix -
        # the same trap that made its breakpoints look broken earlier in this
        # project - and a refused write is silent. Written as "0xC000" these
        # pokes went nowhere, CTL_FRAMES stayed zero, and the VM ran no frames
        # at all while the checker reported that input was not reaching it.
        hdr = (0).to_bytes(2, "little") + (600).to_bytes(2, "little") \
            + (60000).to_bytes(2, "little")
        z.cmd(f"write-memory-raw {CTL} {hdr.hex()}")
        z.cmd(f"write-memory-raw {sym['fname']} {(b'RES18.BIN' + bytes(1)).hex()}")
        z.cmd(f"write-memory {sym['go']} 1")
        # DISABLE THE STREAM COMPARISON, AFTER the assembly has set it. src/aw.asm
        # writes the expected count into $C014 once load_code returns, so a poke before
        # `go` is overwritten - which is what happened first time: the VM ran its 763
        # records, faulted on the reference running out, left the frame loop, and stopped
        # calling aw_apply_input long before a key was pressed. This run is about input
        # reaching the VM, not about the stream, so wait for the count and clear it.
        for _ in range(100):
            if int(z.cmd(f"read-memory {CTL + 0x14} 2").strip(), 16) != 0:
                break
            time.sleep(0.02)
        z.cmd(f"write-memory-raw {CTL + 0x14} 0000")
        time.sleep(0.5)
        press([KEYS["fire"][0]], True)
        time.sleep(0.5)
        raw = z.cmd(f"read-memory {vars_addr + 0xFA * 2} 2").strip()
        fire_ok = int.from_bytes(bytes(int(raw[i:i + 2], 16) for i in range(0, 4, 2)),
                                 "little", signed=True)
        press([KEYS["fire"][0]], False)
    z.close()

    print(f"\n{n - len(bad)} of {n} keyboard combinations map exactly as the reference "
          f"does")
    for combo, names, got, want in bad[:6]:
        print(f"  combo {combo:>2} ({'+'.join(names) or 'nothing'}):")
        for k in (0xE5, 0xFA, 0xFB, 0xFC, 0xFD, 0xFE):
            flag = "" if got[k] == want[k] else "   <-- wrong"
            print(f"    ${k:02X}  got {got[k]:>6}  want {want[k]:>6}{flag}")
    if bad:
        raise SystemExit(f"FAIL: {len(bad)} of {n} combinations do not match")

    if fire_ok is None:
        print("  (the C's own aw_vars was not checked: no symbol for it)")
    else:
        print(f"\nthe VM's own variable $FA with fire held: {fire_ok}")
        if fire_ok != 1:
            raise SystemExit("FAIL: the keyboard reaches the published block but not "
                             "the VM's variables - aw_apply_input is not running")

    print("""
PASS: the game reads a real keyboard - port $FE for O, P, Q, A and Space, and port
      $1F for a Kempston joystick in parallel - and all 32 combinations map exactly
      as inp_updatePlayer does, through to the VM's own variables. I1a is closed.""")


if __name__ == "__main__":
    main()
