# Host-side driver. Every target is a thin wrapper around the container so
# nothing but the native ZEsarUX app is installed on the Mac.
#
# The shape, the FRESH rule and the check-<name> convention follow wolf3d-next;
# what is new here is the `cc:` step, because this port compiles C.

DC      := docker compose
# PYTHONUNBUFFERED, because a checker that is KILLED loses everything still
# sitting in stdio's buffer.
RUN     := $(DC) run --rm -e PYTHONUNBUFFERED=1 tools
BUILD   := build

NATIVE_ZESARUX := $(HOME)/Applications/ZEsarUX.app/Contents/MacOS/zesarux
WOLF3D  ?= $(HOME)/src/wolf3d-next

# The player's own game files. Never in the repository - see docs/licence.md.
DATA_DIR ?= data

ZESARUX := zesarux --vo null --ao null --machine tbblue --enable-remoteprotocol \
                   --remoteprotocol-port 10000 --enable-breakpoints \
                   --tbblue-max-turbo-rom 8 --tbblue-max-turbo-everywhere 8 \
                   --enable-esxdos-handler --esxdos-root-dir /work/$(BUILD)/assets \
                   --nex-no-automount-esxdos \
                   --nosplash --noconfigfile

.PHONY: help image doctor shell asm cc cc-game emu clean distclean \
        assets check-data check-ref frame-load voices check-span check-cc \
        check-map check-aw check-input check-draw check-res check-text check-mus check-poly check-mix check-polycost check-reader check-readmachine check-load check-boot check-pace check-snd check-parts check-part check-bmp check-save check-bitmap \
        toolchain-diff play record check-sndcalls gus-assets check-gus check-card play-gus check-ddma check-ddma256 measure-ddma \
        asm256 check-wide check-poly256 check-readmachine256 check-draw256 check-intro256 \
        check-text256 check-bmp256 check-save256 check-part256 check-res256 check-aw256 \
        measure-wide320 measure-wide320-isr

help:
	@echo "make image          build the toolchain container (first run: ~10-20 min)"
	@echo "make doctor         report tool versions from inside the container"
	@echo "make assets         convert the player's data to Next form (host only)"
	@echo "make check-data     Gate A: every resource decodes and its CRC cancels"
	@echo "make check-ref      Gate A: the reference matches the engine byte for byte"
	@echo "make frame-load     model every frame against the pause the script asked for"
	@echo "make voices         how many mixer voices are live, and at what rates"
	@echo "make cc             compile the C to a raw binary + .exp"
	@echo "make asm            assemble src/ -> $(BUILD)/*.nex; the game, aw.nex, is 320x256"
	@echo "make asm256         the earlier 256x192 game -> $(BUILD)/aw256.nex (its gates: check-*256)"
	@echo "make check-span     Step 0: what one polygon span costs, measured"
	@echo "make check-cc       Gate B: C calls assembly at a fixed address and returns"
	@echo "make check-poly     Gate C: the rasteriser, pixel-exact vs the reference (320x256)"
	@echo "make check-wide     W1: RefVideo320 is the engine's picture at one byte a pixel. Host only"
	@echo "make check-mix      Step 1: what one output sample of the mixer costs"
	@echo "make check-polycost Step 2: T a polygon and T a span, fitted apart (256x192 harness)"
	@echo "make check-reader   Gate C4: the reference reader IS the engine's"
	@echo "make check-readmachine  Gate C4: the Z80N reader, pixel-exact"
	@echo "make check-load     Step 5: how fast esxDOS reads, and what a part costs"
	@echo "make check-aw       I1: one program, everything live at once"
	@echo "make check-map      I1: the game's five windows and its code coexist"
	@echo "make check-boot     Gate D: the VM dispatches exactly what the engine does"
	@echo "make check-pace     Gate E: the input mapping, and pacing to its deadline"
	@echo "make check-snd      Gate E: four voices byte-exact, and the DMA's rate"
	@echo "make check-parts    Step 9: every part the probe can reach, separately"
	@echo "make check-bitmap   is our full-screen deplaner the engine's? Host only"
	@echo "make toolchain-diff has the shared toolchain drifted from wolf3d-next?"
	@echo "make check-sndcalls plan-pi-gus A0: the intro's sound calls in CSpect = the engine's (a window)"
	@echo "make gus-assets     plan-pi-gus A1: the Pi card's files, built by nextpi-gus (NEXTPI_GUS)"
	@echo "make check-gus      plan-pi-gus A1: the card holds every sound byte for byte, the pins"
	@echo "make check-card     plan-pi-gus A2/A3: the game with a fake Pi card in CSpect (windows, one at a time)"
	@echo "make measure-ddma   plan-ddma.md D2: a 320x256 row by the zxnDDMA's 2D fill against the CPU, CSpect 4.5"
	@echo "make check-ddma     plan-ddma.md D1: the zxnDDMA's fills against the plain ones, CSpect 4.5 on Xvfb (check-ddma256: 256x192)"
	@echo "make play-gus       plan-pi-gus A4: play it in CSpect, the card on the Mac's speakers (CARD=0: the Z80 path)"

image:
	$(DC) build

