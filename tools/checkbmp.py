"""I7. A full-screen bitmap on the machine, against the deplaner check-bitmap already proved.

copyPage(const uint8_t *src) (video.cpp:550) deplanes four planes 8,000 bytes apart into page 0
at 320x200, four bits a pixel. mkassets.py does that at build time and writes the result as OUR
page - 256x192 at 8bpp, 49,152 bytes - and `make check-bitmap` proves that deplaner is the
engine's, pixel for pixel, on real resources. So what is left to prove on the machine is the
copy, and this proves it byte for byte against the same file.

Two other things the reference does that are easy to get wrong, and both are checked:

  a bitmap goes to PAGE 0, always        video.cpp:554 takes _pages[0], not a page id
  a bitmap is NOT KEPT                   loadMarkedAsNeeded marks it NOT_NEEDED
                                         (resource.cpp:214) - it never becomes resident and the
                                         heap never sees it, which matters because part 7 loads
                                         seventy of them
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zrcp import Zrcp                   # noqa: E402

# AW_WIDE=1: the 320x256 build (docs/plan-wide320.md W3): ten strips a page, BMWnn.BIN, the heap at 90.
WIDE = bool(os.environ.get("AW_WIDE"))
NEX, ASSETS = ("build/aw320.nex" if WIDE else "build/aw.nex"), "build/assets"
L2_BASE_BANK, BANDS, BAND, DWIN, NR_MMU7 = 12, (10 if WIDE else 6), 8192, 0xE000, 0x57
PAGE = BANDS * BAND                     # 49,152: one Layer 2 page (81,920 in 320x256)

RES_FIRST_PAGE = 90 if WIDE else 72     # = the EQU in src/aw.asm, as checkres.py keeps it
CASES = [0x12, 0x43, 0x91]              # the first, one from the arena's run, and the last


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
    sym = symbols("build/aw320.exp" if WIDE else "build/aw.exp")
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
    for rid in CASES:
        z.cmd(f"smartload /work/{NEX}")
        time.sleep(3.2)
        z.cmd("set-memory-zone -1")
        z.cmd(f"write-memory-raw {sym['fname']} {(b'RES18.BIN' + bytes(1)).hex()}")
        z.cmd(f"write-memory {sym['probe_bmp']} {rid}")
        z.cmd(f"write-memory {sym['go']} 1")
        for _ in range(900):
            if read(sym["done"], 1)[0] == 0x5A:
                break
            time.sleep(0.05)

        # QUIESCE BEFORE READING THROUGH MMU7. It is the Layer 2 band window, the loader's
        # staging window and the mixer's sample window all at once, and the mixer borrows it
        # fifty times a second - which showed up in check-res and check-draw as reads differing
        # from byte 2,048 exactly, where a second ZRCP chunk starts.
        z.cmd(f"write-memory {sym['snd_off']} 1")
        time.sleep(0.1)

        n_bmp = int.from_bytes(read(sym["n_bmp"], 2), "little")
        pages = read(sym["res_page"], 256)
        next_page = read(sym["next_page"], 1)[0]
        err = read(sym["res_err"], 1)[0]

        got = bytearray()
        p0 = L2_BASE_BANK * 2
        for band in range(BANDS):
            z.cmd(f"tbblue-set-register {NR_MMU7} {p0 + band}")
            got += read(DWIN, BAND)
        got = bytes(got)
        want = open(os.path.join(ASSETS, f"{'BMW' if WIDE else 'BMP'}{rid:02X}.BIN"), "rb").read()

        fails = []
        if err:
            fails.append(f"the load failed with esxDOS error {err:#04x}")
        if n_bmp != 1:
            fails.append(f"{n_bmp} bitmaps were presented, wanted 1")
        if pages[rid]:
            fails.append(f"resource {rid:#04x} is marked resident at page {pages[rid]} - a "
                         f"bitmap is NOT_NEEDED after it is presented")
        if next_page != RES_FIRST_PAGE:
            fails.append(f"the heap cursor moved to {next_page}; a bitmap must not use the heap")
        if len(want) != PAGE:
            fails.append(f"BMP{rid:02X} is {len(want):,} bytes, not {PAGE:,}")
        elif got != want:
            d = next(i for i in range(PAGE) if got[i] != want[i])
            n = sum(1 for i in range(PAGE) if got[i] != want[i])
            fails.append(f"{n:,} of {PAGE:,} pixels differ, first at {d} "
                         f"(row {d // 256}, column {d % 256}): {got[d]:#04x} vs {want[d]:#04x}")
        if fails:
            print(f"  BMP{rid:02X}: " + "; ".join(fails[:3]))
            bad += fails
        else:
            print(f"  BMP{rid:02X} - all {PAGE:,} pixels identical to the deplaner's, page 0, "
                  f"not resident, heap untouched  IDENTICAL")
    z.close()
    if bad:
        raise SystemExit(f"FAIL: {len(bad)} thing(s) wrong with the bitmap path")
    print(f"""
PASS: {len(CASES)} full-screen bitmaps presented on the machine, all {PAGE:,} pixels of each
      identical to what mkassets.py's deplaner produced - and `make check-bitmap` proves that
      deplaner is the engine's on real resources, so the pair covers copyPage end to end. Each
      landed in page 0, none was left resident, and the heap cursor never moved: a bitmap is
      loaded into its own six-page scratch, presented and forgotten, which is what
      MEMENTRY_STATE_NOT_NEEDED amounts to and what lets part 7 load seventy of them.""")


if __name__ == "__main__":
    main()
