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

.PHONY: help certs image doctor shell asm cc emu clean distclean \
        assets check-data check-ref check-span check-cc check-poly toolchain-diff

help:
	@echo "make certs          extract the corporate TLS-inspection CA for the image"
	@echo "make image          build the toolchain container (first run: ~10-20 min)"
	@echo "make doctor         report tool versions from inside the container"
	@echo "make assets         convert the player's data to Next form (host only)"
	@echo "make check-data     Gate A: every resource decodes and its CRC cancels"
	@echo "make check-ref      Gate A: the reference matches the engine byte for byte"
	@echo "make cc             compile the C to a raw binary + .exp"
	@echo "make asm            assemble src/ -> $(BUILD)/*.nex"
	@echo "make check-span     Step 0: what one polygon span costs, measured"
	@echo "make check-cc       Gate B: C calls assembly at a fixed address and returns"
	@echo "make check-poly     Gate C: the rasteriser, pixel-exact vs the reference"
	@echo "make toolchain-diff has the shared toolchain drifted from wolf3d-next?"

certs:
	@mkdir -p certs
	@security find-certificate -a -c "caadmin.netskope.com" -p /Library/Keychains/System.keychain > certs/netskope-root.crt
	@security find-certificate -a -c "ca.tenant.goskope.com" -p /Library/Keychains/System.keychain > certs/netskope-tenant.crt
	@echo "certs/ populated from the system keychain"

image: certs
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
CC_RUN     := docker run --rm -v "$(CURDIR):/work" -w /work $(CC_IMAGE)

# Build order is C first, then assembly: the jump table the C calls sits at an
# address sjasmplus fixes by construction, so nothing is resolved twice.
#
# NOTE the _c suffix on the .exp: sjasmplus writes <name>.exp for the same base
# name, and without it the assembly symbols silently overwrite the C's.
cc: | $(BUILD)
	@set -e; for f in preflight/cc/*.c src/*.c; do \
		[ -e "$$f" ] || continue; b=$$(basename "$$f" .c); echo "  CC  $$f"; \
		$(CC_RUN) zcc $(CFLAGS_ZXN) -pragma-define:CRT_ORG_CODE=$(CC_ORG) \
		    -o $(BUILD)/$$b "$$f" preflight/cc/jumptab.asm; \
		python3 tools/mkexp.py $(BUILD)/$$b.map $(BUILD)/$${b}_c.exp; \
	done

asm: | $(BUILD)
	$(RUN) sh -c 'set -e; for f in src/*.asm; do \
		b=$$(basename "$$f" .asm); echo "  ASM $$f"; \
		sjasmplus --zxnext=cspect --fullpath --exp="$(BUILD)/$$b.exp" \
			--lst="$(BUILD)/$$b.lst" "$$f"; done'

emu:
	$(DC) run --rm --service-ports tools $(ZESARUX)

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
	python3 tools/mkpolytest.py $(TRACE) $(BUILD)/polytest.inc $(BUILD)/expected.bin
	@$(MAKE) --no-print-directory asm
	@$(RUN) sh -c '$(ZESARUX) >/tmp/z.log 2>&1 & \
		sleep 3; python3 tools/checkpoly.py'

check-cc: cc asm
	@$(RUN) sh -c '$(ZESARUX) >/tmp/z.log 2>&1 & \
		sleep 3; python3 tools/checkcc.py'

# ---- decision 7's drift check ----------------------------------------------
# The shared files are duplicated from wolf3d-next rather than submoduled. This
# is what stops that being invisible.
SHARED := tools/zrcp.py tools/zesarux/prescalar.patch \
          tools/zesarux/readback.patch tools/zesarux/autorestart.patch
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
