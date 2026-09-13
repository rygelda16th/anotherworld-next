# Where things stand

**This file is canonical.** Where it disagrees with anything else, including the
published blueprint at
`claude.ai/code/artifact/f4d9e319-0bbb-47c3-b675-3efd6413f0a3`, believe this one.
The blueprint is the shareable version of the same material and is kept in step,
but it is a copy.

Last updated 2026-09-13.

---

## The short version

An Another World engine port to the ZX Spectrum Next. The virtual machine will be
plain C compiled with z88dk; the polygon rasteriser is Z80N assembly, and after
measurement that is the **only** thing that needs to be.

| Phase | State |
|---|---|
| Scoping, seven decisions | **done**, five confirmed, one amended, one rejected |
| A - asset pipeline and reference rasteriser | **done**, Gate A passed |
| B - toolchain | **done**, Gate B passed |
| C - rasteriser core | **done**, Gate C passed |
| C - polygon reader, vertex scale, register allocation | outstanding |
| D - the virtual machine | not started |
| E - pacing, input, sound | not started, and sound is unscoped |

Nothing here is a guess unless it says so. Every number was measured on the
machine, on the host, or read out of a pinned source and cited.

## Run it

    make doctor        both toolchain images, with versions and a smoke compile
    make check-data    Gate A: every resource decodes and its CRC cancels
    make check-ref     Gate A: the reference matches the real engine byte for byte
    make assets        convert palettes and bitmaps to Next form
    make check-span    step 0: what one polygon span costs
    make check-cc      Gate B: C calls assembly at a fixed address and returns
    make check-poly    Gate C: the rasteriser, pixel-exact vs the reference
    make toolchain-diff  has the shared toolchain drifted from wolf3d-next?

`make check-ref` and `make check-poly` need the host probe built and run first;
see `preflight/hostprobe/README.md`.

---

## The seven decisions, and what happened to them

All seven were David's, resolved before any code. Verdicts after measurement:

| | Decision | Verdict |
|---|---|---|
| 1 | 256x192 at 8bpp | confirmed, and the argument is stronger than stated |
| 2 | store the low nibble, offset the palette | confirmed and **extended** |
| 3 | zero-copy page flip | **amended** - two corrections, one load-bearing |
| 4 | map 48K of Layer 2 via `$123B` | **rejected** - right conclusion, wrong route |
| 5 | DMA with a span threshold | **amended**, then refuted by measurement |
| 6 | sjasmplus stays master | confirmed, but its premise was false |
| 7 | separate repo, shared toolchain | confirmed - duplicate with a drift check |

### 1. 256x192, 8bpp

Both Layer 2 layouts are as the wiki describes: 256x192 is divided horizontally
into three 16K banks of 64 lines, so a horizontal span is contiguous; 320x256 is
divided vertically into five banks of 64 columns, so consecutive bytes step in Y.

The brief rested this on zxnDMA having no stride, which is true - the wiki gives
only "Port A address decrements / increments / is fixed" and the same for port B -
but it is the weaker half of the case and is not needed. In 320x256 a span steps
256 bytes per pixel **for the CPU too**, and crosses a bank every 64 pixels of X.
In 256x192 a span is `inc l`, wraps inside its own line for free because a line
is exactly 256 bytes, and can never cross anything. Since spans turn out to be
CPU work (decision 5), the CPU argument is the one that decides it.

The retraction of "256x192 distorts the vector art" was right. See the memory map
for the scale, which is a vertex transform and costs nothing per pixel.

### 2. Low nibble plus palette offset - and there are TWO palettes

`NextReg $70` bits 3-0 are a palette offset "added to top four bits of pixel
value". With the game's 4-bit index in the low nibble and the top nibble clear,
the offset selects one of sixteen 16-colour palettes.

**Layer 2 has two 256-entry palettes, not one.** `NextReg $43` bit 2 selects which
is displayed; bits 6-4 select which one `$40`/`$44` write to. 512 entries is
exactly the 32 palettes an `RT_PALETTE` resource holds, so **every palette a part
can ask for stays resident and `op_setPalette` is two register writes with no
upload, ever.**

Verified in the emulator's own source as well as the wiki:
`tbblue_palette_layer2_first[256]` and `_second[256]`, selected by
`tbblue_registers[0x43] & 4`, with `palette_offset = (reg112 & 15) * 16` added to
the pixel index.

