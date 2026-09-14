#!/usr/bin/env python3
"""Cut one part's opcode stream out of a probe run that jumped into it.

    python3 tools/mkpartops.py <probe ops.txt> <out> [--part N]

I9a asks for Gate D to be re-run against a GAMEPLAY part, and the probe reaches one through
instrJumpPart (its argv[5]). But a jump is a REQUEST: the engine finishes the frame it is in,
and the part it was already running keeps dispatching until the change is acted on. A stream
taken straight from such a run therefore opens with several frames of the WRONG part, and the
harness - which starts the new part's bytecode from its first instruction - diverges at record
two every time. It did.

THE PART CHANGE IS VISIBLE IN THE STREAM. initForPart resets thread 0 to pc 0, which the probe
logs as `thread <frame> 0 0`. The first such record is the original boot; the next is the jump.
Everything from there is the new part, and renumbering its frames from zero makes it the same
shape as a run that had started there.

Checked by construction: the result's first records are `thread 0 0 0` then `op 0 0 0 4`, which
is a thread starting at pc 0 and its first opcode - exactly what the harness produces.
"""
import sys


def main():
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    src, dst = sys.argv[1], sys.argv[2]
    lines = open(src).read().split("\n")
    seed = next((l for l in lines if l.startswith("seed")), None)
    if seed is None:
        raise SystemExit(f"{src}: no seed line - was the probe run with tracing on?")

    resets = [i for i, l in enumerate(lines)
              if l.split()[:1] == ["thread"] and l.split()[2:4] == ["0", "0"]]
    if len(resets) < 2:
        raise SystemExit(f"{src}: only {len(resets)} thread-0-at-pc-0 record(s) - this run "
                         "never changed part, so there is no second part to cut out")
    start = resets[1]
    base = int(lines[start].split()[1])

    out, n = [seed], 0
    for l in lines[start:]:
        f = l.split()
        if f and f[0] in ("op", "thread"):
            f[1] = str(int(f[1]) - base)
            out.append(" ".join(f))
            n += 1
    open(dst, "w").write("\n".join(out) + "\n")
    frames = max(int(l.split()[1]) for l in out[1:]) + 1
    print(f"wrote {dst}: {n:,} records over {frames} frames, cut at frame {base} of the run")
    if out[1] != "thread 0 0 0":
        print(f"  WARNING: it does not begin with a thread at pc 0 but with {out[1]!r}")
    if n * 4 > 8192:
        print(f"  WARNING: {n * 4:,} bytes will not fit the harness's 8,192 at $E000")


if __name__ == "__main__":
    main()
