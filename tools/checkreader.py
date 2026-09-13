#!/usr/bin/env python3
"""Gate C4: is the reference's polygon reader the engine's polygon reader?

Gate C proved the rasteriser against geometry the host probe recorded AFTER
readVertices had applied the zoom. That was the right call - it left one thing
under test - but it means the reader, the zoom multiply and the record structure
sit outside every gate so far, and 97.4% of the intro's polygons are at zoom 0x40,
the identity, so a vector drawn from it would barely exercise them.

This closes that. The probe now logs the TOP-LEVEL draw calls too, so for each one
the reference reader is run over the raw polygon segment and the fillPolygon calls
it emits are compared, record for record, against the ones the engine emitted.
Comparing pictures would say only that something is wrong; comparing the call
sequence says which record, at which offset, with which field wrong.

No tolerance: every field of every call must match.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from refvideo import RefVideo, read_trace  # noqa: E402


class Recorder(RefVideo):
    """A reference whose fill is a log. The geometry is what is under test."""

    def __init__(self):
        super().__init__()
        self.calls = []

    def _draw_polygon(self, colour, ptx, pty, bbw, bbh, points):
        self.calls.append(dict(colour=colour, px=ptx, py=pty,
                               bbw=bbw, bbh=bbh, points=list(points)))

    def fill_polygon(self, *a):             # never reached; kept explicit
        raise AssertionError("the recorder must not rasterise")


def main():
    probe = sys.argv[1] if len(sys.argv) > 1 else "preflight/hostprobe/probe"
    trace = os.path.join(probe, "trace.bin")

    segs = {}
    for part in range(8):
        for name, key in (("seg_cine_%d.bin" % part, (part, 0)),
                          ("seg_video2_%d.bin" % part, (part, 1))):
            path = os.path.join(probe, name)
            if os.path.exists(path):
                segs[key] = open(path, "rb").read()
    if not segs:
        raise SystemExit(f"no segment dumps in {probe} - re-run the probe with a "
                         "trace-frame count")
    print("segments loaded:")
    for (part, v2), b in sorted(segs.items()):
        print(f"  part {part} {'video2   ' if v2 else 'cinematic'} {len(b):>7,} bytes")

    part = 0
    draws = 0
    engine = []          # fillPolygon calls the engine emitted since the last draw
    pending = None       # the draw whose calls we are collecting
    faults = []
    matched = 0
    depth = 0
    kinds = {}

    def flush():
        """Compare one top-level draw's emitted calls against the engine's."""
        nonlocal matched, depth
        if pending is None:
            return
        key = (part, pending["video2"])
        if key not in segs:
            faults.append((pending, None, f"no segment dumped for {key}"))
            return
        r = Recorder()
        try:
            r.read_and_draw_polygon(segs[key], pending["off"], pending["colour"],
                                    pending["zoom"], pending["x"], pending["y"])
        except Exception as exc:                       # noqa: BLE001
            faults.append((pending, None, f"reader raised {exc!r}"))
            return
        depth = max(depth, getattr(r, "n_reader_depth", 0))
        if len(r.calls) != len(engine):
            faults.append((pending, None,
                           f"emitted {len(r.calls)} fills, engine emitted "
                           f"{len(engine)}"))
            return
        for k, (got, want) in enumerate(zip(r.calls, engine)):
            for f in ("colour", "px", "py", "bbw", "bbh"):
                if got[f] != want[f]:
                    faults.append((pending, k,
                                   f"{f}: reference {got[f]}, engine {want[f]}"))
                    return
            if got["points"] != want["points"]:
                n = next(i for i, (a, b2) in
                         enumerate(zip(got["points"], want["points"])) if a != b2)
                faults.append((pending, k,
                               f"point {n}: reference {got['points'][n]}, "
                               f"engine {want['points'][n]}"))
                return
            matched += 1

    for kind, a in read_trace(trace):
        kinds[kind] = kinds.get(kind, 0) + 1
        if kind == "part":
            flush()
            pending, engine = None, []
            part = a["index"]
        elif kind == "draw":
            flush()
            pending, engine = a, []
            draws += 1
        elif kind == "poly":
            if pending is not None:
                engine.append(a)
    flush()

    print(f"\ntrace records: " + ", ".join(f"{k} {v:,}" for k, v in
                                           sorted(kinds.items())))
    print(f"top-level draws replayed: {draws:,}")
    print(f"fillPolygon calls matched: {matched:,}")
    print(f"deepest hierarchy nesting seen by the reference: {depth}")

    if faults:
        print(f"\n{len(faults)} FAULTS, first few:")
        for d, k, why in faults[:6]:
            where = "the draw itself" if k is None else f"fill {k}"
            print(f"  draw off={d['off']:#06x} colour={d['colour']:#04x} "
                  f"zoom={d['zoom']} at ({d['x']},{d['y']}) video2={d['video2']}")
            print(f"    {where}: {why}")
        raise SystemExit("FAIL: the reference reader is not the engine's reader")

    if matched == 0:
        raise SystemExit("FAIL: nothing was compared - the trace has no kind 7 "
                         "records, so the probe predates this gate")
    print("\nPASS: the reference reader emits exactly the engine's fillPolygon "
          "calls,\n      every field of every record.")


if __name__ == "__main__":
    main()
