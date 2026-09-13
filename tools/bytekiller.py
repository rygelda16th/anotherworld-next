#!/usr/bin/env python3
"""The "byte killer" decompressor Another World's bank files are packed with.

Ported from Bank::unpack() and friends in the GPL lineage - Gregory Montoir's
Another-World-Bytecode-Interpreter, src/bank.cpp:56-145, cited line by line
below. Nothing here comes from an unlicensed reimplementation.

Three things about it are unusual and all three are load bearing:

  * It runs BACKWARDS. The packed stream's last twelve bytes are three
    big-endian words - the unpacked length, a CRC, and the initial bit
    reservoir - and the input pointer walks down from there four bytes at a
    time while the output pointer walks down from the END of the unpacked
    buffer. (bank.cpp:87-91)

  * Input and output share one buffer, exactly as the original does: the packed
    bytes sit at the start of a buffer the size of the UNPACKED data, and the
    two pointers converge. The original asserts they never cross
    (bank.cpp:61, :76), and so does this.

  * The bit reservoir is a 32-bit word carrying a sentinel. Bits are shifted out
    of the bottom; when the word reaches exactly zero it is exhausted, a fresh
    word is pulled in, and a new sentinel is shifted into the top. That is what
    `rcr` is doing (bank.cpp:140-145) - it is a rotate-through-carry lifted
    straight from the 68000 original.

The CRC is not decoration: every word read into the reservoir is XORed into it
(bank.cpp:91, :134) and a correct stream leaves it at zero. That makes every
compressed resource self-checking, which is what lets a data set of unknown
provenance be verified rather than trusted.
"""

import struct


class CorruptStream(Exception):
    """The packed stream did not decode - bad CRC, or the pointers crossed."""


class _Unpacker:
    __slots__ = ("buf", "i", "o", "size", "datasize", "crc", "chk")

    def __init__(self, buf, packed_size):
        # buf is a bytearray of the UNPACKED length with the packed bytes at
        # its start, which is how Bank::read() sets it up (bank.cpp:47-49).
        self.buf = buf
        self.i = packed_size - 4          # _iBuf
        self.size = 0                     # _unpCtx.size, persists across steps
        self.datasize = self._word()      # bank.cpp:87
        self.o = self.datasize - 1        # _oBuf, writes backwards
        self.crc = self._word()           # bank.cpp:89
        self.chk = self._word()           # bank.cpp:90
        self.crc ^= self.chk              # bank.cpp:91

    def _word(self):
        """One big-endian 32-bit word, walking the input pointer backwards."""
        if self.i < 0:
            raise CorruptStream("input pointer ran off the front of the buffer")
        w = struct.unpack_from(">I", self.buf, self.i)[0]
        self.i -= 4
        return w

    # --- the bit reader: bank.cpp:129-145 -------------------------------------

    def _rcr(self, carry_in):
        """Rotate the reservoir right through carry. Returns the bit shifted out."""
        out = self.chk & 1
        self.chk >>= 1
        if carry_in:
            self.chk |= 0x80000000
        return out

    def _bit(self):
        cf = self._rcr(False)
        if self.chk == 0:                 # reservoir spent
            self.chk = self._word()
            self.crc ^= self.chk
            cf = self._rcr(True)          # and a fresh sentinel into the top
        return cf

    def _code(self, nbits):
        """nbits gathered most-significant first. bank.cpp:118-127."""
        c = 0
        for _ in range(nbits):
            c = (c << 1) | self._bit()
        return c

    # --- the two operations: bank.cpp:56-80 ----------------------------------

    def _literals(self, nbits, add):
        """decUnk1: a run of bytes carried in the stream verbatim."""
        count = self._code(nbits) + add + 1
        self.datasize -= count
        for _ in range(count):
            if self.o < self.i or self.o < 0:
                raise CorruptStream("output pointer crossed the input")
            self.buf[self.o] = self._code(8)
            self.o -= 1

    def _backref(self, nbits):
        """decUnk2: repeat bytes already emitted, `i` further on in memory.

        Because output is written backwards, `o + i` is data already produced,
        so this is a back-reference despite the addition.
        """
        dist = self._code(nbits)
        count = self.size + 1
        self.datasize -= count
        for _ in range(count):
            if self.o < self.i or self.o < 0:
                raise CorruptStream("output pointer crossed the input")
            src = self.o + dist
            if src >= len(self.buf):
                raise CorruptStream(f"back-reference {dist} past the buffer end")
            self.buf[self.o] = self.buf[src]
            self.o -= 1

    # --- the dispatch: bank.cpp:92-115 --------------------------------------

    def run(self):
        while True:
            if not self._bit():
                self.size = 1
                if not self._bit():
                    self._literals(3, 0)          # 1..8 literal bytes
                else:
                    self._backref(8)              # 2 bytes, distance 0..255
            else:
                c = self._code(2)
                if c == 3:
                    self._literals(8, 8)          # 9..264 literal bytes
                elif c < 2:
                    self.size = c + 2             # 2 or 3
                    self._backref(c + 9)          # distance 9 or 10 bits
                else:
                    self.size = self._code(8)
                    self._backref(12)             # distance 0..4095
            if self.datasize <= 0:
                break
        return self.crc == 0


def unpack(packed, unpacked_size):
    """Decompress one resource. Returns bytes of length unpacked_size.

    Raises CorruptStream if the CRC does not cancel to zero or the pointers
    cross, which is the check that makes a bank file self-verifying.
    """
    if unpacked_size < len(packed):
        raise CorruptStream(
            f"unpacked size {unpacked_size} smaller than packed {len(packed)}")
    buf = bytearray(unpacked_size)
    buf[:len(packed)] = packed
    u = _Unpacker(buf, len(packed))
    if u.datasize != unpacked_size:
        raise CorruptStream(
            f"stream says {u.datasize} bytes, memlist says {unpacked_size}")
    if not u.run():
        raise CorruptStream(f"CRC did not cancel (left 0x{u.crc:08X})")
    return bytes(buf)


def read_resource(entry, bank_bytes):
    """One resource out of its bank, decompressed if it needs to be.

    entry is a dict with packed/size/offset, as tools/memlist.py yields.
    Mirrors Bank::read() (bank.cpp:43-51): equal sizes means stored.
    """
    off, packed, size = entry["offset"], entry["packed"], entry["size"]
    raw = bank_bytes[off:off + packed]
    if len(raw) != packed:
        raise CorruptStream(
            f"bank is short: wanted {packed} at {off}, got {len(raw)}")
    if packed == size:
        return raw
    return unpack(raw, size)
