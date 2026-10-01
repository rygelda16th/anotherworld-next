# Plan: the 320x256 drawing mode

Written 2026-10-01, before any code. **Status, 2026-10-01: done.** W0-W4 built and gated (tags
`wide-w0` .. `wide-w4`, numbers in `preflight/wide320/README.md`); at W5 David made 320x256 the normal
build, with the build-time switch kept (tag `wide-w5`): `make asm` is 320x256, `make asm256` the
earlier 256x192 game, and the plain gates test the former, the 256-suffixed ones the latter.

| step | gate | result |
|---|---|---|
| W0 | the gameplay table | part index 3: 70% today; 320x256 projected 1-6 points slower |
| W1 | `make check-wide` | RefVideo320 identical to RefVideo at all 17 intro blits and to the engine's pages; 5 bitmaps identical |
| W2 | `make check-poly check-readmachine` | 64,000 of 64,000 pixels, every bucket; 17 real draws |
| W3 | `make check-intro` and the rest | all 17 intro blits, text, bitmaps, save, parts, resources; the 256x192 sweep (now `make check-*256`) unchanged |
| W4 | speed.py, measured-part | intro 100.3%; part index 3 71.8% (256x192: 72.4%), part index 4 81.1% (85.0%) |
| W5 | David plays it | 320x256 made the normal build (2026-10-01); the KS3 run is still owed |

Gate names are as they are since W5. Until then the 320x256 gates had a `320` suffix
(`check-poly320`, `check-intro320`, ...) and the plain names tested 256x192.

## Why

Today the game draws at 256x192. Every shape is scaled by 205/256 across and 246/256 down, so
five of the original's columns become four. Shapes one or two pixels wide then land on each other:
Lester's hair, face, neck and arm are drawn and painted over (David saw it in play, 2026-09-15 and
2026-10-01). The one-row rule (`RefVideo8.scale_record`, `rd_flat`) fixed shapes that vanished; it
cannot fix shapes that are covered.

Layer 2's 320x256 mode holds the original's 320x200 with no scale at all. Its cost is the memory
layout: a pixel is at `x * 256 + y`, ten 8K pages of 32 columns each. So a horizontal span steps
`inc h`, changes 8K page every 32 columns, and cannot go to the zxnDMA, which has no stride. A
screen page is 80K, not 48K.

## What is already known

`preflight/wide320/README.md` (`make measure-wide320`, `tools/wide320.py`):

- Over the whole intro, drawing costs **6.8 s more** of its 152 s (4.4 s with a 64-column window).
- The intro still ends on time in a simulation of `pace_blit`: **99.9%**, the same as today's build
  simulated the same way (CSpect measured 100.2%).
- The worst lag behind the original grows from **1.2 s to 1.7 s**.
- Gameplay frames get **0.15-0.3 ticks more** at the median and 1-2 at the 99th percentile,
  against a 4-tick frame. How busy those frames already are is NOT measured.
- Not counted: the sound interrupt's share of the extra time (about 7-7.5 s, not 6.8 s, on the Z80
  sound path), and the GUS card's own interrupt work (no Pi here).

## Rules for every step

- **A build switch.** `DEFINE WIDE320` picks the mode. Without it the build is today's, byte for
  byte. The 256x192 mode stays until 320x256 has passed W5.
- **Every existing gate still passes**, in the 256x192 build, at every step.
- **Pixel-exact against the reference**, as every drawing step has been.
- **The other session.** The GUS work (`docs/plan-pi-gus.md`) shares `src/aw.asm`, the Makefile
  and the tools. Before any step that touches them, tell it, and pull first.
- **Licence**, as `docs/licence.md`: facts from Fabien's GPL repository only, cited by file and line.
- **ZEsarUX gates depend on the three local patches** (`prescalar`, `readback`, `autorestart`).

## The steps

### W0. Measure gameplay, with the sound counted

- `tools/cspect/awidle.cs` on gameplay: start parts 3 and 4 with the synthetic player, and log
  each blit's busy time, as `tools/wide320.py idle` does for the intro.
- Add the sound interrupt's share: sample how often the interrupt is running (a second trap at
  the interrupt's exit, or the trampoline's count against the frame count).
- Re-run `project` for the intro and for gameplay.
- **Gate:** the numbers in a table in `preflight/wide320/README.md`: per part, blits late today and
  blits late in 320x256, and the worst lag.
- **Check-point (David): port or stop.** If stop, the plan ends here and costs nothing else.

### W1. A 320x200 reference

- `RefVideo320` in `tools/refvideo.py`: the engine's own geometry, one byte a pixel, no scale. Its
  span loops are `RefVideo8`'s; only W, H and the scale differ.
- Text with the original 8x8 font, 40 cells of 8 pixels (`video.cpp` drawChar, cited when written).
  `tools/mkfont6.py` is not needed in this mode.
