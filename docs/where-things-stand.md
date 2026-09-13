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
| C - rasteriser core | **done**, Gate C passed, 61 polygons pixel-exact |
| C - 16-bit geometry, polygon reader, segment window | **done**, Gates C4 and C5a passed |
| D - the virtual machine | **built**, Gate D claims 1 and 3 passing as far as traced |
| E - pacing, input, sound | **specified and priced**, not built |
| F - the rest of the game | **scoped**, three known gaps |

**Eight of the nine gates pass.** The exception is Gate D: the virtual machine is
built and its opcode stream has been observed identical to the engine's for 354
consecutive records, but not repeatably - see *Gate D* for what was ruled out and
what to try next. Everything else - the rasteriser, the polygon reader, the segment
window, the loader, the mixer, pacing, input and six of the seven parts - is gated
and green.

Nothing here is a guess unless it says so. Every number was measured on the
machine, on the host, or read out of a pinned source and cited.

**The headline changed on 2026-09-13.** A second round of host measurement found
that the previous numbers described the intro cinematic only - with no input the
run stalls at a "press fire" prompt and 57,386 of 60,000 frames draw nothing -
and that the frame budget had been compared against the wrong denominator. The
scripts ask for **80 to 100 ms a frame**, not 20. Measured against the pause each
frame itself requests, the rasteriser uses a quarter of the time available and
**0.73% of frames overrun**. The two optimisations that were on the critical path
are now optional. See *What has been measured*.

## Run it

    make doctor        both toolchain images, with versions and a smoke compile
    make check-data    Gate A: every resource decodes and its CRC cancels
    make check-ref     Gate A: the reference matches the real engine byte for byte
    make assets        convert palettes and bitmaps to Next form
    make check-span    step 0: what one polygon span costs
    make check-cc      Gate B: C calls assembly at a fixed address and returns
    make check-poly    Gate C: the rasteriser, pixel-exact vs the reference
    make check-reader  Gate C4: the reference reader IS the engine's reader
    make check-readmachine  Gate C4: the Z80N reader, pixel-exact
    make check-load    step 5: esxDOS reads correctly; its speed needs hardware
    make check-pace    Gate E: the input mapping, and pacing to its deadline
    make check-snd     Gate E: four voices byte-exact, and the DMA's output rate
    make check-parts   step 9: every part the probe can reach, measured separately
    make check-mix     step 1: what one output sample of the mixer costs
    make check-polycost step 2: T a polygon and T a span, measured apart
    make frame-load    every frame against the pause its own script asked for
    make voices        how many mixer voices are live, and at what rates
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
Adequate here: the VM's worst measured frame dispatches 509 opcodes, which at
the measured 400 T of dispatch is 9% of the pause the scripts ask for, so even
sccz80's worse code generation has room.

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

And three more, from the second round of measurement on 2026-09-13:

| Claim | Finding |
|---|---|
| the scripts set the pause to 1 to 5 slices | true as a range and misleading as a fact. They ask for **4 slices 71.8% of the time in gameplay and 5 slices 78.9% of the time in the intro**. A budget of one refresh a frame was never the game's budget |
| `_scriptStackCalls` is 64 entries | the *declaration* is 64 (`vm.h:81`), the *serialiser* writes 256 (`vm.cpp:712`), and the *bounds check* allows 255 (`vm.cpp:96-99`). The reference can overrun its own array. Allocate 256 |
| the child count in a hierarchy record is a count | it is a count **minus one**, read as an unsigned byte and widened to signed, then looped while `>= 0` (`video.cpp:210-215`). 0 means one child; 255 means 256 |

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

Two runs through a headless instrumented build of the reference interpreter: 12,000
frames with no input, and 60,000 frames with synthetic input.

**The second run exists because the first one lies.** Without input the intro
reaches its "press fire" prompt and stops: over 60,000 frames, 57,386 of them draw
nothing at all, the player-and-enemy polygon segment is never loaded, and every
number describes the protection screen and the intro cinematic. The probe now
takes a fourth argument that walks right, jumps and fires, which is enough to
enter the game and to keep dying in it - and a death restarts the part, which is
the heaviest drawing there is.

| Per VM frame | Intro mean | Gameplay mean | Worst intro | Worst gameplay |
|---|---|---|---|---|
| opcodes dispatched | 20.9 | 64.0 | 96 | **509** |
| polygons filled | 20.3 | 55.4 | 270 | **956** |
| spans drawn | 152 | 376 | **4,004** | 3,637 |
| `fillVideoPage` | 0.02 | 0.10 | 2 | 2 |
| `copyVideoPage` | 0.82 | 0.98 | 2 | 3 |

Gameplay dispatches five times the opcodes and fills three and a half times the
polygons, and yet draws **no more spans**. The intro's spans are long - 1.3% of
them are 256 pixels or wider - and gameplay's are short, 96.0% under 47 bytes
against the intro's 87.6%. Gameplay draws many more, much smaller shapes.

The single heaviest frame is a scene redraw: **956 polygons and 3,637 spans, 3.8
spans a polygon**, recurring exactly every 141 frames in the autoplay run as the
part restarts. **That inverts the cost model.** For the intro the span fill is the
cost; for gameplay the per-polygon setup is, and setup has never been measured on
the machine.

### The budget's denominator, which had been assumed

A frame is allowed `vmVariables[0xFF] * 20` ms (`vm.cpp:283-287`), and the
received wisdom - written into the previous version of this document - is "the
scripts use 1 to 5". What they actually ask for:

| slices | ms | gameplay, 60,000 blits | intro, 12,000 blits |
|---|---|---|---|
| 1 | 20 | 0.0% | 3.0% |
| 2 | 40 | - | 6.1% |
| 3 | 60 | 8.1% | 5.2% |
| 4 | 80 | **71.8%** | 6.4% |
| 5 | 100 | 20.1% | **78.9%** |
| 6 and 9 | 120, 180 | - | 0.3% |

**The game asks for 80 to 100 ms a frame.** It is a 10 to 12 fps game by design -
which is what Another World looked like on an Amiga - and the budget is four to
five refreshes, 2.24 to 2.80 million T-states, not 560,000.

### What that does to the rasteriser's verdict

`make frame-load` scores every frame against the pause **it itself asked for**.
Both cost terms are now measured rather than swept - step 2, `make check-polycost` -
and there are two models, because which applies is a decision about how much
optimising gets done rather than a fact about the game:

| gameplay | p50 | p90 | p99 | worst | frames that overrun | mean load |
|---|---|---|---|---|---|---|
| **as built** | 1.25 | 4.00 | 5.57 | 18.79 | **12.72%** | **48.4%** |
| **with the two optimisations** | 0.71 | 1.74 | 2.15 | 9.13 | **0.73%** | **22.6%** |

| intro | p50 | p90 | p99 | worst | frames that overrun | mean load |
|---|---|---|---|---|---|---|
| as built | 0.18 | 0.69 | 3.28 | 31.88 | 0.52% | 9.6% |
| with the two optimisations | 0.18 | 0.42 | 1.38 | 11.62 | 0.06% | 6.4% |

In refreshes, at 2,974 T a polygon and a 22-byte opaque span at either 2,037 T as
the code stands or 552 T optimised.

**The rasteriser is comfortably fast enough once it is optimised, and not before.**
Optimised it uses just over a fifth of the time the scripts give it, the 99th
percentile has nearly half a four-slice pause spare, and one frame in 137
overruns - room entries and part restarts, where a long frame reads as a load
rather than a stutter. As built it uses half the time and one frame in eight
overruns.

Two earlier readings of this were both wrong, in opposite directions. "The worst
frame clears its budget by about 4%, passing but not comfortable" set the worst
frame of the whole run against a **one**-slice pause the scripts almost never
request. The correction to that, published earlier the same day, used 672 T a
span - which is step 0's purpose-built span row rather than the rasteriser, and so
described code that does not exist yet. The figures above are the rasteriser.

### Structure, heap and voices

`structure.patch` on the host probe, over 3.3 million polygon records and 990,000
hierarchy records. Each of these decides a design rather than describing the
engine:

| | measured | what it decides |
|---|---|---|
| deepest hierarchy nesting | **4** | a four-entry explicit stack, not recursion |
| widest fan-out | 119 children | the child counter is a byte and 119 fits it |
| most vertices in one record | 40, an 83-byte record | any sliding window over 8K is overkill |
| full-screen bitmaps loaded | **0** in 72,000 frames | the `RT_POLY_ANIM` path is unexercised, and so unverified by Gate A |
| peak script-heap use | **241,363** of 581,632 bytes | 30 pages of 8K, 15 banks |

Voices, simulated by `make voices` from the event log, each voice holding its
channel until it is replaced, stopped, or exhausted at its own playback rate:

| | silent | mean voices | all four busy |
|---|---|---|---|
| intro, music playing | **1.7%** | 2.83 | 26.1% |
| gameplay, effects only | 25.0% | 1.60 | 9.7% |

**Sound is not an occasional cost.** Through the intro something is playing 98.3%
of the time and the mean is nearly three voices, so the mixer is a permanent tax
on the frame budget and has to be counted as one - not, as wolf3d-next could
fairly treat it, as "2 to 7% while something plays". Playback rates run 3,327 to
25,031 Hz with a median of 10,559, and 205 of 710 voice starts loop, so a looping
voice holds its channel until something displaces it.

