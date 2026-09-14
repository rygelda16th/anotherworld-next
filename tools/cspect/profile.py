#!/usr/bin/env python3
"""Resolve an awprobe AWPROBE_PROF sample file to routines, from the assembly listing and the C map.

    python3 tools/cspect/profile.py /tmp/x.prof build/aw.lst build/aw_vm.map

Labels come from the listing (global labels only, the ones in column one) and from z88dk's map
(public code symbols). A sample is charged to the nearest label at or below it.
"""
import re
import sys
from collections import Counter


def labels(lst, cmap):
    out = {}
    for line in open(lst, errors="replace"):
        m = re.match(r"\s*\d+\+?\s+([0-9A-F]{4})\s+([A-Za-z_][A-Za-z0-9_]*):", line)
        if m:
            out.setdefault(int(m.group(1), 16), m.group(2))
    for line in open(cmap, errors="replace"):
        m = re.match(r"(_[A-Za-z0-9_]+)\s+=\s+\$([0-9A-F]{4})\s+;\s+addr,", line)
        if m:
            out.setdefault(int(m.group(2), 16), "C:" + m.group(1))
    return sorted(out.items())


def main():
    prof, lst, cmap = sys.argv[1:4]
    table = labels(lst, cmap)
    addrs = [a for a, _ in table]
    import bisect
    by = Counter()
    total = 0
    for line in open(prof):
        if line.startswith("#"):
            continue
        a, n = line.split()
        a, n = int(a, 16), int(n)
        i = bisect.bisect_right(addrs, a) - 1
        name = table[i][1] if i >= 0 else "?"
        if a < 0x4000:
            name = "(below $4000: ROM or a paged window) " + name
        by[name] += n
        total += n
    for name, n in by.most_common(25):
        print(f"{100 * n / total:5.1f}%  {n:5}  {name}")
    print(f"{total} samples")


if __name__ == "__main__":
    main()