- Full-screen bitmaps: `tools/mkassets.py` writes a column-major 320x200 page (80K) when asked,
  next to today's 256x192 one. Check it against the engine's own deplaner, as check-bitmap does.
- **Gate:** the reference replays the whole intro at 320x200 and matches the engine's own 4-bit
  pages, pixel for pixel, at every `check-intro` blit. (Gate A did the same for 256x192.)

### W2. The span and point code

- In `src/inc/raster.inc`, under `IFDEF WIDE320`: the row walk's clip for x up to 319, the strip
  instead of the band, the address `$E000 + ((x & 31) << 8) + y`, and the three fills - opaque,
  blend (0x10), copy from page 0 (0x11) - with the strip change every 32 columns. `draw_point` too.
- Start from `preflight/wide320/wide.asm`, which already paints correctly in ZEsarUX.
- The reader's vertex scale goes: `scale_*`, the `.fast_pt` and `.zlow` multiplies, and `rd_flat`
  are not assembled.
- `src/polytest.asm` and `tools/mkpolytest.py` get a 320 build.
- **Gate:** `check-poly` and `check-readmachine` pixel-exact in the 320 build; `check-span` reports
  the new per-span cost.

### W3. Into the game

- **The memory map.** Four pages of five 16K banks. A proposal, to be checked first: pages 0 and 1
  at banks 12-21 (8K pages 24-43), pages 2 and 3 at banks 96-105 (8K pages 192-211). Bitmaps need
  10 pages at `BMP_PAGE` 64, so the resource heap starts at 74, not 72 (74-169, below the stream at
  175). Page 11 (the GUS card) and 175-191 (the music stream) do not move.
- **As built** (src/aw.asm), not the proposal: the four pages are contiguous at banks 12-31 (8K
  pages 24-63; NextReg $12 = page * 5 + 12). The bytecode segment is at `CODE_PAGE` 64, the
  cinematic at `POLY_PAGE` 72, the ten-page bitmap scratch at `BMP_PAGE` 80, and the heap at
  `RES_FIRST_PAGE` 90 for 78 pages (90-167). It stops 7 pages short of the stream at 175,
  because `clear_code` (vmhost.inc) zeroes 8 pages from a load's first page; an ASSERT holds it there.
- **What the Pi card already claims** (from the GUS session, 2026-10-01; table in
  `docs/plan-pi-gus.md`), which this step must not break:
  - page 11 is the card's code and data, 125 bytes free: nothing else goes there;
  - the interrupt borrows MMU7 for page 11 while the card is on, and the card's sender borrows
    MMU2/MMU3 for the module's pattern; each reads the slot and puts it back. MMU7 is also the
    320 draw window, so the strip code must survive that, as the band code does today;
  - `$BACA-$BAFB` holds the card's gates, and 9 of the 16 free resident bytes are its hooks: new
    320 code goes in a page or in MMU6, not in the resident block;
  - the copper and the two line interrupts keep their meaning (`cop_half`, LINE_A/LINE_B): the
    card tells the frame's interrupt from the half-frame one by them. The screen mode must not
    change the copper list or the interrupt lines.
- **The screen.** NextReg $70 for 320x256, $12/$13 to the page's first bank, the clip window, and
  the picture's 200 rows placed in the 256.
- **Page work.** `aw_fill_page`, `aw_copy_page` and `present_bitmap` over ten 8K strips. The dirty
  rule (`dirty_band`) becomes per strip: ten bits, so `dt_dirty` becomes a word.
- **Text.** `aw_draw_string` with the 8x8 font; the text page holds it.
- **Save and load.** `sv_save`/`sv_load` write 40 strips, not 24. Old saves are refused, not misread.
- **Gate:** in the 320 build, `check-draw`, all 17 `check-intro` blits, `check-text`, `check-bmp`,
  `check-bitmap`, `check-save`, `check-part` and Gate D part 2 pass. In the 256 build, the full
  sweep passes unchanged.

### W4. Speed

- `tools/cspect/speed.py` on the whole intro, and W0's gameplay measurement again.
- Make the strip change cheaper if needed: the first version costs 318 T a crossing. A 64-column
  window (MMU6 and MMU7) halves the crossings, if MMU6 can be freed.
- **Gate:** the intro at 99.5% or more in CSpect, and gameplay no worse than W0's projection.

### W5. Play it

- **Check-point (David):** play the intro and some gameplay in CSpect, in both builds.
- Then on the KS3, with and without the Pi.
- If 320x256 is kept, it becomes the default build; the 256x192 code can go later, in its own step.

## What could stop it

- **W0's gameplay numbers.** If gameplay is already late in many frames, 0.2-2 ticks more may be
  too much. That is why W0 comes first.
- **Memory.** 320K of screen against 192K today. The map in W3 is a proposal; if it does not fit
  with everything else live, W3 stops there.
- **Real hardware.** The zxnDMA's speed and the memory timing at 28 MHz are the emulators'. The KS3
  decides.
