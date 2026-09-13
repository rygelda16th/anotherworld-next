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
| C - rasteriser core | done, Gate C passed, 49,152/49,152 pixels exact |
| C - polygon reader, vertex scale, segment window | specified, not built |
| D - the virtual machine | specified, not built |
| E - pacing, input, sound | specified, not built |
| F - the rest of the game | scoped, three known gaps |

## Getting started

    make certs      # once, on the corporate network: the TLS-inspection CA
    make image      # build the toolchain container
    make doctor     # prove both toolchain images are real
    make help       # everything else

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
