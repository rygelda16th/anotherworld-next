#!/usr/bin/env python3
"""MEMLIST.BIN: the index of every resource in the bank files.

Entry layout is 20 bytes, big-endian, exactly as Resource::readEntries() reads
it in the GPL lineage (awbi/src/resource.cpp): state, type, bufPtr (present in
the file but ignored - it is a runtime pointer), unk4, rankNum, bankId,
bankOffset, unkC, packedSize, unk10, size.

The list has no count. It ends at the first entry whose state byte is 0xFF,
MEMENTRY_STATE_END_OF_MEMLIST (resource.h:25) - so a loader that trusts a
hardcoded 146 is trusting the DOS data set's shape rather than the format's.

Run it directly to print the table:  python3 tools/memlist.py data/
"""

import os
import struct
import sys

ENTRY_SIZE = 20
STATE_END = 0xFF

# Resource::ResType (resource.h:64-76). Type 6 is not in that enum and one
# resource uses it - 0x11, the player and enemy polygon set every action part
# loads. Any switch on type has to cope with it.
TYPES = {
    0: "RT_SOUND",
    1: "RT_MUSIC",
    2: "RT_POLY_ANIM",
    3: "RT_PALETTE",
    4: "RT_BYTECODE",
    5: "RT_POLY_CINEMATIC",
    6: "type6 (video2)",
}


def entries(path):
    """Yield one dict per resource, stopping at the sentinel."""
    raw = open(path, "rb").read()
    if len(raw) % ENTRY_SIZE:
        raise ValueError(
            f"{path} is {len(raw)} bytes, not a multiple of {ENTRY_SIZE}")
    for i in range(len(raw) // ENTRY_SIZE):
        e = raw[i * ENTRY_SIZE:(i + 1) * ENTRY_SIZE]
        if e[0] == STATE_END:
            return
        yield {
            "id": i,
            "state": e[0],
            "type": e[1],
            "rank": e[6],
            "bank": e[7],
            "offset": struct.unpack_from(">I", e, 8)[0],
            "packed": struct.unpack_from(">H", e, 14)[0],
            "size": struct.unpack_from(">H", e, 18)[0],
        }


def bank_path(data_dir, bank_id):
    """The bank file for a bank id, whichever case it is on disk.

    Bank::read() builds the name with sprintf("bank%02x") - lowercase hex - and
    File::open() then tries lowercase and falls back to uppercase (file.cpp).
    Both are accepted here so a data set extracted either way just works.
    """
    for name in (f"bank{bank_id:02x}", f"BANK{bank_id:02X}",
                 f"bank{bank_id:02X}", f"BANK{bank_id:02x}"):
        p = os.path.join(data_dir, name)
        if os.path.exists(p):
            return p
    raise FileNotFoundError(f"no bank file for id {bank_id} in {data_dir}")


def memlist_path(data_dir):
    for name in ("memlist.bin", "MEMLIST.BIN"):
        p = os.path.join(data_dir, name)
        if os.path.exists(p):
            return p
    raise FileNotFoundError(f"no memlist.bin in {data_dir}")


def load(data_dir):
    """(entries, {bank_id: bytes}) for a data directory."""
    es = list(entries(memlist_path(data_dir)))
    banks = {}
    for e in es:
        if e["bank"] and e["bank"] not in banks:
            banks[e["bank"]] = open(bank_path(data_dir, e["bank"]), "rb").read()
    return es, banks


def main():
    data_dir = sys.argv[1] if len(sys.argv) > 1 else "data"
    es, banks = load(data_dir)
    print(f"{'id':>5} {'type':<18}{'bank':>5}{'offset':>9}{'packed':>9}"
          f"{'size':>9}  packed?")
    for e in es:
        print(f"  {e['id']:#04x} {TYPES.get(e['type'], '?'):<18}"
              f"{e['bank']:>5}{e['offset']:>9}{e['packed']:>9}{e['size']:>9}"
              f"  {'yes' if e['packed'] != e['size'] else 'stored'}")
    comp = sum(1 for e in es if e["packed"] != e["size"])
    print(f"\n{len(es)} resources: {comp} compressed, {len(es) - comp} stored")
    print(f"banks referenced: {sorted(banks)}")
    print(f"unpacked total:   {sum(e['size'] for e in es):,} bytes")


if __name__ == "__main__":
    main()
