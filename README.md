# Another World on the ZX Spectrum Next

A port of the Another World (Out of This World) engine to the ZX Spectrum Next.
GPLv2. Work in progress.

**Read `docs/where-things-stand.md` first.** It is the canonical status: what is
built, what every number was measured at, which of the original design decisions
survived contact with the hardware, and the traps that cost real time.

The short version: the virtual machine will be plain C compiled with z88dk, and
the polygon rasteriser is Z80N assembly. After measurement that is the only thing
that needs to be - the worst frame in 12,000 dispatches 96 opcodes against a
budget of 280, and spends essentially all its time drawing spans.

## State

| Phase | |
|---|---|
| A - asset pipeline, reference rasteriser | done, Gate A passed |
| B - toolchain | done, Gate B passed |
| C - rasteriser core | done, Gate C passed, 49,152/49,152 pixels exact |
| C - polygon reader, vertex scale, register allocation | outstanding |
| D - the virtual machine | not started |
| E - pacing, input, sound | not started |

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
