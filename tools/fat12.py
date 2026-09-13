#!/usr/bin/env python3
"""Minimal FAT12 reader for raw floppy images - list and extract, no mounting."""
import struct, sys, os

class Fat12:
    def __init__(self, path):
        self.img = open(path, 'rb').read()
        b = self.img
        self.bps    = struct.unpack_from('<H', b, 0x0B)[0]
        self.spc    = b[0x0D]
        self.rsvd   = struct.unpack_from('<H', b, 0x0E)[0]
        self.nfats  = b[0x10]
        self.rootn  = struct.unpack_from('<H', b, 0x11)[0]
        self.total  = struct.unpack_from('<H', b, 0x13)[0]
        self.spf    = struct.unpack_from('<H', b, 0x16)[0]
        self.oem    = b[0x03:0x0B].decode('latin1').strip()
        self.fat_off  = self.rsvd * self.bps
        self.root_off = self.fat_off + self.nfats * self.spf * self.bps
        self.data_off = self.root_off + self.rootn * 32

    def describe(self):
        return (f"OEM {self.oem!r}  {self.bps}B/sector  {self.spc} sector/cluster  "
                f"{self.total} sectors  {self.nfats} FATs of {self.spf}  "
                f"root {self.rootn} entries")

    def fat_entry(self, n):
        off = self.fat_off + (n * 3) // 2
        v = struct.unpack_from('<H', self.img, off)[0]
        return (v >> 4) if (n & 1) else (v & 0x0FFF)

    def chain(self, start):
        out, c, guard = [], start, 0
        while 2 <= c < 0xFF0 and guard < 4096:
            out.append(c); c = self.fat_entry(c); guard += 1
        return out

    def root(self):
        for i in range(self.rootn):
            e = self.img[self.root_off + i*32: self.root_off + i*32 + 32]
            if e[0] == 0x00: break
            if e[0] == 0xE5: continue
            attr = e[0x0B]
            if attr & 0x08 and not (attr & 0x10):   # volume label
                yield ('<label>', e[0:11].decode('latin1').strip(), attr, 0, 0); continue
            if attr & 0x0F == 0x0F: continue        # LFN fragment
            name = e[0:8].decode('latin1').rstrip()
            ext  = e[8:11].decode('latin1').rstrip()
            full = f"{name}.{ext}" if ext else name
            clus = struct.unpack_from('<H', e, 0x1A)[0]
            size = struct.unpack_from('<I', e, 0x1C)[0]
            yield (full, name, attr, clus, size)

    def read(self, clus, size):
        out = bytearray()
        for c in self.chain(clus):
            off = self.data_off + (c - 2) * self.spc * self.bps
            out += self.img[off: off + self.spc * self.bps]
        return bytes(out[:size])

if __name__ == '__main__':
    fs = Fat12(sys.argv[1])
    print(fs.describe()); print()
    print(f"{'name':<14}{'attr':>6}{'clus':>7}{'size':>10}")
    tot = 0
    ents = list(fs.root())
    for full, _, attr, clus, size in ents:
        print(f"{full:<14}{attr:>6}{clus:>7}{size:>10,}")
        tot += size
    print(f"\n{len([e for e in ents if e[0]!='<label>'])} files, {tot:,} bytes")
    if len(sys.argv) > 2:
        out = sys.argv[2]; os.makedirs(out, exist_ok=True)
        for full, _, attr, clus, size in ents:
            if full == '<label>' or attr & 0x10: continue
            open(os.path.join(out, full), 'wb').write(fs.read(clus, size))
        print(f"extracted to {out}")