doctor:
	@echo "=== host ==="
	@echo "docker context: $$(docker context show)"
	@docker version --format 'docker server: {{.Server.Version}} ({{.Server.Arch}})'
	@echo "=== assembler / emulator image ==="
	@$(RUN) sh tools/doctor.sh
	@echo "=== C compiler image ($(CC_IMAGE)) ==="
	@echo "digest:      $$(docker image inspect $(CC_IMAGE) --format '{{index .RepoDigests 0}}' 2>/dev/null || echo 'not pulled')"
	@$(CC_RUN) sh -c 'echo "arch:        $$(uname -m)"; \
		printf "zcc:         "; zcc 2>&1 | head -1; \
		printf "zsdcc:       "; (z88dk-zsdcc --version 2>&1 | head -1) || true; \
		printf "sccz80:      "; (ls /opt/z88dk/bin/z88dk-sccz80 >/dev/null 2>&1 && echo present) || echo MISSING'
	@echo "--- C smoke test, the configuration the VM will use ---"
	@printf 'volatile int n;\nint main(void){for(;;)++n;return 0;}\n' > $(BUILD)/_smoke.c
	@$(CC_RUN) sh -c 'cd $(BUILD) && zcc +zxn -vn -SO3 -clib=sdcc_iy -m \
		-pragma-define:CRT_ORG_CODE=0xA000 -o _smoke _smoke.c >/dev/null 2>&1' \
		&& echo "             OK - $$(wc -c < $(BUILD)/_smoke_CODE.bin | tr -d ' ') byte CODE image, \
$$(grep -c 'addr, public' $(BUILD)/_smoke.map) public addresses" \
		|| echo "             FAILED"
	@rm -f $(BUILD)/_smoke*

shell:
	$(RUN) bash

$(BUILD):
	mkdir -p $(BUILD)

# ---- host-side only: no emulator, no container needed for these two ---------
assets: | $(BUILD)
	python3 tools/mkassets.py $(DATA_DIR) $(BUILD)/assets

check-data:
	python3 tools/checkdata.py $(DATA_DIR)

# Needs the host probe built and run first; see preflight/hostprobe/README.md.
PROBE ?= preflight/hostprobe/probe
check-ref:
	python3 tools/checkref.py $(PROBE)/trace.bin $(PROBE)/page0.bin \
		$(PROBE)/page1.bin $(PROBE)/page2.bin $(PROBE)/page3.bin

# The probe's own two reports. frames.txt and sound.txt are overwritten on every
# run, so an autoplay run and an intro run must be kept in separate files - see
# the README. FRAMES and VOICES can point at either.
FRAMES ?= $(PROBE)/frames.txt
VOICES ?= $(PROBE)/sound.txt
frame-load:
	python3 tools/frameload.py $(FRAMES)

voices:
	python3 tools/voices.py $(VOICES)

# ---- the C step -------------------------------------------------------------
# z88dk runs from ITS OWN pinned image, not the one built by this Dockerfile. It
# cannot be built on bookworm (Boost 1.74 against SDCC's required 1.79), and it
# does not need to be: upstream publishes an arm64 variant carrying
# z88dk-zsdcc. That image is Alpine and musl-linked, so it is a separate
# container rather than a COPY stage.
#
#   tag    z88dk/z88dk:20260907
#   digest sha256:3ef9ff8b174df4f9dfcae11b07763a5535168119a301cbdad4a52c8f30ce9782
#
# If upstream ever retags, pin the digest. If the image goes away entirely, the
# fallback is a from-source build with BUILD_SDCC unset, which gives sccz80
# rather than zsdcc - adequate here, because the VM's worst measured frame
# dispatches 96 opcodes against a 280 budget.
CC_IMAGE   ?= z88dk/z88dk:20260907
CFLAGS_ZXN := +zxn -vn -SO3 -clib=sdcc_iy -m --list
CC_ORG     ?= 0xA000
# REGISTER_SP, not CRT_STACK_ADDRESS: this is the stack pointer the C runtime sets
# on entry, and left to its default it put the stack inside $0000-$3FFF - which is
# where the bytecode window is mapped. Every push then wrote into the bytecode, and
# a RET eventually jumped into it: the machine was found executing at $0068 with
# its trace counter reading 129 when nineteen records had been written, and the
# bytecode's own second byte altered. The assembly sets SP before calling in, and
# this makes the runtime agree rather than overrule it.
#
# The STACK stays at $BF00, which is what SAVENEX declares and what NEXLOAD
# respects; moving it to $FF00 instead broke the load. Room for it is made by
# loading the VM's C LOWER rather than by raising the stack: at CC_ORG the C's code
# and data ended at $BBF5 and left 779 bytes, and the four HIGHEST globals were the
# ones reading wrong, in address order downwards, which is what that looks like.
CC_STACK   ?= 0xBF00
# The VM's C loads here, not at CC_ORG: 7,166 bytes of image plus about 1.5K of
# data, so it ends near $AE00 and leaves the stack four and a half kilobytes. Gate
# B's ctest keeps CC_ORG, because changing it would change what that gate proved.
VM_ORG     ?= 0x8C00
CC_RUN     := docker run --rm -v "$(CURDIR):/work" -w /work $(CC_IMAGE)

# Build order is C first, then assembly: the jump table the C calls sits at an
# address sjasmplus fixes by construction, so nothing is resolved twice.
#
# NOTE the _c suffix on the .exp: sjasmplus writes <name>.exp for the same base
# name, and without it the assembly symbols silently overwrite the C's.
# Each C program is compiled with the jump table that belongs beside it: the
# preflight one for ctest, src/aw/jumptab.asm for the virtual machine.
# The game's own build of the same C. Different control addresses, because the game
# has no spare 8K page for them: see the AW_CTL comment in src/aw/vm.c. A smaller
# record buffer for the same reason - the verdict is what matters and it is 32 bytes.
AW_CTL       ?= 0xC000
AW_EXP       ?= 0        # the game compares PICTURES, not streams: see src/aw.asm
AW_LOG_RECS  ?= 32       # the game's trace buffer: small on purpose, see RES_TABLE_AT
AW_IN        ?= 0xC380
AW_DRAW      ?= 0xC390
AW_MUS       ?= 0xC3B0
AW_SND       ?= 0xC3B4
AW_STR       ?= 0xC3A0

