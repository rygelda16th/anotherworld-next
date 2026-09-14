# Where things stand

**This file is canonical.** Where it disagrees with anything else, including the
published blueprint at
`claude.ai/code/artifact/f4d9e319-0bbb-47c3-b675-3efd6413f0a3`, believe this one.
The blueprint is the shareable version of the same material, but it is a copy - and it is
**out of step as of 2026-09-14**: it still describes the project before Chain 2 started. It has
not been republished this session, and saying it "is kept in step" would be a claim this file
cannot make for it.

Last updated 2026-09-14.

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
| D - the virtual machine | **done**, Gate D passed, 763 records identical, repeatably |
| E - pacing, input, sound | **built and gated** |
| F - the rest of the game | **scoped**, three known gaps |
| **integration - a playable game** | **Chain 2, in progress: eight of thirteen steps done, one half done** |

**The end goal is a fully playable Another World with sound**, and the state of that is:
**it is one binary now, and almost all of it works, and it does not yet run.**

That sentence needs unpacking, because both halves are true. There is a single `build/aw.nex`
which boots into part 0 - the protection screen - sets its palette, bytecode and polygons up
correctly, and holds everything live at once: the frame interrupt, the DMA streaming a ring to
the DAC, the mixer refilling it from inside the interrupt, the VM, the rasteriser, the loader,
the text, the module player. Of the thirteen Chain 2 steps, **eight are done and gated** and one
is half done. The VM draws the intro's four pages byte-for-byte against the engine; text is
pixel-exact; resources arrive at runtime byte-for-byte against the card; sound plays real samples
and real music, mixed byte-exact; parts transition; full-screen bitmaps present; a 198,272-byte
save writes and every field in it matches the machine.

**And the shipped game runs zero frames.** The C's frame loop is bounded by `CTL_FRAMES`, which
only a harness pokes and which the image leaves at zero, so booting normally sets part 0 up and
then does nothing. The fix is six bytes of C and the margin between the C's top and the music code
is smaller than that. It is a memory problem, not a logic one, and it is the single thing standing
between "almost all of it works" and "it runs". See **I9** for the space, and **I10**, which
cannot start until this is closed.

See **What "done" means** for the definition and **Chain 2** for the rest.

**All nine gates of Chain 1 pass**, and that is a statement about risk rather than
about progress: it means nothing remains that we know of that could stop this
working. Gate D closed on 2026-09-13: the virtual machine dispatches exactly what
the engine dispatches - all 763 records of the reference, thread by thread and opcode
by opcode - three runs in a row with the same numbers, which is the part that had
been missing. The comparison now happens ON the machine, against the engine's own
stream shipped in the .nex, so what crosses the boundary is a 32-byte verdict rather
than eight kilobytes of trace.

What had been wrong was not the VM. z88dk's exit path is `im 1 / ei / ret`, and `EI`
delays interrupt acceptance by exactly one instruction - the `RET` - so the interrupt
lands before the caller's next instruction runs, and `$0038` here is not the ROM but
the bytecode segment MMU0 and MMU1 are holding. The machine executed Another World's
bytecode as Z80 code about twenty milliseconds after every successful run, and the
checker was reading the wreckage. **The full account is in D5**, because four other
real faults were found and fixed while chasing it and each one looked like the
answer.

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

The above are Chain 1's, and each builds its own single-purpose harness. **Chain 2's gates all
build the same `build/aw.nex` - the game** - and check one thing about it:

    make check-map     I1: all five windows and the resident code coexist
    make check-aw      I1: one program, everything live, Gate D re-run inside it
    make check-boot    I1: the VM dispatches exactly what the engine dispatches
    make check-input   I1a: a real keyboard, through to the VM's own variables
    make check-draw    I2: the intro's four pages, byte for byte against the engine
    make check-res     I3: every resource the bytecode asks for, against the card
    make check-text    I4: every string the intro draws, pixel-exact
    make check-mus     I5: the module, the voices, op_playSound, and the mixer's OUTPUT
    make check-part    I6 and I8: part transitions, and the game's own boot into part 0
    make check-bmp     I7: a full-screen bitmap, in page 0, not resident
    make check-save    I9: a save against the machine, and a load back (load half RED)
    make check-bitmap  I7: mkassets.py's deplaner IS the engine's, on real resources

`make check-ref` and `make check-poly` need the host probe built and run first;
see `preflight/hostprobe/README.md`. `make diag D=_name` runs a one-off script in
`tools/` against a live emulator - the habit that has settled more of these than
reasoning has.

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

### D5. Gate D - PASSED, and what it cost to get there

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

**The final result is 763 of 763 records identical, three runs with the same
numbers** - every record the reference contains, thread by thread, opcode by opcode,
program counter by program counter. `make check-boot` prints it.

**Getting there took most of a session, and the history below is kept deliberately.**
For a long time the same inputs gave 0, 64, 122 and 354 matching records on different
runs. Non-determinism with identical inputs means something uninitialised, and four
separate uninitialised or misconfigured things were found and fixed along the way -
each of them a genuine fault, none of them the cause. That is the interesting part,
and *The interrupt that ate the evidence* at the end of this section is the answer.

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
| `$4000-$7FFF` | **not available DURING A DOS CALL** - bank 5 holds the ZX system variables from `$5B00`, which esxDOS needs, and staging a read here loaded 68 bytes and then failed. Outside a DOS call it is ours, and **I1 proved it**: `make check-map` |
| `$8000-$82xx` | `vmtest.asm`: jump table, code, data |
| `$8C00-$AExx` | the C and its data, low on purpose |
| `$BF00` | the stack. What SAVENEX declares; moving it to `$FF00` broke the load |
| `$C000-$DFFF` | the trace buffer |
| `$E000-$FFFF` | the loader's staging window |

**So the channel went.** The C now writes everything - the header the checker pokes
and the records it reads - into one 8K block at `$C000`, which it has demonstrably
always been able to write since records appeared there correctly all along. After
`main` returns, the assembly writes that block to `AWTRACE.BIN` through esxDOS, the
path step 5 proved byte-exact. The checker reads the file. **The only memory it
touches now is six bytes of header at a fixed address in assembly-owned RAM.** A
file either holds the records or it does not.

**The trace file was the wrong idea, and finding out why took the rest of the
session.** It is recorded here because the reasoning was sound and the conclusion
still wrong, which is the sort of thing worth keeping.

**Two things had to be right before it would write at all**, and both are worth
carrying:

**The ROM has to go back first.** The virtual machine has been paging bytecode over
`$0000-$3FFF` through MMU0 and MMU1, and esxDOS is reached by `RST $08`, which needs
the ROM at `$0000` and pages its own memory over the bottom 16K besides. `$FF` is the
MMU value that means the ROM.

**And the open mode is `$0C` alone, not `$0C | $02`.** ZEsarUX's handler switches on
the mode byte as a whole rather than testing bits, and the cases it knows are `$01`
read, `$03` read-write, `$06` create-if-absent-and-write, `$0A`
open-or-create-and-write, and `$0C` create-or-truncate **on its own**. `$0E` - that
last one OR'd with the write bit, which is what the bit names suggest - is not a case
it knows, and it refuses the open. Read the emulator's accepted modes rather than the
ones that seem to follow from the constants. Both failures produced no file and no
message until `write_trace` was made to record the error code and which call refused
it.

The seed is taken from the host's own run, because the reference sets variable
`0x3C` from `time(0)` and the two streams would diverge the first time the
bytecode read it.

#### The interrupt that ate the evidence

**z88dk's exit path is `im 1 / ei / ret`.** Four bytes, `ED 56 FB C9`, at `$8C40` in
this build, visible in `build/vm_CODE.bin` with `xxd`. And `EI` does not take effect
immediately: the Z80 defers interrupt acceptance by exactly one instruction, and that
one instruction is the `RET`. So the interrupt is taken **before the caller's first
instruction runs**.

`$0038` is not the ROM here. MMU0 and MMU1 are holding the bytecode segment the
virtual machine has spent the last two hundred milliseconds reading. So the Z80
started executing Another World's bytecode as Z80 instructions, the stack ran down
from `$BF00` and wrapped, and the smear covered every counter this gate reads - the
record count, the frame count, the fault code, the segment length, all of it, with
whatever those bytes happened to push.

**That is the whole of "Gate D will not repeat".** The virtual machine had been
finishing correctly in under a quarter of a second and then destroying itself about
twenty milliseconds later, and the checker was reading the wreckage. How much
survived depended on how long the read took, which is why identical inputs gave
different numbers. A `di` placed immediately after `call CC_ORG` is one instruction
too late, every time; it was tried, and it changed the smear without stopping it.

**The fix is that `main` never returns.** Its last statement is `for (;;)
CTL_FINISHED = 0x5A;`. Nothing runs the code that turns interrupts on, so nothing
needs to be true about the ROM, the MMU or the timing. `write_trace` came out of the
path with it - calling esxDOS meant putting the ROM back over `$0000-$3FFF`, taking
the bytecode out from under a machine still holding pointers into it, and the `RST
$08` did not come back.

**What found it, after everything else had failed, was stopping earlier on purpose.**
`stage_stop` in `src/vmtest.asm`: 1 clears the bytecode pages and stops, 2 loads the
segment and stops, 0 runs the lot. Stages 1 and 2 were clean and repeatable and the
loader read 9,871 bytes - exactly `RES18.BIN` - every time. Then an **opcode budget
of zero**: the C dispatches nothing, sets `finished` to `$5A`, and leaves a control
block that reads back perfectly - segment length 9,871, expected count 679,
out-of-budget set - while `done` is still zero, because the assembly never got back
to set it. The virtual machine cannot have been at fault in that run. Everything
after the C was.

**The general lesson, which is not specific to this project.** A program that hands
control to somebody else's runtime gets that runtime's interrupt state back, not its
own. Ask what the CRT does on exit before believing any measurement taken after it -
and if a measurement is not repeatable, suspect the reader before the thing being
read.

#### The comparison moved onto the machine

The engine's own stream now ships **in the .nex at `$E000`** - `tools/mkexpected.py`
emits it as four-byte records - and `aw_logrec` checks each record against it as the
record is written. On a mismatch the VM stops dead: it records the index, its own
record and the engine's, and returns. Nothing runs afterwards.

That shape is better than a trace for three reasons, and the third is the one that
mattered:

1. The verdict is 32 bytes, and the checker reads it twice and compares, so a bad
   read is a verdict that disagrees with itself rather than a rasteriser bug.
2. It says WHERE, at the record, rather than handing back eight kilobytes to diff.
3. **It stops before the damage.** Whatever the VM did wrong, it did it before the
   first wrong record; anything that destroys state does so after. A trace read at
   the end can only ever show the aftermath.

`src/aw/vm.c` also gained a fault trap - a code, the program counter and one word of
context, first one wins - for five conditions the reference never has to check
because its bytecode is always bytecode:

| fault | what it means |
|---|---|
| 1 | the pc left the segment that was loaded |
| 2 | `resetThread` over a range outside the thread table |
| 3 | an opcode the reference calls `error()` on |
| 4 | `ret` with nothing on the call stack |
| 5 | a record the engine did not produce |
| 6 | the reference ran out, every record in it matched |

Fault 2 deserves a note. `op_resetThread` takes a first thread and a last, masks the
last to 0-63 as the reference does, and takes the difference **as `int8_t`** - which
is what `vm.cpp:96-99` does. A first of 200 with a last masked to 10 gives a
*positive* count of 67: sixty-seven words written past a sixty-four word array, over
whatever follows it. The reference has the same hazard and never meets it, because
its script is always the script. Ours was reading past the end of a segment at the
time, so it met it immediately.

#### Three traps in the harness, each of which produced a wrong answer first

**The reference must be LONGER than the run under test.** The first version asked the
probe for 40 frames and the machine for 40 frames, and the machine matched all 679
records and then produced a 680th with nothing to compare it against. That is neither
a pass nor a failure - it is a reference that ended before the test did.
`AW_OP_FRAMES` in `preflight/hostprobe/headless.cpp` now sets the length, and
`tools/checkboot.py` takes its frame count from the reference rather than from a
constant.

**The reference must be generated with the input the machine has, which is none.**
A reference generated with the probe's synthetic input diverged at record 53, on a
`condJmp` at pc 135 reading variable `0xFA` - the hero's action button, which
`inp_updatePlayer` sets and the VM under test has no way to know about. The bytecode
there is `0a 01 fa 00 09 b8`: compare variable 250 against 0, jump to 2488 if it
differs. The engine jumped and the machine did not, and both were right about their
own world. Run the probe with autoplay off for this gate.

**The probe counts BLITS, not VM frames.** `instrFrame()` hangs off
`Video::updateDisplay`, so what `ops.txt` labels frame *N* is the *N*th blit. 45 of
the probe's frames is 44 of the VM's here. The record stream carries no frame
boundaries, so the comparison cannot tell them apart and does not need to - but
asking both sides for "45 frames" asks for different amounts of work, and the
difference shows up as the reference running out early.

#### Two smaller things, recorded so nobody spends the time again

**ZEsarUX breakpoints are not a debugging tool in this container.** Two independent
reasons. Conditions reject a `0x` prefix - `PC<0x8000` is refused, `PC<32768` and
`PC<8000h` are accepted - and the default action on a hit is to *open the debugger
window*, which `--vo null` cannot do, so the CPU never stops. Several hours went into
breakpoints that were firing and doing nothing. `set-breakpointaction` with `write`
is the headless-usable form; stopping after a named stage is better.

