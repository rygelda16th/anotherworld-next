# Another World on the ZX Spectrum Next

A port of the Another World (Out of This World) engine to the ZX Spectrum Next.
GPLv2. Work in progress.

**Read `docs/where-things-stand.md` first.** It is the canonical status: what is
built, what every number was measured at, which of the original design decisions
survived contact with the hardware, and the traps that cost real time.

The short version: the virtual machine will be plain C compiled with z88dk, and
the polygon rasteriser is Z80N assembly. After measurement that is the only thing
that needs to be - the heaviest frame the game produces dispatches 509 opcodes,
about 9% of the time the scripts allow a frame, and spends the rest drawing
polygons.

The scripts ask for **80 to 100 ms a frame**, not 20, which is the number that
sets every budget here. Measured against the pause each frame itself requests,
the rasteriser uses a quarter of the time available and fewer than one frame in a
hundred overruns. The largest remaining unknown is not the renderer but the sound
mixer, which turns out to be running almost all the time.

## State

| Phase | |
|---|---|
| A - asset pipeline, reference rasteriser | done, Gate A passed |
| B - toolchain | done, Gate B passed |
| C - rasteriser, 16-bit geometry, reader, window | done, Gates C, C4 and C5a passed |
| D - the virtual machine | built in C; Gate D's stream matches as far as it is traced |
| E - pacing, input, sound | specified, and the mixer priced on the machine |
| F - the rest of the game | scoped, three known gaps |

Measured on the machine so far: a polygon span end to end, a polygon's setup cost,
one output sample of the four-voice mixer, and that esxDOS reads every byte
correctly (its speed needs hardware - the emulator charges nothing for it).

## Playing it

You need a ZX Spectrum Next (tested on a KS3, core 3.03.03), `AW.NEX` from a release, and **your
own copy of the DOS game** - the folder with `MEMLIST.BIN` and the `BANKxx` files. The DOS playable
demo should work as well. No game data is in this repository or in the `.nex`.

    python3 tools/mkcard.py <your DOS game folder> <output folder> --nex AW.NEX

needs only Python 3.6 or later. Copy the output folder to the Next's SD card, run `AW.NEX` from it
in the Browser, and press ENTER. Keys: O left, P right, Q up, A down, Space fire - or a Kempston
joystick. The output folder is the game's data from your copy: don't share it.

`AW.NEX` is the 320x256 build; `AW256.NEX` is the same game at 256x192. Please report what you find
as a GitHub issue: the part, what happened, and the core version.

## Getting started (building it)

    make image      # build the toolchain container, once
    make doctor     # prove both toolchain images are real
    make help       # everything else

The container is the easy route, and the only practical one for the `check-*` targets: they
drive a ZEsarUX built at a pinned commit with three local patches (`tools/zesarux/`), and their
numbers depend on it. To build the game with your own tools instead you need
[sjasmplus](https://github.com/z00m128/sjasmplus) (the z00m128 fork; measured at `8c87edd`),
[z88dk](https://github.com/z88dk/z88dk) (measured with the `z88dk/z88dk:20260907` image) and
Python 3 for the asset tools. The `Dockerfile` and the `Makefile`'s `cc` target record the exact
versions.

You need your own copy of the game's DOS data files in `data/`. **None of them are
in this repository and none are in the binary** - see `docs/licence.md`, which also
records which reimplementation the engine facts are taken from and, importantly,
the two they are deliberately not taken from.

## Layout

    src/            Z80N assembly, assembled by sjasmplus into .nex
    preflight/      measurements that gate the work: the host probe, the C binding
    tools/          host-side Python: asset conversion, the reference, the checkers
    docs/           where-things-stand.md is canonical; licence.md is the lineage

Every `check-*` target is a measurement that either passes or says why not. The
reference implementation in `tools/refvideo.py` is the specification: the machine
matches it, not the other way round.

Two of those measurements are host-side reports rather than gates - `make
frame-load` scores every frame against the pause its own script asked for, and
`make voices` says how much of the time the mixer is busy. Both need the host
probe run first, and both need its **synthetic input** enabled, or they describe
the intro's idle screen; `preflight/hostprobe/README.md` says why.