The 25,031 Hz top end is the one number that constrains the output rate: a mix
clocked below it decimates the fastest samples. The reference itself mixes at
22,050 (`sysImplementation.cpp:30`).

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

**Read that last line against the right budget.** A five-slice pause is 2,800,000
T, so the worst frame of the whole run fits it - and the scripts ask for four or
five slices over 90% of the time. Scored frame by frame against the pause each one
requests, 0.73% overrun; see *What that does to the rasteriser's verdict* above.

**Where the margin is, if it is ever wanted**, in order of return: hold the four
accumulator words in registers across a trapezoid instead of loading and storing
them per scanline, which is most of the 433 T; and unroll the blend and copy fills
as the opaque one already is, taking blend from 32 to about 19 T/byte and copy from
37.5 to about 24. Both are techniques already measured here, not guesses.

**Both are required, and step 2 established that by measuring the alternative.**
For a while they looked optional, which was the consequence of budgeting a span at
this file's 433 T entry plus a PUSH fill when the rasteriser uses neither.
`make check-polycost` charges the real code at 1,570 T entry and 21.3 T an opaque
byte, and these two optimisations are exactly what closes that gap. The
per-polygon cost the same run measures, 2,974 T, landed inside the range the plan
had swept, so that half of the budget was sound all along.

**Stores versus PUSH cross at 12 bytes**, and 88% of the intro's spans are longer,
so the fill should be PUSH with a store fallback below that. In gameplay 96% of
spans are under 47 bytes and the median is far shorter, so **re-check that
crossover against gameplay's distribution** before trusting it: the fallback may
be the common path, not the exception.

### The mixer, priced on the machine

`make check-mix`, step 1 of the plan, fitted over five block lengths with a NULL
mode subtracting the harness - the same method `check-span` used, and for the same
reason: a figure obtained by dividing one measurement carries whatever else was in
it.

Correctness first, because a benchmark of wrong code measures nothing. All 256
volume-table entries match the reference's `(int)b * volume / 0x40` computed on
the host, the sample ramp is exact, and an eight-sample mix matches a host walk of
the same 16.8 accumulator.

| T-states per output sample | |
|---|---|
| the advance alone, branchless | 27.7 |
| one voice, table volume, store and bias | 58.9 |
| one voice, accumulate and saturate | 79.1 |
| **four voices, unrolled** | **295.2** |
| four voices, rolled | 325.4 |
| one voice through Z80N `MUL D,E` | 186.2 |
| one voice with the reference's interpolation | 178.4 |

**Four voices at each candidate rate**, against the renderer's measured 24.8%:

| rate | mixer | with the renderer |
|---|---|---|
| 11,025 | 11.6% | 36% |
| 15,625 | 16.5% | 41% |
| **22,050, the reference's own** | **23.2%** | **48%** |

**The plan's threshold was 35% for four voices at 22,050, and the measurement is
23.2%, so the ring-and-tick design stands and the reference's own output rate is
affordable.** Decided: mix at 22,050 Hz. The estimates the plan carried - 22%, 16%
and 11% - came out at 23%, 16% and 12%, which is the one part of this document
that was scaled from another project rather than measured, and it held.

Three decisions fall out of the same run:

- **The volume table wins, and the 16,384 bytes are well spent.** `MUL D,E` costs
  **127 T a sample more**, because an unsigned multiply of a signed sample is
  magnitude-then-sign plus a six-place shift of a 16-bit product, and the table is
  `ld e,a` / `ld a,(de)`.
- **Drop the linear interpolation.** It costs **+119 T a sample, 203% more than
  the whole rest of a voice**, for an anti-aliasing nicety. Build it later behind a
  switch if a listening test asks for it.
- **Unroll by four**: 30 T a sample on four voices, for 240 bytes of code.

**The advance is 47% of a storing voice**, which is why it must be branchless: the
fractional add sets carry, `LD` does not disturb it, so `ADC HL,DE` applies the
integer increment and the fraction's carry in one 15 T instruction. The first
draft used `JR NC` / `INC HL` and cost 14 T a sample more. The page-boundary,
sample-end and loop-point tests are **not** in the loop - the block is split at
each of those before the loop runs, which is O(1) a block instead of 18 T a voice
a sample.

Additivity holds to 8.9%: one store plus three saturating voices predicts 296 T
against 325 measured for the rolled version.

### The rasteriser, decomposed - and the plan's span cost was three times too low

`make check-polycost`, step 2. It draws **windows** of the Gate C vector rather
than prefixes, because taking prefixes leaves the polygon count and the span count
at r = 0.96 and a fit cannot then tell the two costs apart.

**The per-polygon cost is measured, not fitted.** One window draws a single polygon
that produces no spans at all, so its whole pass is the per-polygon path - the
bounding-box test, the walk's setup, the record advance:

    per polygon                      2,974 T

With that subtracted the span terms are well posed:

| | measured here | step 0, by another method |
|---|---|---|
| per span entry | 1,570 T | 433 T (its own span row) |
| per opaque byte | 21.3 T | 5.4 PUSH, 10.7 unrolled |
| per blend or copy byte | **32.0 T** | **32.2** and 37.6 |

**The blend term agreeing to 0.6% by two entirely different methods is the evidence
that this decomposition means anything.** The opaque term matches `span_opaque` as
written - `ld (hl),a` / `inc l` / `djnz` is 24 T a byte in theory and 21.3
measured, the difference being `djnz`'s cheaper last iteration.

**And that is the finding.** The plan budgeted 672 T a span. That figure is step
0's *purpose-built span row with a PUSH fill*, not the rasteriser. The rasteriser
as it stands charges **1,570 + 22 x 21.3 = 2,037 T** for the same 22-byte opaque
span - three times as much.

Re-run against every frame the host measured, at each frame's own requested pause:

| gameplay | mean load | p90 | p99 | worst | frames overrunning |
|---|---|---|---|---|---|
| **as built** | **48.4%** | 4.00 | 5.57 | 18.79 | **12.72%** |
| **with the two optimisations** | **22.6%** | 1.74 | 2.15 | 9.13 | **0.73%** |

The earlier "24.8% and 0.73%" in this document was, by coincidence, almost exactly
the *optimised* model - because 672 T a span is close to the 552 T the
optimisations would actually achieve. The conclusion "the rasteriser is comfortably
fast enough" was therefore right about the destination and wrong about where the
code is.

**So the optimisations were required - and step 2a did them.** Two changes, both
protected by Gate C:

- **the row loop fused, with inline specialised clipping.** The four calls a row to
  a general signed comparator went, along with two call/ret pairs and the six
  memory round-trips for `sx1` and `sx2`. At this point in the walk `hliney` is
  either negative or 0..191, so its test is one `or a` rather than a subroutine.
- **all three fills unrolled with a computed entry**, replacing `djnz` loops whose
  13 T of branch was more than half the cost of an opaque byte.

| | before | after | step 0's floor | theory |
|---|---|---|---|---|
| span entry | 1,570 T | **1,007 T** | 433 | |
| opaque byte | 21.3 T | **10.8 T** | 5.4 (PUSH) | 11 |
| blend or copy byte | 32.0 T | **16.4 T** | 19 (unrolled) | 19 |
| a 22-byte opaque span | 2,037 T | **1,245 T** | 552 | |

The opaque byte at 10.8 against a theoretical 11 - `ld (hl),a` plus `inc l` - is
the check that the decomposition is still measuring what it claims.

| gameplay | mean load | p90 | worst | frames overrunning |
|---|---|---|---|---|
| original | 48.4% | 4.00 | 18.79 | 12.72% |
| **after step 2a** | **37.3%** | 3.05 | 15.43 | **0.97%** |
| the floor | 22.7% | 1.76 | 9.21 | 0.73% |

**The overrun rate is now at the floor** - 0.97% against 0.73%, one frame in 103
against one in 137 - so the thing the optimisation was for is done. What remains
between here and the floor is mean load, which is headroom rather than
correctness: 37.3% with the mixer's 23.2% is 61% of the machine. The last two
techniques, a PUSH fill and the accumulators in registers, are therefore back to
being optional, and this time that is a conclusion drawn from a measurement of
this code.

**The per-polygon cost is a range, not a number**, which is the other thing step
2a established. Eight windows draw a single polygon and no spans at all, and they
cost **689 to 4,404 T**: a bounding-box rejection at one end, and at the other a
polygon that sets up, walks every row and has every span clipped. `check-polycost`
fixes the term at the median and reports the span fit at the extremes too - they
move by a few per cent across that whole 4.5-fold range. Fitting it as a free term
instead returned **minus 7,180 T a polygon** and a 30% residual, because polygons
and spans stay correlated across any sweep of a fixed vector and least squares
will trade one against the other without complaint.

**Gate C found the one fault in the rewrite in a single run.** The blend fill needed
a spare register pair to compute length x 3, took DE - which was holding the
destination - and restored the length as the destination. The bisect named it
immediately: polygon 35, bucket `blend`. The fix is to push the destination first.

The copy-byte term is **not** measured here: copy-mode bytes never exceed 952 in any
window and are zero in most, so fitted freely the coefficient came out at minus 243
T a byte. They are folded in with blend, which step 0 measured at 32.2 against
copy's 37.6.

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

### Still outstanding in Phase C, now specified

