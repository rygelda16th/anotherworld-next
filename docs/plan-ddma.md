# Plan: the zxnDDMA ("the blitter")

Written 2026-11-17, before any code. David's call the same day: "B" - the page fill first, then
measure the long-row fill and build it only if it wins.

| step | what | gate | result |
|---|---|---|---|
| D0 | find the zxnDDMA at boot (`ddma_have`) | ZEsarUX: 0, and every gate as before; CSpect 4.5.1.0: 1 | done: 1 in CSpect 4.5.1.0, both builds; the ZEsarUX sweep below |
| D1 | every DMA fill by the zxnDDMA's fill where it is there | `make check-ddma` (CSpect 4.5.1.0, Xvfb): the intro's screens the same with it on and off, and the fills really took the new path; ZEsarUX: the sweep, both builds | done: `check-ddma` 13 of 13 screens the same, 70 fills the new way (`check-ddma256`: 13 of 13, 1,783, the long spans included), none with it off |
| D2 | measure a 320x256 row by a 2D fill | a bench in CSpect 4.5.1.0: T-states a row, by length, against the CPU's 11 a pixel | **no price**: CSpect 4.5.1.0's 2D fill writes the wrong bytes (below) |
| D3 | only if D2 wins: long rows in 320x256 by the 2D fill | as D1, and speed.py | **not built**: D2 showed no win it can be trusted for; the KS3 can run the bench |

## Why

Core 3.03.00 gave the zxnDMA new commands (the core distribution's guide, `docs/zxnDDMA/zxnddma.gde`,
part 2.5; the KS3 runs 3.03.03). Two of them matter here:

