#!/usr/bin/env python3
"""W1 of docs/plan-wide320.md: is RefVideo320 the engine's own picture, at one byte a pixel?

RefVideo320 is the reference the 320x256 machine will be compared against. It shares RefVideo8's
span loops at the engine's own geometry, so it must agree with RefVideo - which Gate A proved
against the engine itself - on every pixel: RefVideo's 4-bit nibble against RefVideo320's byte.
This replays the intro trace through both, compares all four pages at every check-intro blit and at
the end, and compares the end against the engine's own dumped pages too.

    python3 tools/checkwide.py build/ref2614 30 60 100 ... 2600
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from refvideo import RefVideo, RefVideo320, replay   # noqa: E402


def nibbles(page4):
    out = bytearray(320 * 200)
    for i, b in enumerate(page4):
        out[2 * i] = b >> 4
        out[2 * i + 1] = b & 15
    return bytes(out)


def main():
    ref = sys.argv[1]
    blits = sorted(int(b) for b in sys.argv[2:])
    trace = os.path.join(ref, "trace.bin")
    font = open(os.path.join(ref, "font.bin"), "rb").read()
    snaps = {RefVideo: {}, RefVideo320: {}}

    for cls in snaps:
        def grab(n, v, cls=cls):
            if n in blits:
                snaps[cls][n] = [bytes(p) for p in v.pages]
        v, total = replay(trace, on_frame=grab, font=font, cls=cls)
        snaps[cls]["end"] = [bytes(p) for p in v.pages]
    bad = 0
    for n in blits + ["end"]:
        if n not in snaps[RefVideo]:
            print(f"blit {n}: not reached (the trace has {total})")
            bad += 1
            continue
        for p in range(4):
            a = nibbles(snaps[RefVideo][n][p])
            b = bytes(x & 15 for x in snaps[RefVideo320][n][p])
            if a != b:
                d = [i for i in range(len(a)) if a[i] != b[i]]
                print(f"blit {n} page {p}: {len(d)} pixels differ, first at x {d[0] % 320} y {d[0] // 320}")
                bad += 1
        print(f"blit {n}: {'all four pages identical' if not bad else 'see above'}")
    for p in range(4):
        dump = os.path.join(ref, f"page{p}.bin")
        if os.path.exists(dump):
            want = nibbles(open(dump, "rb").read())
            got = bytes(x & 15 for x in snaps[RefVideo320]["end"][p])
            same = want == got
            print(f"the engine's own page {p} at the end: {'IDENTICAL' if same else 'DIFFERENT'}")
            bad += not same
    # the full-screen bitmaps: mkassets.py's 320x256 copy (BMWnn.BIN, column-major) against the
    # engine's own page 0 straight after it loaded each one (the probe's bmp_engine_NN.bin)
    import glob
    dumps = sorted(glob.glob("preflight/hostprobe/probe/bmp_engine_*.bin"))
    for path in dumps:
        rid = os.path.basename(path)[11:13]
        want = nibbles(open(path, "rb").read())
        wid = open(f"build/assets/BMW{rid}.BIN", "rb").read()
        got = bytes(wid[x * 256 + y] for y in range(200) for x in range(320))
        same = want == got
        print(f"bitmap {rid}: BMW{rid}.BIN {'IDENTICAL to' if same else 'DIFFERENT from'} the engine's page 0")
        bad += not same
    if bad:
        raise SystemExit("FAIL check-wide")
    print("PASS check-wide: RefVideo320 is the engine's picture at one byte a pixel")


if __name__ == "__main__":
    main()