**`clear_code`, because the bytecode window reaches eight 8K pages and the segment
fills two.** Everything past the segment's last byte was the previous run's memory,
because `smartload` does not clear RAM. The fill byte is a variable rather than a
constant so the experiment can be run in reverse: if behaviour changes when the fill
changes, the VM is reading past the end of what it was given, which is a fault in the
VM rather than in the memory it was handed.

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
3. **The opcode trace matches the host.** **This is the claim that matters, and it
   passes: 763 of 763 records.** It catches a wrong operand length at the opcode that
   has it, rather than as a wrong picture 4,000 opcodes later. It is the VM's
   equivalent of Gate C's bisect, and for the same reason - **a whole-image
   comparison only ever says that something is wrong**. The comparison happens on the
   machine, against the engine's own stream in the .nex, and the VM stops on the first
   record that differs.
4. **Then the intro renders**, and `check-ref`'s page comparison can be run against
   the machine rather than against the Python reference. **This one is not done**: it
   is D4, the next piece of Phase D, and it is a milestone rather than part of Gate D.

Claims 1, 2 and 3 are Gate D and all three pass. Gate D3 was the prerequisite for D4
being meaningful; C4 (the reader) is the prerequisite for D4 rendering anything, and
it passed earlier. **So D4 is unblocked on both sides** - what it needs now is the
video calls wired to the real rasteriser instead of to the counters, and the stubbed
`op_updateMemList` replaced by the loader step 5 measured.

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

## What "done" means

The end goal is **a fully playable Another World with sound**: a person starts it,
plays from the first screen to the ending, and hears what they should hear. Nothing
in this document is finished until that playthrough happens.

That needs saying because the chain below it was never a plan to build the game. It
was a plan to find out whether the game was POSSIBLE, and it answered that. Reading
"nine of nine gates pass" as "nearly done" is the mistake it invites: what it
actually means is *nothing remains that we know of that could stop this working*.
Distance to a playable game is Chain 2, and Chain 2 has not been started.

**The definition, agreed 2026-09-13:**

| | |
|---|---|
| plays through | the first screen to the ending, every part, unaided |
| input | keyboard **and** joystick |
| picture | polygons, full-screen bitmaps, text, palettes, page flips, scrolling |
| sound | the four-voice mixer for SFX **and** the music player |
| codes | the code-wheel screen implemented, **and** a build flag that bypasses it |
| state | save and load |
| time | every frame inside its own deadline, or an overrun rate measured and stated |
| the last gate | a full playthrough under the patched ZEsarUX |

**Real hardware is a named follow-on, not part of this.** The final gate is the
emulator deliberately: the three local ZEsarUX patches (`prescalar`, `readback`,
`autorestart`) are not upstream, so every number here reproduces only in our own
container, and the KS3 has not arrived. Card boot, the real joystick wiring and
timing on metal are **H1** at the end of Chain 2, and they are the one part of this
plan whose gate cannot be run yet.

---

## Chain 1 - the risk chain. COMPLETE.

Nine steps, each an experiment that could have changed or stopped the build. **The
order was forced by measurement, not by preference:** each step was unblocked only
once the one it names had produced a number. Integration was deliberately absent -
integration cannot kill a project, it is only work - which is why finishing this
chain is not the same as having a game.

| # | do this | because | gate |
|---|---|---|---|
| 1 | ~~price the mixer's inner loop~~ **DONE** | it was the largest unpriced cost, and it decided the output rate | `make check-mix`: **295 T a sample for four voices**, 23.2% of the machine at the reference's own 22,050 Hz |
| 2 | ~~measure the per-polygon setup cost~~ **DONE** | gameplay spends its time there, and every budget number carried it as a guess | `make check-polycost`: **2,974 T a polygon**, and it found the span cost had been understated threefold |
| 2a | ~~the rasteriser optimisations~~ **DONE** | one gameplay frame in eight was overrunning its own deadline | fused row loop and unrolled fills: **1,296 T a span, 0.94% overrunning** against a 0.73% floor, Gate C still 49,152/49,152 |
| 3 | ~~C4, the polygon reader~~ **DONE, both halves** | nothing renders a real scene without it | `check-reader`: 10,700 draws, 64,897 fills, field for field. `check-readmachine`: **49,152/49,152 pixels** over 771 polygons at 55 distinct zooms |
| 3a | ~~C5a, widen the geometry to 16 bits~~ **DONE** | the machine reader was blocked on it: the trace reaches 483 and the rasteriser held bytes | Gate C with a `wide` bucket reaching 303, and `calc_step` **576 of 576** exact as words |
| 4 | ~~C6, the segment window~~ **DONE** | a 65,230-byte segment cannot be mapped flat | the same gate: the whole 65,230-byte segment is read through a two-page window at `$0000` |
| 5 | ~~D4's read rate~~ **DONE, and the answer is "not here"** | a four-second part load is a design decision, not a detail | `make check-load`: the path works and every byte arrives; the rate is r = -0.518 against size, so the emulator cannot time it |
| 6 | **D2 and D3, the scheduler and opcodes** - built and **gated** | the rest of the port hangs off them | Gate D: 763 of 763 records identical, three runs with the same numbers |
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

**What this chain bought.** A span costs what it costs and the rasteriser is
pixel-exact; the mixer fits at the reference's own rate; the VM dispatches what the
engine dispatches; the DMA empties the ring at rate; input and pacing are the
reference's; six of seven parts are measured and the budget holds at 74% of the
machine in the worst of them. Every expensive uncertainty is now a number.

**What it did not buy.** Anything that runs. Every `.nex` in `build/` is a
single-purpose harness. The VM's six video callbacks increment counters and return;
`op_updateMemList`, `op_drawString`, `op_playSound` and `op_playMusic` consume their
operands and do nothing; nothing loads a resource at runtime; there are no part
transitions, no text, no save, no code screen. The parts are proven and the seams
between them are untouched.

> That paragraph is Chain 1's verdict and is left as written, because it is what was true when
> Chain 1 closed. **Chain 2 has since closed all of it bar the last clause**: there is one binary,
> the callbacks draw, all four opcodes do their work, resources load at runtime, and there are
> part transitions, text, bitmaps, sound and a save. What is still true is the shape of the
> remaining problem - the seams. See *Where Chain 2 has got to*.

---

## Chain 2 - integration, to a playable game

Same discipline, different question. Chain 1 asked *can this be done*. This asks
*what order builds it*, and it is ordered on two rules:

1. **The thing that could force a redesign goes first.** Only one candidate is left
   and it is memory residency, so that is I1.
2. **Every step after it leaves something that RUNS.** No step is allowed to end
   with a component that only a checker can see. From I2 onward there is always a
   `.nex` a person can boot, and it does more than the one before it.

### Where Chain 2 has got to

| | | |
|---|---|---|
| I1, I1a | one program, the memory map, a real keyboard | **done** |
| I2 | the VM draws | **done** |
| I3 | resources at runtime | **partly** - loading gated; *claim 2* still owed |
| I4 | text | **done** |
| I5 | sound in the game | **done**, six parts gated |
| I6 | part transitions | **done** |
| I7 | the full-screen bitmap path | **done** |
| I8 | the code screen and its bypass | **done** |
| I9 | save and load | **save done and gated; load written and running, its gate red** |
| I9a | the whole suite, on the game | not started |
| I10 | playable to the end | not started, and blocked on the zero-frames bug |
| H1 | real hardware | unrunnable until the KS3 arrives |

**25 gates.** `check-part`, `check-bmp` and `check-save` are new.

### Three things this chain has taught that are not about any one step

**1. The C's BSS lives above the image sjasmplus measures, and an assertion that checks the
image checks nothing.** `ASSERT $ <= MUSIC_CODE` compared the C's *image* end against the music
code, but the C's variables sit past it - so a margin that satisfied the assertion still put the
music code inside `aw_vars`. It presented as the VM dispatching thirteen records and stopping,
and on another arrangement as 53,256 records and a fault code nothing in our source writes. Four
hypotheses were wrong before the right one. `tools/mkexp.py` emits **`CC_TOP`** from the link map
now and the build asserts against that, so it fails loudly instead of corrupting quietly.

**2. Paged code at MMU2 can host only what never touches MMU2 - which is more than "what
doesn't draw".** The 16K at `$4000-$7FFF` was empty in the image and is now where save and load
live. But MMU2 is the polygon segment window, *and* `copy_palette`'s source, *and*
`apply_palette`'s text page. The load called `aw_setup_part`, which mapped the palette over the
very code that was running, and the next instruction fetch came from palette data - showing as a
load that never finished with **no esxDOS error to explain it**. Anything moved into paged space
has to be audited for **MMU2 use**, not merely for drawing.

**3. A gate that stops one step short of the thing you care about will let exactly that thing
through.** `check-part` proves a part is *set up* and stops there - which is why it could not see
that the shipped game then runs zero frames. That limit was written into I6's own notes in as
many words, and it still took the save gate to find it. The same shape recurred inside I5: the
mixing gate proved the output byte-exact over two page boundaries and still missed a multi-page
**looping** sample wedging the interrupt, because its own sample does not loop. `check-aw` caught
that one, as a hang, at exactly 549 records.

**And one about method.** Guessing from a symptom has cost a gate run every time, and gate runs
here are ten to fifteen minutes. I5's voice setup, the C's BSS, and I9's load each went the same
way: three or four plausible inferences, then the answer arriving from reading the machine. The
cheapest move is almost always to instrument first - and when a measurement seems to exonerate
something, check its resolution before trusting it. A 250ms poll is twelve frames; "immediately
after" was nothing of the kind.

Every step names its gate, and where a step carries real risk it names the cheapest
experiment that would kill it early - the habit that has paid for itself repeatedly
here, most recently when an opcode budget of zero found in two runs what breakpoints
had failed to find in dozens.

| # | do this | because | gate |
|---|---|---|---|
| ~~**I1**~~ | ~~one program, and the memory map that lets it exist~~ **DONE**, `make check-map` and `make check-aw` | the last thing that could force a redesign | **PASSED**: all 763 records of the engine's stream with the frame interrupt pacing the VM, the DMA streaming, and the mixer refilling from inside the interrupt | everything resident at once and a frame runs: Gate D re-run *inside* the integrated program, with the frame interrupt and the sound interrupt both live, for 60 seconds |
| ~~**I1a**~~ | ~~read a real keyboard~~ **DONE**, `make check-input` | nothing in this project read input at all; `petest.asm` is handed a poked byte | **PASSED**: all 32 combinations from the emulator's own keys, through `read_keys` and the reference's mapping, to the VM's own variables |
| ~~**I2**~~ | ~~the VM draws~~ **DONE**, `make check-draw` - the six counting callbacks become the real rasteriser and reader | this is D4, and it is the first step that produces something recognisable | `check-ref` pointed at the MACHINE instead of at the Python reference: the intro's four pages, byte for byte against the engine |
| ~~**I3**~~ | ~~resources arrive at runtime~~ **PARTLY DONE**, `make check-res` - `op_updateMemList` loads, the memory list, invalidation between parts | nothing past the intro exists without it | every resource the intro and part 2 ask for arrives, its CRC cancels on the machine, the heap stays under its reservation, and the in-frame load is measured |
| ~~**I4**~~ | ~~text~~ **DONE**, `make check-text` - `op_drawString` and the font | the intro is unreadable without it, and it is small | every string the intro draws, pixel-exact against the reference |
| ~~**I5**~~ | ~~**sound in the game**~~ **DONE**, `make check-mus` - `op_playSound` and `op_playMusic` reach the player, the module is parsed, and the mixer maps each voice's own page | Chain 1 proved the mixer's arithmetic against a synthetic ramp; it proved neither the game's own samples nor the module format | **PASSED**: three modules parsed and walked against a model of `sfxplayer.cpp`, the four voice records after 1, 70 and 100 events, and six `op_playSound` cases checked against the sample shapes the host probe logged the reference producing - a stop, a loop, three pages, both ends of the pitch table and the clamp. And the MIXER'S OUTPUT byte-exact on a real sample: all 2,048 ring bytes over 19,164 source bytes and two page boundaries, which took a rewrite of the per-voice loop and found five mixer bugs |
| ~~**I6**~~ | ~~**part transitions**~~ **DONE**, `make check-part` - act on `aw_part_req`: tear down, load, restart | one part is a demo; the game is the sequence | the intro runs into part 2 and part 2 into part 3 unaided, and the opcode stream matches the engine's *across* the transition |
| ~~**I7**~~ | ~~**the full-screen bitmap**~~ **DONE**, `make check-bmp` path** | 70 of them load in the arena and no gate covers the machine half | the arena's bitmaps, on the machine, against the engine's pages |
| ~~**I8**~~ | ~~**the code screen**~~ **DONE**, `make check-part`, and its bypass** - which is a **starting part number**, not a subsystem | the wheel screen is `GAME_PART1` and is drawn by ordinary bytecode (`engine.cpp:71-73`); the bypass keeps every gate comparable to the reference build | the screen renders and accepts a correct code; with the flag set, part 2 starts directly, exactly as `BYPASS_PROTECTION` does |
| **I9** | **save and load** | in the definition of done, and the reference has a format to match | save mid-part, reload, and both the VM state and the opcode stream from that point match a run that never saved |
| **I9a** | **the whole suite, on the game** | every gate in Chain 1 was run against a HARNESS, not against the integrated binary | all twelve checkers pass against `aw.nex` rather than their own `.nex`, and the four narrow gates below pass against a gameplay part |
| **I10** | **playable to the end** - every part, real input | this is the goal | **a full playthrough under the patched ZEsarUX**, recorded, with the per-frame budget re-measured on the real thing against the per-part table |
| **H1** | **real hardware** - card boot, joystick wiring, timing on metal | follow-on; its gate cannot be run until the KS3 arrives | it boots from a card and plays, and the timings hold without the three local emulator patches |