# The game's C sits HIGHER than the harness's, because the rasteriser and the reader
# are resident alongside it: see the CC_ORG comment in src/aw.asm.
# 0x9C20, not 0x9C00: the resident assembly grew past 0x9C00 when the mixer's block
# splitting went in, and the upper block had the slack to absorb the same shift at its end.
# MUSIC_CODE in src/aw.asm moves with it and CC_ORG there must match this exactly.
AW_VM_ORG    ?= 0x9C08

# AND THE GAME'S STACK POINTER IS THE ONE IN MMU6, not $BF00. The CRT sets SP itself from
# REGISTER_SP - that is how Gate D's stack was fixed in the first place - so setting it in
# src/aw.asm's start: achieves nothing: the C overwrites it before main runs. Moving the stack
# into MMU6's page and leaving this at $BF00 changed not one byte of behaviour, and cost an
# hour of believing the stack was the problem when the stack had not moved.
AW_STACK     ?= 0xD400

cc-game: | $(BUILD)
	@echo "  CC  src/aw/vm.c -> the game"
	@$(CC_RUN) zcc $(CFLAGS_ZXN) -pragma-define:CRT_ORG_CODE=$(AW_VM_ORG) \
	    -pragma-define:REGISTER_SP=$(AW_STACK) \
	    -DAW_CTL=$(AW_CTL) -DAW_EXP=$(AW_EXP) -DAW_LOG_RECS=$(AW_LOG_RECS) \
	    -DAW_IN=$(AW_IN) -DAW_DRAW=$(AW_DRAW) -DAW_MUS=$(AW_MUS) -DAW_SND=$(AW_SND) -DAW_STR=$(AW_STR) \
	    -o $(BUILD)/aw_vm src/aw/vm.c src/aw/jumptab.asm
	@python3 tools/mkexp.py $(BUILD)/aw_vm.map $(BUILD)/aw_vm_c.exp