Two further consequences, both in our favour:

- **The blend mode needs no special handling.** `drawLineBlend` sets bit 3 of each
  pixel, which at 8bpp is `or 8` on a byte. The game's palettes already carry the
  blended variants at entries 8 to 15.
- **All three fill modes lose their end masking.** At 4bpp every span masks a
  half-byte at each end; at 8bpp every span is whole bytes.

One precision to keep: the wiki says the offset is added to the *top four bits*,
so on hardware the add is nibble-local and wraps in four bits, while the emulator
implements a plain add. Both agree for us because our top nibble is always zero.
Do not start storing values above 15.

### 3. Zero-copy page flip - and `$13` is the draw-page selector

The conclusion is right: a flip is a register write, never a 48K copy. Two things
in the supporting text were wrong.

**"NextReg $13 is the paging shadow register and is a different thing" is the
wrong way round.** It *is* the paging shadow register, and that is exactly why it
matters: when `$123B` bit 3 is set, the mapped window writes to the bank named by
`$13` while `$12` still drives the display. wolf3d-next's own renderer already
does this - `init_buffers` sets `$12`=8 and `$13`=11 with `L2_SHADOW` in
`l2_bits`, and `flip_buffers` exchanges them.

**There is no 3-bank alignment requirement.** Both registers are 7-bit bank
numbers since core 3.0, so a screen may start at any bank 0 to 127. All that is
needed is three consecutive free banks.

The genuinely new behaviour is **tearing**. The original hands a finished buffer
to `sys->updateDisplay`, which copies it; zero-copy shows the page live, and
`op_selectVideoPage` can select the page currently displayed. Instrument it
rather than design it away - the Amiga displayed its buffers directly too.

Note that under the MMU route (decision 4) `$13` becomes irrelevant, because the
draw page is then chosen by MMU page number and only `$12` is touched. That is
the route taken.

### 4. The `$123B` 48K window - rejected, and the conclusion stands anyway

The suspicion was right: a frame's rasterising needs no per-span banking, so
"assembly for MMU page switching" is dead. But `$123B` bits 7-6 = 3 is the
expensive way to get there.

- With the whole 48K mapped and bit 0 set, **every write below `$C000` is
  redirected**. Stack, IM2 vector table, interrupt variables and all C data would
  have to move above `$C000`. For scale: wolf3d-next's handler writes to
  `$BEB3`-`$BEB7` and its stack is at `$BFF0`; both would vanish into the
  framebuffer.
- **Whether zxnDMA honours the redirect is not documented.** The wiki's DMA page
  says nothing at all about Layer 2, `$123B` or the MMU. The emulator *does*
  honour it, since the DMA moves bytes through `poke_byte_no_time` and the tbblue
  poke checks `tbblue_write_on_layer2()`. So a DMA fill through the window would
  work headless and might not on hardware.

**The route taken instead: one 8K page in one MMU slot.** 8K is 32 scanlines, so a
span can never cross it and a full-height polygon crosses at most five
boundaries. Cost is one `nextreg` per band. Layer 2 pages are ordinary RAM, so
the DMA works natively, and nothing behaves differently on hardware.

    ; the recommended route, as implemented in src/polytest.asm
    ; page P's first 8K page is (BASE_BANK + P*3) * 2 ; band = y >> 5, 0..5
    nextreg NR_MMU3, (BASE_BANK + P*3)*2 + band
    ; pixel address: HL = $6000 + ((y & 31) << 8) + x

### 5. DMA for spans - refuted by measurement

Page fills and copies must be DMA; that stands. But the setup cost is larger than
the brief implies and, once priced, **DMA is the page mechanism and the CPU is the
span mechanism.**

`src/dmatest.asm` in wolf3d-next gives the setup exactly: a 16-byte DMA program
pushed with `otir`, which is 331 T-states for the `otir` alone, about 380 with the
call wrapper, and about **430 once the destination and length are patched per
span**.

Filling one 49,152-byte page (note: 49,152, not the original's 32,000, because
that is 4bpp):

| method | T/byte | T-states | % of a 560,000 T refresh |
|---|---|---|---|
| zxnDMA | 1.87 | 91,914 | 16.4% |
| PUSH fill | 5.75 | 282,624 | 50.5% |
| unrolled stores | 11 | 540,672 | 96.5% |
| LDIRX / LDPIRX | 16 | 786,432 | 140% |
| LDIR | 24.95 | 1,226,342 | 219% |