All of it is protected by the Gate C test vector, which is what makes it safe to
attempt rather than hopeful.

**C4. The polygon reader.** `video.cpp:83-115` for the record forms,
`video.cpp:206-243` for the hierarchy, `vm.cpp:485-580` for the two opcode forms
that enter it.

**The reference half is built and gated.** `make check-reader` replays every
top-level draw the host probe logged through the reference's reader and compares
the `fillPolygon` calls it emits against the ones the engine emitted, record for
record and field for field: **10,700 draws, 64,897 calls, no faults, first run.**
It confirms the deepest nesting at 4 independently. Comparing pictures would have
said only that something was wrong; comparing the call sequence says which record,
at which offset, with which field wrong - the same reason Gate D's opcode trace
comes before its picture.

**And the machine half is done.** `make check-readmachine` pokes the intro's
65,230-byte cinematic segment into banked pages, hands the machine 64 top-level
draws chosen for **zoom coverage rather than trace order** - 55 distinct zooms, 61
of them not the identity - and compares the page: **49,152 of 49,152 pixels, over
771 polygons the reader found for itself**, nesting to depth 3.

Choosing the draws for zoom is the point. 97.4% of the intro's polygons are at
zoom 0x40, so a vector taken in order would have left the zoom multiply and its
two truncations essentially untested.

A record's first byte decides everything:

| first byte | meaning |
|---|---|
| `>= 0xC0` | a leaf. If the incoming colour has bit 7 set, the colour becomes `byte & 0x3F`. Vertices follow. |
| `& 0x3F == 2` | a hierarchy record |
| anything else | the reference warns and draws nothing. Do the same, and count it. |

A leaf is `bbw`, `bbh`, `numPoints`, then `numPoints` pairs, every one scaled by
`* zoom / 64` (`video.cpp:25-37`). `numPoints` is asserted even and under 50.

A hierarchy record subtracts a scaled (x, y) from the incoming point, then reads a
child count as **an unsigned byte widened to signed** and loops while `childs >= 0`
(`video.cpp:206-213`). So the byte is children **minus one**: 0 means one child and
255 means 256. Each child is a word offset, a scaled (x, y) pair, and - only when
bit 15 of the offset is set - a colour byte read from the stream **without
advancing past it**, followed by an unconditional `pc += 2` (`video.cpp:226-230`).
The target is `(off & 0x7FFF) * 2` **from the segment base, not from the current
position**, and the reader restores its own program counter afterwards.

Measured depth is 4, so a four-entry explicit stack of saved offsets is enough.
Size it eight and assert on overflow rather than trusting the measurement: it is a
measurement of two parts out of ten.

**The two opcode forms** differ in how much they fetch, not in what they draw:

- **bit 7 set** (`vm.cpp:485-505`): the offset is `((opcode << 8) | nextByte) * 2`,
  x and y are single **signed** bytes, the buffer is always the cinematic segment,
  the zoom is always 0x40, and the colour passed in is `0xFF`, whose bit 7 is set -
  which is what lets the record's own first byte supply the colour. Then the y
  clamp: `h = y - 199; if (h > 0) { y = 199; x += h; }` - a **diagonal** slide, not
  a clamp, and easy to write as two independent clamps by mistake.
- **bit 6 set** (`vm.cpp:507-577`): five nested conditionals over bits 5, 4, 3, 2,
  1 and 0 choosing whether x, y and zoom come from a second byte, a variable, or a
  constant - and two of the branches **rewind the program counter by one** before
  substituting 0x40 for the zoom. One of those also switches the buffer to
  `_segVideo2`. Bit 0 with bit 1 set is the only path that reads the
  player-and-enemy segment at all, which is why the intro never touches it.

**C5. Zoom composes with the vertex scale, and the order is not free.** The
reference computes `byte * zoom / 64` in 320x200 space and truncates; our scale
(above) then maps to 256x192 and truncates again. Two truncations, in that order.
Folding them into one multiply, or scaling before zooming, differs on values a
well-chosen test will find.

**And a test drawn from the intro would barely find any of them.** `DEFAULT_ZOOM`
is 0x40, which makes the first step the identity, and over the 64,897 polygons of
the traced intro window **97.4% are at zoom 0x40**. There are 55 distinct zooms in
there, but the whole non-identity tail is 2.6% of the polygons, running from 0x49
to 0x153 - so magnification as well as reduction. Gameplay reaches the bit-6
opcode form 9.4 times a frame against the intro's 2.6, so draw any zoom vector
from the autoplay trace.

**Gate C does not test the zoom at all, by construction.** The host probe records
a polygon's bounding box and vertices *after* `readVertices` has applied the zoom,
so `tools/mkpolytest.py` gets post-zoom geometry and the machine is fed the same.
That was the right call - it made Gate C a test of the rasteriser alone - but it
means the zoom multiply and the vertex scale need a check of their own, in the
shape of `mkcsteps`: enumerate byte against zoom over the real range, compute both
truncations on the host, compare on the machine. Exhaustive is 256 x 340 = 87,040
cases - a table too large to ship, a loop small enough to run.

**C5a. The geometry was 8-bit and the game is not - DONE.**

The rasteriser now holds boxes and vertex offsets as signed words throughout, and
`calc_step`'s product is 16 x 16, assembled from four `MUL D,E` and three shifted
accumulations. `make check-poly` covers it: the vector has a **`wide` bucket** and
reaches 303, and the unit test runs **576 of 576 cases exact** including
coordinates to 480 and runs to +-260.

Three things fell out of doing it.

**The `wide` bucket came back empty the first time**, because a box wider than the
screen always clips and one of the four clipping buckets claimed it. It is tested
before them now.

**A stale copy of the record advance broke Gate C**, and the bisect named polygon
1 - a plain rectangle - which is the shape of a layout fault rather than an
arithmetic one. The draw loop still stepped over records as though `bbw` were a
byte and a point were two.

**Nothing was reading `cs_results`.** The 576-case unit test has been running on
the machine and storing its answers, and no checker ever read them back, so the
"exhaustive at 648 of 648" in an earlier version of this document rested on a run
nobody repeated. `check-poly` verifies them now, before it believes a pixel. An
unchecked test is not a test.

The original text of this section, for the record:

`src/polytest.asm` holds a polygon's bounding box and its vertex offsets in
**bytes**, and `calc_step` multiplies an 8-bit `dx` by the 16-bit interpolation
value. Over the whole 64,897-polygon trace the post-zoom values reach:

    bounding box    bbw <= 529, bbh <= 503     (320x200 space)
    vertex offsets  0..529 in x, 0..503 in y
    after our scale bbw <= 423, bbh <= 483

**Gate C never caught it because the 57-polygon vector tops out at 204.**
`tools/mkpolytest.py` picks for fill mode, clipping edge, vertex count and size -
not for a box wider than the screen - and every value it picked fits a byte, so
`db` never truncated and `srl a` never halved a value it could not hold. A
differently-picked vector would have broken silently.

It is legitimate data: a 423-wide box is wider than the 256-pixel screen, and the
polygon is simply clipped. The original is `int16_t` throughout.

**What the fix touches**, in dependency order:

1. `tools/mkpolytest.py`: `dw` for `bbw`, `bbh` and every vertex pair, the record
   size in the offset table, and **a new `wide` bucket** so the vector covers a box
   over 255 - without which the gate would go on not covering it.
2. `poly_draw`'s record parse and its box halving: `srl h` / `rr l`, not `srl a`.
3. `point_x` and `point_y`: index times four, returning HL rather than A.
4. `calc_step`: `dx` becomes a 16-bit difference, so the 8x16 product becomes
   16x16, and `dy` likewise. Its 648-case unit test regenerates with word cases.

Item 4 is the real work and it is the one place where the 648-case test earns its
keep: a 16x16 signed multiply assembled out of four `MUL D,E`s is exactly the kind
of code that is plausible and wrong.

**C6. The segment window - DONE.** Built as part of C4 and exercised by the same
gate. Two 8K pages at MMU0 and MMU1, `$0000-$3FFF`, which is the only 16K the
program does not otherwise use: code is at `$8000`, the generated tables at
`$C000`, and the Layer 2 windows at `$4000` and `$6000`.

**A recursive reader has to save the window, not just its pointer.** A child can
live in a different pair of pages, and mapping it moves the window, so the
parent's saved read pointer becomes an address into whatever the child mapped. The
page number is pushed alongside it now. Before that the machine found 31 malformed
records where the reference finds none.

The original text follows, and the arithmetic in it is what was built.

A thread's program counter and a polygon offset are
both 16-bit offsets from a segment base, and the largest cinematic segment is
**65,230 bytes** - 306 bytes short of everything 16 bits can address. A segment
therefore cannot be mapped linearly into a 64K space that also holds code, and
there is no 16-bit arithmetic to avoid, because the offsets are genuinely 16-bit.

Map a **two-page 16K window**: `page = off >> 13`, address `$C000 + (off & 0x1FFF)`,
with pages `base + page` and `base + page + 1` in MMU6 and MMU7. Any record
starting in the low half can then be read to its end without a remap, since the
longest leaf measured is 83 bytes and the widest hierarchy record 717 - three
header bytes and 119 children of six. A
record starting in the high half needs the window advanced by one page first,
which costs one `nextreg` and a subtraction.