### I1 is the one with teeth, so it gets its own account

Eight harnesses each chose absolute addresses and MMU slots for their own
convenience. The integrated program cannot keep all those choices, and the question
underneath is not tidiness - it is whether all of this can be **resident at the same
time**:

- the bytecode window, a 16K sliding view over a segment up to **62,683** bytes
- the polygon/cinematic segment window, a **second** 16K sliding view over a segment
  up to **65,230** bytes - and I2 needs both live at once, which no harness has ever
  needed
- the C virtual machine, `$8C00..$A9FF` = **7,681 bytes** of code and data, from
  z88dk's own map
- the rasteriser, the polygon reader and the interpolation tables
- **four** Layer 2 pages, because the reference keeps four (`video.h:70`,
  `uint8_t *_pages[4]`) and ours are 49,152 bytes each rather than the original's
  32,000: **196,608 bytes, twelve 16K banks**
- the mixer, the volume table, the ring the zxnDMA drains, and the samples
- the music player and its instruments
- the resource heap - the reference's own allocation high-water across the parts
  measured is **305,919 bytes, 38 pages of 8K, 19 banks**, and that figure includes
  the two segments above because the reference allocates them out of the same block
- the stack; the ZX system variables esxDOS needs at `$5B00`; and the ROM, which has
  to be back at `$0000` for `RST $08`

**The arithmetic says capacity is not the problem.** Four framebuffers at 196,608
plus the heap's 305,919 is **502,527 bytes** before our own code, the ring, the
volume table, the instruments and the font - about half of a 1MB machine and a
quarter of a 2MB one. So I1 is **not** a question of whether the game fits in RAM.
It is a question of whether the eight 8K slots of the Z80's 64K can be arranged so
that all of it is *reachable when needed*: two sliding windows, the C and its data,
the rasteriser, the sound player's own page, the ROM for `RST $08`, and bank 5's
system variables, which `src/vmtest.asm` already records as unusable.

That map was learned the hard way and is the starting point, but it was settled for a
program with **one** window and no sound. **What the resident code costs is still
unknown**, and deliberately not estimated here: the harnesses' listings do not
separate emitted code from `ds` reservations, so any total taken off them would be a
guess dressed as a measurement. The experiment below is how to find out, and it is
cheaper than the estimate would be worth.

**That experiment has been run, and I1's arrangement holds.** `make check-map`:
eight banked pages each given a distinct signature, the whole arrangement mapped at
once, every signature read back - and then the one thing known to break it, an esxDOS
call with the ROM back over the bottom 16K and bank 5 back at `$4000`, followed by
reading every signature again. All twelve sampled bytes correct both times.

**The settled slot map, and it has one genuinely new claim in it:**

| slot | | contents |
|---|---|---|
| MMU0, MMU1 | `$0000-$3FFF` | the bytecode window; the ROM during a DOS call |
| **MMU2, MMU3** | **`$4000-$7FFF`** | **the polygon/cinematic window** - the second window, in the region this document called "not available" |
| MMU4, MMU5 | `$8000-$BFFF` | resident code: the assembly, the C, the stack |
| MMU6 | `$C000-$DFFF` | the Layer 2 band being drawn |
| MMU7 | `$E000-$FFFF` | the mixer's sample window, and the loader's staging |

**`$4000-$7FFF` is usable, and the old note was right for the wrong duration.** Bank 5
holds the system variables esxDOS needs, so the region must be handed back for the
length of a file call - which the experiment does and recovers from. Outside a call it
is sixteen kilobytes of address space the project had written off, and it is where the
second window goes. Without it there is no slot for it and I2 could not be built.

**The experiment accused the machine before it cleared it**, which is worth recording
because it is now the third time. The first run reported the arrangement broken at
`$4000` and `$7FFF` - reading 165 and 90 where it wanted 66 and 67. 165 is `$A5` and
90 is `$5A`: exactly the two bytes the test's own write-probe had written, at exactly
the two addresses it wrote them to. The paging was correct throughout. A probe that
modifies what it later samples has to put it back.

### The steps in full

Citations are to the pinned AWBI checkout in `preflight/hostprobe/probe`, which is
GPL-2.0-or-later and may be read. Everything each step REUSES is already gated;
where a step has real risk it names the cheapest experiment that would kill it.

#### I1 is CLOSED, and four things had to be found first

`make check-aw`. `src/aw.asm` is the game: the slot map, the frame interrupt, the
zxnDMA streaming a ring to the DAC, the mixer refilling that ring from inside the
interrupt, the loader, and the virtual machine dispatching **all 763 records of the
engine's stream** through the middle of it. Five seconds of soak afterwards, because
`vm.c`'s `main` never returns and the interrupt has to keep going on its own.

Nothing needed redesigning. Four things needed finding, and none of them was visible
from any harness:

**1. The ring cannot live in a sliding window.** The zxnDMA reads through the CPU's own
memory decode, so a ring at MMU0 - which is what `sndtest.asm` uses, having the slot
spare - vanishes the moment the bytecode window pages. The game's ring is in MMU6's
page, which is never remapped, and that page also holds the control block, the expected
stream, the volume table, the voice records and the vector table.

**2. The CRT owns the interrupt state at BOTH ends.** Gate D found `im 1 / ei / ret` on
the way out. On the way in, `$8C00` is `F3` - `di` as the very first instruction - so
the `ei` before `call CC_ORG` is undone before the C runs a line. The machine spun in
the frame hook forever waiting for a tick that could not arrive: PC at `$8066`, ticks
frozen at 165, `IFF--`. **`aw_frame_sync` now does `ei` every frame**, which is the
only place that can assert it.

**3. z88dk's heap eats the resident region.** The CRT initialises a heap from `$AA00`
upward toward SP and writes a free-block header there. The IM 2 vector table was at
`$AB00`; the header landed on it, the next interrupt read a corrupt vector, and the
interrupt driving both the pacing and the sound simply stopped. **Nothing between the C
and the stack is safe** - the CRT believes all of it is its heap - so the table moved
into MMU6's page, which the C knows nothing about.

**4. The trace counter was a buffer position when it should have been an index.**
`aw_logrec` returned early once the record buffer was full, leaving `aw_log_count`
stuck - so every record after that was compared against the *same* expected record.
The harness has 2,040 slots against a 763-record stream and could never see it. The
game has 256, and diverged at exactly record 256. **A buffer smaller than the thing
being checked is a different program.**

**And one finding that belongs to I5, recorded here because this is where it surfaced.**
The gated mixer has **no end-of-sample handling at all**. Its inner loop deliberately
has no per-sample test - that costs 18 T a voice - and the design says the block is cut
short instead. But `sndtest.asm` only *describes* that cut in a comment; its
`setup_voices` copies fields and never performs it, and `check-snd` never caught the
omission because its sample is 1,024 bytes against blocks that never reach the end. So
**the mixer is gated for its arithmetic and not for the lifecycle of a sample.** Here
it showed as `V_POS` at `$D610` after a few seconds: the voice had run off its 512-byte
ramp, past `V_END`, and was reading the ring as sample data and writing the result back
over it. `src/aw.asm` has a crude rewind to hold it in bounds; real end-of-sample and
loop-point handling is I5's, and it is more unwritten code than the plan credited.

#### I1a. Read a real keyboard, and a joystick behind the same mask

**Nothing in this project reads input.** `src/petest.asm` proves the mapping and is
handed its input as two poked bytes, `in_mask` and `in_button`. That mapping is
exact - all 32 combinations, against `inp_updatePlayer`'s own order - and it is the
half that was hard. The half that does not exist is acquisition.

The six variables it drives are `VM_VARIABLE_HERO_POS_UP_DOWN 0xE5`,
`HERO_ACTION 0xFA`, `HERO_POS_JUMP_DOWN 0xFB`, `HERO_POS_LEFT_RIGHT 0xFC`,
`HERO_POS_MASK 0xFD` and `HERO_ACTION_POS_MASK 0xFE` (`vm.h:35-44`).

Write one routine that produces the mask `petest.asm` already consumes: five bits,
four directions and a button. Read the keyboard's half-rows on port `$FE` and OR in
a Kempston read on port `$1F`, so a joystick needs no second code path and H1 has
nothing to add but wiring. Wolf3D-next's key handling is the model and is ours to
copy from.

**Gate:** the six variables track real keys, with `check-pace`'s existing table as
the oracle - the same 32 combinations, driven from the keyboard rather than from a
poke.

**I1a is closed.** `make check-input`. `src/inc/input.inc` now holds both halves: the
mapping `check-pace` gated, and `read_keys`, which is new - port `$FE` for O, P, Q, A
and Space, with a Kempston read on port `$1F` accumulated in parallel so a joystick
needs no second code path and H1 has only the physical wiring left. It runs in the
frame interrupt beside the mixer, for the same reason: `vm.c`'s `main` never returns,
so anything driven only from the frame hook stops when the last frame does. The C reads
the six published words between `checkThreadRequests` and `hostFrame`, which is the
reference's own order - a port that read them after the frame would be one frame late
on every input and would feel it rather than show it.

**Two things went wrong in the checker and neither was the machine.** The first
version re-derived `inp_updatePlayer` instead of importing `check-pace`'s gated copy,
and got wrong the one detail that is the entire reason two variables exist: `$FD` takes
the mask **without** the fire bit and `$FE` takes it **with**, because the reference
writes `$FD` before the fire test and `$FE` after it. Sixteen of thirty-two
combinations "failed" and the machine was right in all sixteen. **Import the oracle;
never keep two.** The second was `0x`-prefixed addresses in the ZRCP commands -
**ZEsarUX's expression parser refuses them and a refused write is silent** - so
`CTL_FRAMES` stayed zero, the VM ran no frames at all, and the checker reported that
input was not reaching it. That trap is already in this document, in the breakpoint
note, and it cost twenty minutes again anyway.

#### I2 is CLOSED - the intro renders, and the harness was the last bug

**The VM draws polygons on the Next.** `make check-aw` reports 151 polygon draws and
the page the VM drew into holding three distinct values over 3,072 sampled bytes - real
content, not a uniform fill - with the opcode stream still exact over its first 256
records and the sound still running. All eight gates pass.

