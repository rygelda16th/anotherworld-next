# What would Layer 2's 320x256 mode cost? (measured 2026-10-01)

David asked for this before any port: 256x192 merges five columns into four, so shapes a pixel or
two wide land on each other (Lester's head and arm). 320x256 needs no scale, but its memory runs
down the columns (`x * 256 + y`, ten 8K pages of 32 columns), so a span is `inc h`, crosses a page
every 32 columns, and cannot use the zxnDMA. This measures the cost; it changes nothing in the game.

    make measure-wide320                                       the machine half, then the intro's counts
    python3 tools/wide320.py idle build/wide320/idle.txt       busy time per blit, from CSpect (silent)
    python3 tools/wide320.py project build/wide320/intro.json build/wide320/coeff.json \
        build/wide320/idle.txt build/ref2614/frames.txt

## The three halves

1. **Counts** (`tools/wide320.py count`): the reference engine's traces replayed through the same
   polygon walk at both geometries, per blit: rows, pixels by fill mode, the spans today's build
   sends to the DMA, page crossings, and page-copy bytes under the machine's dirty-band rule (per
   32-row band today, per 32-column strip in 320x256).
2. **Prices** (`preflight/wide320/wide.asm`, `tools/wide320.py machine`): each layout's span entry
   and fill, timed in ZEsarUX as check-span does, every mode first checked pixel for pixel in
   physical RAM. Fitted per span, per pixel and per crossing.
3. **Busy time** (`tools/cspect/awidle.cs`): CSpect samples, at every interrupt, whether the game
   was waiting in `pace_blit`. That gives each blit's busy ticks, so the projection can re-run
   `pace_blit`'s deadline with the extra drawing added.

## Results

| T-states | a span | a pixel | a crossing |
|---|---|---|---|
| 256x192 opaque (CPU) | 173 | 8.8 | - |
| 256x192 blend | 92 | 17.1 | - |
| 256x192 opaque by the DMA | 483 | (4.0, CSpect's figure: ZEsarUX charges the DMA nothing) | - |
| 320x256 opaque | 184 | 9.2 | 318 |
| 320x256 blend | 207 | 14.5 | 414 |
| 320x256 opaque, 64-column window | 166 | 9.6 | 307 |

The whole intro (reference blits 5-2613):

| | rows | CPU opaque pixels | DMA pixels | crossings | copy bytes |
|---|---|---|---|---|---|
| 256x192 | 361,675 | 5.3 M | 3.2 M | 0 | 78.4 M |
| 320x256 | 398,114 | 11.1 M | 0 | 352 K (151 K at 64 columns) | 79.1 M |

- **Drawing costs 6.8 s more over the intro's 152 s** (4.4 s with a 64-column window).
- **The intro still finishes on time: 99.9%**, the same as today's build simulated the same way
  (speed.py measured 100.2%, so the simulation is within 0.3 points). The extra lands mostly in
  light frames that were waiting anyway; the heavy scene set-ups (blits 1935, 2371, 1258) get 3-5
  ticks heavier and are caught up inside PACE_DEBT's two seconds.
- **The pictures fall further behind in places**: the worst lag behind the original grows from
  1.2 s to 1.7 s (1.6 s at 64 columns), and the blits shown late from 528 to 730 (662).
- **Gameplay** (autoplay traces of part indexes 3 and 4): 0.15-0.3 ticks more a frame at the median,
  1-2 ticks at the 99th percentile, against the usual 4-tick frame. Gameplay's busy time on the
  machine has not been measured, so whether that tips frames into lateness is open.

## W0: gameplay, measured (docs/plan-wide320.md)

    make measure-wide320-isr                                   the interrupt's share, ZEsarUX
    python3 tools/wide320.py idle build/wide320/idle3.txt --part 3 --seed 8392 --blits 1600
    python3 tools/wide320.py project-part build/wide320/part3.json build/wide320/coeff.json \
        build/wide320/idle3.txt build/ref_gun3/frames.txt build/wide320/isr3.json

The gameplay traces are the probe's autoplay runs (`probe <data> 2000 2000 1 <index> 5`, in
`build/ref_gun3` and `build/ref_gun4`); the machine runs the same part with the same synthetic
player and seed in CSpect.

| | the original | today | 320x256 | 320x256, 64 columns | sound interrupt |
|---|---|---|---|---|---|
| the intro | 151.9 s | 99.9% (speed.py: 100.2%) | 99.9% | 99.9% | 2.6% +-1.0 |
| part index 3, autoplay | 257.6 s | **70.0%** | 68.8% | 68.9% | 4.8% +-1.3 |
| part index 4, autoplay | 167.5 s | 91.2% | 85.4% | 87.2% | 1.9% +-0.8 |

