# Licence, and why this one

**This port is GPLv2.** The full text is in `LICENSE`, fetched from gnu.org
rather than typed (by wolf3d-next; this is the same file). The one exception is the
three ZEsarUX patches, which are GPLv3 - see "The toolchain" below.

## Why GPLv2, and which lineage the facts come from

Another World has been reimplemented several times and the reimplementations do
**not** share a licence. Getting this wrong would be easy and expensive, so the
rule for this port is narrow and absolute:

**Everything taken from an existing implementation comes from
[fabiensanglard/Another-World-Bytecode-Interpreter][awbi], pinned at commit
`170b7d466a6ea6cc36a9e53506d5b858ed503a84`, and is cited by file and line
wherever it is used.**

[awbi]: https://github.com/fabiensanglard/Another-World-Bytecode-Interpreter

That repository carries the GPL-2.0 text in `LICENSE.txt`, and every source file
bears a GPL-2.0-**or-later** grant over **Copyright (C) 2004 Gregory Montoir** -
not Fabien, who cleaned the codebase up rather than wrote it. Or-later is
compatible with this port's GPLv2.

Verified rather than assumed: 26 of the 28 `.cpp`/`.h` files carry that header.

### The two files that carry no header at all

`src/parts.cpp` and `src/parts.h` have **no licence header and no copyright
line**. They are also, inconveniently, the files holding the part table - the
ten parts and the four resource ids each one loads - which any port must
reproduce exactly.

The position taken here is that the table is a *factual description of the
game's data*, not expression: it is a list of which resource numbers belong to
which chapter, discoverable by reading `memlist.bin` and the bytecode. It is
used on that basis, and the gap is recorded here rather than left unremarked so
that anyone revisiting it knows the question was asked.

### The trap: what must NOT be used

- **[cyxx/rawgl][rawgl] has no licence whatsoever.** No `LICENSE` or `COPYING`
  file, GitHub's licence API returns 404, and its headers carry a bare
  `Copyright (C) 2004-2005 Gregory Montoir` with **no permission grant**. It is
  therefore all rights reserved. **No code, structure, comment or identifier
  from it is in this port.** It may be read to *understand* something, but any
  fact so learned must then be confirmed in the GPL repository above and cited
  there.
- **[fgsfdsfgs/rawpsx][rawpsx]** applies its own MIT licence to code derived
  from `rawgl`, which it is not obviously entitled to do. It is genuinely useful
  prior art - a plain-C rendering of the VM - and it is still not a source to
  take from.

[rawgl]: https://github.com/cyxx/rawgl
[rawpsx]: https://github.com/fgsfdsfgs/rawpsx

This mirrors the discipline `wolf3d-next/docs/licence.md` already sets out:
where a GPL lineage of the same engine exists, this port takes from that one.

## What is NOT covered, and must never be

**No Another World data file is in this repository, and no data from the player's
files is in the binary.** Everything the game files hold - bytecode, polygons,
palettes, bitmaps, sounds, music - is read from the player's own copy. `data/` is gitignored, and so are the
converted blobs under `build/`, the polygon traces and the framebuffer dumps,
because all four are derived from that data.

The player's copy is the player's to account for. Another World remains on sale
(the 15th and 20th Anniversary Editions), and the DOS release this port reads is
not what either of those ships - they use `Data/Pak01.pak` and `game/`
respectively. The DOS **playable demo** uses the same format as the full game
(`MEMLIST.BIN` plus `BANK01`, `02`, `05`, `06`, `0D`) and is sufficient for every
measurement in `docs/`.

Two things the binary does embed come from the reference engine's source, not from
the game files, and both arrive under its GPL grant:

- the **8x8 font**, 768 bytes, extracted by dumping it from a build of the reference
  engine rather than transcribed, so there is no opportunity for a typo;
- the **string table** - the game's on-screen text - which the reference keeps in
  `staticres.cpp` and `tools/mkstrings.py` converts at build time
  (`build/strings.inc`). The text was written for the game, and the DOS data files
  do not hold it: every reimplementation of this engine carries it the same way.

Neither is in this repository: both are generated from the pinned reference clone,
which is a build product.

## The toolchain, which is borrowed too

`Dockerfile`, `compose.yml`, `tools/zrcp.py` and the three patches under
`tools/zesarux/` are copies from **wolf3d-next at commit `5a870c8`**, which is
also GPLv2 and also the author's own work.

**The three patches under `tools/zesarux/` are GPLv3, not GPLv2.** They change
ZEsarUX's own source (`src/datagear.c` and others), which is "version 3 of the
License, or (at your option) any later version" (its `src/LICENSE`, and the header
of each file). A patch to it carries its terms. The patches are applied inside the
toolchain container to build the emulator the checks drive; nothing from them is
in the game or linked with it. They are duplicated rather than
shared by submodule; `make toolchain-diff` reports drift. The Dockerfile header
explains why.

## Attribution

Another World, also released as Out of This World, is Eric Chahi's, published by
Delphine Software. This is an independent port of the engine to the ZX Spectrum
Next; it is not affiliated with or endorsed by Eric Chahi, Delphine Software,
DotEmu or ZX Spectrum Next Ltd.