**Done:** the page model (four pages, three pointers, `getPage`'s resolution rules);
`selectVideoPage`; `fillVideoPage`; `copyVideoPage`'s plain path; `blitFramebuffer` with
the reference's ordering, palette request applied before the page is presented;
`aw_draw_poly` wired to the gated reader with the cinematic segment loaded; real keyboard
input reaching the VM's variables.

**Outstanding:** `apply_palette` is a stub - the 512 Layer 2 entries are already resident
as two 256-entry banks so it is a bank select, not a transfer; the **scrolled** copy path
is unimplemented and counted in `cp_unimpl`, and it needs `vscroll` from variable `$F9`
which `op_copyVideoPage` does not yet pass, scaled into our 192-line geometry; the
**video2** segment is not loaded, so draws wanting it are counted in `n_video2` and
skipped. **Neither gap blocks the intro:** over its first 45 frames `n_video2` is 0 and
`cp_unimpl` is 0.

**I2's GATE IS BUILT AND RUNNING, and it reports a real difference.** `make check-draw`
aligns the two sides on a **blit** - the one instant where both agree what the frame is,
since the VM's frames and the probe's frames are different quantities - stops the machine
after its Kth blit through the C's own out-of-budget flag, replays the engine's trace to
its Kth through `RefVideo8`, and compares all four 49,152-byte pages.

At blit 8 it says:

| | machine | engine |
|---|---|---|
| polygon **opcodes** | 55 | **55** |
| polygon **leaves** | - | 276 |
| fills | 3 | 3 |
| copies | 5 | 4 |
| page 3 | identical | identical |
| page 0 | 61.8% differs | |

**The opcode counts match exactly** - `draw=55` in the engine's trace against `poly=55`
on the machine, expanding to 276 leaves - and so do the OPERANDS for every draw the log
holds, and so do the destination pages. The gate has walked the fault backwards through
four suspects and found three real bugs doing it.

**THE BUG THAT MATTERED: the bit-7 polygon form read its coordinates SIGNED.** `vm.cpp`
has `int16_t x = _scriptPtr.fetchByte();` and `fetchByte` returns `uint8_t`, so the
assignment **zero**-extends. Our `(int8_t)` cast sign-extended, and every coordinate at or
above 128 came out 256 too small: the engine's `x=192` was our `-64`, its `247` our `-9`,
its `y=143` our `-113`. Page 0's error went from **61.8% to 36.1%** when it was fixed.

**Nothing had caught it, and the reason is the shape of the other gates.** Gate D proves
the opcode **stream** - thread, program counter, opcode - and says nothing about the
operands the C derives from it. `check-readmachine` proves the reader against a draw list
a **checker poked**, so it has never seen the C compute one. The fault lived exactly in
the seam between two passing gates, which is the whole argument for comparing a picture
rather than a stream.

**And a register clobber, of precisely the kind this document's traps list warns about.**
`aw_copy_page` held the destination page id in B and called `page_to_p0`, which uses B -
so `ld a, b` read rubbish, both ends resolved to page 0, the copy copied page 0 onto
itself, and pages 1 and 2 stayed empty. With it fixed all three pages show the **identical
36.10%**, which is the useful signal: the copies faithfully propagate page 0 and exactly
one fault is left, in page 0's drawn content.

**Two page-pointer bugs were found and fixed on the way, and neither was the fault.**
`Video::init` calls `changePagePtr1($FE)` so drawing starts on the page `ptr2` names, and
`video.cpp:56-57` is `_curPagePtr3 = getPage(1); _curPagePtr2 = getPage(2)`, which I had
the other way round. Both are now right against the source and neither changed the
comparison by a single byte. Two plausible fixes, both correct, both irrelevant - which is
why the next step is the per-draw pixel bisect and not another hypothesis.

**WHAT IS LEFT, and it is now a one-record reproducer.** `make bisect-draw` halves over the
draw count with both sides stopping at the same number, and says:

| | |
|---|---|
| **0 draws** | **IDENTICAL** - so the fills and the copies are right |
| 1 draw | 2,756 bytes differ, rows 0..120, first at row 0 x 51: ours `$03`, engine `$02` |

And `check-draw` had already proved that draw's operands identical to the engine's:
`off=2096, zoom=64, x=192, y=59, colour=$FF`, into the same page. **So the inputs agree,
the destination agrees, and the pixels do not** - which puts the fault in the reader or the
rasteriser for this particular record, or in the segment bytes they are reading.

**That possibility has been tested and closed. The host is correct.**

`RES19.BIN` is **byte-identical** to the probe's `seg_cine_0.bin`, all 65,230 of them - and
the reference reading `RES19.BIN` at offset 2096 produces **exactly** the engine's own leaf
for draw 1. So the asset is right, the reader is right, and the fault is the machine's.

**Two of my own tests were wrong before that held**, which is worth more than the result:

- I diffed against `seg_cine_1.bin` and found 55,781 of 57,510 bytes differing. `gSegDump`
  counts **setupPart calls**, and with `BYPASS_PROTECTION` the engine starts at part 2, so
  `seg_cine_0` is the intro's and `seg_cine_1` is the next part's. Different resource,
  different length, and the numbers looked like a catastrophe.
- Then I fed the engine's leaf to `fill_polygon` while the reader path goes through
  `_draw_polygon`, which **scales** 320x200 into 256x192 first. Comparing a scaled page
  against an unscaled one gave 2,756 bytes - the same count as the machine's difference,
  which made it look like proof that the machine was right and the host wrong. It was a
  coincidence of magnitude, not a match.

**THAT TEST HAS BEEN RUN, and the reader is right.** `src/aw.asm` gained a probe path -
`probe_draw`, one draw from a poked `DRAW_BLOCK` with the C never entered - because no
existing gate separates the reader from its setup: `check-readmachine` drives the reader
from a poked list in the **harness**, `check-draw` drives it from the VM in the **game**,
and the question is which of those two differs. Driven directly with
`off=2096, colour=$FF, zoom=64, x=192, y=59` into page 0, the machine is **IDENTICAL** to
the reference.

**So everything in the chain is individually correct and the combination is not:**

| | |
|---|---|
| the fills and copies before any draw | identical (`bisect-draw` at 0 draws) |
| the record's operands | identical (`check-draw`'s per-draw log) |
| the destination page | identical |
| the reader on this record, page 0 blank | identical (the probe path) |
| the reader on this record, page 0 **filled** | **2,756 bytes wrong** |

**The last line is the whole remaining fault, and the shape says something.** 2,756 bytes
over 121 rows is about 23 a row - a thin sliver, not a wrong polygon. A wrong shape would
differ in blocks; this differs in a ribbon.

**And it only shows when page 0 already has content**, which is what the probe path proves by
passing: with a blank page the copy-mode fill this record uses - `$FF` selects `drawLineP`,
which reads `_pages[0]` (`video.cpp:352`) - copies zeros over zeros and cannot be wrong.

**THE PROBE STILL WILL NOT REPRODUCE IT, and the eliminations are the useful product.**
Everything below has been tested, not reasoned about:

| tested | result |
|---|---|
| all four pages before any draw | **identical** - the fills and copies are right |
| page 0's content before draw 1 | **uniform colour 2 on both sides** |
| the record's five operands | **identical** |
| the destination page | **identical** |
| the reader on the record, page 0 blank | **identical** |
| the reader on the record, page 0 **pre-filled with 2** | **identical** |
| the mixer inside the interrupt (`snd_off=1`) | **makes no difference** |
| `RES19.BIN` against the engine's `seg_cine_0.bin` | **byte-identical** |
| the reference reading `RES19.BIN` vs the engine's own leaf | **identical** |

So the one-record probe, given what looks like the identical starting state, draws the record
correctly - and the VM, from the same state with the same operands, does not. **The probe is
therefore not equivalent for a reason not yet found**, and that is the thing to chase.

**THE PER-ROW EXTENTS WERE THE RIGHT INSTRUMENT and they broke it open.** Rows 0 to 13
disagreed over **exactly columns 51..64**, a constant 14-byte stripe - a block, not an edge.
An endpoint one or two out gives a ribbon down one side; this was a span painted where none
should be.

**Then the decisive read, and it was a contradiction inside the HOST tooling:**

| | |
|---|---|
| the machine's page 0 after draw 1 | 25,577 bytes of `2`, 23,575 of `3` |
| `bisect-draw`'s reference | all 49,152 of `2` - it painted nothing |
| a **standalone** host call of the same draw | painted exactly **23,575** bytes |

The machine agreed with one reference and not the other. The record's first byte at offset
2096 is `$C3`, which is `>= $C0`, so the record supplies its own colour - `$C3 & $3F = 3` -
and the trace's leaf says `colour=3`. So the machine was **right**, and `bisect-draw`'s
reference was wrong.

**`replay` called `fill_polygon` where it had to call `_draw_polygon`.** `_draw_polygon` is
the leaf hook each geometry overrides: `RefVideo`'s is the engine's own 320x200, `RefVideo8`'s
scales into 256x192 and then fills. Calling `fill_polygon` fed a `RefVideo8` unscaled
coordinates - and **this is the second time that exact mistake has been made in this
project.** The first cost a day of believing the machine's rasteriser was wrong.

**With one line changed, all four pages are identical - 196,608 bytes.** I2's gate passes.

**WHAT THE HARNESS BUG COST, recorded because the pattern is the lesson.** Nine eliminations,
a probe path that would not reproduce the failure, and **four fixes that were correct against
the source and changed nothing**: the initial drawing page, the two display pointers, and
`SRC_PAGE`. Every one of them is right and worth keeping. None of them was the fault. When
several correct fixes in a row move the number by zero, the thing being measured is the
measurement.

**Three of the four bugs found in I2 were real and the gate caught them all**: the bit-7
form's signed coordinates, which had been wrong for the whole of Phase D and which no other
gate could see; the register clobber in `aw_copy_page` that copied page 0 onto itself; and the
trace counter that was a buffer position where it should have been an index.

**`SRC_PAGE` was wrong and is now fixed, and it did not change this.** The rasteriser's
copy-mode fill reads page 0 and only page 0; the harness had `SRC_PAGE 2` because its own
test drew from page 2, and the game inherited the number. Correct per `video.cpp:352`,
irrelevant to the symptom - the fourth such fix this step.

**Two wrong attempts at the bisect itself, both worth keeping.** Stopping the machine by
setting the out-of-budget flag AFTER a draw does not stop at that draw: it ends the frame
LOOP while the thread already running carries on to its next yield, so "stop after 1" let
51 through. The test has to refuse the draw. And `0` could not mean "stop immediately"
while it also meant "no limit", so the sentinel is `$FFFF`.

**And the gate as originally described is not yet passed.** What exists proves the callbacks are reached and
that pixels change. What I2 claims is the intro's pages **byte for byte against the
engine**, and that needs the reference replaying the same frames through `refvideo.py` -
the shape `check-readmachine` already uses, but driven by the VM rather than by a poked
draw list.

**Three slot conflicts came out of this step**, all now parameterised in the includes
rather than discovered twice: the sound ring cannot live in a sliding window; the
rasteriser's Layer 2 bands cannot sit where the polygon window must; and the segment
window cannot sit over the bytecode window. A fourth was caught by a gate rather than by
thought - the page copy pointing its source band at MMU0 and never restoring it, which
made the VM dispatch framebuffer and fail inside 2,067 records with "an invalid opcode".

**One operational trap worth carrying:** two gates cannot run at once. They each start an
emulator on port 10000, and a second one makes the first checker hang on a connect that
never resolves. It looked exactly like `check-input` failing.

#### I2. The VM draws

The six callbacks in `src/vmtest.asm` that currently increment a word become the
real thing. Each has an exact counterpart:

| callback | the reference | what it becomes |
|---|---|---|
| `aw_draw_poly` | `readAndDrawPolygon` `video.cpp:85`, `fillPolygon` `video.cpp:127`, `readAndDrawPolygonHierarchy` `video.cpp:222` | the gated reader and rasteriser, already pixel-exact over 771 polygons at 55 zooms |
| `aw_select_page` | `changePagePtr1` `video.cpp:491` | a pointer swap among four pages |
| `aw_fill_page` | `fillPage` `video.cpp:498` | a 49,152-byte fill, already priced |
| `aw_copy_page` | `copyPage(src, dst, vscroll)` `video.cpp:513` | **and vscroll is not optional** - it is how the game scrolls |
| `aw_blit` | `updateDisplay` `video.cpp:597` | NextReg `$12`, with `$FE` meaning no change and `$FF` meaning swap |
| `aw_set_palette` | `changePal` `video.cpp:587` | a Layer 2 palette select, and **it applies BEFORE the flip** |

**Four pages, not three** (`video.cpp:49`, `malloc(4 * VID_PAGE_SIZE)`; `_pages[4]`
at `video.h:70`), and ours are 49,152 bytes rather than the original's 32,000.

**Gate:** `check-ref` pointed at the machine instead of at the Python reference -
the intro's four pages, byte for byte against the engine's.

**The trap this step exists to avoid** is already recorded twice in this document:
the reference was at fault twice and the machine right. So when the pages differ,
suspect the harness before the rasteriser - and bisect to the first polygon, the way
`checkpoly.py` does, rather than reading a 49,152-byte diff.

#### I3. Resources arrive at runtime

`op_updateMemList` currently notices a part request and does nothing else. The
reference's chain is `loadPartsOrMemoryEntry` (`resource.cpp:258`) into
`loadMarkedAsNeeded` (`166`) into `readBank` (`32`), with `invalidateRes` (`229`)
and `invalidateAll` (`241`) clearing between parts.

**The decompression is already done.** `tools/mkassets.py` writes every resource out
as a file - `RES%02X.BIN` for anything that passes through, `PAL%02X.BIN` for the
nine palette resources, `BMP%02X.BIN` for the full-screen bitmaps - so `readBank`'s
Bytekiller unpacking happens on the host at asset-build time, not on the Z80. 125
RES, 9 PAL and 12 BMP files are on the card now. The six types are `RT_SOUND 0`,
`RT_MUSIC 1`, `RT_POLY_ANIM 2` (0x7D00 bytes), `RT_PALETTE 3` (2048),
`RT_BYTECODE 4`, `RT_POLY_CINEMATIC 5` (`resource.h:65-76`).

So this step is the memory list and the lifetime, not the codec: which resources a
part marks as needed, where they land in banked RAM, and what is freed when the part
changes.

**Gate:** every resource the intro and part 2 ask for arrives, its CRC cancels **on
the machine**, the heap stays under its reservation, and the in-frame load is
measured and reported.

**The thing to measure, not assume:** `op_updateMemList` loads one resource inside a
frame and the largest is 65,230 bytes. Step 5 established that the emulator cannot
time esxDOS, so this frame's cost is unknown until H1 - report it, do not model it.

#### I3 loads, and two of its three claims hold

`make check-res`. `op_updateMemList` now does what `loadPartsOrMemoryEntry` does
(`resource.cpp:258`): zero invalidates, an id above the memory list requests a part,
anything else loads. Over the intro's 45 frames the machine loads **23 resources** and
**every one is byte-for-byte against the card**, read back off the machine rather than
trusted. The heap sits at **33 of its 40 reserved pages**.

`tools/mkreslist.py` generates the table it loads by, from MEMLIST: 146 resources, four
bytes each - type, unpacked size, page count. The name is derived rather than stored,
`PAL`/`BMP`/`RES` by type, which is what `mkassets.py` writes.

**The tables went into MMU6's page, not the resident region**, and the trace buffer paid
for it: 730 bytes of table against 951 bytes of stack left if it went below the C. The
game's trace buffer dropped from 256 records to 32, which costs nothing real - `check-boot`
gates the opcode stream at 763 in the harness, so the game's copy is a post-mortem
convenience.