- **Gameplay is already slow on the machine today**: part index 3 runs at 70% of the original's
  speed and is waiting only 3.7% of the time. That is what David noticed in play. 320x256 does not
  cause it and would not fix it.
- **320x256 makes gameplay 1-6 points slower** (1.2 in part index 3, 5.8 in part index 4; 4.0 there
  with the 64-column window).
- The simulation of today's machine is within 2% of the measured time in part index 3; in part
  index 4 it is 7% optimistic (183.8 s simulated against about 197 s measured), so read part index
  4's figures as a lower bound on the time.
- The sound share is the Z80 path's (no Pi). With the GUS card on it is not measured.

## W1-W4: built, and measured again (2026-10-01)

The 320x256 build is `make asm320` (build/aw320.nex, the same sources with `-DWIDE320`); the
256x192 build is unchanged byte for byte. Its gates are `make check-wide check-poly320
check-readmachine320 check-intro320 check-text320 check-bmp320 check-save320 check-part320
check-res320`, every one pixel-exact against RefVideo320 or the engine's own pages.

| CSpect, emulated time | the original | 256x192 | 320x256 |
|---|---|---|---|
| the intro, blits 5-2613 (speed.py) | 151.9 s | 100.2% | **100.3%** |
| part index 3, autoplay (measured-part) | 257.6 s | 72.4% | **71.8%** |
| part index 4, autoplay (measured-part) | 167.5 s | 85.0% | **81.1%** |

    python3 tools/wide320.py measured-part build/ref_gun3/frames.txt build/wide320/idle3.txt build/wide320/idle320_3.txt

W4's gate holds: the intro at 99.5% or more, and gameplay no worse than W0's projection (part index
3 loses 0.6 points where 1.1-1.2 were projected; part index 4 loses 3.9 where 4.0 were projected for
the 64-column window). The first working build was nowhere near: **86.8%** on the intro. What took it
to 100.3%, each found by profiling the intro's worst stretch through awprobe's AWPROBE_PROF:

1. **The dirty rule off the row path.** band_set marked a strip dirty at every strip a span crossed and
   again at the next row's first; dirty_band and its unmirror loop were 28% of the time. A polygon's
   strips are now marked once, from its box (`dirty_box`), one column past the box's right edge -
   a point's offset can reach bbw where the box ends at ptx + bbw / 2 (check-intro320's blit 180, one
   pixel). 86.8% to 91.4%.
2. **Run entries as a byte sum** (the unrolled block inside one 256-byte page). 95.2%.
3. **Rows start from whichever end is mapped.** A span crossing strips leaves its last strip mapped,
   and the next row starts there, so each row is drawn left to right or right to left to match.
   96.4%, then 97.7% with a cheaper strip change.
4. **64-column strips**: two 8K pages side by side in the polygon segment's 16K window, which nothing
   reads while a polygon is drawn (the reader has the record by then and a parent maps its pages back
   after a child). Half the crossings. The copy fill reads page 0 through the bytecode window, MMU0
   and MMU1, both saved and put back by aw_draw_poly. 100.3%. Text keeps its own window (MMU7).
5. **The copy fill unrolled** (part index 4: 73.7% to 81.1%) and **the row's common path** - both
   edges under 256, y kept in L - for part index 3 (70.0% to 71.8%).

**What the 320x256 build still costs:** gameplay is 0.6-3.9 points slower than 256x192, from page
fills and copies that are 80K, not 48K, and spans the zxnDMA cannot fill. Gameplay was already slow
on the machine in 256x192 (72-85%), which the 320x256 mode neither causes nor fixes.

## What this leaves out, and which way it leans

- No 320x256 code was optimised: the crossing (318 T) is a first version.
- Left out, in 320x256's favour: no vertex scale at all, and fewer band/strip switches (14 K
  against 23 K).
- Left out, against it: the 0x11 copy-from-page-0 mode (0.1% of pixels), and full-screen bitmaps
  (80K a page instead of 48K: part 7 loads seventy).
- `ROW_T` (250 T a row) is an estimate from raster.inc's comments; 320x256 has 10% more rows.
- The DMA's cost per byte is CSpect's emulation; real hardware's is unknown.
- Memory: four 80K pages are 320K against 192K, on a 2 MB machine.
