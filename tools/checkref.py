#!/usr/bin/env python3
"""Gate A, second half: does the reference video layer match the real engine?

Replays the trace the instrumented host engine wrote and compares all four of
its framebuffers against the four the engine dumped at the same frame. Byte for
byte, no tolerance: the reference is the specification, so anything short of
identical means the specification is wrong.

    python3 tools/checkref.py trace.bin page0.bin page1.bin page2.bin page3.bin
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from refvideo import PAGE_SIZE, replay

def main():
    trace = sys.argv[1]
    dumps = sys.argv[2:6]
    v, frames = replay(trace)
    print(f"replayed {frames} frames from {os.path.basename(trace)}")
    ops = {}
    from refvideo import read_trace
    for kind, _ in read_trace(trace):
        ops[kind] = ops.get(kind, 0) + 1
    print("operations: " + ", ".join(f"{k} {n}" for k, n in sorted(ops.items())))
    print()
    allok = True
    for i, path in enumerate(dumps):
        want = open(path, "rb").read()
        got = bytes(v.pages[i])
        if len(want) != PAGE_SIZE:
            print(f"page {i}: dump is {len(want)} bytes, expected {PAGE_SIZE}")
            allok = False
            continue
        if got == want:
            print(f"page {i}: IDENTICAL  ({PAGE_SIZE:,} bytes)")
            continue
        allok = False
        diff = [k for k in range(PAGE_SIZE) if got[k] != want[k]]
        first = diff[0]
        print(f"page {i}: {len(diff):,} of {PAGE_SIZE:,} bytes differ "
              f"({100*len(diff)/PAGE_SIZE:.2f}%)")
        print(f"         first at offset {first} = row {first//160}, "
              f"x {(first%160)*2}:  ours {got[first]:02X} vs engine {want[first]:02X}")
        rows = sorted({k // 160 for k in diff})
        print(f"         rows touched: {len(rows)}  "
              f"({rows[0]}..{rows[-1]})")
    print()
    if allok:
        print("PASS: the reference reproduces every page byte for byte.")
    else:
        raise SystemExit("FAIL: the reference does not match the engine")

if __name__ == "__main__":
    main()