The CPU comparison should use the measured PUSH figure, not 11 T/byte, which
makes the DMA's margin **threefold, not sixfold**. The conclusion is unchanged
because half a refresh per page operation is still unusable.

**For spans, measurement settles it and the answer is stronger than a threshold.**
Over 469,537 real spans the mean is about 22 bytes and 87.6% fall below the
47-byte crossover. A 22-byte span costs roughly 240 T on the CPU against 430 T of
DMA setup alone, so the DMA path would be two to three times *slower*. **Build no
DMA span path.**

**The figure everything else rests on is emulator fiction.** 1.87 T/byte is
`datagear.c:601` pacing every transfer at a hardcoded two T-states a byte
regardless of the prescalar. The wiki gives no per-byte figure either - only that
the DMA "operates at the same speed as the CPU" - so there is nothing to check it
against but hardware. Until a KS3 says otherwise, carry the PUSH fallback at 5.75
T/byte as the planning figure. Exposure is now small: the port uses no DMA for
spans, so only the once-a-frame page copy touches it, and that fits even at the
pessimistic rate.

### 6. sjasmplus master - confirmed, premise false

Take (b): z88dk compiles C to a raw binary at a fixed ORG, sjasmplus `INCBIN`s it.

- **One `INCBIN` is enough.** The earlier Wolf3D preflight emitted
  `doors_CODE.bin` at 4,704 bytes from `$8000`, reaching `$9260`, with a BSS
  symbol at `$925C` - code, data and BSS contiguous in one file.
- **The shim is about forty lines.** `tools/mkexp.py`. Run against that real map it
  reduced 5,711 symbols to 188 public addresses with every address matching.
- **Neither tool looks up a symbol in the other's output.** C calls assembly
  through a jump table at `$8000`, an address fixed as the bottom of the sjasmplus
  image, declared to the C side by a two-line `defc` stub. sjasmplus calls the C
  at `CRT_ORG_CODE`, which is where the runtime's entry lands - the map confirms
  `__Start = $A000` for `CRT_ORG_CODE=0xA000`. One pass of each tool, C first.

**But "build z88dk from source" was wrong, from a premise that no longer holds.**
See the toolchain section below.

### 7. Separate repo, shared toolchain

Duplicate five files with a header naming the upstream commit, plus
`make toolchain-diff`. Not a submodule (drags a 28,000-byte Makefile and a whole
game for five files), not a published base image (there is nowhere to publish to,
so the commit pinning the numbers depend on would be lost).

As it turned out the Dockerfile is very nearly a straight copy, because z88dk did
not end up living in it at all. So the drift check is genuinely meaningful, and it
reports no drift on all four shared files.

---

## The toolchain

Two images, deliberately.

**`aw-next-tools`**, from this `Dockerfile`: sjasmplus, hdfmonkey and a patched
headless ZEsarUX, all pinned to the same commits wolf3d-next uses. Nearly a
straight copy of that project's file.

    SJASMPLUS_REF 8c87edd    HDFMONKEY_REF 76d400f    ZESARUX_REF f02514f
    + tools/zesarux/{prescalar,readback,autorestart}.patch

**`z88dk/z88dk:20260907`** for the C step only.

    digest sha256:3ef9ff8b174df4f9dfcae11b07763a5535168119a301cbdad4a52c8f30ce9782

Two findings behind that split, and both correct earlier beliefs:

- **The prebuilt z88dk image is not amd64-only.** An `aarch64` variant exists and
  carries the patched sdcc. It is named **`z88dk-zsdcc`**, not `zsdcc` - every
  binary in that image is `z88dk-` prefixed, so a check for the bare name wrongly
  reports it missing. Rosetta was never required.
