#!/usr/bin/env python3
"""Gate A, first half: decompress every resource and prove the data set is sound.

Host-side only, no emulator. Three independent checks, and the first is the one
that matters most because it needs no external reference at all:

  1. Every compressed resource's CRC cancels to zero. The packer XORed each
     reservoir word into a running check value, so a stream that decodes
     correctly ends at exactly zero. A tampered or truncated bank cannot pass
     this by accident.
  2. Every resource's decompressed length equals the size field in its
     MEMLIST.BIN entry - two independent statements of the same number.
  3. No resource's packed extent runs past the end of its bank file.

That is what lets a dump of unknown provenance be verified rather than trusted.
Optionally cross-checks against Fabien's published resource table if given.

    python3 tools/checkdata.py data/ [fullResourceStats.txt]
"""

import collections
import hashlib
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bytekiller import CorruptStream, read_resource  # noqa: E402
from memlist import TYPES, load  # noqa: E402


def published(path):
    """id -> unpacked size, from the published per-resource dump."""
    out = {}
    for line in open(path):
        m = re.match(r"R:0x([0-9a-fA-F]+),\s+\S+\s+size=\s*(\d+)", line)
        if m:
            out[int(m.group(1), 16)] = int(m.group(2))
    return out


def main():
    data_dir = sys.argv[1] if len(sys.argv) > 1 else "data"
    es, banks = load(data_dir)

    print(f"data:      {os.path.abspath(data_dir)}")
    print(f"resources: {len(es)} before the sentinel")
    print(f"banks:     {len(banks)} referenced, "
          f"{sum(len(b) for b in banks.values()):,} bytes total\n")

    ok = bad = stored = 0
    failures = []
    by_type = collections.Counter()
    out = {}
    for e in es:
        by_type[e["type"]] += 1
        if e["bank"] == 0:
            continue                      # entry references no bank at all
        cap = len(banks[e["bank"]])
        if e["offset"] + e["packed"] > cap:
            failures.append((e["id"], f"extent {e['offset']}+{e['packed']} "
                                      f"past bank {e['bank']} ({cap})"))
            bad += 1
            continue
        try:
            data = read_resource(e, banks[e["bank"]])
        except CorruptStream as ex:
            failures.append((e["id"], str(ex)))
            bad += 1
            continue
        if len(data) != e["size"]:
            failures.append((e["id"], f"got {len(data)} bytes, "
                                      f"memlist says {e['size']}"))
            bad += 1
            continue
        out[e["id"]] = data
        if e["packed"] == e["size"]:
            stored += 1
        else:
            ok += 1

    print("by type:")
    for t in sorted(by_type):
        print(f"  {t}  {TYPES.get(t, 'UNDEFINED'):<20}{by_type[t]:>4}")

    print(f"\ncompressed, CRC verified and length matched : {ok}")
    print(f"stored, length matched                      : {stored}")
    print(f"failed                                      : {bad}")
    for i, why in failures[:12]:
        print(f"    res 0x{i:02X}: {why}")

    if len(sys.argv) > 2 and os.path.exists(sys.argv[2]):
        pub = published(sys.argv[2])
        diff = [(i, len(out[i]), pub[i]) for i in sorted(out)
                if i in pub and len(out[i]) != pub[i]]
        missing = sorted(set(pub) - set(out))
        print(f"\ncross-check against the published table ({len(pub)} rows):")
        print(f"  sizes that differ : {len(diff)}")
        print(f"  ids not decoded   : {len(missing)}"
              + (f"  {[hex(i) for i in missing[:8]]}" if missing else ""))
        for i, a, b in diff[:8]:
            print(f"    res 0x{i:02X}: ours {a:,} vs published {b:,}")

    # A fingerprint of the whole decoded set, so a future run can say "the same
    # data" in one line rather than re-deriving it.
    h = hashlib.sha256()
    for i in sorted(out):
        h.update(out[i])
    print(f"\ndecoded {sum(len(v) for v in out.values()):,} bytes")
    print(f"sha256 of the decoded set, in id order: {h.hexdigest()}")

    if bad:
        raise SystemExit(f"\nFAIL: {bad} resources did not verify")
    print("\nPASS: every resource decodes, its CRC cancels, and its length "
          "matches MEMLIST.BIN.")


if __name__ == "__main__":
    main()