**C7. The register allocation** that attacks the 433 T of per-span overhead. **Now
optional.** See the note in *On the machine*: measure the per-polygon setup cost
first, because gameplay spends its time there and nothing has weighed it.

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

## Phase D - the virtual machine

Unblocked, and specified below. Every fact is read out of the pinned reference and
cited. Each step is gated on the previous one's measurement, and the gates are
cheap deliberately: a VM that is wrong in one opcode is a VM that renders almost
correctly, which is the worst kind of wrong to debug at the end.

### D1. Where a part's data lives

A part is four resources. These are the real sizes, from the user's own memlist via
`tools/memlist.py`:

| part | palette | bytecode | cinematic | video2 | total |
|---|---|---|---|---|---|
| protection | 2,048 | 4,321 | 5,124 | - | 11,493 |
| intro cinematic | 2,048 | 9,871 | 65,230 | - | 77,149 |
| 3, water | 2,048 | 20,810 | 57,510 | 25,108 | 105,476 |
| 4, jail | 2,048 | 39,695 | 53,720 | 25,108 | 120,571 |
| 5, cave | 2,048 | 62,683 | 65,132 | 25,108 | **154,971** |
| battlechar cinematic | 2,048 | 8,287 | 29,212 | - | 39,547 |
| 7, arena | 2,048 | 50,736 | 64,958 | 25,108 | 142,850 |
| 8, baths | 2,048 | 2,886 | 20,026 | 25,108 | 50,068 |
| 9, final | 2,048 | 4,257 | 5,048 | - | 11,353 |
| password screen | 2,048 | 4,257 | 5,048 | - | 11,353 |

The largest bytecode is 62,683 bytes and the largest cinematic 65,230, and the
player-and-enemy segment is always resource 0x11 at 25,108 bytes (`parts.cpp:14-26`).

On top of a part, sound effects load at run time onto the same heap and are never
freed until the part changes (`resource.cpp:165-222`), so the peak is not the part
total: **measured peak 241,363 bytes**. As 8K pages that is 30 pages, or 15 banks
of 16, against 112 on the 2 MB profile with 12 already spent on the four
framebuffers. There is room, and the constraint is the 64K address space, not the
memory.

**The heap is two-ended in the reference and does not need to be here.** Script
data grows up from the bottom; a 32,000-byte staging area sits at the top for
full-screen bitmaps, and `_vidCurPtr` never advances, so it is a fixed scratch
buffer rather than an allocator (`resource.cpp:337-341`). Our allocator is a page
counter: each resource gets whole 8K pages, rounded up, which wastes about 4K per
resource across the 53 seen live - 217K of a 2 MB machine, for an allocator with
no arithmetic in it.

**The decision: pre-decompress on the host.** `make check-data` already decodes
every resource and proves its CRC cancels; `make assets` writes them out flat, so
the Next never runs byte-killer and never carries its 32-bit reservoir. That trades
1,730,258 bytes of SD card - the whole game, decoded - for the entire decompressor.
The data stays the user's and out of the repository, exactly as `DATA_DIR` does for
Wolf3D.

### D2. The scheduler

`engine.cpp:31-42` is the whole main loop, four calls:

    checkThreadRequests();     apply what last frame asked for
    inp_updatePlayer();        input into variables 0xE5, 0xFA-0xFE
    processInput();            save/load slots; ours does nothing
    hostFrame();               run all 64 threads once

`checkThreadRequests` (`vm.cpp:401-431`) does three things in order: it switches
part if one was requested; it copies `vmIsChannelActive[REQUESTED]` over
`[CURR]` for every thread; and for every thread whose `REQUESTED_PC` is not
`0xFFFF` it moves that into `PC`, translating the sentinel `0xFFFE` to
`0xFFFF`, then resets the request to `0xFFFF`. The doubling is the whole point:
a thread may retarget or pause any thread including itself, and nothing takes
effect until the frame boundary.

`hostFrame` (`vm.cpp:433-476`) skips threads whose `CURR` state is non-zero, sets
the script pointer from the thread's PC, **resets `_stackPtr` to 0**, clears
`gotoNextThread`, and runs `executeThread` until an opcode sets it. A thread with
no `pauseThread` (0x06) or `killThread` (0x11) in its path never yields.

**The call stack is one shared scratch array, and the reference's own bounds
disagree.** It is declared `uint16_t _scriptStackCalls[64]` (`vm.h:81`), serialised
as 256 entries (`vm.cpp:712`), and bounds-checked against 255 (`vm.cpp:96-99`) -
and the check happens *after* the write. Allocate **256** and assert. Because the
pointer resets per thread, a `call` cannot survive a `pauseThread`: this is
scratch, not per-thread state, and it is the correction that most changes code.