- **z88dk cannot be built from source on bookworm at all**, and not for the reason
  the risk list gave. SDCC refuses to compile its Z80 register allocator against
  Boost below 1.79 (SDCC bug #3772) and bookworm ships 1.74. That fails
  identically on amd64. bookworm-backports is also 1.74; only trixie carries
  1.83. A base-image constraint wearing an architecture problem's clothes.

The prebuilt image is Alpine and musl-linked, so its binaries cannot be COPYed
into the glibc image - hence a separate container rather than a build stage.

**Fallback if that image ever disappears:** a from-source build with
`BUILD_SDCC` unset builds cleanly and yields sccz80 instead of zsdcc. Verified.
Adequate here, because the VM's worst measured frame dispatches 96 opcodes
against a 280 budget.

---

## The data

The English PC DOS release. **No game data is in this repository and none is in
the binary**; `data/` is gitignored, and so are the converted blobs, the polygon
traces and the framebuffer dumps, because all three are derived from it. See
`docs/licence.md`.

The archive it came out of was three layers deep, which is worth knowing:

    000111_another_world.7z
      -> disk1.img            1,474,560 bytes, a raw FAT12 1.44MB floppy
         -> AWORLD.EXE        an LHA self-extracting archive, "LHA's SFX 2.13S"
            -> 23 members     MEMLIST.BIN, BANK01..BANK0D, ANOTHER.EXE, ...
            -> plus INSTALL.BAT and LHA213.EXE beside it on the disk

macOS has no `7z`, but `bsdtar` reads both 7z and lzh. The SFX needs carving:
find the first `-lh5-` tag and back up two bytes to the LHA header.
`tools/fat12.py` reads the floppy image without mounting anything, which avoids
fighting a managed Mac over permissions.

**Verified canonical, four independent ways** (`make check-data`):

| | |
|---|---|
| resources before the sentinel | 146 |
| compressed, CRC cancelling to zero | 118 |
| stored, length matched | 28 |
| lengths disagreeing with `MEMLIST.BIN` | 0 |
| sizes disagreeing with the published table | 0 |
| entries whose packed extent runs past its bank | 0 |
| banks total | 1,153,105 bytes |
| decoded total | 1,730,258 bytes |
| sha256 of the decoded set, in id order | `07292206da633b4e1f3b9fb9609cfa85b502c68f86d6b40a7e0ba5ab2531cd28` |

The bank total was **predicted** at 1,153,946 bytes from the published per-resource
table before anything was opened, which is 0.07% out. That was a blind prediction,
not a fit.

The CRC is the check that matters: the packer XORs every reservoir word into a
running value and a correct stream ends at exactly zero, so a tampered or
truncated bank cannot pass by accident. That is what let a dump labelled
"Unverified" be verified rather than trusted.

### Corrections to the facts the scoping started from

| Claim | Finding |
|---|---|
| 64 threads, 256 variables, doubled request arrays | confirmed |
| requested values applied between frames | confirmed, in `checkThreadRequests()` before `hostFrame()`; `0xFFFE` in a requested PC means "make inactive" |
| `_scriptStackCalls[64]` is per-thread call state | **wrong, and it changes the struct.** One shared 64-entry scratch stack whose pointer `hostFrame()` resets for every thread it runs, so **a call cannot survive an `op_pauseThread`**. `op_call` also tests for overflow at `_stackPtr == 0xFF` on a 64-entry array, 191 entries too late |
| 27 opcodes `0x00`-`0x1A`, guarded | confirmed |
| bit 7, then bit 6, then the table | confirmed; each polygon branch ends in `continue`, so the table is never reached for them |
| 4 pages, `VID_PAGE_SIZE` 32,000 | confirmed. The *displayed* page is always `_curPagePtr2` |
| palette is `0x0RGB`, the "565" comments are wrong | confirmed twice over; `changePal` rejects ids >= 32 so only the first kilobyte (VGA) is ever read |
| 13 banks, lowercase `bank01`..`bank0d` | confirmed, but the case worry is misplaced: `File::open` already tries lowercase then uppercase. Moot for us anyway, since decompression happens on the host |
| 146 resources, 120 compressed, 26-28 uncompressed | **146 is right; the split is 118 and 28**, counted by `packedSize != size` on the real file. "26-28" bracketed the truth; the 120 was high |
| terminated by a sentinel | confirmed, `MEMENTRY_STATE_END_OF_MEMLIST` = `0xFF` |
| one entry has no type | confirmed: id `0x11` carries **type 6**, outside the six named constants. It is the 25,108-byte player and enemy polygon set every action part loads. Any switch on type must cope |

Also found, and not in the original list: **`calcStep` takes `dy` by reference and
the original calls it twice, so the second call overwrites it.** The loop height
comes from the *second* edge. For a well-formed trapezoid both are equal, which
is why taking the first passed every frame of a 64,897-polygon trace, but it is
not what the original does.

### The three sizes that shape the memory map

| Segment | Largest | Part |
|---|---|---|
| bytecode | 62,683 | 5 (res `0x21`) |
| cinematic polygons | 65,230 | 2 (res `0x19`) |
| player/enemy polygons | 25,108 | res `0x11`, shared |
| **worst concurrent set** | **152,923** | part 5, so **10 banks of 16K** |

Both segments are addressed by 16-bit offsets, so each is at most 64K by
construction.

---

## Memory map

The 2 MB profile: 1,792 KiB usable, 8K pages 0-223, 16K banks 0-111. The `.nex`
must ask for it - `SAVENEX CFG 0, 0, 0, 1`, the fourth argument.

### 16K banks

| Banks | 8K pages | Holds | `$12` / `$13` |
|---|---|---|---|
| 0-7 | 0-15 | the classic 128K, left alone | |
| 8-11 | 16-23 | free; keeps clear of bank 8, which holds NextBASIC warm-restart variables | |
| 12-14 | 24-29 | Layer 2 **page 0** - the background source for fill mode `0x11`, and where full-screen bitmaps land | 12 |
| 15-17 | 30-35 | Layer 2 **page 1** | 15 |
| 18-20 | 36-41 | Layer 2 **page 2** | 18 |
| 21-23 | 42-47 | Layer 2 **page 3** | 21 |
| 24-39 | 48-79 | part data arena, 256 KiB against a 149 KiB worst case | |
| 40-111 | 80-223 | free | |

Banks 5, 7 and 8 are avoided as the wiki asks. For the record, wolf3d-next
displays from bank 8 without trouble because it never returns to BASIC, so the
warning is about warm restart rather than about the memory.

### The 64K address space

| MMU | Range | Holds |
|---|---|---|
| 0-1 | `$0000`-`$3FFF` | ROM, for esxDOS calls; a 16K part-data window between loads if wanted |
| 2 | `$4000`-`$5FFF` | part-data window, or the copy mode's source band |
| 3 | `$6000`-`$7FFF` | **Layer 2 draw window** - the 8K page holding scanlines *y*..*y*+31 |
| 4-7 | `$8000`-`$FFFF` | the program: jump table, C code, data, BSS, VM state, IM2 table and handler, stack |

    pixel address   HL = $6000 + ((y & 31) << 8) + x
    band            y >> 5, 0..5, one nextreg on change

### The vertex scale

320x200 and 256x192 fill the same 4:3 screen, so the geometry is reproduced and
only sampling resolution is lost. The scale is a vertex transform and folds into
the multiply the engine already does for zoom, so it costs nothing per pixel.

**The exact arithmetic is part of the specification**, because the Z80 must
reproduce it bit for bit:

    x' = (|x| * 205) >> 8, sign restored      205/256 = 0.80078
    y' = (|y| * 246) >> 8, sign restored      246/256 = 0.96094

Magnitude-then-sign rounds toward zero for negatives, which is what a Z80 doing
`abs, multiply, negate` naturally produces. A plain arithmetic shift would floor
instead, and the two disagree on every negative odd value. Both extremes land
exactly: 319 to 255, and 199 to 191.

### VM state, all resident

    vmVariables        512 bytes   int16_t [256]
    threadsData        256         uint16_t [2][64]  PC, requested PC
    vmIsChannelActive  128         uint8_t  [2][64]  state, requested
    scriptStackCalls   128         uint16_t [64] - ONE shared stack
    polygon buffer     ~256        50 points, bbw, bbh, numPoints
                     -------
                     ~1,280 bytes

The claim in wolf3d-next's `preflight/README.md` that space rather than speed is
the real constraint looks much weaker here: there is no raycaster holding
`$8000`-`$A500`, resident VM state is under 1.3 KB, and the C image gets 32K. Read
the actual size off the Phase B build, which reports its ORG and end address for
nothing.

---

## What has been measured

### On the host, over real bytecode

12,000 frames through a headless instrumented build of the reference interpreter,
reaching the intro cinematic and the first gameplay part by natural progression.

| Per VM frame | Intro mean | Gameplay mean | Worst seen | Budgeted |
|---|---|---|---|---|
| opcodes dispatched | 20.9 | 13.5 | **96** | 280 |
| polygons filled | 20.3 | 1.3 | 270 | |
| spans drawn | 152 | 7.6 | **4,004** | |
| `fillVideoPage` | 0.02 | 0.00 | 2 | 1 |
| `copyVideoPage` | 0.82 | 1.00 | 2 | 1 |

Span lengths over 469,537 spans: mean about 22 bytes at 256 wide, 87.6% below 47
bytes, 96.1% below 111.

**Conclusions.** The VM is not the problem and C is safe - 96 opcodes at 400 T is
under 7% of a refresh, so even a fourfold miss on compiled C fits. The rasteriser
is the entire cost. Page operations are cheaper than budgeted: a copy about once a
frame and a fill almost never, so about 16% of a refresh rather than 32%.

**Caveats.** Only two parts were reached and no input was fed, so Lester never
moved and the gameplay means understate real play. Design against the worst-frame
column. The intro is genuinely the polygon-heavy case.

### On the machine

`make check-span`, measured with a null mode so the harness subtracts its own
loop, and the span length set at run time so cost per byte is *fitted* over seven
lengths rather than inferred by dividing one figure.

| Fill mode | Measured | Theoretical | At 22 bytes |
|---|---|---|---|
| unrolled `ld (hl),a / inc l` | 10.74 T/byte + 81 | 11 | 317 T |
| PUSH | 5.36 T/byte + 133 | 5.5 | **240 T** |
| blend, `set 3,(hl)` loop | 32.22 T/byte | 32 | 621 T |
| copy from page 0, loop | 37.56 T/byte | 37 | 751 T |

Every mode lands within a fraction of a T-state of its hand-computed cost, which
is the evidence that the harness measures what it claims.

    per-span overhead                433 T   (63% of a span)
    cheapest opaque fill at 22 bytes 240 T
    PER SPAN, end to end             672 T
    worst frame, 4,004 spans         2,692,379 T = 4.81 refreshes

**The budget.** A VM frame is the script's pause-slice variable times 20 ms, and
the scripts use 1 to 5, so the budget is 560,000 to 2,800,000 T-states. The worst
frame fits a five-slice pause with about 4% spare. Passing, not comfortable.

**Where the margin is**, in order of return: hold the four accumulator words in
registers across a trapezoid instead of loading and storing them per scanline,
which is most of the 433 T; and unroll the blend and copy fills as the opaque one
already is, taking blend from 32 to about 19 T/byte and copy from 37.5 to about
24. Both are techniques already measured here, not guesses.

**Stores versus PUSH cross at 12 bytes**, and 88% of real spans are longer, so the
fill should be PUSH with a store fallback below that.

### Palette loss

Nine palette resources, 32 palettes of 16 colours each, RGB444 down to RGB333.

Globally 395 of 679 distinct colours collapse, which sounds alarming and mostly
reflects palettes sharing colours with one another. Within a single 16-colour
palette, which is what actually costs a scene a distinguishable colour:

| Colours lost within one palette | Palettes | |
|---|---|---|
| 0 | 128 | 44.4% |
| 1 | 101 | 35.1% |
| 2 | 43 | 14.9% |
| 3 to 5 | 16 | 5.6% |

Worst case loses five of sixteen. A quantiser that nudged colliding entries to
adjacent RGB333 values would trade a little hue error for separation, at no
run-time cost. **That is a fidelity call and David's to make**, like coarse detail
and pixel doubling were on the other project.

---

## Phase A - done, Gate A passed

Three parts, all host-side.

1. **`tools/bytekiller.py`** - the decompressor, ported from `bank.cpp`. It reads
   its input backwards from the end, writes its output backwards, shares one
   buffer between the two, and carries a 32-bit reservoir with a sentinel bit
   plus a running CRC that must cancel to zero.
2. **`tools/mkassets.py`** - 32 palettes into the two Layer 2 palettes; the twelve
   planar full-screen bitmaps deplaned exactly as `Video::copyPage(const uint8_t*)`
   does it and resampled to 256x192. The resampling is nearest-neighbour and that
   is not laziness: the data is palette-indexed, so averaging two neighbouring
   pixels would average their *indices* and produce an unrelated colour.
3. **`tools/refvideo.py`** - the reference video layer, and **the specification**, in
   the same sense that wolf3d-next's `tools/raycast_ref.py` is for the walls. The
   machine matches this, not the other way round.

**Gate A, both halves passed.** Every resource decodes with its CRC cancelling
(above), and the reference reproduces the real engine's four framebuffers **byte
for byte**:

    2,750 frames   64,897 polygons   12,954 glyphs   2,283 copies   72 fills
    page 0 IDENTICAL   page 1 IDENTICAL   page 2 IDENTICAL   page 3 IDENTICAL

### Two things Phase A taught

**The trace is also the Phase C test vector.** Rather than tracing only polygons,
the probe records every video operation - polygon, glyph, page fill, page copy,
page select, blit - with **raw** operands, so the replayer must resolve `0xFE` and
`0xFF` the way the original does. The same file is replayed on the Next, which
makes Gate C mechanical rather than a judgement call.

**The reference needed a piece the plan had not listed.** It diverged at 64,897
polygons on 611 bytes across fourteen short rows in colour 12. That is text:
`drawString` is part of the video layer. Glyph rendering is now traced and
implemented, and the font is **dumped from the engine** rather than transcribed,
so there is no chance of a typo in 768 bytes.

---

## Phase B - done, Gate B passed

| Check | Result |
|---|---|
| assembly reached its handover to the C | `0xA5` |
| the C is running, its counter advancing | yes |
| C to assembly, argument intact at a fixed address | `0x5AA5` |
| assembly to C, return value correct | `0x2222` |
| shared toolchain files drifted from wolf3d-next | 0 of 4 |

`make check-cc`. The findings are in the toolchain section above.

One trap: sjasmplus and the shim both want to write `<name>.exp`, so the C symbols
were silently overwritten by the assembly's until the C's gained a `_c` suffix.

---

## Phase C - rasteriser core done, Gate C passed

The trapezoid walk, all three fill modes, the degenerate point case, clipping on
all four edges and the 8K band window are on the machine and **pixel-exact:
49,152 of 49,152 bytes**, over 57 polygons taken from a real trace and picked for
coverage. `calc_step` is separately exhaustive at **648 of 648 cases**.

`make check-poly`.

### Still outstanding in Phase C

- the polygon reader: both opcode forms, including the five nested conditionals
  over the bit-6 opcode's low bits, and the child hierarchy with its saved
  program counter
- the vertex scale on the machine (the arithmetic is specified above)
- the register allocation that attacks the 433 T of per-span overhead

All three are now protected by the test vector, which is what makes them safe to
attempt rather than hopeful.

### Six faults, and one was in the specification

1. **The bounding-box rejection was inverted for the equal case.** The original
   tests `x1 > 255`, so `x1 == 255` is on screen. The comment beside the wrong
   code said "equal is fine".
2. **`srl a` leaves the shifted-out bit in carry**, and the following `sbc hl,de`
   consumed it, so an odd bounding-box width subtracted one too many.
3. **The band was computed as `(y >> 3) & 7` instead of `y >> 5`.** Three `rrca`
   leaves bits 3 to 5 in the low bits; **three `rlca`** brings bits 5 to 7 down,
   which is what `y >> 5` means for a byte. The window therefore moved every 8
   scanlines instead of every 32, which shows up as "the first eight rows are
   perfect and then nothing". The same fault was in `src/span.asm` from step 0, so
   the step 0 figures were re-measured afterwards.
4. **`point_x` and `point_y` clobber D**, because they build their index in DE, and
   the first point was being held in D across the second call. **Every negative
   run computed as zero.**
5. **The two edges cross, so a span can be backwards.** The original takes the
   minimum and maximum inside each `drawLine`; without that the length underflows
   and paints the entire 256-byte row. It appears only on the last rows of a
   sliver, where the accumulators finally overtake one another.
6. **The sixth was the reference's, not the machine's.** Parameterising the
   reference's geometry replaced a clamp's assignment but not its condition, which
   still read `if sx2 > 319` in the 256-wide mode, so a span reaching 257 went
   unclamped and spilled two pixels into the next row. The machine had been right
   about that shape all along.

### What actually finds rasteriser bugs

Not the 49,152-byte comparison, which only ever says that something is wrong.

- **A bisect over the polygon count.** The program takes a limit and the checker
  halves it, so a failure is attributed to one named shape in six reboots. Every
  fault above was diagnosed that way.
- **A unit test for `calc_step`.** Its first version used `p1 = 0` in every case,
  which made the clobbered-register bug invisible - **zero is the one value that
  corruption and the truth agree on.** Widened to vary both points, it went from
  60 of 110 to 648 of 648.
- **The assembler's warnings.** `ld b, 648` truncated to 136, so 512 unit-test
  cases silently read back as zeros and looked like an arithmetic fault.
  sjasmplus said so in a warning. This is wolf3d-next's "grep the build for
  warnings, not just errors" arriving on schedule.

---

## What is next

**Phase D, the virtual machine**, is unblocked and has everything it needs.

1. the scheduler in C: the doubled request arrays applied between frames, and the
   shared 64-entry call stack whose pointer resets per thread
2. the 27 table opcodes, plus the two polygon dispatches calling into Phase C
3. resource loading over esxDOS from the Phase A blobs, and part switching

Gate D: `make check-boot` - the thread table matches `initForPart` exactly
(thread 0's PC at 0, every other thread inactive at `0xFFFF`, all channel states
zero), thread 0's PC advances between two reads, and then the intro renders.

Phase C's three outstanding items can be done before or alongside D; the reader is
a prerequisite for the intro actually rendering.

---

## Risks, worst first

1. **The worst frame clears its budget by about 4%.** 4,004 spans at 672 T is 4.81
   refreshes against a five-slice pause. That 4,004 came from one run over two
   parts with no player input, so a busier frame elsewhere would not fit. Both
   known optimisations are measured techniques rather than guesses. Separately,
   extend the host probe with scripted input to find a genuinely worst frame.
2. **Sound is entirely unscoped.** 103 sound effects and three music resources
   against three AY chips and a DAC. No estimate, no design, no measurement. It is
   the easiest thing to postpone, which is how it comes to be underestimated.
   Cheapest first step: decode one music resource and one effect on the host and
   look at what they actually are, before assuming wolf3d-next's mixer transfers.
3. **32K may not hold the C image.** `actors.c` was 5K of code and 10K with data,
   for one state machine. The fallback is the banked-call plumbing this port hoped
   to avoid. Read the size off the build, which reports it for nothing.
4. **Hardware divergence from the emulator**, deliberately minimised rather than
   solved. The MMU window means nothing depends on whether the DMA honours
   `$123B`; dropping the DMA span path means nothing depends on the suspect 1.87
   T/byte. Only the once-a-frame page copy still touches it. `make check-dma` on
   the KS3 when it arrives.
5. **IY under `-clib=sdcc_iy` against esxDOS calls.** The library reserves IY and
   DOS calls may destroy it. Never exercised, because no preflight program has
   opened a file. One C program that opens a file through the assembly loader and
   then reads a global settles it; the fix is `sdcc_ix` or saving IY.
6. **Dependence on an upstream image tag** for z88dk. Mitigated by pinning the
   digest as well as the dated tag, and by a proven from-source fallback.

---

## Traps to carry forward

Z80 and Next specifics, all now commented where they bit:

- `point_x`-style helpers that build an index in DE **clobber D**. Do not hold a
  value there across such a call.
- Band selection is `y >> 5`, which for a byte is **three `rlca`**, not `rrca`.
- `srl a` leaves the shifted-out bit in carry and a following `sbc hl,de` eats it.
- Polygon edges cross, so spans can be backwards. Take min and max.
- `ld b, <count>` truncates silently above 255. The assembler warns; grep for it.
- The `$123B` port **is not readable in this emulator**, so a program that needs to
  know its own paging state must shadow it, as wolf3d-next's `l2_now` does.
- A checker reading Layer 2 must hold the program first, or it reads whichever
  band the renderer happens to be on. Same shape as wolf3d-next's `snd_hold`.

Method, which cost more than the code did:

- **Piping a build through `tail` returns `tail`'s exit status.** A Docker build
  reported success while sdcc had failed, and shipped an image with no compiler.
- **A frame counter must advance where the thing it labels happens.** Incrementing
  it one call too late made the page dump contain drawing the trace had omitted,
  and the comparison failed intermittently depending on whether that extra frame
  touched the page being checked. It passed at 1, 2, 3, 10, 20, 40 and 80 frames
  and failed at 5 and 120.
- **Vary both operands in a unit test.** Zero agrees with corruption.
- **Read the evidence before changing the thing under test.** One of six faults
  was in the reference, and the machine had been right.