**CLAIM 2 IS NOT CHECKED AND THE CHECKER SAYS SO.** "It asked for the same resources the
engine did" needs the probe to log resource **ids**, and its sound log is keyed by time and
type. **A port that silently skipped a load would pass the other two claims.** Closing it
means an `instrOp` in `loadPartsOrMemoryEntry`; until then the count is reported, not
verified.

**And 33 of 40 pages is tighter than it looks.** That is the intro alone, and the
reference's measured high-water across the parts is 38 pages - so the reservation has
seven pages of headroom for parts that load more than the intro does. I6 will find out.

#### I4 is CLOSED - the machine draws the game's text

**The geometry, decided 2026-09-13: 40 cells of SIX pixels, 240 of our 256.** Every cell the
original can address is reachable, no letter touches its neighbour, and the cost is that the
font is no longer the original's. The two alternatives were scaling the cell origin and
letting 8-pixel glyphs overlap by 1.6 pixels, or keeping 8-pixel cells and losing everything
past cell 31.

**`tools/mkfont6.py` narrows the font and shows its work.** Eighty-five of ninety-six glyphs
only needed shifting left - they already inked six columns or fewer. Eleven had a column
removed, always the one whose removal changed the fewest pixels, which is fine for `=`
(seven solid columns becoming six) and for `&` (one pixel from one row). **Five are
hand-drawn** - `M W m w %` - because the mechanical version of `M` came out
`#....# / #...## / ##.#.# / #.#..#`, asymmetric and not an M. `--show` prints every altered
glyph before and after, which is the only way to judge that.

**`tools/mkstrings.py` parses the reference's own table** rather than transcribing it: 139
strings, 2,187 bytes of text, 556 of index, sorted by id so the machine can binary-search
instead of walking 264 entries the way `drawString` does. Thirteen contain a newline, which
`drawString` treats as a line break rather than a glyph (`video.cpp:288`), and nothing in
them falls outside the font's range.

**And `RefVideo8` now has the `draw_char` it never had.** Without it the 4bpp version ran on
an 8bpp page - four bytes a cell, two pixels a byte, a 160-byte stride - which is meaningless
here. `HELLO` rendered out of the page bytes is legible. The cell origin in y scales like
every other coordinate; the glyph does not, because a vertically scaled 8-row glyph is an
unreadable one.

**`make check-text` passes: five strings pixel-identical**, chosen to break it rather than to
flatter it - one plain, one with three newlines, the longest in the table at 174 characters,
one lowercase-heavy for the hand-drawn `m` and `w`, and **one at cell 34, which no
eight-pixel cell could have reached at all.** That last case is the decision justifying
itself.

The machine walks the dictionary by **bisection** rather than the reference's linear scan of
264 entries, reads the font out of a banked page mapped at MMU2 - the polygon window, idle
during text because nothing reads a polygon segment and draws a glyph at once - and maps a
Layer 2 band **per row**, which is the only way a glyph straddling row 32 comes out whole.

**Two bugs, both mine, both the same kind.** `scale_uy` takes its argument in **HL** and I
passed it in A, so the row was scaled from whatever HL happened to hold; it showed as both
sides drawing exactly twenty pixels for an `A` with the first disagreement one row above the
machine's, which is what an off-by-one in a scaled origin looks like. And I hand-computed the
string blob's address as `$E53C` where the index's 556 bytes put it at `$E52C` - every string
sixteen bytes adrift, with nothing to say so. The generated file has `str_index` and
`str_blob` as labels and the code now uses those. **Do not hand-compute an address a
generator already names.**

#### Why no gate caught the missing override

**`RefVideo8` does not override `draw_char`.** The 4bpp version it inherits writes four
bytes a cell with two pixels a byte into a 256-byte stride, which is meaningless at 8bpp.
So **there is no specification for what text looks like on the Next** - the thing I4 is
supposed to reproduce does not exist yet. This is the third time a missing `RefVideo8`
override has mattered, after `_draw_polygon` twice.

**And the geometry does not divide.** `drawChar` takes x in CHARACTER CELLS, `x <= 39`
(`video.cpp:299`), so the original addresses 40 cells across its 320 pixels - 8 pixels a
cell. Our page is 256 wide, which is **32 cells**. There is no arrangement in which 40
eight-pixel cells fit in 256 pixels, so something has to give, and what gives is a visual
decision rather than an arithmetic one. **Same class as F4, and therefore David's.**

**Why no gate caught this earlier:** the 45-frame intro trace contains **no `char` records
at all**. Text needs input - the code screen waits for keys and dialogue follows progress -
and the traces every gate uses are input-free so the streams stay deterministic. With
autoplay on, the protection screen draws **2,378** glyphs in 400 frames and part index 2
draws **5,800**. So text is reachable, just not on the path anything currently measures.

**How I4 gets gated once the geometry is decided**, and it does not need the VM to reach any
text: drive `drawString` directly the way `probe_draw` drives one polygon - poke a string id,
a colour and a position, compare the page against the reference. Deterministic, and the same
shape as `check-readmachine`.

**A trap that cost an hour and nearly a pointless refactor.** `IN_BLOCK` and `DRAW_BLOCK` are
fixed addresses **set in two files** - `AW_IN` and `AW_DRAW` in the Makefile, the constants in
`src/aw.asm` - and there is no way to assert agreement across two toolchains. Moving the
assembly's without the Makefile's left the C writing its polygon parameters to `$D310` while
the assembly read `$C390`. All zeros, so the reader was called 151 times and drew nothing, and
`check-aw` said *"the reader draws nothing"* with no hint that an address was the cause.

**What it nearly cost:** the stack was down to 1,191 bytes at the time and I took the three
failures as proof it had run out, and was most of the way into re-laying MMU6's whole page to
move the stack there. It was not the stack. **1,191 bytes is enough** - all twelve gates pass
on it - and the refactor was unnecessary. Measure which of two changes broke something before
redesigning around one of them.

**One trap earned here.** Hunting for text overwrote `trace.bin` and `ops.txt`, which I2's
and I3's gates both rest on. They were copied to `preflight/hostprobe/keep/` first and
restored after, and both gates re-run clean - but the document already warned about exactly
this ("Two runs, two output files, one name") and it nearly happened again.

#### I4. Text

`drawString` (`video.cpp:267`) looks a string id up in `_stringsTableEng`
(`staticres.cpp:123`) and calls `drawChar` (`video.cpp:299`) per character: an 8x8
glyph, x in character cells and y in pixel rows.

Two things are already in hand. The font is dumped - 96 glyphs of 8 bytes from
`' '`, written to `font.bin` by the probe rather than transcribed. And the string
table is static data in the reference, so it converts on the host like everything
else.

**Gate:** every string the intro draws, pixel-exact against the reference.

#### I5. Sound in the game

`op_playSound` and `op_playMusic` reach the player that `make check-snd` already
proves. **But read what that gate actually covers before trusting it:** it proves
the mixer's arithmetic - four voices byte-exact at three block lengths, nine ring
wraps, nothing written outside the ring - and `src/sndtest.asm` feeds it **a
synthetic ramp**, chosen so that a wrong pointer shows as a wrong value. It has
never mixed one of the game's own sound resources.

And the music is a module, not a sample. `SfxModule` holds `curPos`, `curOrder`,
`numOrder` and an `orderTable[0x80]`, with `SfxInstrument` and `SfxPattern` beside
it (`sfxplayer.h:24-38`); `loadSfxModule(resNum, delay, pos)`, `setEventsDelay` and
`handleEvents` drive it (`sfxplayer.h:71-76`). **Nothing anywhere in this project
has parsed that format.** It is the largest single piece of unwritten code in
Chain 2.

**Gate, in two halves because it is two claims:** SFX and music events fire at the
same frames as the engine's `sound.txt` log; and the mixer's output stays byte-exact
**on the game's own sound resources**, not on a ramp.

#### I5: the module format is decoded, which is where it had to start

**Nothing in this project parsed a module**, and the plan had I5 down as wiring. It is not:
`sfxplayer.cpp` reads a format with no counterpart here, so `tools/sfxmod.py` decodes it
first - there has to be something that says what the right answer is before any Z80 is
written.

**The layout, from `loadSfxModule` and `prepareInstruments`, big-endian throughout:**

| offset | |
|---|---|
| `0x00` | delay, a word - the default if `op_playMusic` passes zero, then `* 60 / 7050` for ms |
| `0x02` | fifteen instruments of four bytes: a resource number and a volume, both words |
| `0x3E` | `numOrder`, a word: how many order entries are played |
| `0x40` | the order table, `0x80` bytes, each selecting a 1024-byte pattern block |
| `0xC0` | the pattern blocks - 64 rows of four channels of four bytes |

**And the parser validates itself against the data.** `RES07.BIN` is 15,552 bytes; from
`numOrder` 16 and an order table using blocks 0 to 14, the patterns need `0xC0 + 15 * 1024`
= **exactly 15,552**. A format guessed wrongly would not land on the file's own length.

Its six instruments reference resources `0x01` to `0x06` - which `check-res` already shows
the machine loading - at volumes 63, 63, 63, 15, 51 and 45.

**`voice_run` is in, which is the block-splitting the design always described and never did.**
The mixer's inner loop deliberately has no end-of-sample test - one costs 18 T a voice a
sample - and the design says to cut the block short instead. `sndtest.asm` never cut it, and
`check-snd` could not notice because its sample is 1,024 bytes against blocks that never reach
the end. `voice_run` returns how many samples a voice may mix before `V_END`: the bytes
remaining when the integer increment is zero, since each sample then advances under a byte,
and a 16-by-8 divide by the integer part otherwise - which under-estimates, because the
fraction advances too, so it is safe and merely means the caller loops again. One divide a
block a voice against 18 T a sample a voice.

**`make check-mus` passes: all three modules parsed exactly as `tools/sfxmod.py` parses them**
- the delay with and without `op_playMusic`'s override, `numOrder`, all 128 order entries and
all 15 instruments. The header is right, which had to come before the event loop: a player
built on a misread header produces plausible noise, the worst failure mode sound has.

**THE WORST BUG OF THE SESSION was a silent no-op in my own tooling.** The scripted edits that
were supposed to add `jp aw_draw_string` and `jp aw_play_music` to **`src/aw.asm`'s** jump table
used a string replacement **with no check** and matched nothing. The table stayed at 30 bytes
while `src/aw/jumptab.asm` declared `_aw_play_music` at `$8021` - and `$8021` is **inside
`start:`**. The C called into the middle of an instruction and the VM faulted eleven records in
with "ret with an empty stack", taking `check-res`, `check-draw` and `check-input` down with it.

**I4 never noticed**, because its gate calls `aw_draw_string` directly in assembly and never
through the table. **A slot nothing calls is a slot nothing tests**, and the `ASSERT $ -
jump_table == 36` is the only thing that can catch it. Every scripted edit needs its assertion;
the ones that had it worked.

**Two further wrong diagnoses on the way to it, both costing real time:**

- **The stack, twice.** 1,137 bytes looked like the cause, so the stack was moved into MMU6's
  page and the palette displaced into the text page to pay for it. It changed nothing - because
  **the CRT sets SP itself from `REGISTER_SP`**, so `ld sp` in `start:` is overwritten before
  `main` runs. That is the same mechanism Gate D's stack fix used and I had already written it
  down. The move is kept: it is correct, and it freed 1,179 bytes of resident tail for code,
  which the next steps will need.
- **The control block's reservation.** The assembly said `ds 32 + 256 * 4` while the Makefile
  told the C to use 32 records, so 1,056 bytes were reserved to `$C41F` and every table placed
  from `$C0A0` sat inside it. Nothing corrupted - `ds` only reserves - but no assert in that
  page was measuring anything real. Also fixed, also not the cause.

**The voice setup is done and `make check-mus` passes it.** Four things are gated now: the
header on three modules, the event walk on three cases including a block crossing, the four
voice records after 1, 70 and 100 events, and the period divide over eleven periods.

**The bug was one instruction, and it was in the probe.** `probe_walk` read `probe_ticks` into
A, then ran a fifteen-iteration loop that loads the module's instruments - and every iteration
does `ld a,(hl)`. The `ld b,a` that followed therefore took its event count from a table byte,
which is zero, and `djnz` reads zero as **256**. Every probe run walked the module to its end no
matter what the checker asked for, which is exactly why a one-event walk whose only row was a
stop came back with all four voices active, in two identical pairs.

Worth writing down because of how the search went. The symptom pointed at the voice logic, and
three inferences from it in a row were wrong. What actually found it was giving up on inference
and reading the boot state off the machine, which came back correct - and once the boot state
and the event decode were both known good, the only thing left between them was the loop count.

**One wrong turn on the way, and the reason it was wrong is worth keeping.** `sfxplayer.cpp:81-96`
has the instrument table at four bytes an entry, a resource word then a volume word, both
big-endian; `mus_voice` indexes it by two. That looks like a bug and is not: `aw_play_music`
**compacts** the table on the way out, keeping only each word's low byte, because the resident
copy has to fit the thirty-two bytes between `MUS_INSTR_AT` and `DRAW_LOG`. Changing the readers
to the module's stride broke a correct routine, and the gate said so immediately. The compaction
holds only while every id and every volume fits a byte, so check-mus now asserts it instead of
assuming it - across the three modules the largest id is 131 and the largest volume 63.