cc: | $(BUILD)
	@set -e; for f in preflight/cc/*.c src/*.c; do \
		[ -e "$$f" ] || continue; b=$$(basename "$$f" .c); echo "  CC  $$f"; \
		$(CC_RUN) zcc $(CFLAGS_ZXN) -pragma-define:CRT_ORG_CODE=$(CC_ORG) \
		    -o $(BUILD)/$$b "$$f" preflight/cc/jumptab.asm; \
		python3 tools/mkexp.py $(BUILD)/$$b.map $(BUILD)/$${b}_c.exp; \
	done
	@set -e; for f in src/aw/*.c; do \
		[ -e "$$f" ] || continue; b=$$(basename "$$f" .c); echo "  CC  $$f"; \
		$(CC_RUN) zcc $(CFLAGS_ZXN) -pragma-define:CRT_ORG_CODE=$(VM_ORG) \
		    -pragma-define:REGISTER_SP=$(CC_STACK) \
		    -o $(BUILD)/$$b "$$f" src/aw/jumptab.asm; \
		python3 tools/mkexp.py $(BUILD)/$$b.map $(BUILD)/$${b}_c.exp; \
	done

# Extra assembler defines. The code-wheel bypass is a STARTING PART NUMBER and not a feature - see
# START_PART in src/aw.asm:
#
#     make asm ASMDEF=-DBYPASS_PROTECTION            the game starts at part 1, the intro
#
# The screen is the other: the game is 320x256 unless SCREEN256 is defined, and `make asm256` does
# that, writing build/aw256.nex (docs/plan-wide320.md).
#
# Use the short form. `--define=KEY` with no value swallows the next argument, which is
# --exp, and the symbol file then lands next to the source instead of in build/.
#
# Every gate builds without it, so the wheel screen is what the suite sees and what a player
# gets. I10's playthrough is the one thing that needs it.
ASMDEF     ?=

asm: | $(BUILD)
	python3 tools/mksndfreq.py $(PROBE) $(BUILD)/sndfreq.inc
	@test -f $(BUILD)/gusdata.inc || python3 tools/mkgusdata.py $(NEXTPI_GUS) $(BUILD) $(PROBE)
	python3 tools/mkparts.py $(PROBE) $(BUILD)/parts.inc
	@# src/polytest.asm's own default is the 256x192 harness, which INCLUDEs this vector; only the
	@# 256-suffixed Gate C targets write it now, so a clean build makes one here.
	@test -f $(BUILD)/interp.inc || python3 tools/mktables.py $(BUILD)/interp.inc
	@test -f $(BUILD)/csteps.inc || python3 tools/mkcsteps.py $(BUILD)/csteps.inc $(BUILD)/csteps.txt
	@test -f $(BUILD)/polytest.inc || AW_SCREEN=256 python3 tools/mkpolytest.py $(TRACE) $(BUILD)/polytest.inc $(BUILD)/expected.bin
	$(RUN) sh -c 'set -e; for f in src/*.asm; do \
		b=$$(basename "$$f" .asm); echo "  ASM $$f"; \
		sjasmplus --zxnext=cspect --fullpath $(ASMDEF) --exp="$(BUILD)/$$b.exp" \
			--lst="$(BUILD)/$$b.lst" "$$f"; done'

emu:
	$(DC) run --rm --service-ports tools $(ZESARUX)

# ---- I10: a person plays, and the machine is recorded while they do ----------
#
# The gate is "a full playthrough under the patched ZEsarUX, RECORDED, with the per-frame
# budget re-measured on the real thing against the per-part table". The playthrough is the
# player's; the other two are not, and should not depend on anyone remembering them.
#
#     make play        native ZEsarUX, in a window, with the game and ZRCP open
#     make record      attach and log until Ctrl-C, then report against the table
#
# Two terminals, `play` first. It is the NATIVE emulator, not the container's: the container
# runs headless (--vo null) because every gate reads over a socket and none of them needs a
# screen. A person does.
#
# O and P left and right, Q and A up and down, Space fire, ENTER to start - the boot
# handshake, which nothing pokes on real hardware.
PLAY_NEX  ?= build/aw.nex
play:
	@test -x "$(NATIVE_ZESARUX)" || { echo "no native ZEsarUX at $(NATIVE_ZESARUX)"; exit 1; }
	@echo "  ENTER starts it.  O/P left-right, Q/A up-down, Space fire."
	@echo "  In another terminal: make record"
	"$(NATIVE_ZESARUX)" --machine tbblue --enable-remoteprotocol 		--remoteprotocol-port 10000 --enable-esxdos-handler 		--esxdos-root-dir "$(CURDIR)/$(BUILD)/assets" --nex-no-automount-esxdos 		--tbblue-max-turbo-rom 8 --tbblue-max-turbo-everywhere 8 		--quickload "$(CURDIR)/$(PLAY_NEX)"

record:
	python3 tools/record.py

# ---- checks on the machine, over ZRCP ---------------------------------------
check-span: asm
	@$(RUN) sh -c '$(ZESARUX) >/tmp/z.log 2>&1 & \
		sleep 3; python3 tools/checkspan.py'

# Gate C: the rasteriser, pixel-exact against the reference. Regenerates the
# tables and the test vector first, because a stale vector is worse than none.
TRACE ?= preflight/hostprobe/probe/trace.bin
check-poly: | $(BUILD)
	python3 tools/mktables.py $(BUILD)/interp.inc
	python3 tools/mkcsteps.py $(BUILD)/csteps.inc $(BUILD)/csteps.txt
	python3 tools/mkpolytest.py $(TRACE) $(BUILD)/polytest320.inc $(BUILD)/expected320.bin
	$(RUN) sjasmplus --zxnext=cspect --fullpath -DWIDE320 --exp=$(BUILD)/polytest320.exp \
		--lst=$(BUILD)/polytest320.lst src/polytest.asm
	@$(RUN) sh -c '$(ZESARUX) >/tmp/z.log 2>&1 & \
		sleep 3; python3 tools/checkpoly.py'

# Gate C for the earlier 256x192 build (make asm256): the harness's own default, polytest.nex.
check-poly256: | $(BUILD)
	python3 tools/mktables.py $(BUILD)/interp.inc
	python3 tools/mkcsteps.py $(BUILD)/csteps.inc $(BUILD)/csteps.txt
	AW_SCREEN=256 python3 tools/mkpolytest.py $(TRACE) $(BUILD)/polytest.inc $(BUILD)/expected.bin
	@$(MAKE) --no-print-directory asm
	@$(RUN) sh -c '$(ZESARUX) >/tmp/z.log 2>&1 & \
		sleep 3; AW_SCREEN=256 python3 tools/checkpoly.py'

check-cc: cc asm
	@$(RUN) sh -c '$(ZESARUX) >/tmp/z.log 2>&1 & \
		sleep 3; python3 tools/checkcc.py'

# Step 2: separate per-polygon setup cost from per-span cost, by fitting both.
check-polycost: | $(BUILD)
	python3 tools/mktables.py $(BUILD)/interp.inc
	python3 tools/mkcsteps.py $(BUILD)/csteps.inc $(BUILD)/csteps.txt
	AW_SCREEN=256 python3 tools/mkpolytest.py $(TRACE) $(BUILD)/polytest.inc $(BUILD)/expected.bin
	@$(MAKE) --no-print-directory asm
	@$(RUN) sh -c '$(ZESARUX) >/tmp/z.log 2>&1 & \
		sleep 3; python3 tools/checkpolycost.py'

# The full-screen bitmap path: our deplaner against the engine's. Host only.
check-bitmap:
	python3 tools/checkbitmap.py

# Step 9: every part the probe can reach, measured separately. Host only.
check-parts:
	python3 tools/checkparts.py

# Gate E, third claim: the mixer's bytes, and the DMA's output rate.
check-snd: asm
	@$(RUN) sh -c '$(ZESARUX) >/tmp/z.log 2>&1 & \
		sleep 3; python3 tools/checksnd.py'

# Gate E, first two claims: the input mapping and frame pacing.
check-pace: asm
	@$(RUN) sh -c '$(ZESARUX) >/tmp/z.log 2>&1 & \
		sleep 3; python3 tools/checkpace.py'

# Gate D: the VM's opcode stream against the engine's. Needs `make assets`.
# I1: the integrated program. Everything live at once - the frame interrupt, the DMA,
# the mixer inside the interrupt, the loader, and the VM - with Gate D re-run inside it.
check-aw: cc-game
	python3 tools/mkexpected.py $(PROBE)/ops.txt $(BUILD)/expected_ops.inc
	$(MAKE) asm
	@$(RUN) sh -c '$(ZESARUX) >/tmp/z.log 2>&1 & \
		sleep 3; python3 tools/checkaw.py'

check-aw256: cc-game
	python3 tools/mkexpected.py $(PROBE)/ops.txt $(BUILD)/expected_ops.inc
	$(MAKE) asm asm256
	@$(RUN) sh -c '$(ZESARUX) >/tmp/z.log 2>&1 & \
		sleep 3; AW_SCREEN=256 python3 tools/checkaw.py'

# I9, first half: the save, against the machine's own state.
check-save: cc-game
	python3 tools/mkreslist.py $(DATA_DIR) $(BUILD)/reslist.inc
	$(MAKE) asm
	@$(RUN) sh -c '$(ZESARUX) >/tmp/z.log 2>&1 & \
		sleep 3; python3 tools/checksave.py'

# I7: a full-screen bitmap on the machine, against mkassets.py's deplaner.
check-bmp: cc-game
	python3 tools/mkreslist.py $(DATA_DIR) $(BUILD)/reslist.inc
	$(MAKE) asm
	@$(RUN) sh -c '$(ZESARUX) >/tmp/z.log 2>&1 & \
		sleep 3; python3 tools/checkbmp.py'

# I6: a part transition, against what setupPart promises.
check-part: cc-game
	python3 tools/mkreslist.py $(DATA_DIR) $(BUILD)/reslist.inc
	$(MAKE) asm
	@$(RUN) sh -c '$(ZESARUX) >/tmp/z.log 2>&1 & \
		sleep 3; python3 tools/checkpart.py'

# I5: the machine's module-header parse against tools/sfxmod.py's.
check-mus: cc-game
	python3 tools/mkreslist.py $(DATA_DIR) $(BUILD)/reslist.inc
	$(MAKE) asm
	@$(RUN) sh -c '$(ZESARUX) >/tmp/z.log 2>&1 & \
		sleep 3; python3 tools/checkmus.py'

# I4: the machine's text against the reference's, driven directly.
check-text: cc-game
	python3 tools/mkfont6.py $(PROBE)/font.bin $(BUILD)/font6.bin
	python3 tools/mkstrings.py $(PROBE)/staticres.cpp $(BUILD)/strings.inc
	$(MAKE) asm
	@$(RUN) sh -c '$(ZESARUX) >/tmp/z.log 2>&1 & \
		sleep 3; python3 tools/checktext.py'

# I3: the resources the bytecode asks for arrive, byte for byte against the card.
check-res: cc-game
	python3 tools/mkreslist.py $(DATA_DIR) $(BUILD)/reslist.inc
	$(MAKE) asm
	@$(RUN) sh -c '$(ZESARUX) >/tmp/z.log 2>&1 & \
		sleep 3; python3 tools/checkres.py'

# A scratch target for one-off diagnostics: tools/_mixdiag.py and friends. Not a gate, and
# nothing depends on it - it exists so a focused question does not need a whole gate's run.
diag:
	@$(DC) run --rm -e PYTHONUNBUFFERED=1 -e AW_SCREEN=$(AW_SCREEN) tools sh -c '$(ZESARUX) >/tmp/z.log 2>&1 & \
		sleep 3; python3 tools/$(D).py'

# Which record first draws wrongly. The companion to check-draw: it says the pages
# differ, this says which draw did it, by halving.
bisect-draw: cc-game
	$(MAKE) asm
	@$(RUN) sh -c '$(ZESARUX) >/tmp/z.log 2>&1 & \
		sleep 3; python3 tools/bisectdraw.py'

# I2's gate: the game's own picture against the engine's, aligned on a blit.
# I2's gate, against the intro or against a GAMEPLAY part - I9a's second half:
#     make check-draw              the intro's four pages, as before
#     make check-draw AW_PART=2    part 2's, from trace_part2.bin
check-draw: cc-game
	$(MAKE) asm
	@$(DC) run --rm -e PYTHONUNBUFFERED=1 -e AW_PART=$(AW_PART) \
		-e AW_BLITS=$(AW_BLITS) -e AW_PROBE_DIR=$(AW_PROBE_DIR) -e AW_AUTOPLAY=$(AW_AUTOPLAY) -e AW_TEXTPAGE=$(AW_TEXTPAGE) tools \
		sh -c '$(ZESARUX) >/tmp/z.log 2>&1 & \
		sleep 3; python3 tools/checkdraw.py'

# THE INTRO, LONG. check-draw's committed trace stops at blit 45, and the first polygon that
# copies from page 0 (colour 0x11, the patch of floor under the lift) is not drawn until blit
# 218 - so the copy fill's source band was never compared against the engine, and a stale
# band cache sent it to the BYTECODE window instead: rainbow speckle on the machine, 807
# bytes in rows 165-191, page 0 itself identical. This regenerates a 700-blit reference from
# the host probe (gitignored, like the rest of the probe's output, because it is derived from
# the game data) and compares all four pages at 226, the last copy-mode frame, and at 699.
INTRO_REF := $(BUILD)/ref2614
$(INTRO_REF)/trace.bin:
	mkdir -p $(INTRO_REF)
	cd $(INTRO_REF) && $(CURDIR)/$(PROBE)/probe $(CURDIR)/$(DATA_DIR) 4000 2614 0 >probe.out
	cp $(PROBE)/font.bin $(INTRO_REF)/

#
# AT A DOZEN BLITS, NOT TWO. With 226 and 699 alone this gate passed a build whose dirty-band hook
# had not been assembled at all - every copy onto a page that still mirrored its source moved
# nothing, and the previous frame's shapes stayed - because both of those blits land just after a
# scene cut, where a page fill resets everything. Spread across the intro, the stale shapes show.
# PAST BLIT 699, TO THE END OF THE INTRO. Stopping at 699 missed that no bytecode string had ever
# been drawn: the intro's first is at frame 1,122 ("IDENTIFICATION") and Lester's terminal writes
# text every frame from 1,173. 1130 and 1290 are text; the rest spread over the second half.
INTRO_BLITS ?= 30 60 100 140 180 226 260 330 420 520 600 699 1130 1290 1700 2100 2600
# The intro's music, rendered on the host as the original played it, for the machine to stream
# instead of mixing the module live. Timed by the reference engine's own run. The file is made from
# the player's data and stays in build/, like the rest of the assets.
music: $(INTRO_REF)/trace.bin
	python3 tools/mkmusic.py $(BUILD)/assets $(INTRO_REF)/sound.txt $(BUILD)/assets/MUSIC.PCM

# The stream on the machine: what the interrupt copies against the file, and the markers.
check-stream: music cc-game
	$(MAKE) asm
	@$(RUN) sh -c '$(ZESARUX) >/tmp/z.log 2>&1 & \
		sleep 3; python3 tools/checkstream.py'

check-intro: $(INTRO_REF)/trace.bin
	@bad=0; for b in $(INTRO_BLITS); do \
		if $(MAKE) --no-print-directory check-draw AW_BLITS=$$b AW_PROBE_DIR=$(INTRO_REF) \
				>$(BUILD)/intro-$$b.log 2>&1; then echo "  blit $$b: PASS"; \
		else echo "  blit $$b: FAIL"; grep -E "page [0-3]: [0-9]|first at" $(BUILD)/intro-$$b.log; bad=1; fi; \
	done; test $$bad -eq 0

# I1a: the game reads a real keyboard and a Kempston joystick, and the reference's
# mapping survives the trip. Driven by the emulator's own keys, not by a poke.
check-input: cc-game
	$(MAKE) asm
	@$(RUN) sh -c '$(ZESARUX) >/tmp/z.log 2>&1 & \
		sleep 3; python3 tools/checkinput.py'

# I1's killing experiment: can the game's five windows and its resident code coexist,
# and does the second window survive being stood down for esxDOS? Run this before
# building anything on the slot map.
check-map: asm
	@$(RUN) sh -c '$(ZESARUX) >/tmp/z.log 2>&1 & \
		sleep 3; python3 tools/checkmap.py'

# The engine's own stream ships IN the .nex and the VM checks itself against it as
# it runs, so the expected data has to be regenerated before the assembly that
# embeds it - a stale .inc would be compared confidently against the wrong run, and
# the seed alone differs between probe runs. Make the reference LONGER than the
# machine's own frame count: AW_OP_FRAMES=45 ./probe <data> 4000 45 0, with the last
# 0 meaning no synthetic input, because the VM under test has no input either.
# Gate D against a GAMEPLAY part as well as the intro - I9a's second half:
#     make check-boot              the intro's 763 records, as before
#     make check-boot AW_PART=2    part 2's bytecode against part 2's own stream
# The stream comes from a probe run that JUMPED into that part, cut down to the part itself:
#
#     (cd <scratch> && AW_OP_FRAMES=30 ./probe <data> 30 30 0 2 0)     0 = no autoplay
#     python3 tools/mkpartops.py <scratch>/ops.txt $(PROBE)/ops_part2.txt
#
# The cut matters and tools/mkpartops.py explains why: a jump is a REQUEST, so the run opens
# with several frames of the part it was already in, and the harness starts the new part's
# bytecode at its first instruction. Uncut, it diverges at record two. It did.
AW_PART   ?=
AW_BLITS  ?= 8
OPS_FILE   = $(if $(AW_PART),$(PROBE)/ops_part$(AW_PART).txt,$(PROBE)/ops.txt)

check-boot: | $(BUILD)
	python3 tools/mkexpected.py $(OPS_FILE) $(BUILD)/expected_ops.inc
	$(MAKE) cc asm
	@$(DC) run --rm -e PYTHONUNBUFFERED=1 -e AW_PART=$(AW_PART) tools \
		sh -c '$(ZESARUX) >/tmp/z.log 2>&1 & \
		sleep 3; python3 tools/checkboot.py'

# COPPER SOUND: the copper driving the DAC once a scanline, fed twice a frame, measured in
# ZEsarUX's own audio output. See src/coptest.asm and tools/checkcop.py.
check-cop: asm
	@rm -f $(BUILD)/cop.raw
	@$(RUN) sh -c '$(ZESARUX) --aofile /work/$(BUILD)/cop.raw >/tmp/z.log 2>&1 & \
		sleep 3; python3 tools/checkcop.py'

# The esxDOS window invariant: is the ROM back over the bottom 16K during a DOS call?
# See tools/checkesx.py for why this gates the REGISTERS and not the load - ZEsarUX
# answers RST $08 whatever the paging says, which is how the fault survived twelve gates.
check-esx: asm
	@$(RUN) sh -c '$(ZESARUX) >/tmp/z.log 2>&1 & \
		sleep 3; python3 tools/checkesx.py'

# Step 5: how fast does esxDOS read? Needs `make assets` first.
check-load: asm
	@$(RUN) sh -c '$(ZESARUX) >/tmp/z.log 2>&1 & \
		sleep 3; python3 tools/checkload.py'

# Gate C4 on the machine: the Z80N reader against the reference reader.
check-readmachine: check-poly
	@$(RUN) sh -c '$(ZESARUX) >/tmp/z.log 2>&1 & \
		sleep 3; python3 tools/checkreadmachine.py'

check-readmachine256: | $(BUILD)
	python3 tools/mktables.py $(BUILD)/interp.inc
	python3 tools/mkcsteps.py $(BUILD)/csteps.inc $(BUILD)/csteps.txt
	AW_SCREEN=256 python3 tools/mkpolytest.py $(TRACE) $(BUILD)/polytest.inc $(BUILD)/expected.bin
	@$(MAKE) --no-print-directory asm
	@$(RUN) sh -c '$(ZESARUX) >/tmp/z.log 2>&1 & \
		sleep 3; AW_SCREEN=256 python3 tools/checkreadmachine.py'

# Gate C4: the reference reader against the engine's, call for call. Host only.
check-reader:
	python3 tools/checkreader.py $(PROBE)

# Step 1 of the plan: price the mixer before designing around it.
check-mix: asm
	@$(RUN) sh -c '$(ZESARUX) >/tmp/z.log 2>&1 & \
		sleep 3; python3 tools/checkmix.py'

# ---- decision 7's drift check ----------------------------------------------
# The shared files are duplicated from wolf3d-next rather than submoduled. This
# is what stops that being invisible.
SHARED := tools/zrcp.py tools/zesarux/prescalar.patch \
          tools/zesarux/readback.patch tools/zesarux/autorestart.patch
# plan-pi-gus.md A1: the Pi card's files. nextpi-gus packs this game's sounds (it reads data/ through
# this repo's own tools) and builds the card's installer; mkgusdata.py takes them into build/assets,
# writes build/gusdata.inc, and copies the Next's side into src/inc/gus/. Without a nextpi-gus build
# gusdata.inc says GUS_BLOCKS 0 and the card is never tried.
NEXTPI_GUS ?= $(HOME)/src/nextpi-gus
gus-assets: | $(BUILD)
	$(MAKE) -C $(NEXTPI_GUS) upload pi-card
	python3 tools/mkgusdata.py $(NEXTPI_GUS) $(BUILD) $(PROBE)

check-gus:
	$(MAKE) -C $(NEXTPI_GUS) build/mac/ngus
	NEXTPI_GUS=$(NEXTPI_GUS) python3 tools/checkgus.py

# plan-ddma.md D1: the intro in CSpect 4.5.1.0 (~/nextdev/cspect4, the one emulator with the zxnDDMA)
# twice, the zxnDDMA's fill on and poked off, the screens compared at the same blit counts. On the
# Deck it runs in the nextdev-gui image (mono) on Xvfb, so no window opens on the desktop.
CSPECT_BOX := $(if $(wildcard $(HOME)/.local/bin/nextdev),$(HOME)/.local/bin/nextdev env ALSOFT_DRIVERS=null xvfb-run -a -s "-screen 0 1280x1024x24",)
check-ddma: asm
	$(CSPECT_BOX) python3 tools/cspect/checkddma.py
check-ddma256: asm256
	$(CSPECT_BOX) env AW_SCREEN=256 python3 tools/cspect/checkddma.py
# plan-ddma.md D2: what a 320x256 row costs by the zxnDDMA's 2D fill, against the CPU, in CSpect 4.5.
measure-ddma:
	$(RUN) sjasmplus --zxnext=cspect --fullpath --exp=$(BUILD)/ddmabench.exp \
		--lst=$(BUILD)/ddmabench.lst preflight/ddma/bench.asm
	$(CSPECT_BOX) python3 tools/cspect/ddmabench.py

# plan-pi-gus.md A2 and A3: the shipped image in CSpect with its Pi UART on nextpi-gus's fake NextPi -
# the boot, the upload and %M (A2: sessions 1-3), the effects and music on the card, the markers, the
# speed, a card lost mid-intro (A3: 4-5). ONLY=1,2,3 runs some. Opens CSpect windows, one at a time.
ONLY ?= 1,2,3,4,5
check-card: cc-game
	$(MAKE) asm
	$(MAKE) -C $(NEXTPI_GUS) build/mac/ngus
	NEXTPI_GUS=$(NEXTPI_GUS) python3 tools/checkcard.py --only $(ONLY)

# plan-pi-gus.md A4, David's: the BYPASS_PROTECTION image (the intro, then part 2) in CSpect, its sound
# on the card on the Mac's speakers - or with CARD=0 no Pi, the Z80 path, for the comparison. The plain
# image is built again after, so build/aw.nex stays what every gate expects. See tools/play_gus.sh.
CARD ?= 1
play-gus: cc-game
	$(MAKE) asm ASMDEF=-DBYPASS_PROTECTION
	cp $(BUILD)/aw.nex $(BUILD)/aw-play.nex
	$(MAKE) asm
	$(MAKE) -C $(NEXTPI_GUS) build/mac/ngus
	CARD=$(CARD) NEXTPI_GUS=$(NEXTPI_GUS) sh tools/play_gus.sh

# plan-pi-gus.md A0: the game's own sound calls, logged from outside in CSpect (tools/cspect/awsnd.cs),
# against the reference engine's run of the intro. Opens a CSpect window; one at a time.
check-sndcalls:
	python3 tools/checksndcalls.py

toolchain-diff:
	@test -d $(WOLF3D) || { echo "no wolf3d-next checkout at $(WOLF3D)"; exit 1; }
	@rc=0; for f in $(SHARED); do \
		if diff -q "$$f" "$(WOLF3D)/$$f" >/dev/null 2>&1; then \
			echo "  same      $$f"; \
		else \
			echo "  DRIFTED   $$f"; diff -u "$(WOLF3D)/$$f" "$$f" | head -20; rc=1; \
		fi; done; \
	echo "(compose.yml and the Dockerfile are supersets by design and not compared)"; \
	exit $$rc

clean:
	rm -rf $(BUILD)

distclean: clean
	-docker image rm aw-next-tools

# What would Layer 2's 320x256 mode cost? A measurement, not a port: see tools/wide320.py.
# The machine half times one span of each kind in ZEsarUX; the host half counts the intro's spans.
measure-wide320: $(INTRO_REF)/trace.bin
	$(RUN) sjasmplus --zxnext=cspect --fullpath --exp=$(BUILD)/wide320.exp \
		--lst=$(BUILD)/wide320.lst preflight/wide320/wide.asm
	@$(RUN) sh -c '$(ZESARUX) >/tmp/z.log 2>&1 & \
		sleep 3; python3 tools/wide320.py machine $(BUILD)/wide320/coeff.json'
	python3 tools/wide320.py count $(INTRO_REF)/trace.bin $(BUILD)/wide320/intro.json

# W1 of docs/plan-wide320.md: RefVideo320 - the engine's picture at one byte a pixel, no scale - against
# RefVideo (Gate A's) at every check-intro blit and the engine's own pages, and the 320x256 bitmaps
# (BMWnn.BIN, from make assets) against the engine's own deplaned pages. Host only.
check-wide: $(INTRO_REF)/trace.bin
	python3 tools/checkwide.py $(INTRO_REF) $(INTRO_BLITS)

# THE EARLIER 256x192 BUILD (docs/plan-wide320.md). 320x256 is the normal build since 2026-10-01 and
# every plain target above is about it; the same sources with -DSCREEN256 build the 256x192 game as
# build/aw256.nex, and these gates check it. Each checker takes AW_SCREEN=256.
asm256: | $(BUILD)
	$(RUN) sjasmplus --zxnext=cspect --fullpath -DSCREEN256 $(ASMDEF) --exp=$(BUILD)/aw256.exp \
		--lst=$(BUILD)/aw256.lst src/aw.asm

check-draw256: cc-game
	$(MAKE) asm asm256
	@$(DC) run --rm -e PYTHONUNBUFFERED=1 -e AW_SCREEN=256 -e AW_PART=$(AW_PART) \
		-e AW_BLITS=$(AW_BLITS) -e AW_PROBE_DIR=$(AW_PROBE_DIR) -e AW_AUTOPLAY=$(AW_AUTOPLAY) -e AW_TEXTPAGE=$(AW_TEXTPAGE) tools \
		sh -c '$(ZESARUX) >/tmp/z.log 2>&1 & \
		sleep 3; python3 tools/checkdraw.py'

check-intro256: $(INTRO_REF)/trace.bin
	@bad=0; for b in $(INTRO_BLITS); do \
		if $(MAKE) --no-print-directory check-draw256 AW_BLITS=$$b AW_PROBE_DIR=$(INTRO_REF) \
				>$(BUILD)/intro256-$$b.log 2>&1; then echo "  blit $$b: PASS"; \
		else echo "  blit $$b: FAIL"; grep -E "page [0-3]: [0-9]|first at" $(BUILD)/intro256-$$b.log; bad=1; fi; \
	done; test $$bad -eq 0

check-text256: cc-game
	python3 tools/mkfont6.py $(PROBE)/font.bin $(BUILD)/font6.bin
	python3 tools/mkstrings.py $(PROBE)/staticres.cpp $(BUILD)/strings.inc
	$(MAKE) asm asm256
	@$(RUN) sh -c '$(ZESARUX) >/tmp/z.log 2>&1 & \
		sleep 3; AW_SCREEN=256 python3 tools/checktext.py'

check-bmp256: cc-game
	python3 tools/mkreslist.py $(DATA_DIR) $(BUILD)/reslist.inc
	$(MAKE) asm asm256
	@$(RUN) sh -c '$(ZESARUX) >/tmp/z.log 2>&1 & \
		sleep 3; AW_SCREEN=256 python3 tools/checkbmp.py'

check-save256: cc-game
	python3 tools/mkreslist.py $(DATA_DIR) $(BUILD)/reslist.inc
	$(MAKE) asm asm256
	@$(RUN) sh -c '$(ZESARUX) >/tmp/z.log 2>&1 & \
		sleep 3; AW_SCREEN=256 python3 tools/checksave.py'

check-part256: cc-game
	python3 tools/mkreslist.py $(DATA_DIR) $(BUILD)/reslist.inc
	$(MAKE) asm asm256
	@$(RUN) sh -c '$(ZESARUX) >/tmp/z.log 2>&1 & \
		sleep 3; AW_SCREEN=256 python3 tools/checkpart.py'

check-res256: cc-game
	python3 tools/mkreslist.py $(DATA_DIR) $(BUILD)/reslist.inc
	$(MAKE) asm asm256
	@$(RUN) sh -c '$(ZESARUX) >/tmp/z.log 2>&1 & \
		sleep 3; AW_SCREEN=256 python3 tools/checkres.py'

# W0 of docs/plan-wide320.md: the sound interrupt's share of the machine, sampled in ZEsarUX, for the
# intro (part index 1) and two gameplay parts with the synthetic player, at the reference runs' seeds.
measure-wide320-isr: asm
	@$(RUN) sh -c '$(ZESARUX) >/tmp/z.log 2>&1 & \
		sleep 3; python3 tools/wide320.py isr $(BUILD)/wide320/isr1.json --part 1 --seed 4493'
	@$(RUN) sh -c '$(ZESARUX) >/tmp/z.log 2>&1 & \
		sleep 3; python3 tools/wide320.py isr $(BUILD)/wide320/isr3.json --part 3 --seed 8392'
	@$(RUN) sh -c '$(ZESARUX) >/tmp/z.log 2>&1 & \
		sleep 3; python3 tools/wide320.py isr $(BUILD)/wide320/isr4.json --part 4 --seed 8430'
