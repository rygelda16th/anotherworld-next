#!/bin/sh
# play_gus.sh - plan-pi-gus.md A4: the game in CSpect with its sound on the Pi card, for David to
# play and listen to (make play-gus). The card is nextpi-gus's build/mac/ngus behind its fake NextPi
# (tools/fakepi.py), and it plays on the Mac's speakers; CSpect's own sound is the Next's, which is
# silent while the card is on.
#
#   make play-gus            the card: the boot uploads every sound (about 17 s of a blank screen at
#                            CSpect's 115,200), then ENTER starts the intro; part 2 follows it
#   make play-gus CARD=0     no Pi: the Z80 path, CSpect's own sound - the comparison
#   OUT=null                 the card plays nowhere (the default is coreaudio)
#
# The image is the BYPASS_PROTECTION build (the intro, then part 2), as ~/src/cspect/run-aw.sh's.
# O and P left and right, Q and A up and down, Space fire, ENTER to start. Close the window to stop;
# the fake Pi stops with it. What the card did: ~/src/nextpi-gus/build/fakepi/ (fakepi.log, ngus.log,
# status.log).
#
# PROVENANCE: nextpi-gus tools/run_cspect_gus.sh (G5), with this game's image and SD folder.
set -e
cd "$(dirname "$0")/.."
GUS=${NEXTPI_GUS:-$HOME/src/nextpi-gus}
CSPECT=${CSPECT:-$HOME/src/cspect}
NEX=${NEX:-build/aw-play.nex}
[ -f "$NEX" ] || { echo "no $NEX: make play-gus builds it"; exit 1; }
[ -d "$CSPECT/CSpect" ] || { echo "no CSpect at $CSPECT"; exit 1; }
if pgrep -f CSpect.exe >/dev/null; then echo "another CSpect (mono) is running: close it first"; exit 1; fi
cp "$NEX" "$CSPECT/sd/aw/AWGUS.NEX"
cp build/assets/GUSALL.GUS build/assets/GUSINST.TXT "$CSPECT/sd/aw/"
COM=""
if [ "${CARD:-1}" != 0 ]; then
    [ -x "$GUS/build/mac/ngus" ] || { echo "no $GUS/build/mac/ngus: make -C $GUS build/mac/ngus"; exit 1; }
    mkdir -p "$GUS/build/fakepi"
    rm -f "$GUS/build/fakepi/PTY"
    (cd "$GUS" && exec python3 tools/fakepi.py --out "${OUT:-coreaudio}") > "$GUS/build/fakepi/stdout.log" 2>&1 &
    PI=$!
    trap 'kill $PI 2>/dev/null || true; wait $PI 2>/dev/null || true' EXIT INT TERM
    i=0
    while [ ! -s "$GUS/build/fakepi/PTY" ] && [ $i -lt 50 ]; do sleep 0.1; i=$((i + 1)); done
    [ -s "$GUS/build/fakepi/PTY" ] || { echo "the fake Pi did not start:"; cat "$GUS/build/fakepi/stdout.log"; exit 1; }
    COM="-com=$(cat "$GUS/build/fakepi/PTY"):115200"
    echo "the card: a fake NextPi on ${COM#-com=}; the boot uploads every sound first (about 17 s), then ENTER"
else
    echo "no Pi: the Z80 path (half a second's probe, then ENTER)"
fi
cd "$CSPECT/CSpect"
PATH="/opt/homebrew/bin:$PATH" mono CSpect.exe -w3 -mouse -basickeys -zxnext -mmc=../sd/aw/ $COM ../sd/aw/AWGUS.NEX "$@"
