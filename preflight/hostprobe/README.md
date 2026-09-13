# The host probe

A headless build of the reference interpreter, instrumented, used for two jobs
neither of which can be done on the Next:

1. **Weighing the workload.** How many opcodes a frame does the virtual machine
   dispatch, how many polygons and spans does the rasteriser draw, and how long
   are those spans? Those numbers set the T-state budget, and they cannot be
   derived from the code - they depend on how the bytecode actually behaves.
2. **Producing the specification.** It writes a byte-exact trace of every video
   operation and dumps all four framebuffers, so `tools/refvideo.py` can be
   proved identical to the real engine before anything is ported. The same trace
   is the test vector Phase C replays on the machine.

## Why a patch and not a copy

The engine source is not vendored here. It is cloned at a pinned commit and
patched, matching how `Dockerfile` pins sjasmplus, hdfmonkey and ZEsarUX - the
numbers are only reproducible against an exact revision, and a vendored copy
drifts silently.

    AWBI_REF = 170b7d466a6ea6cc36a9e53506d5b858ed503a84

That is Gregory Montoir's Another World interpreter as cleaned up by Fabien
Sanglard, GPL-2.0-or-later. See `docs/licence.md`.

## Building it

    git clone https://github.com/fabiensanglard/Another-World-Bytecode-Interpreter awbi
    git -C awbi checkout -q $AWBI_REF
    cp -r awbi/src probe && rm probe/main.cpp probe/sysImplementation.cpp
    cp headless.cpp instr.h probe/
    (cd probe && patch -p1 < ../instrument.patch)
    (cd probe && patch -p1 < ../structure.patch)
    cd probe && clang++ -std=c++11 -O1 -fno-rtti -fno-exceptions \
        -DAUTO_DETECT_PLATFORM -DBYPASS_PROTECTION -w \
        bank.cpp engine.cpp file.cpp mixer.cpp parts.cpp resource.cpp \
        serializer.cpp sfxplayer.cpp staticres.cpp util.cpp video.cpp vm.cpp \
        headless.cpp -lz -o probe

`main.cpp` and `sysImplementation.cpp` are replaced rather than patched:
`headless.cpp` supplies both the entry point and a `System` implementation with
no SDL, no audio and **a virtual clock**. The clock matters - the engine's own
pacing arithmetic in `op_blitFramebuffer` subtracts elapsed time from the
script's requested pause, so a stub that returned real time would either sleep
for hours or skew every frame. Here `sleep()` advances the clock and
`getTimeStamp()` reads it, so the arithmetic runs exactly and costs nothing.

## The two patches

`instrument.patch` is the first round: the counters, the video trace and the page
dumps that Gate A rests on. `structure.patch` stacks on top of it and is the
second round, added after Gate A passed, to answer four questions that each
decide a design rather than describe the engine:

| what it measures | what it decides |
|---|---|
| how deep the polygon hierarchy nests, and how wide it fans | whether the reader needs real recursion |
| the longest single polygon record | how big the sliding window over a polygon segment must be |
| the high-water mark of the script heap | how many banks a part needs |
| how many mixer voices are ever live at once | whether sound is an occasional cost or a permanent tax |

They are kept apart rather than merged so that the first round, which Gate A's
byte-exactness depends on, stays exactly as it was when that gate passed.

## Running it

    ./probe <data-dir> <frame-cap> [trace-frames] [autoplay]

With a non-zero third argument it writes `trace.bin`, `font.bin` and, at the
moment the traced window closes, `page0.bin` through `page3.bin`. Then:

    python3 ../../tools/checkref.py trace.bin page0.bin page1.bin page2.bin page3.bin

Every run also writes `sound.txt` and `frames.txt`, for:

    python3 ../../tools/voices.py sound.txt
    python3 ../../tools/frameload.py frames.txt

**Pass `1` as the fourth argument for anything about gameplay.** Without it the
run reaches the intro's "press fire" prompt and stalls there: 57,386 of 60,000
frames drew nothing, the player and enemy polygon segment was never loaded, and
every number described the intro. The synthetic input walks right, jumps and
fires, which is enough to enter the game and to keep dying in it - and a death
restarts the part, which is the heaviest drawing there is.

Because `sound.txt` and `frames.txt` are overwritten on every run, copy them
between an autoplay run and an intro run. Losing that once made a gameplay
analysis silently describe the intro.

## Two traps worth knowing

The frame counter must be advanced **at the blit, before the page dump**, which
is why `instrFrame()` increments it rather than the `System` stub. The stub's
`updateDisplay` runs after `instrPages`, so incrementing there dumped the pages
one frame later than the trace stopped recording - the dump then contained
drawing the trace had omitted, and the comparison failed intermittently
depending on whether that extra frame happened to touch the page being checked.
It passed at 1, 2, 3, 10, 20, 40 and 80 frames and failed at 5 and 120, which is
what a boundary bug looks like when you are hoping for a rasteriser bug.

The second is that `addTimer` was a stub returning a token and doing nothing, so
the music player never ticked, no note ever reached the mixer, and voice
concurrency read as "effects only" - wrong by a factor of nearly two. It now
implements SDL's timer semantics against the virtual clock: `sleep()` advances
the clock to each due firing, calls the callback, and takes the returned value as
the next interval. Music events therefore fire inside the pacing sleep in
`op_blitFramebuffer`, which is where they fire on real hardware.

**That change could have invalidated Gate A, and did not.** The music player writes
`vmVariables[0xF4]` on a pattern row of `0xFFFD` (`sfxplayer.cpp:183`, wired in `vm.cpp:48`), and the
bytecode can read that variable - so starting the timer puts the score inside the
VM's input. Regenerating `trace.bin` and the four page dumps after both patches
gives files **byte-identical** to the ones Gate A passed on, and `make check-ref`
still reports four identical pages. Over these 2,750 frames the video is
independent of the sound timing. That is an observation, not a guarantee: a later
part that branches on 0xF4 would diverge, and the check to run then is this one.