- **Fill** (`$DF` bit 3, value by `$F7`): "no read; the $F7 value is written. Twice as fast as a
  fixed source address" (2.5). The game fills with a fixed source today (`dma_mem` with A = 1,
  `src/aw.asm`): WR1 and WR2 at cycle length 2, so 4 cycles a byte (guide 2.7: "At the fastest
  setting, 2 and 2, it takes 4"). A screen page is 81,920 bytes in 320x256: about 328,000 T-states
  a clear today, about 164,000 with the fill. **How often the game clears a page** (the reference
  runs' frames.txt, fill and copy per blit): the intro 72 in 4,000 blits, part index 3 46 in 2,000,
  part index 2's play 150 in 1,500 - and part index 4 1,628 in 2,000. Copies, which the fill does
  not help (a copy must read), are about one a blit everywhere. So the gain is part index 4's:
  about 4.8 ms of its 84 ms a blit, which at W4's measured 81.1% would make it about 85%; the
  others gain 0.1-0.6 ms a blit, under a point. These are the guide's cycle counts, not a
  measurement (see D2 for why CSpect 4.5 cannot give one).
- **2D with strides** (`$E3 $E7 $EB $EF`) and **physical addresses** (`$D7 $DB`). A 320x256 row is
  one byte every 256, across 8K pages: the reason plan-wide320.md gave for keeping the DMA off
  320x256 rows ("cannot go to the zxnDMA, which has no stride") is gone. What a 1-byte row costs is
  not in the guide, and the core's source for 3.03 is not public (the GitLab repository's head is
  3.02.03, `cores/zxnext/src/device/dma.vhd`, no 2D). So D2 measures it before anything is built.

The transparent colour, the hidden screen and Layer 2 X,Y are no use to a polygon filler.

## The rules every step keeps

- **Nothing depends on it.** `ddma_have` 0 is the game as it is today, byte for byte in what it
  draws and the order it draws it. Every core before 3.03.00, ZEsarUX (with its three local
  patches) and CSpect 3 take that path.
- **The probe is the guide's** (3.4, `zxnddma_compare.asm`): the zxnDDMA's bytes first and all
  under $80, eight DISABLEs, then one byte copied. A plain zxnDMA copies it to a CPU address in the
  resident code; a zxnDDMA, told the addresses are physical, copies it into a heap page that is
  empty at boot. The game reads the heap page.
- **The flags go down in the same OTIR.** The mode flags stay until `$C3` or the next `$DF` (2.6,
  notes 1). The copper upload and every other DMA programme assume a plain zxnDMA, so a fill
  programme ends `DISABLE, $DF 0` after its ENABLE: continuous mode holds the CPU until the block
  is done, so those bytes arrive after it. The fill runs inside `dma_busy`, so an upload that comes
  due waits as it does today.
- **The bus is held no longer than today.** Pages stay filled one 8K strip a programme, as now: a
  strip is ~16,000 T-states held instead of ~32,000.

## D1's gate, `make check-ddma`

CSpect 4.5.1.0 (`~/nextdev/cspect4`, the one emulator with the zxnDDMA) on Xvfb, no window, through
the nextdev-gui image. The intro, twice, from the same image: once as built, once with `ddma_have`
poked to 0 (AWPROBE_POKE). awprobe dumps the screen at fixed blit counts; the pairs must be the same
byte for byte. It also reads `ddma_have` (1) and `n_ddma`, the fills that took the new path (more
than 0 when on, 0 when off). What it saves is not measured there: see D2 for CSpect 4.5's charge for
a plain fill.

## D0 and D1 as built (2026-11-17)

- `ddma_probe` (page 10, called once from `start`) and `ddma_fill` (page 10, through `ddma_tramp`
  in MMU6 and `paged_call`: the 256x192 build's resident block had 6 bytes left). `dma_mem` sends
  every fill there when `ddma_have` is 1, so `aw_fill_page` and, in 256x192, `span_dma`'s long
  spans both take it. `n_ddma` is in MMU6: CSpect 4.5.1.0's plugins do not see bank 5 (pages 10
  and 11) at its physical address, though the CPU does.
- **The ZEsarUX sweep on the Deck**, both builds: every gate passes but four, and none for this
  change. `check-aw` and `check-aw256` fail their 5-second soak only (about 120 ticks for 250):
  ZEsarUX runs at about half speed on the Deck, and the build without this change fails it the
  same way (119). `check-parts` runs a host probe built for the Mac (`Exec format error`), and
  `check-sndcalls` wants `mcs` on the host. Both are the Deck's set-up, not the game.

## D2: the bench, and what CSpect 4.5.1.0 makes of it (2026-11-17)

`make measure-ddma` assembles `preflight/ddma/bench.asm` and runs it in CSpect 4.5.1.0 on Xvfb
(`tools/cspect/ddmabench.py`). Each test starts on raster line 0 and reads the line it ends on, the
guide's own method (`zxnddma_compare.asm`): a line is 1,792 T-states at 28 MHz. Three runs:

| test | lines | T a pixel or byte | the same in three runs |
|---|---|---|---|
| CPU, `ld (hl), a / inc h`, 64 spans of 64 | 26 | 11.4 | yes; 11 by the instruction count |
| zxnDDMA fill, 8,192 bytes (D1's) | 9 | 2.0 | yes; the guide's "twice as fast" as 4 |
| plain zxnDMA fill, fixed source, 8,192 bytes (today's) | 278 | 60.8 | yes; the guide gives 4 for cycle lengths 2 and 2 |
| zxnDDMA 2D fill, row length 1, stride 256: 64 spans of 64, 256 of 16, 13 of 320 | 8-20 | - | no |

**The 2D fills are wrong in CSpect 4.5.1.0, so its timings for them price nothing.** After 64
spans of 64, the bench counts the pixels in memory: spans 0-36 are whole and spans 37-63 are not
there at all. 256 spans of 16 stop at the same span, 37. 13 spans of 320 are whole, but 7,680 bytes
outside them are written as well. The same happens with the whole programme sent for every span
(no short reload), and with a 3,300 T-state CPU wait after every span, so this is not a transfer cut
short by the next one. The 2D timings also change from run to run (256 spans of 16: 7, 19 and 276
lines). Whatever the core does, this emulator does not do it, so the D2 rule - build D3 only if the
measure shows a win - leaves D3 unbuilt.

The plain fill's 60.8 T-states a byte is CSpect 4.5.1.0's own charge, not the core's (the guide: 4).
So the game's speed in CSpect 4.5 with the zxnDDMA on against off would overstate D1's gain by
that much, and it is not given here. D1's gain from the guide's figures is about 164,000 T-states a
320x256 page clear (81,920 bytes at 4 cycles, against 2).

## Open for the KS3

The bench (`build/ddmabench.nex`) on the machine: whether a 2D fill of 1-byte rows writes what it
is told, and what it costs. Today it leaves its numbers in memory only, for awprobe. How long a fill
takes on metal, and whether the sound (copper DAC, or the Pi card) stumbles with
the zxnDDMA on that does not with it off. The off switch for a player is a build without it, or a
core before 3.03.00.