**Two divergences from the reference found while reading it, both left in place deliberately:**

| the reference | ours | why it is safe |
|---|---|---|
| an odd `$FFxx` note_1 falls through and PLAYS (`:185`), the assert at `:196` merely saying it should not arise | `mus_pattern` returns | across all 7,680 rows of every block the three modules' order tables name, there is no `$FFxx` but `$FFFD` and `$FFFE` |
| note_1 == 0 with a nonzero instrument nibble still reaches `setChannelVolume` (`:177`), so it is a volume change without a retrigger | both machine and model return before the volume | zero such rows in those same 7,680 |

Those are measured, not assumed - and the scan had to be restricted to the three resources
MEMLIST types `RT_MUSIC` (`0x07`, `0x89`, `0x8A`), because a loose "does it parse" filter finds
six more that are bitmaps underneath and invents divergences out of their pixels.

**One thing the reference does that we now do too:** `prepareInstruments` zeroes four bytes at
`data + 8` on every instrument (`:89`), so every module note opens on four samples of silence.
`mus_voice` does it when the note is set up rather than when the module loads - the same thing to
the mixer, since nothing reads a sample the player has not set up - and it is idempotent.

**I5 IS DONE, and `make check-mus` gates all six parts of it.**

**ALL SIX PARTS PASS, and building the sixth found FIVE bugs in the mixer, four of them live and
none of them findable any other way.** The last case mixes RES54 for 60 blocks at the top of the
pitch table - 19,164 source bytes across two 8K page boundaries - and all 2,048 ring bytes come
out byte-exact against a model of what the splitting has to add up to rather than of the splitting
itself. Every one of the five was in the path between a voice record and the bytes that leave for
the DAC: the half nothing had ever checked.

**1. `mix_block` never called `voice_run` or `voice_advance`.** It had a crude guard - rewind if
the next block would not fit - whose own comment said proper end-of-sample and loop-point
handling was still to come. It was worse than crude: a **full** window has `V_END = $0000`, so
`V_POS + blocklen` never borrowed against it, the guard read "would overrun", and `V_POS` went to
`V_LOOP` - **zero for an unlooped sample**. The voice then read from address `$0000`, the bytecode
window. Measured after 40 blocks of RES54: `V_POS = $0096`, `V_LEFT` still 14,506, `V_PAGE`
unmoved. It now splits each block properly, and after the same 40 blocks the voice sits at
absolute offset 6,016 against the 6,008 + 8 the increment says it should.

**2. The ring was not a ring.** `ring_wr` was tested against the end *after* a block was written,
and reset to `RING_ADDR` if it had passed - so **the block that took it over the edge wrote up to
158 bytes past the ring, over `VOLTAB`**, and the bytes near the end were never written at all.
Nine blocks of 221 reach 1,985 of 2,048; the tenth did both. It wraps modulo now.

**3. `mix_voice_*` advanced its destination with `inc l`, which does not carry** - so a block
could not cross a 256-byte boundary inside the ring, and with `BLK_A` of 221 it does. The write
wrapped back into the same page instead. `inc hl` is the same one byte for two T-states a sample
a voice, 0.63% of the machine, and it removes a whole class of splitting from the caller.

**4. `voice_run` read a full window as "past the end", and bounded it by the wrong divisor.**
`V_END - V_POS` borrows when `V_END` is the `$0000` that means `$10000`, and `ret c` took that for
an overrun - so even once wired in, a voice on a full page would have mixed nothing. The borrow is
allowed now, and a genuine wrap past the end is told apart by `V_POS` falling below the window's
base, which `D` still holds after the subtract. Separately, the bound divided by the increment's
**integer part**, on the stated reasoning that this "under-estimates because the fraction also
advances". That is backwards: dividing by `inci` over-estimates, and at 1.4453 bytes a sample it
returned `bytes_left` samples where only `bytes_left / 1.4453` fit - so the pointer ran past
`V_END`, wrapped through `$0000`, and the voice read on from the bottom of memory. `inci + 1` can
only under-estimate.

**5. The page transition dropped bytes, and the fraction's phase with them.** Because that bound
now under-estimates, near a window's edge it rounds to zero while a byte is still there - and
`voice_advance` rewound to the next page's **base**, losing up to `inci + 1` bytes every crossing.
It showed as a one-byte error at the first boundary and a drift after it: 1,300 of 2,048 ring
bytes wrong while the single-page case was already exact. `voice_run` now returns at least one
sample while any byte remains, so the pointer **crosses** the edge, and `voice_advance` adds the
window's base to the remainder the wrap left rather than replacing it.

**And one design simplification that fell out of it: every voice accumulates, none stores.** The
block is filled with 128 first, and `mva` accumulating onto 128 is byte-identical to `mvf`'s
biased store across the whole signed range - for `s >= 0` it is `128 + s` and cannot carry, and
for `s < 0` the carry produces exactly what the XOR would. One pass of stores buys two things: a
voice that stops part way through a block leaves silence behind it rather than stale ring, and
there is no "which voice stores" state left to get wrong. `mix_voice_first` is now `IFNDEF`'d out
of the game entirely - sndtest still uses it - which the resident block needed, having had four
bytes left in it.

**A SIXTH BUG, and the mixing gate did not catch it - `check-aw` did, as a HANG.** With the
block splitting wired in, a **multi-page looping** sample wedged the machine inside the
interrupt. `V_LOOP` is an address in the sample's **first** window - `voice_setup` only records
a loop point it can reach there - so returning to it while `V_PAGE` and `V_END` still described
the **last** window left the position past the end with nothing behind it: `voice_run` returned
zero, `voice_advance` looped straight back to the same place, and neither ever moved. Read off
the wedged machine:

```
WEDGED after 6s: ticks stuck at 288, 549 records dispatched
  ch2 active=1 page=74 pos=0xf010 end=0xe674 loop=0xf010 left=0 incf=51
```

`pos == loop`, `pos > end`, nothing left, still active. 549 records is exactly where `check-aw`
stopped. The module's own instruments are multi-page and looped, so the intro reached it inside a
minute - and it is why `check-draw`, `check-res` and `check-text` all passed while `check-aw` and
`check-input` did not: the short gates never get there.

Looping now restores the **page and the window** with the position, which needs two fields the
voice record did not have - `V_PAGE0` and `V_TOTAL`, taking `V_SIZE` from 15 to 18. Worth naming:
**the mixing gate proved the output byte-exact over two page boundaries and still missed this**,
because its sample does not loop. A gate proves what it exercises.

**Three wrap tests now compare only the high byte**, the ring's end being page-aligned, and an
`ASSERT (RING_END & $FF) == 0` makes sure it stays that way.

**What the gate's own two false starts are worth recording for:**
The ring cursor is not at `RING_ADDR` when a probe starts, because the interrupt has been mixing
since boot - silently, every voice inactive, but `mix_block` advances the cursor whether or not a
voice contributes - so the probe calls `silence_ring` first. And the first model wrote the ring
contiguously while the machine, through bug 2, did not. Both corrections were right and neither
changed the verdict, which is what said the remaining faults were real.

**For the record, the thing I5's own definition names: "the mixer output stays byte-exact on
real sound resources".** Every check here proves the voice records that go *in* -
page, position, increment, end, loop point, volume table - and none of them proves the bytes
that come *out*. `check-snd` does prove output byte-exact, but against a **synthetic ramp** in
a single page: its model computes each sample as `pos & 0xFF` and has no page stepping and no
loop. So the mixer has never been checked against a sample it has to walk across pages.

That matters more than it did an hour ago, because fixing `voice_run` (below) **changed what the
mixer does** on exactly those samples, and nothing currently re-proves it.

| what | how it is checked |
|---|---|
| the header | three modules, delay with and without `op_playMusic`'s override, `numOrder`, all 128 order entries, all 15 instruments |
| the event walk | three cases, one of them crossing a 1024-byte block into the next order |
| the four voice records | after 1, 70 and 100 events |
| `op_playSound` | six cases: a stop, a loop, a 22,690-byte sample over three pages, both ends of the pitch table, and the volume clamp |
| the tuning | eleven periods, worst error 0.96 of a 1/256th step |

**`op_playSound`'s gate is checked against the reference's own numbers, not only against a
model of them.** The host probe logged 970 `snd_playSound` calls while the reference played the
game, with each call's resource, pitch index, volume, channel and the sample length and loop
length it produced. The cases come from that log and carry its lengths, so a wrong model and a
wrong machine would have to agree with the engine to pass. Every case also checks that **the
other three channels did not move** - an IX computed from the wrong operand is how the module
path first went wrong, and it showed as all four channels changing at once.

The one case not from the log says so: no call in 970 has a volume above `0x3F`, so the clamp
at `vm.cpp:715` has to be provoked deliberately.

**What `op_playSound` needed beyond the arithmetic:**

- **No divide.** `snd_playSound` hands the mixer `frequenceTable[freq]` (`vm.cpp:716`) and the
  mixer makes a step of it with `(freq << 8) / rate` (`mixer.cpp:62`) - which is exactly our
  voices' 8.8. So `tools/mksndfreq.py` reduces the reference's own forty frequencies
  (`staticres.cpp:61-67`) to forty increments at build time and the opcode is a lookup. The
  gate recomputes them from the reference and asserts the generated table matches, so a wrong
  digit in a table of forty cannot hide.
- **The channel masked on both paths.** The reference masks for the play (`vm.cpp:715-716`)
  and not for the stop, where `stopChannel` merely asserts `channel < 4`. Masking is the safe
  reading, and the log says it costs nothing: all 970 channels are already 0..3.
- **A missing resource returns before the volume test**, as `vm.cpp:698` does - so an absent
  sample does not stop the channel either.

**THE MIXER NOW MAPS EACH VOICE'S OWN PAGE, which it did not before.** `SND_MAP_PAGES` was
empty in the game: every voice read whatever MMU7 happened to hold. That was survivable while
I1's voices were a resident ramp and is not survivable with real samples. It now maps
`V_PAGE`, and the **interrupt** puts MMU7 back once around both blocks rather than four times -
reading the NextReg to find what was there rather than tracking it, because the frame boundary
borrows the same slot for a sample header and the two have to nest.

**MMU7 IS NOW SHARED FOUR WAYS, and that broke three gates the moment the mixer joined it.**
The slot holds the Layer 2 draw band, the loader's staging window, the frame boundary's sample
header, and now the mixer's sample page fifty times a second. On the machine this is correct -
every borrower reads the NextReg back and puts exactly what it found, so the borrows nest. What
it is *not* safe against is a **checker that maps MMU7 and then reads 8K as four separate ZRCP
calls while the machine runs**. Three gates did exactly that:

| gate | how it showed |
|---|---|
| `check-res` | three resources differing from the card **at byte 2,048 exactly** - where the second chunk starts |
| `check-draw` | bands 0, 1, 4 and 5 wrong against the engine while 2 and 3 were perfect |
| `check-aw` | not this at all - see below |

Both now set `snd_off` before reading, which is what that flag was added for. The interesting
part is that **`check-res` had a fourth failure that survived turning the mixer's mapping off** -
RES03 differing at byte 18,432, again 2,048 into a page - and quiescing fixed that too. So the
race was the whole cause and the bisect's "still failing" was the same fault at a different
phase, not a second one. Had I stopped at the bisect I would have gone looking for a loader bug
that does not exist.

`check-aw` was a different thing and not today's doing. Its third claim was "the ring is not
silence, so the mixer ran", sampled **before the VM is let go** - and the game starts silent
now, since `init_voices` activating four ramp voices was I1 scaffolding. The ring is filled with
128 at boot, so silence there proves nothing in either direction. It now counts mixer passes
(`n_mix`) for that, and asks for a **non-silent ring after the run** - which is a stronger claim
than the old one, because nothing synthetic is playing any more: the only thing that can fill
the ring is the intro's own module.

**Two bugs found on the way that had nothing to do with sound.**

`raster.inc` wrapped the reader's leaf log at a hard-coded `rd_log + 8 * 32` while `aw.asm`
reserved eight records. In the game the reader therefore ran 192 bytes past its reservation,
and because the wrap compared only the high byte it landed five bytes into the C's image at
`$9C00`. polytest - where the code was written - reserves the thirty-two the wrap assumed, so
nothing there ever showed it; nothing in the game reads the log, so nothing there showed it
either. The length is now the includer's to declare (`RD_LOG_RECS`) and the compare is a real
sixteen-bit one. **A parameterised include with one hard-coded constant left in it is the same
class of fault as `STR_BLOCK` inside `DRAW_LOG` and the control block's 32-versus-256: the
third of its kind.**

And the slot count. Adding `aw_play_sound` meant a thirteenth jump-table entry in **three**
files - `aw.asm`, `vmtest.asm` and `jumptab.asm` - and the `ASSERT $ - jump_table == 39` in
the first two is the only thing that catches a slot added to one and not another. That assert
exists because exactly that happened to `aw_play_music`.

**Space.** All of this went into a program with nothing spare. `aw_play_sound` and `mus_voice`
had thirty-six identical bytes of resource lookup and voice multiply each, now `voice_locate`
once; everything from the sample header to activation was common to both, now `voice_setup`.
The pitch table and the leaf log went to the gap between the IM 2 vector table and its
trampoline, which is dead space that is nonetheless mapped at every moment. The upper block
ends at `$BEE3` against a `$BF00` ceiling and the resident block at `$9BD6` against `$9C00`.

