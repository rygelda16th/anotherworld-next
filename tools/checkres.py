#!/usr/bin/env python3
"""I3: do the resources the bytecode asks for actually arrive on the machine?

The VM dispatches op_updateMemList and the machine now loads. Three claims:

 1. EVERY RESOURCE IT ASKED FOR IS THERE, byte for byte. Not "the loader returned" -
    the pages are read back off the machine and compared against the file on the card.
 2. IT ASKED FOR THE SAME ONES THE ENGINE DID. **NOT YET CHECKED** - the probe logs loads
    by time and type, not by resource id, so there is nothing to compare against. A port
    that silently skipped a load would still pass claims 1 and 3. See the note in main.
 3. THE HEAP STAYS INSIDE ITS RESERVATION. 40 pages against the reference's measured
    high-water of 38, and running past it sets a flag rather than wrapping onto Layer 2.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zrcp import Zrcp  # noqa: E402
from memlist import entries, memlist_path  # noqa: E402

NEX = "build/aw.nex"
EXP_ASM, EXP_C = "build/aw.exp", "build/aw_vm_c.exp"
PROBE = "preflight/hostprobe/probe"
ASSETS = "build/assets"
CTL = 0xC000
RES_FIRST_PAGE, RES_MAX_PAGES = 72, 40
NR_MMU7, DWIN = 0x57, 0xE000
FRAMES = int(os.environ.get("AW_FRAMES", "45"))


def symbols(*paths):
    out = {}
    for path in paths:
        for line in open(path):
            name, _, val = line.partition(":")
            if "0x" in val:
                out[name.strip()] = int(val.split("0x")[1], 16)
    return out


def asset_name(rid, rtype):
    pre = {3: "PAL", 2: "BMP"}.get(rtype, "RES")
    return f"{pre}{rid:02X}.BIN"


def main():
    sym = symbols(EXP_ASM, EXP_C)
    es = list(entries(memlist_path("data")))
    seed = next(int(l.split()[1]) & 0xFFFF
                for l in open(os.path.join(PROBE, "ops.txt")) if l.startswith("seed"))

    # CLAIM 2 IS NOT IMPLEMENTED AND THIS SAYS SO. Comparing the machine's load list
    # against the engine's needs the probe to log resource IDS, and its sound log is keyed
    # by time and type rather than by id - so there is nothing here to compare against yet.
    # It matters: a port that quietly skipped a load would pass claims 1 and 3. The probe
    # needs an instrOp in loadPartsOrMemoryEntry before this can be checked, and until then
    # the count is reported rather than verified.

    z = Zrcp()
    print(f"emulator: {z.cmd('get-version')}")
    z.cmd(f"smartload /work/{NEX}")
    time.sleep(3.5)
    z.cmd("set-memory-zone -1")

    def read(a, n):
        out = bytearray()
        while len(out) < n:
            k = min(2048, n - len(out))
            raw = z.cmd(f"read-memory {a + len(out)} {k}").strip()
            out += bytes(int(raw[i:i + 2], 16) for i in range(0, 2 * k, 2))
        return bytes(out)

    if read(sym["ready"], 1)[0] != 0x5A:
        raise SystemExit("FAIL: the game never reached its wait loop")
    hdr = (seed.to_bytes(2, "little") + FRAMES.to_bytes(2, "little")
           + (60000).to_bytes(2, "little"))
    z.cmd(f"write-memory-raw {CTL} {hdr.hex()}")
    z.cmd(f"write-memory-raw {sym['fname']} {(b'RES18.BIN' + bytes(1)).hex()}")
    z.cmd(f"write-memory {sym['go']} 1")
    waited = 0.0
    while waited < 120.0:
        if read(CTL + 10, 1)[0] == 0x5A:
            break
        time.sleep(0.1)
        waited += 0.1

    n_load = int.from_bytes(read(sym["n_load"], 2), "little")
    n_inval = int.from_bytes(read(sym["n_inval"], 2), "little")
    next_page = read(sym["next_page"], 1)[0]
    res_err = read(sym["res_err"], 1)[0]
    res_full = read(sym["res_full"], 1)[0]
    pages = read(sym["res_page"], len(es))
    loaded = [(i, p) for i, p in enumerate(pages) if p]

    print(f"\nthe machine over {FRAMES} frames, {waited:.1f}s:")
    print(f"  op_updateMemList loaded {n_load}, invalidated {n_inval} times")
    print(f"  the heap cursor is at page {next_page}, "
          f"{next_page - RES_FIRST_PAGE} of {RES_MAX_PAGES} pages used")
    print(f"  {len(loaded)} resources are resident: "
          + ", ".join(f"{i:#04x}@{p}" for i, p in loaded[:12])
          + (" ..." if len(loaded) > 12 else ""))

    bad = []
    if res_err:
        bad.append(f"a load failed with esxDOS error {res_err:#04x}")
    if res_full:
        bad.append(f"the heap reservation of {RES_MAX_PAGES} pages was exceeded")
    if next_page - RES_FIRST_PAGE > RES_MAX_PAGES:
        bad.append(f"the cursor is past its reservation at page {next_page}")

    # QUIESCE THE MIXER BEFORE READING THROUGH MMU7. The loop below maps a resource page
    # into MMU7 and reads 8,192 bytes as four ZRCP calls, while the machine is still running
    # its interrupt - and MMU7 is shared: it is the Layer 2 draw band, the loader's staging
    # window, and from I5 the mixer's sample window as well. The mixer borrows and restores it
    # fifty times a second, which is correct on the machine and fatal to a reader that holds
    # the slot across four round trips: three resources came back differing from the card at
    # byte 2,048 exactly, which is where the second chunk starts.
    #
    # snd_off exists for precisely this kind of question and is what the game's own probe path
    # uses. The VM has already finished by here, so nothing is drawing either.
    z.cmd(f"write-memory {sym['snd_off']} 1")
    time.sleep(0.1)

    # Claim 1: every resident resource, byte for byte against the card.
    checked = 0
    for rid, page in loaded:
        e = es[rid]
        want = open(os.path.join(ASSETS, asset_name(rid, e["type"])), "rb").read()
        got = bytearray()
        need = e["size"]
        p = page
        while len(got) < need:
            z.cmd(f"tbblue-set-register {NR_MMU7} {p}")
            got += read(DWIN, min(8192, need - len(got)))
            p += 1
        got = bytes(got[:need])
        if got != want[:need]:
            d = next(i for i in range(need) if got[i] != want[i])
            bad.append(f"resource {rid:#04x} ({asset_name(rid, e['type'])}, "
                       f"{need:,} bytes) differs from the card at byte {d}: "
                       f"{got[d]:#04x} vs {want[d]:#04x}")
        else:
            checked += 1
    z.close()

    print(f"  {checked} of {len(loaded)} verified byte for byte against the card")
    if bad:
        print("\n  " + "\n  ".join(bad[:8]))
        raise SystemExit(f"FAIL: {len(bad)} problem(s) loading resources")
    if not loaded:
        raise SystemExit("FAIL: the intro asked for no resources at all over "
                         f"{FRAMES} frames, which cannot be right - "
                         f"op_updateMemList ran {n_load} times")
    print(f"""
PASS: every one of the {len(loaded)} resources the bytecode asked for is on the machine
      byte for byte against the card, inside a heap reservation of {RES_MAX_PAGES} pages
      with {next_page - RES_FIRST_PAGE} used. I3's loading claim holds.""")


if __name__ == "__main__":
    main()
