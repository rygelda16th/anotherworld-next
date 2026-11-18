#!/usr/bin/env python3
"""Make the SD-card files for Another World Next from your own copy of the DOS game.

    python3 tools/mkcard.py <DOS game folder> <output folder> [--nex AW.NEX ...]

The DOS game folder is the one holding MEMLIST.BIN and the BANKxx files, in either case. The
output folder gets the converted resources (RESxx.BIN, BMPxx.BIN, BMWxx.BIN, PALxx.BIN) and, with
--nex, a copy of each .nex named. Copy that folder to the Next's SD card and run the .nex from it.

Needs nothing but Python 3.6 or later - no Docker, no toolchain. It is tools/mkassets.py, the same
converter the build uses, run with a friendlier front: it checks the input, keeps the converter's
long report in mkcard.log in the output folder, and skips resources whose bank file is missing (the
DOS playable demo ships only some banks) instead of stopping.

No game data is in this repository or in the .nex: everything it plays comes from these files, which
come from your copy. Do not share the output folder - it is the game's data. See docs/licence.md.

Not made here: MUSIC.PCM, the intro's music rendered ahead of time (tools/mkmusic.py). It needs a
trace of the reference engine playing the intro, which needs the full toolchain. Without it the
game mixes the intro's music live, as it does every other part's: the same music, and the intro runs
about 3% slower.
"""
import contextlib
import io
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import memlist  # noqa: E402
import mkassets  # noqa: E402


def tolerant_load(data_dir):
    """memlist.load, but a bank that is not there drops its resources instead of failing."""
    es = list(memlist.entries(memlist.memlist_path(data_dir)))
    banks, missing = {}, set()
    for e in es:
        b = e["bank"]
        if not b or b in banks or b in missing:
            continue
        try:
            banks[b] = open(memlist.bank_path(data_dir, b), "rb").read()
        except FileNotFoundError:
            missing.add(b)
    kept = [e for e in es if not e["bank"] or e["bank"] in banks]
    tolerant_load.missing = sorted(missing)
    tolerant_load.dropped = len(es) - len(kept)
    return kept, banks


def main():
    args = sys.argv[1:]
    nexes = []
    while "--nex" in args:
        i = args.index("--nex")
        if i + 1 >= len(args):
            sys.exit("--nex needs a file after it")
        nexes.append(args[i + 1])
        del args[i:i + 2]
    if len(args) != 2:
        sys.exit(__doc__.strip().split("\n\n")[1])
    data_dir, out_dir = args
    if sys.version_info < (3, 6):
        sys.exit("needs Python 3.6 or later")
    try:
        memlist.memlist_path(data_dir)
    except FileNotFoundError:
        sys.exit(f"no MEMLIST.BIN in {data_dir}: point this at the DOS game's folder, the one with "
                 f"MEMLIST.BIN and BANK01, BANK02 ... in it")
    for n in nexes:
        if not os.path.isfile(n):
            sys.exit(f"no such file: {n}")

    os.makedirs(out_dir, exist_ok=True)
    mkassets.load = tolerant_load               # mkassets took `load` by name at import
    log = io.StringIO()
    old = sys.argv
    sys.argv = ["mkassets.py", data_dir, out_dir]
    try:
        with contextlib.redirect_stdout(log):
            mkassets.main()
    except Exception as e:                      # a bad bank: say so, keep the report
        open(os.path.join(out_dir, "mkcard.log"), "w").write(log.getvalue())
        sys.exit(f"conversion failed: {e}\n(the converter's report so far is in "
                 f"{os.path.join(out_dir, 'mkcard.log')})")
    finally:
        sys.argv = old
    open(os.path.join(out_dir, "mkcard.log"), "w").write(log.getvalue())

    for n in nexes:
        shutil.copy(n, os.path.join(out_dir, os.path.basename(n).upper()))

    made = sorted(f for f in os.listdir(out_dir) if f.endswith(".BIN"))
    kinds = {k: sum(f.startswith(k) for f in made) for k in ("RES", "BMP", "BMW", "PAL")}
    print(f"wrote {len(made)} files to {out_dir}: {kinds['RES']} resources, "
          f"{kinds['PAL']} palettes, {kinds['BMW']} pictures (320x256) and {kinds['BMP']} (256x192)")
    if tolerant_load.missing:
        print(f"bank files not found: {', '.join(f'BANK{b:02X}' for b in tolerant_load.missing)} - "
              f"{tolerant_load.dropped} resources skipped. Fine for the DOS demo; the full game "
              f"has them all")
    nex_on = [f for f in os.listdir(out_dir) if f.upper().endswith(".NEX")]
    print()
    print("Next:")
    if not nex_on:
        print("  - put AW.NEX (from the release) in that folder too")
    print(f"  - copy the folder to the Next's SD card, for example as /aw")
    print("  - on the Next, open the Browser, go into that folder and run AW.NEX; press ENTER to start")
    print("  - keep the folder to yourself: it is the game's data, from your copy")


if __name__ == "__main__":
    main()