**The standing warning about `check-snd` still applies, and less than it did.** That gate
proves four voices byte-exact against a **synthetic ramp**, and `sndtest.asm` still has no
end-of-sample or loop handling. What has changed is that the game's own path - `voice_run`'s
block splitting, `voice_advance`'s page stepping and loop point - is now gated on real samples
through check-mus, including one that spans three pages. What is still not gated anywhere is
the **mixed output** of a real sample: every gate here checks the voice records that go in,
not the bytes that come out.

#### I6. Part transitions - DONE, `make check-part`

**Three parts set up on the machine exactly as `setupPart` describes**, checked against the
reference's own `memListParts` (`parts.cpp`) through `tools/mkparts.py` - so a wrong table here
would have to agree with the engine's to pass. The cases cover the shapes: the introduction (no
second polygon set), a gameplay part that has one, and a cinematic that does not.

```
part 1  palette 0x17, bytecode 0x18@73, polygons 0x19@75, no second set, silent
part 2  palette 0x1a, bytecode 0x1b@73, polygons 0x1c@76 + 0x11@84, silent
part 5  palette 0x23, bytecode 0x24@73, polygons 0x25@75, no second set, silent
```

`aw_setup_part` takes a part **index** - the C turns the id into one and bounds-checks it, since
that is where the id arrives - and does the reference's four things in order: stop the player and
every channel (`initForPart`, before `setupPart` touches a resource), invalidate everything
(`resource.cpp:298`), load the part's four resources (`:310`), and point the three windows at
them. Every load goes through `aw_load_res`, the path `check-res` already proves byte for byte
against the card, so this adds no new way to get a resource wrong - only a new reason to ask for
one.

**Three things had to become variable, and one of them could not afford to be.**

| | |
|---|---|
| the cinematic segment | `seg_base` already was; it now comes from `cin_base` |
| the **second** polygon set | new: `vid2_base`, and `aw_draw_poly` picks between them on the flag the C already sets. Five of the ten parts name one; a part without one still counts the draw and skips it, because there is nothing to read |
| the bytecode window | a **patched immediate**, not a load. `aw_code_window` runs on every fetch, so reading a base out of memory would cost about 4% of a frame - `aw_setup_part` writes `code_add + 1`, the same trick the mixer uses for its increments |

The palette is the one resource that is not simply paged in: `apply_palette` reads it out of the
text page at `PAL_BASE`, so its 1,024 bytes are copied there once the resource is resident, with
MMU7 borrowed and put back because the mixer reads a sample through the same slot from inside the
interrupt. `check-part` compares those bytes against the card.

**A bad part id records a fault rather than halting.** The reference calls `error()` on an id
outside `0x3E80..0x3E89` (`resource.cpp:287`); ours sets `FAULT_BAD_PART` and carries on with the
part it has, because a bad id would be a bug in our VM and a checker can read a fault where it
cannot read a halt.

**Space, again, and this time it came from I1's scaffolding.** `$DE00` held a 256-byte ramp that
`init_voices` used to start four voices on; the game has started silent since I5, so nothing had
read it. That 256 bytes is now `PART_CODE`, holding `aw_setup_part` and `probe_walk`, and
`note_to_inc` had already moved to the seventy-two bytes between `SND_BLOCK` and the order table.
MMU6 is mapped at every moment, so code runs from it as happily as data sits in it - which is
what made both moves possible when the resident block had nothing left.

**And a fourteenth jump-table slot**, which is three files that have to agree and an `ASSERT
$ - jump_table == 42` in two of them. That assert exists because a slot was once added to one and
not another.

**What I6 does NOT yet prove:** that the VM then *runs* the new part - that its opcode stream is
the engine's from the new bytecode, and that its first frames draw what the engine draws. The
transition is right; the playing of what it set up is I9a's and I10's.

#### I7. The full-screen bitmap path - DONE, `make check-bmp`

**Three bitmaps presented on the machine, all 49,152 pixels of each identical**, in page 0, not
resident, with the heap cursor untouched.

The machine's half turned out to be a **copy, not a deplane**. `copyPage(const uint8_t *src)`
(`video.cpp:550`) unpicks four planes 8,000 bytes apart, eight bits at a time, into 320x200 at
four bits a pixel - and `mkassets.py` already does exactly that at build time, writing the result
as **our** page: 256x192 at 8bpp, 49,152 bytes. `make check-bitmap` proves that deplaner is the
engine's pixel for pixel on real resources, so the two gates together cover `copyPage` end to
end and the deplaning never has to happen at 28 MHz.

**Two things the reference does that were easy to get wrong, and both are now checked:**

| | |
|---|---|
| a bitmap goes to **page 0**, always | `video.cpp:554` takes `_pages[0]`, not a page id |
| a bitmap is **not kept** | `loadMarkedAsNeeded` loads an `RT_POLY_ANIM` into a scratch pointer, presents it and marks it `NOT_NEEDED` (`resource.cpp:193`, `:211-214`) |

The second is not a nicety. **Part 7 loads seventy of them**, and seventy times six pages is more
memory than the machine has - so ours go to a fixed six-page scratch at `BMP_PAGE`, between the
cinematic segment's eight pages and the heap's forty, and `aw_load_res` neither marks them
resident nor moves the cursor. `check-bmp` asserts both, because a bitmap that quietly entered the
heap would pass a pixel comparison and exhaust the machine forty resources later.

**The cost, which nothing had measured:** 49,152 bytes of `LDIR` is about **1.8 frames** at 28 MHz.
The reference's deplane of 32,000 bytes is not cheap either, and the plan's own note stands - 70 of
these load in part 7 and **zero** in 72,000 frames of parts 2 and 3, so no budget so far has paid
for this path. It is a stall at a scene change, not a per-frame cost.

**Space is now the binding constraint on everything.** Fitting this needed `MUSIC_CODE` lowered to
`$BAD0` - the C's image ends at `$BAC3`, so 136 bytes were sitting unused between them, and the
`ASSERT $ <= MUSIC_CODE` below the C's include polices it. `present_bitmap` and `voice_locate`
moved into the reclaimed space, and `hex_digit` went to MMU6 beside the two name-builders that
call it. The resident block ends at `$9C04` against a `$9C08` ceiling: **four bytes**.

#### I8. The code screen, and its bypass - DONE, `make check-part`'s boot case

**The protection screen is a game part, and the bypass is a different starting part number.**
`engine.cpp:71-73`:

    uint16_t part = GAME_PART1;  // This game part is the protection screen
    #ifdef BYPASS_PROTECTION
      part = GAME_PART2;

There is no special-case code to port: the wheel screen is drawn by the same opcodes as
everything else. So I8 is a starting index - `START_PART`, 0 for the wheel and 1 with
`BYPASS_PROTECTION` - and the game now boots into it.

**One binary still serves the game and every gate**, which is the part worth recording.
`fname` is zero-filled in the image and every checker **pokes** it before setting `go`, so an
empty first byte means nothing asked for a particular segment - and that is the game starting
normally. A poked name keeps the fixed load all fourteen gates are built on, untouched; an empty
one takes the part path. `check-part`'s first case pokes nothing and gets part 0:

```
boot  palette 0x14, bytecode 0x15@73, polygons 0x16@74, no second set, silent
```

**The pc guard cost a gate to get right.** The fixed load sets it from what the loader last
read, and the part path originally joined *above* that store - so a part ran with the length of
the **last resource loaded**, which is the cinematic, not the bytecode. The boot case came back
with a guard of 5,124 when RES15 is 4,321, and 5,124 is resource `$16` exactly. `aw_setup_part`
takes the length from the resource table now, and the part path joins below the fixed path's
store.

The boot case also waits two seconds rather than polling for `done`: with no name poked the game
does not stop, because `main` never returns. Two seconds is past the three loads and well short
of the VM getting around to requesting a part of its own, which would change the very thing
being checked.

**What is still owed here:** the wheel screen needs the **code wheel's own input** - it asks for
a code and the player types it. That is `op_drawString` and the keyboard, both of which exist,
driven by part 0's own bytecode - so it should need no new code, but nothing has watched it run.
That is I10's business, and `BYPASS_PROTECTION` is what makes I10 reachable without it.

#### I9. Save and load - THE SAVE IS DONE AND GATED, `make check-save`. The load is not.

**A 198,272-byte save, written from page 10 through esxDOS, every field matching the machine it
was taken from** - the VM's variables, call stack, thread pcs and channel flags byte for byte; the
palette and page state; the player down to its pattern position; all four voice records; the
heap's load order; and all 24 bands of the four Layer 2 pages. The load order for part 0 comes out
`0x14 0x15 0x16` - its palette, bytecode and cinematic, in heap order.

**It cost ZERO resident bytes**, which is the only reason it could be written at all. Both things
a save has to know that nothing keeps are **derived** in page 10 instead:

| | |
|---|---|
| which part is running | `part_table`'s rows each name a bytecode resource, and `code_add + 1` holds the page that resource landed at - so matching one against the other identifies the part, and no `cur_part` byte has to exist |
| the heap's load order | `res_page` maps id to first page, so walking pages upward from `RES_FIRST_PAGE` and asking which id owns each recovers it - which is how `resource.cpp:358` derives it too, by walking `_memPtrStart`. Stepping past a resource's whole page count matters: without it the second page of a six-page bitmap reads as another resource starting |

The C's own symbol table does the rest: `tools/mkexp.py` turns its link map into EQUs, so the paged
save reads `aw_vars` and the rest directly. **No C code was written for I9 at all**, which was
forced - the C could not grow by a byte - and turned out better than the alternative.

**A save happens at the frame boundary**, where the reference tests `sys->input.save`
(`engine.cpp:98-104`), never mid-opcode, and for the same reason: half the state is the VM's and
it is only consistent there. Interrupts are off throughout - esxDOS wants them off, and a band is
written out of MMU7 which the mixer borrows fifty times a second - so a save is silent for its
duration, as the reference's is.

**A LATENT TRAP MADE LOUD, and it cost most of a session to find.** `sjasmplus` reports the size
of the C's **image**, and `ASSERT $ <= MUSIC_CODE` compared against that - but **the C's BSS lives
above the image and is not in it**. `_aw_log_count` sits past the image's last byte. So a
`MUSIC_CODE` that satisfies the assertion can still land inside the C's variables, and the
assertion sees nothing wrong.

Walking into it looked like this: the VM dispatched 13 records and stopped, nothing drew, the ring
stayed silent - and on a second arrangement, 53,256 records and a fault code of 208 that no part of
our code writes. Four hypotheses were wrong before the right one (the moved `aw_frame_sync`, a
symbol collision from including the C's map, NEXLOAD's stack smashing the top of the upper block -
that one measured **zero** corrupted bytes - and the loop bound itself). What found it was
reverting `vm.c` to the exact revision where the gate last passed, which is the one experiment that
could not be argued with.

`tools/mkexp.py` now emits **`CC_TOP`** from the link map - the highest address the C occupies,
plus eight for the last object's own size - and `aw.asm` asserts `CC_TOP <= MUSIC_CODE` alongside
the old check. The build fails loudly now where it used to corrupt quietly.

**AND THE SAVE FOUND THAT I8 HAD SHIPPED A GAME THAT RAN ZERO FRAMES.** The C's frame loop was bounded
by `CTL_FRAMES`, which is zero-filled in the image and poked by every checker - so booting normally
set part 0 up correctly and then did nothing at all. `check-part` could not see it, because it
proves the part is *set up* and stops there; that limit is written down under I6 in as many words,
and this is it biting. **That fix is REVERTED and the gap is still open**, because closing it costs the C
36 bytes and the margin between `CC_TOP` and `MUSIC_CODE` is 23 - the upper block cannot move up
without crossing `$BF00`, which is the `.nex` loader's stack. So the shipped game still runs zero
frames, and `check-save` pokes a frame count of its own like every other harness does. **A gate
that stops one step short of the thing you care about will let exactly that thing through** - and
the fix for this one is blocked on thirteen bytes of address space.

**The gate had to freeze what it measures.** A save is a snapshot and the game keeps running, so
the first attempt reported four differences that were nothing but elapsed time. Poking
`CTL_FRAMES` to zero cut it to two - `pg_ptr1` and `aw_vars`, the fields the VM touches every
frame. The answer is the C's own loop order: it runs `aw_frame_sync`, then the part block, then
breaks on budget-or-fault, and only **after** that runs the frame's threads. So exhausting the
budget in the same breath as the save request makes the saving frame the **last** frame, with no
thread work after it, and the machine stands still on exactly the state the file holds.

**THE LOAD IS WRITTEN AND RUNS; ITS HALF OF THE GATE FAILS AND I HAVE NOT ISOLATED WHY.**
`make check-save` passes the save half and fails the load half on six fields. The load reaches its
end - it stamps `sv_done`, which is how the gate knows a 198,272-byte read finished - and most of
the state comes back. What does not match:

```
pg_ptr1        0x01 in the file, 0x12 on the machine
mus_cur_order  0x00 in the file, 0x80 on the machine
the four voice records, aw_vars at byte 1, aw_call_stack at byte 0, aw_pc at byte 0
```

**MEASURED, not guessed: the load writes them wrongly.** Reading the fields the instant `sv_done`
is stamped, with nothing else poked, and again twelve frames later:

