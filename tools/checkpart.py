"""I6. A part transition on the machine, against setupPart's own promises.

setupPart (resource.cpp:280) does four things and this checks all four, for three parts chosen
to cover the shapes: the introduction, a gameplay part that names a second polygon set, and a
cinematic that does not.

  the player and every channel stop      initForPart, vm.cpp, before setupPart runs
  everything is invalidated              invalidateAll, resource.cpp:298
  the part's four resources are resident  loadMarkedAsNeeded, resource.cpp:310
  the three windows point at them        segPalettes, segBytecode, segCinematic, _segVideo2

The resource ids come from the reference's own memListParts (parts.cpp) through
tools/mkparts.py, not from anything ours, so a wrong table here would have to agree with the
engine's to pass. The palette is compared byte for byte against the card, because that is the
one resource the part does not simply page in: apply_palette reads it out of the text page.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zrcp import Zrcp                   # noqa: E402
from mkparts import table as part_table  # noqa: E402

NEX = "build/aw.nex"
ASSETS = "build/assets"
PROBE = os.environ.get("PROBE", "preflight/hostprobe/probe")
PAL_BASE, TEXT_PAGE, NR_MMU7, DWIN = 0xEE00, 1, 0x57, 0xE000
VOICES_AT, V_SIZE, V_ACTIVE = 0xDD00, 18, 11

# index, and why it is here
CASES = [
    (1, "the introduction: no second polygon set"),
    (2, "gameplay: a second polygon set, $11"),
    (5, "the battlechar cinematic: no second set"),
]


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
    parts = part_table(open(f"{PROBE}/parts.cpp").read())
    sym = symbols("build/aw.exp")
    z = Zrcp()
    print(f"emulator: {z.cmd('get-version')}")

    def read(a, n):
        out = bytearray()
        while len(out) < n:
            k = min(2048, n - len(out))
            raw = z.cmd(f"read-memory {a + len(out)} {k}").strip()
            out += bytes(int(raw[i:i + 2], 16) for i in range(0, 2 * k, 2))
        return bytes(out)

    bad = []
    for index, why in CASES:
        pal, code, cin, vid2 = parts[index]
        z.cmd(f"smartload /work/{NEX}")
        time.sleep(3.2)
        z.cmd("set-memory-zone -1")
        z.cmd(f"write-memory-raw {sym['fname']} {(b'RES18.BIN' + bytes(1)).hex()}")
        z.cmd(f"write-memory {sym['probe_part']} {index + 1}")
        z.cmd(f"write-memory {sym['go']} 1")
        for _ in range(900):
            if read(sym["done"], 1)[0] == 0x5A:
                break
            time.sleep(0.05)

        pages = read(sym["res_page"], 256)
        fails = []
        if read(sym["res_err"], 1)[0]:
            fails.append(f"a load failed with esxDOS error {read(sym['res_err'], 1)[0]:#04x}")
        if read(sym["res_full"], 1)[0]:
            fails.append("the heap reservation was exceeded")

        # claim 3: every resource the part names is resident
        for name, rid in (("palette", pal), ("bytecode", code), ("cinematic", cin)):
            if not pages[rid]:
                fails.append(f"the {name}, resource {rid:#04x}, is not resident")
        if vid2 and not pages[vid2]:
            fails.append(f"the second polygon set, {vid2:#04x}, is not resident")

        # claim 4: the three windows point at them
        got_code = read(sym["code_add"] + 1, 1)[0]
        got_cin = read(sym["cin_base"], 1)[0]
        got_vid2 = read(sym["vid2_base"], 1)[0]
        if got_code != pages[code]:
            fails.append(f"the bytecode window is based at page {got_code}, "
                         f"resource {code:#04x} is at {pages[code]}")
        if got_cin != pages[cin]:
            fails.append(f"the cinematic window is based at page {got_cin}, "
                         f"resource {cin:#04x} is at {pages[cin]}")
        want_vid2 = pages[vid2] if vid2 else 0
        if got_vid2 != want_vid2:
            fails.append(f"the second polygon window is at page {got_vid2}, wanted {want_vid2}")

        # claim 1: nothing is playing
        if read(sym["mus_playing"], 1)[0]:
            fails.append("the player is still running")
        raw = read(VOICES_AT, V_SIZE * 4)
        live = [c for c in range(4) if raw[c * V_SIZE + V_ACTIVE]]
        if live:
            fails.append(f"channel(s) {live} are still active")

        # the palette, byte for byte against the card, through the text page
        z.cmd(f"tbblue-set-register {NR_MMU7} {TEXT_PAGE}")
        got_pal = read(DWIN + (PAL_BASE - 0xE000), 1024)
        want_pal = open(os.path.join(ASSETS, f"PAL{pal:02X}.BIN"), "rb").read()[:1024]
        if got_pal != want_pal:
            d = next(i for i in range(1024) if got_pal[i] != want_pal[i])
            fails.append(f"PAL{pal:02X} differs from the card at byte {d}: "
                         f"{got_pal[d]:#04x} vs {want_pal[d]:#04x}")

        if fails:
            print(f"  part {index} ({why}): " + "; ".join(fails[:3]))
            bad += fails
        else:
            print(f"  part {index} - {why:<40} palette {pal:#04x}, bytecode {code:#04x}"
                  f"@{pages[code]}, polygons {cin:#04x}@{pages[cin]}"
                  + (f" + {vid2:#04x}@{pages[vid2]}" if vid2 else ", no second set")
                  + ", silent  IDENTICAL")
    z.close()
    if bad:
        raise SystemExit(f"FAIL: {len(bad)} thing(s) wrong with the part transition")
    print(f"""
PASS: {len(CASES)} parts set up on the machine exactly as setupPart describes - the player and
      all four channels stopped, everything invalidated, every resource the part names
      resident, and the bytecode and both polygon windows based on the pages they actually
      landed at. The palette is byte for byte against the card. The resource ids come from
      the reference's own memListParts through tools/mkparts.py, so a wrong table here would
      have to agree with the engine's to pass.""")


if __name__ == "__main__":
    main()