**Initial state**, `initForPart` (`vm.cpp:381-398`): stop music and all channels,
set `vmVariables[0xE4] = 0x14`, load the part, fill `threadsData` entirely with
`0xFF` bytes so every PC and request is `0xFFFF`, zero both channel-state arrays,
then set thread 0's PC to 0. And from `init` (`vm.cpp:34-49`): `vmVariables[0x54]
= 0x81`, the random seed in `0x3C`, and - because we bypass the protection screen
as the reference does - `0xBC = 0x10`, `0xC6 = 0x80`, `0xF2 = 4000`, `0xDC = 33`.
Those four are set by the original game code and executable, not by the bytecode,
so a port that omits them starts a part that cannot work.

### D3. The opcodes

27 in the table, `0x00` to `0x1A` (`staticres.cpp:31-59`), plus the two polygon
forms. Operand bytes are what the fetch sequence consumes:

| op | name | operands | notes |
|---|---|---|---|
| 0x00 | movConst | var, word | |
| 0x01 | mov | var, var | |
| 0x02 | add | var, var | wraps as int16 |
| 0x03 | addConst | var, word | carries a protection-screen special case at part 0x3E86, pc 0x6D48 |
| 0x04 | call | word | pushes the return offset, then `++sp` |
| 0x05 | ret | - | `--sp` then read |
| 0x06 | pauseThread | - | yields to the next thread |
| 0x07 | jmp | word | |
| 0x08 | setSetVect | thread, word | writes `REQUESTED_PC`, effective next frame |
| 0x09 | jnz | var, word | **pre-decrements the variable**, then jumps if non-zero |
| 0x0A | condJmp | op, var, (var\|word\|byte), word | see below |
| 0x0B | setPalette | word | uses the **high byte** only |
| 0x0C | resetThread | thread, last, action | see below |
| 0x0D | selectVideoPage | page | |
| 0x0E | fillVideoPage | page, colour | |
| 0x0F | copyVideoPage | src, dst | vertical scroll comes from variable 0xF9 |
| 0x10 | blitFramebuffer | page | the frame boundary: pacing, then display |
| 0x11 | killThread | - | sets pc to 0xFFFF |
| 0x12 | drawString | word, x, y, colour | x is a character cell, y a pixel row |
| 0x13 | sub | var, var | |
| 0x14 | and | var, word | unsigned |
| 0x15 | or | var, word | unsigned |
| 0x16 | shl | var, word | unsigned, count is a **word** |
| 0x17 | shr | var, word | unsigned, count is a **word** |
| 0x18 | playSound | word, freq, vol, chan | freq indexes a 40-entry table; `vol == 0` stops the channel |
| 0x19 | updateMemList | word | 0 stops everything and invalidates; `> numMemList` requests a part |
| 0x1A | playMusic | word, word, pos | res 0 with a delay only changes the tempo |

`condJmp` (`vm.cpp:142-208`) fetches a sub-opcode and a variable, then its second
operand from bit 7 (a variable), bit 6 (a word) or neither (a byte), and compares
on the low three bits: 0 `==`, 1 `!=`, 2 `>`, 3 `>=`, 4 `<`, 5 `<=`, and 6 or 7
warn and fall through. **Signed comparison throughout** - both operands are
`int16_t` - which on the Z80 means the overflow-aware form, not `sbc hl,de` and a
carry test. `cmp_signed` from Phase C already exists.

`resetThread` (`vm.cpp:217-245`) reads a first thread, a last thread masked to
`& 63`, and an action. If `last < first` it warns and does nothing. Action 2 writes
`0xFFFE` into `REQUESTED_PC` for the inclusive range - which
`checkThreadRequests` turns into "inactive". Action 0 or 1 writes that value into
`REQUESTED_STATE` for the range, pausing or resuming. Action 3 and above does
nothing at all, silently.

`drawString` needs the engine's own string table: **140 English strings, 2,202 text
bytes plus a 560-byte (id, offset) index, 2,762 bytes total**, ids from 0x0001 to
0x0265 (`staticres.cpp`). It is code, not game data, so it ships in the binary
under GPLv2 like the 768-byte font already does.

**Why C is still the right answer.** Worst gameplay frame is 509 opcodes. At the
measured 400 T of dispatch that is 203,600 T, **9% of a four-slice pause**. Even a
fourfold miss on compiled C fits. Nothing in this table wants assembly.

### D4. Loading, over esxDOS

Flat files from `make assets`, one per resource, plus the memlist as a table.
Per part: four resources, worst case 154,971 bytes; per `updateMemList`, one
resource, worst case 41,506 bytes (sound 0x69). Load order in the reference is by
descending `rankNum` (`resource.cpp:170-181`), which our flat loader can ignore -
it only mattered for packing a single heap.

Two traps are already paid for on the other project and cost nothing to avoid here:

- **esxDOS pages itself over the bottom 16K during a file call**, so nothing in
  slots 0 or 1 may be the code doing the reading, and Layer 2 write-through has to
  be off across it.
- **esxDOS takes a machine-code caller's buffer in IX**, not HL - HL is the BASIC
  caller's. wolf3d-next's `fs_*` set both after CSpect wrote a filename over the
  code following it.

**The loading path is built and verified; the rate is not measurable here.**
`make check-load` opens a resource, reads it into banked pages 8K at a time through
a buffer in IX with the code at `$8000`, and checks the length against the host's.
Seven files from 9,871 to 65,230 bytes, every byte arriving, the largest across
eight pages.

**But ZEsarUX's esxDOS handler does its I/O on the host and charges the emulated
CPU nothing**, so the time a read takes barely depends on how much is read: every
one of those seven files costs between two and three million T-states whatever its
size, and the implied cost a byte therefore spans **34 to 226 T, a sixfold
spread**. A real rate is one number.

**The checker's first two versions both reported a rate anyway**, and the second
failure is the instructive one. Version one divided and got 99 KB/s. Version two
tested the size-against-time correlation and refused - but that correlation is
computed over a narrow band of times and wanders either side of zero: one run gave
**r = -0.518** and another **r = +0.614**, and on the strength of the second the
checker reported 135 KB/s. It now tests whether the per-byte figures AGREE between
files, which is the thing a rate actually means, and gives the same verdict every
run.

So the read rate joins the short list of things only the KS3 can answer, beside
whether the DMA honours `$123B`. Phase D is designed against an assumed rate, and
the assumption is stated where it is used: **at any rate above 100 KB/s the worst
part - 154,971 bytes - loads in under two seconds, which a held frame covers with
no loading screen.** Below that it becomes a design decision rather than a detail.

Also worth carrying: `op_updateMemList` loads ONE resource inside a frame, and the
largest is 65,230 bytes. That is a frame the pacing has to be told about however
fast the card is.

### D5. Gate D - built, and the VM is right as far as it is traced

`make check-boot`. The C virtual machine is written - 426 lines, **7,095 bytes of
code**, which puts risk 6 to rest - and it loads a bytecode segment off the card
through the esxDOS path step 5 verified, runs the scheduler, and logs every opcode
it dispatches.

**Claim 1 passes.** The thread table and the initial variables are exactly what
`initForPart` leaves: thread 0's pc at 0, all 63 others at `0xFFFF`, every
requested pc `0xFFFF`, both channel-state arrays zero, and `0x54 = 0x81`,
`0xE4 = 0x14` plus the four values the original game code and executable set
rather than the bytecode.

**Claim 3 passes as far as the trace runs.** The machine's stream is a **prefix**
of the engine's: **nineteen records, every one identical** - the thread edge, then
`call`, `movConst`, `jmp`, `condJmp`, `setSetVect`, `selectVideoPage`,
`fillVideoPage`, `blitFramebuffer` and `pauseThread` across the first frame, then
the second frame's thread edge and its run of five `updateMemList` calls. Every
field: thread, program counter, opcode.

**The best verified result is 354 of 354 records identical**, reached after moving
the VM's C down to `$8C00` so the stack had room. Every record: the thread edge, the
opcode, the program counter, across many frames and several threads.

**But it is not repeatable, and that is the honest headline.** The same inputs have
given 0, 64, 122 and 354 matching records on different runs. Non-determinism with
identical inputs means something uninitialised, and one cause was found and fixed -
**ZEsarUX's `smartload` does not clear RAM between loads, so a second run inherits
the first run's memory** and C's statics do not start at zero the way C assumes.
`main` now states every one of them explicitly, which a `.nex` should do anyway
because it cannot assume a clean machine. It did not make the result repeatable, so
there is at least one more.

Ruled out, so that nobody re-runs them: the ZRCP client does not desynchronise (30
interleaved reads of a known byte, all correct); the two `.exp` files share no
symbol name; `REGISTER_SP` is honoured and the map confirms it; `TAR__crt_org_code`
is the target's default rather than the effective origin, so `__Start` is the symbol
to read; and z88dk emits one CODE section here with BSS inside it, so no DATA
section is missing from the INCBIN.

**Two SDCC warnings are worth naming, because both sit exactly where a fault would
hurt.** `warning 110: conditional flow changed by optimizer` fires on `op_condJmp`'s
`switch (op & 7)` and on the bit-7 form's diagonal slide - a signed comparison and a
signed clamp, which is where the plan already said the overflow-aware form matters.
Neither is investigated further, because Gate D's stream exercises `condJmp` heavily
and a signedness fault would show as a divergence rather than as a warning. That is
the argument for the gate, and it only holds while the gate runs.

**What is NOT established is a repeatable full-stream comparison**, and the reason
is the channel between the C and the checker rather than the VM. Reading the C's
state back has been unreliable in a way several attempts did not pin down: a trace
counter that read 129 when nineteen records had been written; four adjacent fields
reading as the same value; a trace buffer that read as empty after records had
demonstrably been written into it. Three arrangements were tried - a jump-table
logger, an `extern uint8_t x[]` against a `defc`, and a cast address constant - and
each failed differently.

**What the search did settle is the memory map**, and that is written into
`src/vmtest.asm` where the next reader will need it, because every wrong turn
presented as something other than a memory-map problem:

| | |
|---|---|
| `$0000-$3FFF` | the bytecode window; the ROM until first mapped, and esxDOS pages itself here during a file call |
| `$4000-$7FFF` | **not available.** Bank 5 holds the ZX system variables from `$5B00`, which esxDOS needs: staging a read here loaded 68 bytes and then failed |
| `$8000-$82xx` | `vmtest.asm`: jump table, code, data |
| `$8C00-$AExx` | the C and its data, low on purpose |
| `$BF00` | the stack. What SAVENEX declares; moving it to `$FF00` broke the load |
| `$C000-$DFFF` | the trace buffer |
| `$E000-$FFFF` | the loader's staging window |

**So Gate D stands at: the VM is built, its initial state is exactly the engine's,
and its opcode stream has been observed identical for 354 consecutive records - but
not repeatably.** It is the one gate of nine that does not pass.

**So the channel went.** The C now writes everything - the header the checker pokes
and the records it reads - into one 8K block at `$C000`, which it has demonstrably
always been able to write since records appeared there correctly all along. After
`main` returns, the assembly writes that block to `AWTRACE.BIN` through esxDOS, the
path step 5 proved byte-exact. The checker reads the file. **The only memory it
touches now is six bytes of header at a fixed address in assembly-owned RAM.** A
file either holds the records or it does not.

**And the ROM has to go back before that write.** The virtual machine has been
paging bytecode over `$0000-$3FFF` through MMU0 and MMU1, and esxDOS is reached by
`RST $08`, which needs the ROM at `$0000` and pages its own memory over the bottom
16K besides. `$FF` is the MMU value that means the ROM. Without it the write simply
produced no file, which is at least an honest failure.

The seed is taken from the host's own run, because the reference sets variable
`0x3C` from `time(0)` and the two streams would diverge the first time the
bytecode read it.

#### The stack was in the bytecode window, and that is worth the whole section

The symptom was that after nineteen records the machine stopped logging and the
four highest C globals read back wrong. The cause is one line of build
configuration: **z88dk's runtime sets its own stack pointer on entry, and left to
its default it put the stack inside `$0000-$3FFF` - which is exactly where the
bytecode window is mapped.**

So every push wrote into the bytecode, and a `RET` eventually jumped into it. The
machine was found executing at `$0068`, which is not an address in this program at
all. It also explains two things that had looked like separate faults earlier in
the session: the bytecode's own second byte reading `0x19` where the file has
`0x00`, and the trace counter reading 129 when nineteen records had been written.

The fix is `-pragma-define:REGISTER_SP=0xBF00`. **Not `CRT_STACK_ADDRESS`**, which
was tried first and changed nothing: that pragma sizes the stack for some targets
rather than placing it. The assembly already set SP before calling in; this makes
the runtime agree instead of overrule it.

**What found it was a memory write breakpoint**, the first time this project has
needed one. Reasoning had already ruled out the addresses being wrong, the fault
being progressive with frame count, and the globals the checker pokes being
unreadable - and was going nowhere. The breakpoint gave the program counter, and
`$0068` named the cause immediately.

**Carry this forward.** Any C on this machine that maps a window over the bottom
16K has to be told where its stack is, and the symptom will not look like a stack
problem: it looks like corrupted data a long way from the stack, because the stack
is somewhere data is not.

The evidence, kept because it is what a stack in the wrong place looks like from
the outside:

| symbol | address | reads | should be |
|---|---|---|---|
| `aw_log_count` | `$BBCD` | 129 | 19 |
| `aw_finished` | `$BBD3` | `0x81` | `0x5A` |
| `aw_frames_done` | `$BBD4` | 0 | the frame count |
| `aw_bad_op` | `$BBC4` | `0x19` | 0 |

- **It is not frame-dependent.** Identical at 2, 3, 5 and 10 frames: nineteen
  records, all matching, the same three wrong values. So it is not a progressive
  overrun driven by how much work is done.
- **The addresses are right**, straight from z88dk's map, and the two globals the
  checker POKES - `aw_seed` at `$BBAE` and `aw_frames` - are read correctly by the
  C, because the opcode stream is right and the frame loop runs.
- **The symbols that read wrong are the four HIGHEST in the C's data**, in address
  order down from the stack at `$BF00`, and the C's data ends at about `$BBD6`.
  That is 810 bytes of gap, and the pattern is what a stack growing into its own
  data looks like.
- **Pinning `CRT_STACK_ADDRESS` to `$BF00` changed nothing**, which was the clue
  that the pragma was the wrong lever rather than the diagnosis being wrong.
- `0x81` is a value this VM writes into `vmVariables[0x54]`, which looked like
  something copying rather than a stack - and was in fact just whatever that
  address held when the stack walked over it.

### D5a. Gate D, the rest of it

`make check-boot`, in four claims, each of which fails loudly on its own:

1. **The thread table matches `initForPart` exactly.** Thread 0's PC is 0, all 63
   others are `0xFFFF`, every `REQUESTED_PC` is `0xFFFF`, both channel-state arrays
   are entirely zero, and `vmVariables` holds `0x54 = 0x81`, `0xE4 = 0x14` and the
   four bypass values. Read back over ZRCP.
2. **A frame advances.** Thread 0's PC differs between two reads, and the
   `pauseThread` count is non-zero - a VM that never yields would also "advance".
3. **The opcode trace matches the host.** Extend the host probe to log
   (thread, pc, opcode) for the first N frames, log the same on the machine into a
   ring in a spare page, and compare. This is the gate that matters: it catches a
   wrong operand length at the opcode that has it, rather than as a wrong picture
   4,000 opcodes later. It is the VM's equivalent of Gate C's bisect, and for the
   same reason - **a whole-image comparison only ever says that something is
   wrong**.
4. **Then the intro renders**, and `check-ref`'s page comparison can be run against
   the machine rather than against the Python reference.

Gate D3 is a prerequisite for D4 being meaningful, and C4 (the reader) is a
prerequisite for D4 rendering anything.

---

## Phase E - pacing, input, sound

### E1. Pacing

`op_blitFramebuffer` (`vm.cpp:274-296`) is the frame boundary and does four things:
handles the special keys, sleeps for `vmVariables[0xFF] * 20` ms **minus the time
already elapsed since the last blit**, zeroes `vmVariables[0xF7]`, and updates the
display.

The subtraction is the part worth copying exactly: the pause is a deadline, not a
delay, so a frame that took 60 ms of a 80 ms budget sleeps 20 and the game keeps
time. A port that sleeps the full 80 runs at two thirds speed and looks correct
while doing it.

Our clock is the 50 Hz frame interrupt, so the arithmetic is in refreshes rather
than milliseconds: `slices * 1` refresh each, wait until the counter reaches the
deadline, and **if it has already passed, do not wait** - that is how the 0.73% of
overrunning frames degrade, by losing time rather than by dropping out of sync.

`updateDisplay` (`video.cpp:567-589`) takes a page id, with `0xFE` meaning "no
change" and `0xFF` meaning "swap the two display pages", and applies a pending
palette change **before** presenting. On our hardware presenting is `NextReg $12`
and the palette is already resident in one of the two 256-entry Layer 2 palettes,
so both are register writes and the order between them is what matters: palette
first, then the flip, or one frame shows new pixels in the old palette.

### E2. Input

`inp_updatePlayer` (`vm.cpp:501-537`) maps a direction mask and one button into six
variables, and the mapping has two quirks worth reading off the source rather than
inferring:

| variable | meaning |
|---|---|
| 0xE5 | up/down, where **up is checked twice** - once to set -1, once to set the jump |
| 0xFB | jump/down: down is 1, up is -1 |
| 0xFC | left/right: right 1, left -1 |
| 0xFD | a bitmask: right 1, left 2, down 4, up 8 |
| 0xFA | the action button, 0 or 1 |
| 0xFE | the same mask plus 0x80 for the button |

Left and right both set their value, so pressing both gives left. `0xE5` is
assigned `ud` and then **overwritten** by -1 if up is held, which is not the same
as `0xFB`.

`inp_handleSpecialKeys` (`vm.cpp:539-566`) is pause, which is refused during parts
1 and 2, and the code screen, which requests the password part - the game's own
level select. Both worth having; neither is on the path to the intro rendering.

Part 0x3E89, the password screen, also consumes typed characters into
`vmVariables[0xDA]`, uppercased by `& ~0x20` (`vm.cpp:488-495`).

### E3. Sound

**This is no longer unscoped, and it is bigger than it looked.** Sound is live
98.3% of the intro at a mean of 2.83 voices; see *Structure, heap and voices*. It
is a permanent cost, not an occasional one.

**What the engine does.** Four channels of 8-bit signed PCM
(`mixer.cpp:96-146`). Each channel holds a sample pointer, a 24.8 fixed-point
position, an increment of `(freq << 8) / outputRate`, a volume of 0 to 0x3F, and an
optional loop point. Per output sample the mixer linearly interpolates between two
adjacent sample bytes by the fractional part, scales by `volume / 0x40`, sums into
the buffer and clamps to int8. A non-looping sample deactivates its channel at the
end; a looping one wraps to `loopPos` and plays forever.

Sound effects come from `op_playSound` with a frequency **index** into a 40-entry
table running 0x0CFF to 0x7BBD - 3,327 to 31,677 Hz (`staticres.cpp:61-67`) - and
a resource whose first eight bytes are a header: length and loop length, both in
words (`vm.cpp:668-694`).

Music is a four-channel tracker (`sfxplayer.cpp`): a module of 15 instruments,
a 128-entry order table and 1,024-byte patterns, stepped by a timer whose period is
`delay * 60 / 7050` ms, four bytes per channel per row. A row can set a volume with
effect 5 or 6, stop a channel with note `0xFFFE`, or write
`vmVariables[0xF4]` with note `0xFFFD` - **the music drives a VM variable**
(`sfxplayer.cpp:183`, wired in `vm.cpp:48`), which is how the game synchronises to
the score. Note periods convert as `7159092 / (period * 2)`, straight Amiga
arithmetic.

That last one is a coupling, not a detail: the sound tick writes into the VM's
input, so the mixer cannot be a wholly separate subsystem that runs when there is
time spare. It has to tick on schedule whether the renderer is busy or not - which
is what the ring-and-interrupt design gives, and what a "mix at the end of the
frame" design would not.

**The hardware, and why most of this is already built.** wolf3d-next has a proven,
measured digitised-sample path that is the same shape: zxnDMA in burst mode
streaming a 2K ring buffer to the DAC on port `$DF` with auto-restart, at a rate
set by the prescalar, while a tick asks the DMA where it is and mixes ahead of it.
It cost 2 to 7% of the machine there for one to four voices. Its `docs/sound.md` is
the reference, and it depends on the same three local ZEsarUX patches this project
already carries.

Three things Another World adds:

1. **Per-voice resampling.** Wolf3D's samples all play at one rate; these span
   3,327 to 25,031 Hz and each channel has its own. So each voice needs the 24.8
   accumulator, which is three bytes of add and a page-crossing fetch per output
   sample.
2. **64 volume levels**, against Wolf3D's nine fixed attenuation tables. Either a
   64 x 256 table, which is 16,384 bytes and so exactly two 8K pages, or Z80N's
   `MUL D,E` on the magnitude with a conditional negate. Measure both; the table is
   probably one `ld a,(hl)` and the multiply is 8 T plus the sign handling.
3. **Loops**, which Wolf3D has none of. A looping voice never ends on its own, which
   is why occupancy is what it is.

**The output rate was the one real decision, and it is now measured rather than
argued.** `make check-mix` says four voices cost **295 T an output sample**, so:

| rate | mixer | with the renderer's 24.8% | |
|---|---|---|---|
| **22,050, as the reference** | **23.2%** | 48% | **chosen** |
| 15,625, one per scanline | 16.5% | 41% | the first lever if needed |
| 11,025 | 11.6% | 36% | decimates the top third of the frequency table |

**Mix at 22,050 Hz**, the reference's own rate, so nothing is lost to decimation.
See *The mixer, priced on the machine* for the rest: the volume table beats
`MUL D,E` by 127 T a sample, interpolation costs 203% more than the whole rest of a
voice and is dropped, and the advance must be branchless because it is 47% of a
storing voice.

**What cannot be a byte-exact gate.** Every other gate here compares against the
real engine byte for byte. Sound cannot: we choose a different output rate, so the
samples differ by construction. So the specification has to be a **host reference
mixer at our chosen rate** - the same role `tools/refvideo.py` plays for the
rasteriser, and the same discipline. `sound.txt` is already the event trace it
needs to consume.

### E1 and E2 - DONE, Gate E's first two claims passed

`make check-pace`, and both are checked against a model of the reference rather
than against a picture.

**The input mapping matches over all 32 combinations** of the four directions and
the button, every one of the six variables. The two quirks that only reading
`vm.cpp:586-638` gives you are both reproduced: left and right together give
`0xFC = -1`, left winning because both branches assign; and `0xE5` is assigned and
then overwritten by the up test, which is a different path from the one `0xFB`
takes. A port that got either wrong would still feel like it worked.

**Pacing holds its deadline**, measured in refreshes from the machine's own 50 Hz
tick:

| asked | work done | mean gap | verdict |
|---|---|---|---|
| 4 | 0 | 4.00 | paces to the request |
| 5 | 0 | 5.00 | paces to the request |
| 1 | 0 | 1.00 | paces to the request |
| 4 | 2 | 4.00 | absorbs work inside the pause |
| 4 | **6** | **6.00** | overran, and kept the overrun |

The last row is the claim that matters. A frame asking for four refreshes and doing
six refreshes of work comes out at **six, not ten**: the deadline advanced by four,
had already passed, and the wait was skipped. That is the reference's own
arithmetic - the pause is a deadline a slow frame eats into, not a delay added on
top of it - and it is how the 0.97% of frames that overrun degrade.

**Two things fell out of building it**, both about IM 2 rather than about pacing.
The interrupt cannot be IM 1 here: that puts the handler at `$0038` in ROM, which
cannot coexist with paging RAM over the bottom 16K, and the VM's bytecode window
does exactly that. And an IM 2 vector table needs **257** bytes, not 256 - the Z80
reads the vector from `I<<8|databus` and the byte after it, so a databus of `$FF`
reads the last table byte and one past the end. The first version also placed the
table at `$8100` and filled 256 bytes over this program's own instructions, which
presented as the machine simply never finishing.

### E3 - built, and Gate E's third claim passed

`make check-snd`. The architecture is wolf3d-next's, which is proven and measured
there: zxnDMA in burst mode streams a 2K ring to the DAC on port `$DF` with WR5
auto-restart, round and round, while a tick asks the DMA where it is and mixes into
the bytes ahead of that. What this port adds is everything Another World's mixer
does that Wolf3D's does not - per-voice resampling, 64 volume levels through a
table, and loops - and that is what is under test.

**The mixer's bytes are exact.** Four voices at four real rates from the trace -
10,559, 25,031, 3,327 and 14,915 Hz, so increments of 0.958, 2.270, 0.302 and
1.353 - mixed into the real ring at three block lengths, and **every byte matches a
host model of the reference's own arithmetic**. The first active voice stores and
biases; the rest add a signed delta to an unsigned accumulator and saturate.

**The block splitting is the design, and it is why the inner loop has no tests in
it.** A voice's page boundary, its sample end and its loop point are all resolved
before the loop runs by cutting the block short - O(1) a block instead of 18 T a
voice a sample.

**The DMA empties the ring and wraps.** Its port A address sampled every 20 ms over
0.78 s: **9 wraps, nothing outside the ring**, so auto-restart is reloading the
address as the patch intends.

**The rate reads 10% high, and that is worth stating rather than hiding.** Prescalar
40 should give 875 kHz / 40 = 21,875 bytes a second, and the fit over those samples
says 24,079 - 482 bytes a 20 ms tick rather than 437, so about 1,162 T a byte where
1,280 is intended. The likely cause is the emulator's own accounting rather than the
programme: the local patch derives the per-byte delay as four T-states times the
turbo multiplier, and the frame interrupt is 50.08 Hz rather than 50. This is the
same territory as wolf3d-next's "what the recording can and cannot say" - a
sampled address is a coarse instrument, and the accurate check there was a
frequency fit against a recording. **Carried as a hardware-readiness item, not as a
passing number.**

Everything here rests on the **three local ZEsarUX patches**. Upstream the
prescalar is read and used as a boolean, a read of the DMA port returns zero, and a
block stops at its end whatever WR5 says - so none of it is reproducible there.

### E4. Gate E

1. `make check-pace` - a script asking four slices produces frames 80 ms apart,
   measured from the recording, and a deliberately overlong frame loses time rather
   than drifting out of step.
2. `make check-input` - each key sets the six variables to the values the table
   above says, including both-directions-at-once and the double assignment to 0xE5.
3. `make check-mix` - the machine's ring, read back, matches a host mixer fed the
   same event trace at the same rate, sample for sample; then the recording carries
   each voice at the right rate through its overlap, as wolf3d-next's `check-digi`
   does.

---

## Phase F - the rest of the game

Scoped, not specified, and it is honest to say which parts are genuinely unknown.

**F1. The parts beyond the intro - DONE, and six of seven of them run.**

`make check-parts`. The game's own route onward is the password screen and its codes
are not in the data, so the probe requests a part directly - which
`engine.cpp:75-85` warns can crash. Each part is therefore reported separately and
the ones that did not run say so, rather than being averaged in.

| part | frames in it | drew | polys/frame | spans/frame | worst frame | bitmaps | verdict |
|---|---|---|---|---|---|---|---|
| 3, water | 5,795 | 4,169 | 62.3 | 429 | 3,637 | 0 | ran |
| **4, jail** | 5,795 | 5,698 | 63.0 | **1,121** | **12,329** | 0 | ran |
| 5, cave | 5,795 | 3,977 | 17.4 | 96 | 2,643 | 0 | ran |
| battlechar | 5,795 | 5,470 | 75.7 | 764 | 6,946 | 0 | ran |
| **7, arena** | 5,795 | 5,253 | 46.9 | 490 | 3,096 | **70** | ran |
| 8, baths | 5,795 | 345 | 1.5 | 27 | (20,306) | 0 | **did not run** |
| 9, final | 5,795 | 5,695 | 4.2 | 43 | 225 | 0 | ran |

**Five numbers this project rested on came from two parts, and four of them move:**

- **the worst frame is 12,329 spans, in the jail** - 3.4 times the 3,637 that parts
  2 and 3 gave.
- **the deepest hierarchy nesting is 5, not 4.** The reader's stack is eight deep
  with an assert, which the plan argued for precisely because the measurement was
  of two parts; it earned its keep.
- **peak script-heap use is 305,919 bytes, not 241,363** - 38 pages of 8K, 19 banks
  rather than 15.
- **the pause the scripts ask for is not one profile.** Part 3 asks for 4 slices
  71.8% of the time; **the jail asks for 7 slices - 140 ms - 78.9% of the time.**
- widest fan-out (99 here against 119) and the longest record (40 vertices) do not
  move.

**And the budget holds, which is the point of having measured it.** Scored against
the pause each frame itself requests:

| | mean load | p99 | frames overrunning |
|---|---|---|---|
| part 3, gameplay | 37.3% | 3.97 | 0.97% |
| **part 4, the jail** | **50.8%** | 4.29 | **0.53%** |
| part 7, the arena | 42.8% | 3.62 | 0.42% |

The jail draws three times the spans and overruns *less often*, because its scripts
ask for 140 ms a frame rather than 80. With the mixer's 23.2% on top, the jail is
74% of the machine as the rasteriser stands and 52% at the floor - tight, and the
two remaining optimisations are what the headroom is for.

**70 full-screen bitmaps load in the arena.** That path had zero loads in 72,000
frames of parts 2 and 3, which is why Gate A covers none of it and
`tools/mkassets.py`'s deplaner has never been compared against the engine's. It is
locatable now, and that comparison is a host-only check needing no machine.

One fault worth recording, because the wrong version was far more convincing than a
crash: the probe writes `frames.txt` into its own working directory, and running it
from the repository root left every part reading one stale file - so the table came
out **identical for seven different parts** and called them all sane.

**F2. The full-screen bitmap path, which no gate covers.** `RT_POLY_ANIM`
resources - 12 of them, 32,000 bytes each - are loaded into a staging buffer and
deplaned into page 0 by `Video::copyPage(const uint8_t *)` (`video.cpp:523-549`).
**Zero were loaded in 72,000 frames**, so Gate A's byte-exactness says nothing
about this path, and `tools/mkassets.py` has a host port of the deplaner that has
never been checked against the engine.

Its shape on the Next is pleasant: the four bit planes are 8,000 bytes each, so
**one plane per 8K page**, and the deplaner reads one byte from each of four pages
and writes eight pixels. Planes in slots 2 to 5, the destination band in slot 6,
code in slot 7, ROM in 0 and 1 - it fits exactly. It also needs the same
nearest-neighbour resample as the palette bitmaps, since 320x200 has to become
256x192.

Find where they are used first: `grep` the decoded resource types for which parts
reference them, and if it is only the ending, it is an ending-sized problem.

**F3. Save and load.** The reference serialises the VM, the resource heap pointers
and the mixer (`serializer.cpp`). Ours has a page-counter allocator instead of a
heap, so a save file is the variable array, the thread tables, the part id and the
mixer's channel state - a few hundred bytes, not a memory image. Not required for
the game to be playable.

**F4. The palette question, still David's.** Nine palette resources, 32 palettes,
RGB444 to RGB333: 44.4% of palettes lose nothing, 35.1% lose one colour, and the
worst loses five of sixteen. A quantiser that nudged colliding entries apart would
trade hue for separation at no run-time cost. Same class of call as coarse detail
and pixel doubling on the other project.

**F5. The 320x256 mode**, decided against in decision 1 and worth re-reading once
the game runs, since the game's own 320x200 maps into it without horizontal
resampling at all. The cost is five banks of stride-256 columns and a rasteriser
that writes down columns rather than along rows, which is a different program, not
a flag.

---

## What is next, and what gates what

The order is forced by measurement, not by preference. Each step below is
unblocked only once the one it names has produced a number.

| # | do this | because | gate |
|---|---|---|---|
| 1 | ~~price the mixer's inner loop~~ **DONE** | it was the largest unpriced cost, and it decided the output rate | `make check-mix`: **295 T a sample for four voices**, 23.2% of the machine at the reference's own 22,050 Hz |
| 2 | ~~measure the per-polygon setup cost~~ **DONE** | gameplay spends its time there, and every budget number carried it as a guess | `make check-polycost`: **2,974 T a polygon**, and it found the span cost had been understated threefold |
| 2a | ~~the rasteriser optimisations~~ **DONE** | one gameplay frame in eight was overrunning its own deadline | fused row loop and unrolled fills: **1,296 T a span, 0.94% overrunning** against a 0.73% floor, Gate C still 49,152/49,152 |
| 3 | ~~C4, the polygon reader~~ **DONE, both halves** | nothing renders a real scene without it | `check-reader`: 10,700 draws, 64,897 fills, field for field. `check-readmachine`: **49,152/49,152 pixels** over 771 polygons at 55 distinct zooms |
| 3a | ~~C5a, widen the geometry to 16 bits~~ **DONE** | the machine reader was blocked on it: the trace reaches 483 and the rasteriser held bytes | Gate C with a `wide` bucket reaching 303, and `calc_step` **576 of 576** exact as words |
| 4 | ~~C6, the segment window~~ **DONE** | a 65,230-byte segment cannot be mapped flat | the same gate: the whole 65,230-byte segment is read through a two-page window at `$0000` |
| 5 | ~~D4's read rate~~ **DONE, and the answer is "not here"** | a four-second part load is a design decision, not a detail | `make check-load`: the path works and every byte arrives; the rate is r = -0.518 against size, so the emulator cannot time it |
| 6 | **D2 and D3, the scheduler and opcodes** - built, gate **NOT** passing | the rest of the port hangs off them | Gate D: 354 records observed identical, not repeatably. The one gate of nine that does not pass |
| 7 | ~~E1 and E2, pacing and input~~ **DONE** | the game is unplayable without them and they are small | `make check-pace`: all 32 input combinations, and a 4-slice frame doing 6 refreshes of work comes out at 6 |
| 8 | ~~E3, sound~~ **DONE** | priced at step 1, and the ring proven on the other project | `make check-snd`: four voices byte-exact at three block lengths, 9 ring wraps, nothing outside it |
| 9 | ~~F1, a later part~~ **DONE** | everything so far was two parts of ten | `make check-parts`: six of seven parts run, and four of the five numbers that rested on two parts move |

Steps 1 and 2 are measurements, not code, and they are first because both of them
can still change what gets built. Steps 3 and 4 are the remainder of Phase C and
can proceed in parallel with them.

**Step 1 came back under its threshold.** 23.2% of the machine at the reference's
own rate against a 35% limit, so sound keeps its fidelity: 22,050 Hz, four voices,
the volume table rather than `MUL`, and no interpolation.

**Step 2 changed one thing.** The per-polygon cost it set out to measure came in at
2,974 T, inside the range the plan had swept, so that was sound. But measuring it
required decomposing the rasteriser, and that showed the plan's 672 T a span
describes step 0's purpose-built span row rather than the rasteriser, which charges
2,037 T. So **step 2a is now the two optimisations**, which are required rather
than optional and which measurement says are sufficient: they take the gameplay
mean from 48.4% of its pause to 22.6% and the overrun rate from one frame in eight
to one in 137.

---

## Risks, worst first

Reordered on 2026-09-13. What had been risk 1 is now risk 7, and what had been
risk 2 is now risk 1 - which is the ordinary consequence of measuring two things
that had been estimated.

1. ~~**The mixer is a permanent cost and its budget is the least evidenced number
   here.**~~ **Closed by measurement.** The experiment named here was run:
   `make check-mix` prices four voices at 295 T an output sample, **23.2% of the
   machine at the reference's own 22,050 Hz** against a threshold of 35%. Sound is
   still live 98.3% of the intro at a mean of 2.83 voices - that has not changed -
   but it is affordable at full fidelity. What remains of the risk is that this
   prices the *mixer*, not the *player*: the tick that decides which voices are
   live, splits blocks at page and loop boundaries, and reads the DMA's position is
   unwritten, and wolf3d-next's equivalent cost seven faults to get right.
2. ~~**The rasteriser's geometry is 8-bit and the game reaches 483.**~~ **Closed.**
   Widened to signed words throughout, `calc_step`'s product to 16 x 16, and the
   vector has a `wide` bucket reaching 303. What the episode leaves behind is the
   general risk it is an instance of: **a gate covers what its vector happens to
   contain.** `mkpolytest.py` picks for fill mode, clipping edge, vertex count and
   size, and for as long as none of those correlated with a box over 255 the 8-bit
   format was wrong and green. The same question is open for every bucket that
   does not exist yet - a zoom other than the identity, a hierarchy five deep, a
   record whose first byte is neither a leaf nor a 2.

3. ~~**Everything is measured on two parts out of ten.**~~ **Closed.**
   `make check-parts` runs six of the seven, and four of the five numbers that
   rested on two parts moved: the worst frame is 12,329 spans not 3,637, the
   deepest nesting 5 not 4, the peak heap 305,919 bytes not 241,363, and the pause
   profile differs by part - the jail asks for 140 ms a frame where part 3 asks for
   80. The budget survived all of it: the jail draws three times the spans and
   overruns *less* often. What remains is that part 8 does not survive being
   requested cold, and that no part is reached the way a player reaches it.

   The original text follows. Parts 2 and 3 were all the
   probe reaches. The hierarchy depth of 4, the fan-out of 119, the 83-byte
   record, the heap peak of 241,363 and every frame-cost percentile are properties
   of those two parts. **Cheapest experiment:** the probe types a level code at the
   password screen, which `inp_handleSpecialKeys` already reaches, and the same
   reports run over a later part.
4. ~~**The per-polygon setup cost has never been measured.**~~ **Closed, and it
   opened a bigger one.** `make check-polycost` measures 2,974 T a polygon, inside
   the swept range. But decomposing the rasteriser to get it showed that **the
   plan's 672 T a span was step 0's purpose-built span row, not this code**, which
   charges 2,037 T for the same 22-byte opaque span. As built, one gameplay frame
   in eight overruns its own deadline and the mean load is 48.4%, not 24.8%. The
   two optimisations step 0 measured are required and sufficient - 552 T a span,
   22.6% mean, one frame in 137 - so this is scheduled work rather than an open
   question. **The residual risk is that they do not reach their measured
   targets in the real rasteriser**, where the accumulators are shared with the
   trapezoid walk rather than being a benchmark's four words.
5. **The full-screen bitmap path is unverified and its host port unchecked.** Zero
   `RT_POLY_ANIM` loads in 72,000 frames, so Gate A's byte-exactness covers none of
   it, and `mkassets.py`'s deplaner has never been compared against
   `Video::copyPage`. **Cheapest experiment:** deplane one such resource on the host
   both ways and compare - no machine involved.
6. **32K may not hold the C image.** `actors.c` was 5K of code and 10K with data,
   for one state machine. The VM adds 256 int16 variables, two 64-entry word
   tables, two 64-byte state arrays, a 256-entry call stack and a 2,762-byte string
   table - about 3.5K of data before any code. The fallback is the banked-call
   plumbing this port hoped to avoid. Read the size off the build, which reports it
   for nothing.
7. **IY under `-clib=sdcc_iy` against esxDOS calls.** The library reserves IY and
   DOS calls may destroy it. Never exercised, because no preflight program has
   opened a file - and Phase D opens files as its first act. One C program that
   opens a file through the assembly loader and then reads a global settles it; the
   fix is `sdcc_ix` or saving IY.
8. **The frame budget, now the mildest of these.** 0.73% of gameplay frames
   overrun the pause their own script asked for, at a mean load of 24.8%. Room
   entries are where it happens, and a long frame there reads as a load. Both known
   optimisations remain available and measured. Listed at all because the previous
   version of this list had it first, on a comparison against a one-slice pause the
   scripts almost never request.
9. **Hardware divergence from the emulator**, deliberately minimised rather than
   solved. The MMU window means nothing depends on whether the DMA honours
   `$123B`; dropping the DMA span path means nothing depends on the suspect 1.87
   T/byte. Sound puts some of that back, because the ring rests on all three local
   ZEsarUX patches. `make check-dma` on the KS3 when it arrives.
10. **Dependence on an upstream image tag** for z88dk. Mitigated by pinning the
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
- **A harness that does nothing measures nothing.** The host probe's `addTimer`
  was a stub returning a token, so the music player never ticked, no note ever
  reached the mixer, and voice concurrency read as 1.60 voices instead of 2.83.
  Every stub in a measurement harness is a claim that the thing it replaces does
  not matter.
- **An interactive program left alone measures its idle screen.** 57,386 of
  60,000 frames drew nothing because nobody pressed fire. The numbers were not
  wrong; they were answers to a question nobody had asked.
- **Check the denominator before optimising the numerator.** Weeks of a budget
  argument rested on "a frame is 20 ms". The scripts ask for 80. The measurement
  cost four lines in the blit opcode and reversed the conclusion.
- **Two runs, two output files, one name.** `sound.txt` and `frames.txt` are
  rewritten on every probe run; a gameplay analysis silently described the intro
  until the timestamps did not add up. Copy the outputs before re-running.
- **A trace-window analysis cannot answer a whole-run question.** Voice
  concurrency needed the entire run, so the sound log deliberately ignores the
  traced window that everything else respects.