```
the file says   pg_ptr1=0x01 mus_cur_order=0x00 aw_pc[0]=ffff aw_vars[0]=0000
at sv_done      pg_ptr1=0x12 mus_cur_order=0x80 aw_pc[0]=0807 aw_vars[0]=0001
a moment later  pg_ptr1=0x12 mus_cur_order=0x80 aw_pc[0]=0807 aw_vars[0]=0001
```

Already wrong when the load finishes, and unchanged afterwards - so the gate's freeze is sound and
the fault is in `sv_load`. The values are telling: `aw_pc[0]` holds `0x0708`, a **live** program
counter, where the file holds `0xFFFF` for an inactive thread. That is not corruption - **it is
the running game's own value, untouched.** The arrays were not written at all.

**WHAT THE INSTRUMENTATION PROVED, which is the useful part.** `sv_rblock` now records its first
read - the count, the esxDOS error, and the first byte that landed - into page 10 where a checker
can read it. Pointed at the `aw_vars` read:

```
a read was recorded: yes
it returned BC = 512 bytes, first byte 0x00, esxDOS error 0x00
the file's aw_vars[0..1] = 0000; on the machine afterwards = 0001
```

**So the read happens, succeeds, and lands in the right place.** Byte 0 is written correctly and
is still correct at the end. **Exactly one byte differs**, at offset 1 - which rules out a
misplaced read, a short read, and a failed read all at once. Something writes `aw_vars[0]` to
`0x0100` between the load finishing and the comparison.

**Three different freeze mechanisms have failed to stop it** - zeroing `CTL_BUDGET` (only opcodes
spend budget, so it does not stop the frame the load is in), poking `CTL_FAULT` before the request
(races the boundary, and the load is then never read at all), and poking `CTL_FAULT` 300ms after
the request so it lands mid-load (still eight fields wrong). That last one should have worked: the
C breaks on a fault at the check right after `aw_frame_sync` and before any thread work.

**I have stopped here rather than try a fifth time.** Four attempts have each cost a gate run of
roughly fifteen minutes and none converged. What is left to establish is simply **what runs**
between the load and the reading - read `CTL_FRAMES_DONE` either side of the load and see whether
the loop iterated at all. If it did not, the writer is not the VM and the search moves elsewhere
entirely; if it did, the freeze is still the problem and the C's loop order needs re-reading rather
than re-guessing.

**An earlier hypothesis, recorded because it was tested and wrong.** `sv_rblock` bails silently on a non-zero `err`,
and `load_code` writes `err` during the part setup between the two passes - so clearing `err`
before pass two looked certain. It changed nothing: the same eight fields, the same values. The
change is kept because a read pass that silently does nothing on a flag somebody else set is the
wrong shape regardless, but it was not the fault.

**So the arrays are still never written, and I do not know why.** What is ruled out: the gate's
freeze (measured), `err` (tested), and the file's layout (the save writes header, `aw_vars`,
`aw_call_stack`, `aw_pc`, `aw_state`, pages; the load reads them in that order, and the save half
of the same gate passes against the same offsets).

**The next step is instrumentation, not another hypothesis.** `sv_load` should record what it
actually did into spare page-10 bytes the checker can read: `err` after pass two's open, the byte
count the first `F_READ` returned, and the first byte it landed. Three bytes of evidence will say
whether the reads happened at all, happened and returned nothing, or happened and went somewhere
else. **Two guesses from the symptom have now cost a gate run each**, which is the same pattern as
I5's voice setup - where what finally worked was reading the machine rather than reasoning about
it.

**Two real bugs were found getting this far, both the same shape.** `copy_palette` mapped the
palette resource into **MMU2** for its source, and `apply_palette` maps the text page into MMU2
too - and MMU2 is where page 10's code executes from. The load sawed off the branch it was sitting
on: the next instruction fetch came from palette data. It showed as a load that never finished
with **no esxDOS error to explain it**. The source moved to MMU3, where page 11 is empty, and the
load now sets `pal_req` and lets `aw_blit` apply it - which is the reference's own
`paletteIdRequested` arrangement, so it is more faithful as well as safer.

**That is the constraint written down under I9's groundwork, biting from a direction I had not
checked.** Anything else moved into paged space has to be audited for **MMU2 use**, not merely
for drawing - which matters for I9a and I10.

**And the gate's freeze took three attempts, all ordering.** Between two ZRCP commands the machine
keeps running, so whichever of the pair stops the VM must be poked **second**: zeroing the budget
or setting the fault first ends the loop in the gap, and then nothing is left to read the request.
Zeroing the budget also does not stop the frame the load happens in, because only opcodes spend
budget - `CTL_FAULT` breaks at the very next check, before any thread work.

**What is left of I9:** the load's six fields. Reading the file back is the mirror of writing it, with one
piece of real work - the resident resources have to be reloaded **in the saved order** so the heap
reconstructs identically - and then the gate the plan asks for: save mid-part, reload, and compare
the opcode stream from that point against a run that never saved. The stream comparison is the
real test; a state dump that matches can still resume wrongly.

**The program ran out of the 48K it can address at once, and I9 is the step that hit the wall.**
The resident block ends at `$9C04` against a `$9C08` ceiling - **four bytes** - and the C's image
ends thirteen bytes below `MUSIC_CODE`. I7 only fitted by reclaiming 136 bytes that were sitting
unused between the C and the music code and pushing `hex_digit` into MMU6. The natural place for
I9's state-gathering is the C, because the C is where the state lives, and the C cannot grow by a
byte.

**Where the room came from.** Every `ORG` in `src/aw.asm` is at `$8000` or above, so
**`$4000-$7FFF` - pages 10 and 11, bank 5, sixteen kilobytes - was empty in the image**, and
SAVENEX never wrote it: the `.nex` was 33,280 bytes. Code ORGed there lands in page 10 and runs
at its own assembled address the moment page 10 is mapped at MMU2, which is where it lives at
boot anyway. The `.nex` is 49,664 bytes now, because SAVENEX writes the whole bank once anything
is in it - 16K of load time for however much of it gets used.

That is the right home for **rare** work: save and load run at a frame boundary, once, so the two
NextReg writes to page it in cost nothing measurable. It is **not** a home for anything per-frame,
because MMU2 and MMU3 are the polygon segment window and every draw re-maps them. And esxDOS pages
itself over the **bottom** 16K during a file call, not `$4000`, which is what makes a file writer
up there possible at all.

**What is in place:** the region, its borrow-and-restore stub (`aw_write_file`, in MMU6 because the
resident block had no room even for that), and an esxDOS writer - `F_WRITE`, and `FA_WRITE` of
`$0C` rather than `$0E`, which this project has paid for once already. `check-map` and `check-aw`
both pass with the bigger image, so the region is additive and harmless.

**What is NOT in place, and is the whole of I9:** nothing calls the writer yet. The state has to be
enumerated over the five objects the reference serialises, in this order (`engine.cpp:136-138`):
`vm.saveOrLoad` (`vm.cpp:736` - 1,408 bytes of variables, call stack, thread pcs and channel
flags), `res.saveOrLoad` (`resource.cpp:358` - an **ordered** list of resident ids plus the part
id, replayed on load so the heap reconstructs identically), `video.saveOrLoad` (`video.cpp:624` -
the palette ids, the page mask, and **all four pages**, which for us is 196,608 bytes),
`player.saveOrLoad` (`sfxplayer.cpp:212`) and `mixer.saveOrLoad` (`mixer.cpp:156`).

Our format does not have to be theirs - nothing reads our saves but us - so the work is enumerating
the state, not matching a layout. The mixer and the player being in that list is the part worth
noticing: a save taken mid-note has to restore the note, and since I5 a voice's record is eighteen
bytes including the two fields a multi-page loop needs.

**Gate:** save mid-part, reload, and both the VM state and the opcode stream from that point match
a run that never saved. The stream comparison is the real test; a state dump that matches can still
resume wrongly.


#### I10. Playable to the end

Every part, real input, sound, from the first screen to the ending.

**Gate:** a full playthrough under the patched ZEsarUX, recorded, with the per-frame
budget re-measured against the per-part table in *Phase F*. The playthrough is the
gate. Nothing smaller is a substitute for it, which is the whole reason this chain
exists.

#### H1. Real hardware

Card boot, the joystick's physical wiring, and timing on metal without the three
local ZEsarUX patches (`prescalar`, `readback`, `autorestart`). Its gate cannot be
run until the KS3 arrives, and it is the only step in this document of which that is
true. It is also where the one genuinely unmeasurable number lands: esxDOS read
rate, which step 5 established the emulator cannot time.

### Four gates are narrower than they sound, and must be re-run before I10

Every gate in Chain 1 that used bytecode used **the intro's** bytecode. The intro is
a cinematic: it draws polygons, blits, and pauses. It does not exercise what gameplay
exercises.

- **Gate D** proved 763 records of the intro's stream. Later parts dispatch
  thousands of opcodes a frame, and `check-parts` showed four of the five numbers
  that rested on two parts move when a fifth is measured.
- **Gate C and the reader gates** drew from the intro's trace. The `wide` bucket
  reaches 303 and the widest fan-out across all parts is 99 children in one record.
- **I4's and I5's gates** will cover the intro's strings and the intro's sound
  events only.
- **Gate E's sound claim is the narrowest of the four, and the wording here has been
  too generous about it.** `make check-snd` proves the mixer's arithmetic - four
  voices byte-exact at three block lengths, nine ring wraps - but `src/sndtest.asm`
  feeds it **a synthetic ramp**, chosen deliberately so that a wrong pointer shows as
  a wrong value. It has never mixed one of the game's own sound resources, and
  nothing anywhere has parsed a music module. "Four voices byte-exact" is true of the
  arithmetic and says nothing about the data.

So I2, I4, I5 and Gate D itself each get a second run against a **gameplay** part
before I10 is allowed to pass. That is cheap - the reference length is a parameter
now - and it is the difference between "the intro works" and "the game works".

### Decisions and measurements still owed

None of these is integration work, and that is exactly why they had no place in the
chain and were about to be lost. Each one says who owns it and what it blocks.

| | owner | what it blocks |
|---|---|---|
| **the PUSH-versus-stores crossover, re-measured against GAMEPLAY's span distribution.** The 12-byte crossover was established on the intro, where 88% of spans are longer. In gameplay 96% are under 47 bytes and the median is far shorter, so *the fallback may be the common path, not the exception* - this document already says to re-check it before trusting it | mine | nothing until the budget is tight; then it decides whether the two optional optimisations help or hurt |
| **F4, the palette question.** RGB444 to RGB333: 44.4% of palettes lose nothing, 35.1% lose one colour, the worst loses five of sixteen. A quantiser that nudged colliding entries apart would trade hue for separation at no run-time cost | **David's** | not a gate - page comparisons are on indices, not colours - but it decides what a player actually sees, so it wants settling before I10 |
| **F5, the 320x256 mode**, decided against in decision 1 | **David's** | a re-read, not a task. It would change the rasteriser's geometry, so it must stay decided-against or be reopened before I2, not after |

### What could still stop this, worst first

1. **Memory residency (I1).** The only redesign risk left. Two sliding windows, the
   sound player and a 305,919-byte heap have never been asked to coexist.
2. **The budget in the jail: 74% of the machine** with the mixer on top, as the
   rasteriser stands - 52% at the floor. The two deferred rasteriser optimisations
   are what the headroom is for, and integration adds cost that has not been
   measured. If they are spent and a gameplay part still overruns, there is no third
   optimisation identified.
3. **The arena's bitmap path (I7).** Wholly new work, not wiring, and the frames it
   lands in are the ones already doing 70 loads.
4. **In-frame resource loads.** `op_updateMemList` loads one resource inside a frame
   and the largest is 65,230 bytes. At any rate above 100 KB/s a held frame covers
   it; below that it becomes a design decision, and **step 5 established the
   emulator cannot time it**, so this stays open until H1.


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
- **A runtime you did not write returns its interrupt state, not yours.** z88dk's
  exit is `im 1 / ei / ret`, and `EI` defers acceptance by one instruction - the
  `RET` - so the interrupt lands before the caller's next instruction and a `di`
  placed after the call is always one instruction late. With the bottom 16K paged to
  data rather than ROM, `$0038` is data, and the machine executes it. Cost: most of a
  session, and four wrong diagnoses that were each a real fault.
- **When the result is not repeatable, suspect the reader.** Every one of 0, 64, 122
  and 354 matching records was a correct read of a machine that had already started
  destroying itself. Nothing was wrong with the thing being measured.
- **Move the comparison to where the fault happens.** Checking each record against
  the reference *on the machine* and stopping dead beats reading a trace afterwards,
  because whatever went wrong went wrong before the first bad record and whatever
  destroys the evidence happens after it.
- **A reference must outlast the run it judges, and share its inputs.** A 40-frame
  reference against a 40-frame run ends mid-test and reports neither pass nor fail. A
  reference generated with synthetic input diverges at the first `condJmp` on the
  hero's action variable, and both sides are right about their own world.
- **Stopping after a named stage is worth more than a breakpoint.** ZEsarUX's
  breakpoints reject a `0x` prefix and their default action opens a window `--vo null`
  cannot open, so they fire and do nothing. A `stage_stop` byte and an opcode budget
  of zero localised in two runs what breakpoints had failed to localise in dozens.
