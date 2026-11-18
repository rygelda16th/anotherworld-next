# Another World Next build toolchain.
#
# ---------------------------------------------------------------------------
# PROVENANCE. The sjasmplus, hdfmonkey and ZEsarUX stages below, the three
# ZEsarUX patches under tools/zesarux/, tools/zrcp.py and compose.yml are
# copies from wolf3d-next, taken at commit 5a870c8. They are duplicated rather
# than shared, and `make toolchain-diff` reports any drift against a checkout.
#
# Why duplicated: there is nowhere to publish a base image to, so a "FROM" would
# lose the commit pinning the numbers depend on; a submodule drags a 28,000-byte
# Makefile and a whole game to obtain five files; and this image has to be a
# superset in any case. As it turns out this file is very nearly a straight copy,
# because z88dk did not end up living here at all - see the note further down.
# So `make toolchain-diff` should report no drift on the shared files, and any
# it does report is worth reading. See docs/licence.md and decision 7.
# ---------------------------------------------------------------------------
#
# Everything with a build step lives in here so the Mac stays clean: the
# assembler, an SD-image tool, and a *headless* ZEsarUX used only for scripted,
# reproducible timing runs. The C compiler is the one exception and runs from its
# own pinned image. Interactive play happens in the native
# ZEsarUX app on the host.
#
# Native arm64 build (no emulation). Disposable: `docker image rm aw-next-tools`.

FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential ca-certificates git make cmake pkg-config \
        autoconf automake libtool python3 \
        libncurses-dev libssl-dev zlib1g-dev \
    && update-ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Pinned to the exact commits the numbers were measured against. Upstream
# sjasmplus and ZEsarUX have no clean release tags, so a commit pin is the only
# way to keep timing runs reproducible.
ARG SJASMPLUS_REF=8c87edd
ARG HDFMONKEY_REF=76d400f
ARG ZESARUX_REF=f02514f

# --- sjasmplus (z00m128 fork): Z80N assembler, emits .nex directly ------------
RUN git clone https://github.com/z00m128/sjasmplus.git /tmp/sjasmplus \
    && git -C /tmp/sjasmplus checkout -q "$SJASMPLUS_REF" \
    && git -C /tmp/sjasmplus submodule update --init --recursive \
    && make -C /tmp/sjasmplus -j"$(nproc)" \
    && make -C /tmp/sjasmplus install PREFIX=/usr/local \
    && (cd /tmp/sjasmplus && git rev-parse --short HEAD > /usr/local/share/sjasmplus.commit) \
    && rm -rf /tmp/sjasmplus

# --- hdfmonkey: build/edit the FAT SD-card image ------------------------------
RUN git clone https://github.com/gasman/hdfmonkey.git /tmp/hdfmonkey \
    && cd /tmp/hdfmonkey \
    && git checkout -q "$HDFMONKEY_REF" \
    && (test -x ./configure || autoreconf -i) \
    && ./configure && make -j"$(nproc)" && make install \
    && git rev-parse --short HEAD > /usr/local/share/hdfmonkey.commit \
    && cd / && rm -rf /tmp/hdfmonkey

# --- z88dk is NOT built here, and that is deliberate --------------------------
# It lives in its own pinned image and the Makefile's `cc:` target runs it there.
# Two reasons, both found by trying the alternative:
#
#   1. It cannot be built here. SDCC refuses to compile its Z80 register
#      allocator against Boost below 1.79 (SDCC bug #3772) and bookworm ships
#      1.74, so `zsdcc` - which -clib=sdcc_iy requires - fails on ANY
#      architecture on this base, not just arm64. Only trixie carries 1.83.
#   2. It does not need to be. Upstream's z88dk/z88dk image has an arm64 variant
#      with `z88dk-zsdcc` in it, which corrects the assumption that the prebuilt
#      image is amd64-only and that Rosetta was required.
#
# That image is Alpine and musl-linked, so its binaries cannot simply be COPYed
# into this glibc image - hence a separate pinned image rather than a stage.
#
# The happy consequence is that this file stays a near-exact copy of
# wolf3d-next's, which is what makes `make toolchain-diff` worth running.

# --- ZEsarUX, headless: cycle-accurate timing truth ---------------------------
# No X, no SDL. Driven over ZRCP (its telnet debug protocol) on port 10000.
#
# PATCHED, and this is the one place the emulator is not upstream's. The three
# patches are wolf3d-next's, unchanged; see that project's Dockerfile for what
# each does and which check proves it. In short: prescalar.patch makes the DMA
# honour its transfer rate, readback.patch makes the DMA's registers readable,
# and autorestart.patch implements WR5 bit 5.
#
# This port depends on them much less than wolf3d-next does - it uses no DMA for
# polygon spans at all - but the page copy still goes through the DMA, so the
# timing patch still matters for that one operation.
COPY tools/zesarux/prescalar.patch tools/zesarux/readback.patch tools/zesarux/autorestart.patch /tmp/
RUN git clone https://github.com/chernandezba/zesarux.git /opt/zesarux-src \
    && git -C /opt/zesarux-src checkout -q "$ZESARUX_REF" \
    && git -C /opt/zesarux-src apply /tmp/prescalar.patch \
    && git -C /opt/zesarux-src apply /tmp/readback.patch \
    && git -C /opt/zesarux-src apply /tmp/autorestart.patch \
    && (cd /opt/zesarux-src && git rev-parse --short HEAD > /usr/local/share/zesarux.commit \
        && for p in prescalar readback autorestart; do \
             echo "+tools/zesarux/$p.patch" >> /usr/local/share/zesarux.commit; done) \
    && cd /opt/zesarux-src/src \
    && ./configure --prefix=/usr/local --disable-caca --disable-aa \
    && make -j"$(nproc)" && make install \
    && rm -rf /opt/zesarux-src/src/*.o

WORKDIR /work
CMD ["/bin/bash"]
