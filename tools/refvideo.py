#!/usr/bin/env python3
"""The reference video layer: what the Next's renderer must reproduce exactly.

This is the specification, in the same sense that wolf3d-next's
tools/raycast_ref.py is the specification for the walls. The machine matches
this, not the other way round.

Every routine is a transcription of the GPL lineage's src/video.cpp - page
management, the trapezoid walk, and the three span fills - at the original
320x200 and 4 bits a pixel, so it can be checked byte for byte against the real
engine before anything is scaled or ported.

The one thing deliberately NOT reimplemented here is Polygon::readVertices.
The trace already carries its output (the scaled bounding box and vertex list),
which isolates fillPolygon from the vertex transform and lets each be checked
separately.

Two coordinate conventions worth keeping straight:

  * A page row is 160 bytes, two pixels per byte, high nibble the left pixel.
  * fillPolygon walks two edges at once, from opposite ends of the vertex list,
    and reseeds the fractional halves of its two accumulators to 0x7FFF and
    0x8000 at every trapezoid. Those two constants are not interchangeable and
    not arbitrary: they bias the left edge down and the right edge up so a span
    rounds outward, which is what makes adjacent polygons meet without a seam.
"""

import os
import struct

W, H = 320, 200
STRIDE = W // 2          # 160 bytes a row, 4bpp
PAGE_SIZE = STRIDE * H   # 32,000

# _interpTable, generated exactly as Video::init does (video.cpp:60-64).
INTERP = [0x4000] + [0x4000 // i for i in range(1, 0x400)]


def _s32(v):
    """Wrap to signed 32-bit; the original's accumulators are int32/uint32."""
    v &= 0xFFFFFFFF
    return v - 0x100000000 if v & 0x80000000 else v


class RefVideo:
    """Four pages and the operations the bytecode can perform on them.

    The geometry lives in class attributes rather than module constants so a
    second mode can inherit the walk unchanged. RefVideo is the original:
    320x200, two pixels a byte. RefVideo8 below is the Next's.
    """

    W, H = 320, 200
    STRIDE = 160            # bytes a row
    PAGE = 160 * 200
    PPB = 2                 # pixels a byte

    def __init__(self):
        self.pages = [bytearray(self.PAGE) for _ in range(4)]
        # Accounting only. These cannot change a byte of output - `make check-ref`
        # is re-run to prove it - and step 2 of the plan needs them: separating
        # per-polygon setup cost from per-span cost on the machine requires the
        # span count of a polygon PREFIX, and the reference is the only thing
        # that knows it.
        self.n_polys = 0
        self.n_spans = 0
        self.n_span_bytes = 0
        self.n_points = 0
        # Per fill mode, because step 0 measured the three at 5.4, 32 and 37.6 T
        # a byte independently. Splitting them turns a fit that could trade cost
        # between its terms into one whose terms can be checked against constants
        # measured by another method. Index 0 opaque, 1 blend, 2 copy.
        self.n_mode_spans = [0, 0, 0]
        self.n_mode_bytes = [0, 0, 0]
        # Video::init(): curPagePtr2 = page 2, curPagePtr3 = page 1,
        # then changePagePtr1(0xFE) points the work page at curPagePtr2.
        self.cur2 = 2
        self.cur3 = 1
        self.cur1 = self.cur2
        self.hliney = 0

    def _fill_byte(self, colour):
        """The byte that represents one pixel of `colour` repeated across a byte."""
        return ((colour & 0x0F) << 4) | (colour & 0x0F)

    # --- page selection: getPage(), video.cpp:445 -------------------------

    def _page_index(self, page):
        if page <= 3:
            return page
        if page == 0xFF:
            return self.cur3
        if page == 0xFE:
            return self.cur2
        return 0                      # the original warns and uses page 0

    def select(self, page):
        """changePagePtr1"""
        self.cur1 = self._page_index(page)

    def fill_page(self, page, colour):
        """fillPage: a 4-bit index duplicated into both halves of every byte."""
        p = self.pages[self._page_index(page)]
        c = self._fill_byte(colour)
        for i in range(self.PAGE):
            p[i] = c

    def copy_page(self, src, dst, vscroll):
        """copyPage, including its vertical-scroll form (video.cpp:488)."""
        if src == dst:
            return
        if src >= 0xFE or not ((src & 0xBF) & 0x80):
            s = self._page_index(src & 0xBF if src < 0xFE else src)
            d = self._page_index(dst)
            if s == d:
                return
            self.pages[d][:] = self.pages[s]
            return
        # scrolled: the low two bits pick the source page directly
        s = self._page_index((src & 0xBF) & 3)
        d = self._page_index(dst)
        if not (-(self.H - 1) <= vscroll <= self.H - 1):
            return
        h = self.H
        so, do = 0, 0
        if vscroll < 0:
            h += vscroll
            so = -vscroll * self.STRIDE
        else:
            h -= vscroll
            do = vscroll * self.STRIDE
        n = h * self.STRIDE
        if s == d:
            chunk = bytes(self.pages[s][so:so + n])
            self.pages[d][do:do + n] = chunk
        else:
            self.pages[d][do:do + n] = self.pages[s][so:so + n]

    def blit(self, page):
        """updateDisplay: which page becomes visible (video.cpp:567)."""
        if page != 0xFE:
            if page == 0xFF:
                self.cur2, self.cur3 = self.cur3, self.cur2
            else:
                self.cur2 = self._page_index(page)
        return self.cur2

    # --- spans: drawLineN / drawLineBlend / drawLineP ---------------------

    def _span_opaque(self, x1, x2, colour):
        xmax, xmin = max(x1, x2), min(x1, x2)
        p = self.cur1
        buf = self.pages[p]
        off = self.hliney * self.STRIDE + xmin // self.PPB
        w = xmax // self.PPB - xmin // self.PPB + 1
        cmasks = cmaske = 0
        if xmin & 1:
            w -= 1
            cmasks = 0xF0
        if not (xmax & 1):
            w -= 1
            cmaske = 0x0F
        colb = self._fill_byte(colour)
        if cmasks:
            buf[off] = (buf[off] & cmasks) | (colb & 0x0F)
            off += 1
        for _ in range(w):
            buf[off] = colb
            off += 1
        if cmaske:
            buf[off] = (buf[off] & cmaske) | (colb & 0xF0)

    def _span_blend(self, x1, x2, _colour):
        """Colour 0x10: set bit 3 of each pixel already there (video.cpp:341)."""
        xmax, xmin = max(x1, x2), min(x1, x2)
        buf = self.pages[self.cur1]
        off = self.hliney * self.STRIDE + xmin // self.PPB
        w = xmax // self.PPB - xmin // self.PPB + 1
        cmasks = cmaske = 0
        if xmin & 1:
            w -= 1
            cmasks = 0xF7
        if not (xmax & 1):
            w -= 1
            cmaske = 0x7F
        if cmasks:
            buf[off] = (buf[off] & cmasks) | 0x08
            off += 1
        for _ in range(w):
            buf[off] = (buf[off] & 0x77) | 0x88
            off += 1
        if cmaske:
            buf[off] = (buf[off] & cmaske) | 0x80

    def _span_copy(self, x1, x2, _colour):
        """Colour above 0x10: take the pixels from page 0 (video.cpp:409)."""
        xmax, xmin = max(x1, x2), min(x1, x2)
        dst = self.pages[self.cur1]
        src = self.pages[0]
        off = self.hliney * self.STRIDE + xmin // self.PPB
        w = xmax // self.PPB - xmin // self.PPB + 1
        cmasks = cmaske = 0
        if xmin & 1:
            w -= 1
            cmasks = 0xF0
        if not (xmax & 1):
            w -= 1
            cmaske = 0x0F
        if cmasks:
            dst[off] = (dst[off] & cmasks) | (src[off] & 0x0F)
            off += 1
        for _ in range(w):
            dst[off] = src[off]
            off += 1
        if cmaske:
            dst[off] = (dst[off] & cmaske) | (src[off] & 0xF0)

    def draw_char(self, ch, cx, y, colour, font):
        """One 8x8 glyph. drawChar, video.cpp - cx is a CHARACTER cell (4 bytes
        wide at 4bpp), y a pixel row, and two pixels come out of each glyph byte
        pair of bits, most significant first."""
        if not (cx <= 39 and y <= self.H - 8):
            return
        buf = self.pages[self.cur1]
        ft = (ch - 0x20) * 8
        p = cx * 4 + y * self.STRIDE
        for j in range(8):
            row = font[ft + j]
            for i in range(4):
                b = buf[p + i]
                cmask = 0xFF
                colb = 0
                if row & 0x80:
                    colb |= (colour << 4) & 0xFF
                    cmask &= 0x0F
                row = (row << 1) & 0xFF
                if row & 0x80:
                    colb |= colour
                    cmask &= 0xF0
                row = (row << 1) & 0xFF
                buf[p + i] = (b & cmask) | colb
            p += STRIDE

    def _point(self, colour, x, y):
        """drawPoint, the degenerate polygon (video.cpp:312)."""
        if not (0 <= x < self.W and 0 <= y < self.H):
            return
        buf = self.pages[self.cur1]
        off = y * self.STRIDE + x // self.PPB
        if x & 1:
            cmaskn, cmasko = 0x0F, 0xF0
        else:
            cmaskn, cmasko = 0xF0, 0x0F
        colb = ((colour & 0xF) << 4) | (colour & 0xF)
        if colour == 0x10:
            cmaskn &= 0x88
            cmasko = ~cmaskn & 0xFF
            colb = 0x88
        elif colour == 0x11:
            colb = self.pages[0][off]
        buf[off] = ((buf[off] & cmasko) | (colb & cmaskn)) & 0xFF

    # --- the trapezoid walk: fillPolygon, video.cpp:119 -------------------

    @staticmethod
    def _calc_step(p1, p2):
        """(step, dy). dy is uint16 in the original, so a negative height wraps."""
        dy = (p2[1] - p1[1]) & 0xFFFF
        return _s32((p2[0] - p1[0]) * INTERP[dy & 0x3FF] * 4), dy

    # ---- the polygon reader -------------------------------------------------
    # Video::readAndDrawPolygon (video.cpp:83-115), readAndDrawPolygonHierarchy
    # (video.cpp:206-243) and Polygon::readVertices (video.cpp:25-37).
    #
    # This works in the original's 320x200 space and emits exactly the
    # fillPolygon calls the engine emits, which is what makes it checkable: the
    # host probe logs both the top-level draw calls and the resulting fillPolygon
    # calls, so the two sequences can be compared record for record. Our own
    # 256x192 scale is deliberately NOT here - RefVideo8 applies it in the fill,
    # so the reader is one thing under test.

    @staticmethod
    def zoomed(v, zoom):
        """`(*p++) * zoom / 64` - an unsigned byte times zoom, truncated.

        Both operands are non-negative here, so C's truncation towards zero and
        a floor division agree. That is NOT true of the 256x192 scale, which
        takes signed offsets and rounds magnitude-then-sign.
        """
        return v * zoom // 64

    # A limit across a whole run of draws, so a machine comparison can be
    # bisected to one polygon. A draw makes up to 256 of them, and comparing the
    # page after a whole draw says only that one of them is wrong.
    reader_limit = 0            # 0 = no limit

    def _draw_polygon(self, colour, ptx, pty, bbw, bbh, points):
        """What a leaf record ends in. RefVideo8 overrides to apply its scale."""
        self.n_reader_polys = getattr(self, "n_reader_polys", 0) + 1
        if self.reader_limit and self.n_reader_polys > self.reader_limit:
            return
        self.fill_polygon(colour, ptx, pty, bbw, bbh, points)

    def read_vertices(self, buf, off, zoom):
        bbw = self.zoomed(buf[off], zoom)
        bbh = self.zoomed(buf[off + 1], zoom)
        n = buf[off + 2]
        off += 3
        pts = []
        for _ in range(n):
            pts.append((self.zoomed(buf[off], zoom),
                        self.zoomed(buf[off + 1], zoom)))
            off += 2
        return bbw, bbh, pts

    def read_and_draw_polygon(self, buf, off, colour, zoom, ptx, pty, depth=1):
        self.n_reader_depth = max(getattr(self, "n_reader_depth", 0), depth)
        i = buf[off]
        off += 1
        if i >= 0xC0:
            # A leaf. If the incoming colour has bit 7 set the record supplies
            # its own, which is how the bit-7 opcode form - which passes 0xFF -
            # lets the data choose.
            if colour & 0x80:
                colour = i & 0x3F
            bbw, bbh, pts = self.read_vertices(buf, off, zoom)
            self._draw_polygon(colour, ptx, pty, bbw, bbh, pts)
        else:
            i &= 0x3F
            if i == 2:
                self.read_and_draw_polygon_hierarchy(buf, off, zoom, ptx, pty,
                                                     depth + 1)
            else:
                # The engine warns and draws nothing. Count it rather than
                # ignoring it: a reader that silently does nothing looks like a
                # reader that works.
                self.n_reader_bad = getattr(self, "n_reader_bad", 0) + 1

    def read_and_draw_polygon_hierarchy(self, buf, off, zoom, pgcx, pgcy, depth):
        ptx = pgcx - self.zoomed(buf[off], zoom)
        pty = pgcy - self.zoomed(buf[off + 1], zoom)
        # A count MINUS ONE, read as an unsigned byte and widened to signed, then
        # looped while >= 0 (video.cpp:210-215). 0 means one child; 255 means 256.
        childs = buf[off + 2]
        off += 3
        for _ in range(childs + 1):
            o = (buf[off] << 8) | buf[off + 1]      # big-endian, Ptr::fetchWord
            off += 2
            pox = ptx + self.zoomed(buf[off], zoom)
            poy = pty + self.zoomed(buf[off + 1], zoom)
            off += 2
            colour = 0xFF
            if o & 0x8000:
                # The colour byte is read WITHOUT advancing past it, and then the
                # pointer moves two (video.cpp:226-230).
                colour = buf[off] & 0x7F
                off += 2
            # The target is an offset from the SEGMENT BASE, not from here.
            self.read_and_draw_polygon(buf, (o & 0x7FFF) * 2, colour, zoom,
                                       pox, poy, depth)

    def fill_polygon(self, colour, ptx, pty, bbw, bbh, points):
        n = len(points)
        self.n_polys += 1
        self.n_points += n
        if bbw == 0 and bbh == 1 and n == 4:
            self._point(colour, ptx, pty)
            return

        x1 = ptx - bbw // 2
        x2 = ptx + bbw // 2
        y1 = pty - bbh // 2
        y2 = pty + bbh // 2
        if x1 > self.W - 1 or x2 < 0 or y1 > self.H - 1 or y2 < 0:
            return

        self.hliney = y1
        i, j = 0, n - 1
        x2 = points[i][0] + x1
        x1 = points[j][0] + x1
        i += 1
        j -= 1

        if colour < 0x10:
            span, mode = self._span_opaque, 0
        elif colour > 0x10:
            span, mode = self._span_copy, 2
        else:
            span, mode = self._span_blend, 1

        cpt1 = (x1 << 16) & 0xFFFFFFFF
        cpt2 = (x2 << 16) & 0xFFFFFFFF
        numPoints = n
        while True:
            numPoints -= 2
            if numPoints == 0:
                return
            # calcStep takes dy by REFERENCE and the original calls it twice,
            # so the second call overwrites h: the loop height comes from the
            # SECOND edge, not the first. For a well-formed trapezoid the two
            # are equal, which is why taking the first passed every frame of a
            # 64,897-polygon trace - but it is not what the original does, and
            # degenerate input would diverge.
            step1, _ = self._calc_step(points[j + 1], points[j])
            step2, h = self._calc_step(points[i - 1], points[i])
            i += 1
            j -= 1
            cpt1 = (cpt1 & 0xFFFF0000) | 0x7FFF
            cpt2 = (cpt2 & 0xFFFF0000) | 0x8000
            if h == 0:
                cpt1 = (cpt1 + step1) & 0xFFFFFFFF
                cpt2 = (cpt2 + step2) & 0xFFFFFFFF
            else:
                while h:
                    h -= 1
                    if self.hliney >= 0:
                        sx1 = _s32(cpt1) >> 16
                        sx2 = _s32(cpt2) >> 16
                        if sx1 <= self.W - 1 and sx2 >= 0:
                            if sx1 < 0:
                                sx1 = 0
                            if sx2 > self.W - 1:
                                sx2 = self.W - 1
                            self.n_spans += 1
                            nb = abs(sx2 - sx1) + 1
                            self.n_span_bytes += nb
                            self.n_mode_spans[mode] += 1
                            self.n_mode_bytes[mode] += nb
                            span(sx1, sx2, colour)
                    cpt1 = (cpt1 + step1) & 0xFFFFFFFF
                    cpt2 = (cpt2 + step2) & 0xFFFFFFFF
                    self.hliney += 1
                    if self.hliney > self.H - 1:
                        return


# --- the trace format the instrumented host engine writes ------------------

def read_trace(path):
    """Yield ('poly'|'fill'|'copy'|'select'|'blit'|'char'|'draw'|'part', payload)."""
    b = open(path, "rb").read()
    o = 0
    while o < len(b):
        kind = b[o]
        o += 1
        if kind == 1:
            (frame, colour, zoom, px, py, bbw, bbh) = struct.unpack_from(
                "<IHHhhHH", b, o)
            o += 16
            npoints, page = b[o], b[o + 1]
            o += 2
            pts = []
            for _ in range(npoints):
                x, y = struct.unpack_from("<hh", b, o)
                o += 4
                pts.append((x, y))
            yield ("poly", dict(frame=frame, colour=colour, zoom=zoom,
                                px=px, py=py, bbw=bbw, bbh=bbh,
                                page=page, points=pts))
        elif kind == 2:
            yield ("fill", dict(page=b[o], colour=b[o + 1]))
            o += 2
        elif kind == 3:
            src, dst = b[o], b[o + 1]
            vscroll = struct.unpack_from("<h", b, o + 2)[0]
            o += 4
            yield ("copy", dict(src=src, dst=dst, vscroll=vscroll))
        elif kind == 4:
            yield ("select", dict(page=b[o]))
            o += 1
        elif kind == 5:
            yield ("blit", dict(page=b[o]))
            o += 1
        elif kind == 6:
            ch, cx = b[o], b[o + 1]
            y = struct.unpack_from("<H", b, o + 2)[0]
            colour, page = b[o + 4], b[o + 5]
            o += 6
            yield ("char", dict(ch=ch, cx=cx, y=y, colour=colour, page=page))
        elif kind == 7:
            # One top-level polygon draw, as the bytecode asked for it: which
            # segment, the byte offset into it, and the three parameters the two
            # opcode forms compute.
            useV2 = b[o]
            off = struct.unpack_from("<H", b, o + 1)[0]
            colour, zoom = struct.unpack_from("<HH", b, o + 3)
            x, y = struct.unpack_from("<hh", b, o + 7)
            o += 11
            yield ("draw", dict(video2=useV2, off=off, colour=colour,
                                zoom=zoom, x=x, y=y))
        elif kind == 8:
            yield ("part", dict(index=b[o]))
            o += 1
        else:
            raise ValueError(f"unknown trace record {kind} at offset {o-1}")


def replay(path, on_frame=None, font=None, cls=None, stop_after=None,
           stop_draws=None, start_at_part=None):
    """Run a trace through the reference and return the RefVideo.

    `cls` picks the geometry: RefVideo for the engine's own 320x200 4bpp, which is what
    Gate A compares, or RefVideo8 for the Next's 256x192 8bpp, which is what the machine
    has to reproduce. `stop_after` ends the replay after that many blits, so a comparison
    can be aligned on a blit - the one moment where both sides agree what the picture is.
    """
    if font is None:
        d = os.path.dirname(os.path.abspath(path))
        fp = os.path.join(d, "font.bin")
        font = open(fp, "rb").read() if os.path.exists(fp) else None
    v = (cls or RefVideo)()
    frames = 0
    draws = 0
    # `start_at_part` ignores everything before the Nth part record, so a trace that JUMPED
    # into a part can be replayed as the part alone - which is what a machine booted straight
    # into it actually performs. Replaying from the trace's start instead includes drawing the
    # machine never does, and the comparison then fails for that reason rather than any fault.
    seen_parts = 0
    for kind, a in read_trace(path):
        if start_at_part is not None and seen_parts < start_at_part:
            if kind == "part":
                seen_parts += 1
            continue
        if kind == "draw":
            # A draw record marks the OPCODE; the leaves that belong to it follow as poly
            # records. So stopping when the next one arrives includes all of draw N's
            # leaves and none of draw N+1's, which is what makes a bisect comparable.
            draws += 1
            if stop_draws is not None and draws > stop_draws:
                break
            continue
        if kind == "poly":
            # The trace records which page was the work page; trust it rather
            # than re-deriving, so a select the trace missed cannot silently
            # send a polygon to the wrong page.
            v.cur1 = a["page"]
            # _draw_polygon, NOT fill_polygon. _draw_polygon is the leaf hook each
            # geometry overrides: RefVideo's is the engine's own 320x200, RefVideo8's
            # scales into 256x192 and then fills. Calling fill_polygon here fed a
            # RefVideo8 unscaled coordinates, and this is the SECOND time that exact
            # mistake has been made in this project - the first cost a day of believing
            # the machine's rasteriser was wrong when the reference was.
            #
            # What it cost this time: I2's gate reported the game's first polygon as
            # 2,756 wrong bytes when the machine was right. Nine eliminations, four
            # correct-but-irrelevant fixes, and a one-record probe that would not
            # reproduce the failure - all of it measuring the harness.
            v._draw_polygon(a["colour"], a["px"], a["py"],
                            a["bbw"], a["bbh"], a["points"])
        elif kind == "fill":
            v.fill_page(a["page"], a["colour"])
        elif kind == "copy":
            v.copy_page(a["src"], a["dst"], a["vscroll"])
        elif kind == "select":
            v.select(a["page"])
        elif kind == "char":
            if font is None:
                raise RuntimeError("trace has glyphs but font.bin was not found")
            v.cur1 = a["page"]
            v.draw_char(a["ch"], a["cx"], a["y"], a["colour"], font)
        elif kind == "blit":
            v.blit(a["page"])
            frames += 1
            if on_frame:
                on_frame(frames, v)
            if stop_after is not None and frames >= stop_after:
                break
    return v, frames


# --- the Next's geometry ----------------------------------------------------

class RefVideo8(RefVideo):
    """256x192, one byte a pixel: what the Next's renderer must reproduce.

    The algorithm is inherited unchanged - that is the point of validating the
    4bpp form against the real engine first. Only three things differ:

      * Geometry. One byte a pixel, so a row is 256 bytes and a page 49,152.
      * No end masking. At 4bpp a span has to mask a half-byte at each end; at
        8bpp every span is a whole number of bytes and all of that disappears
        from all three fill modes.
      * Vertices are scaled on the way in.

    The scaling is a vertex transform, so it costs nothing per pixel - it folds
    into the multiply the engine already does for zoom. 320x200 and 256x192 fill
    the same 4:3 screen, so the geometry is reproduced and only sampling
    resolution is lost.

    The exact arithmetic is part of the specification, not an implementation
    detail, because the Z80 has to reproduce it bit for bit:

        x' = (|x| * 205) >> 8, sign restored     205/256 = 0.80078
        y' = (|y| * 246) >> 8, sign restored     246/256 = 0.96094

    Magnitude-then-sign means rounding is toward zero for negatives, which is
    what a Z80 doing `abs, multiply, negate` naturally produces. A plain
    arithmetic shift would floor instead, and the two disagree on every negative
    odd value - so the choice is written down rather than left to the compiler.
    Both extremes land exactly: 319 -> 255 and 199 -> 191.
    """

    W, H = 256, 192
    STRIDE = 256
    PAGE = 256 * 192
    PPB = 1

    X_MUL = 205
    Y_MUL = 246

    @staticmethod
    def _scale(v, mul):
        if v < 0:
            return -(((-v) * mul) >> 8)
        return (v * mul) >> 8

    @classmethod
    def sx(cls, v):
        return cls._scale(v, cls.X_MUL)

    @classmethod
    def sy(cls, v):
        return cls._scale(v, cls.Y_MUL)

    def _fill_byte(self, colour):
        """The index in the low nibble, top nibble zero.

        The top nibble is what NextReg $70's palette offset is added to, so it
        must stay clear: leaving it zero is what makes op_setPalette a register
        write instead of an upload.
        """
        return colour & 0x0F

    # --- the three fills, without any of the 4bpp masking -----------------

    def _span_opaque(self, x1, x2, colour):
        a, b = (x1, x2) if x1 <= x2 else (x2, x1)
        off = self.hliney * self.STRIDE + a
        buf = self.pages[self.cur1]
        c = self._fill_byte(colour)
        for i in range(b - a + 1):
            buf[off + i] = c

    def _span_blend(self, x1, x2, _colour):
        """Colour 0x10: set bit 3 of the index, which at 8bpp is `or 8`.

        The game's own palettes already hold the blended variants at entries
        8 to 15, so this reproduces the original effect with no palette surgery.
        """
        a, b = (x1, x2) if x1 <= x2 else (x2, x1)
        off = self.hliney * self.STRIDE + a
        buf = self.pages[self.cur1]
        for i in range(b - a + 1):
            buf[off + i] |= 0x08

    def _span_copy(self, x1, x2, _colour):
        """Colour above 0x10: take the pixels from page 0."""
        a, b = (x1, x2) if x1 <= x2 else (x2, x1)
        off = self.hliney * self.STRIDE + a
        dst = self.pages[self.cur1]
        src = self.pages[0]
        dst[off:off + (b - a + 1)] = src[off:off + (b - a + 1)]

    def _point(self, colour, x, y):
        if not (0 <= x < self.W and 0 <= y < self.H):
            return
        buf = self.pages[self.cur1]
        off = y * self.STRIDE + x
        if colour == 0x10:
            buf[off] |= 0x08
        elif colour > 0x10:
            buf[off] = self.pages[0][off]
        else:
            buf[off] = colour & 0x0F

    # --- scaled entry point ------------------------------------------------

    def draw_char(self, ch, cx, y, colour, font):
        """One 6x8 glyph. THE OVERRIDE RefVideo8 HAS BEEN MISSING.

        Without it the 4bpp version ran on an 8bpp page - four bytes a cell, two pixels a
        byte, a 160-byte stride - which is meaningless here. It went unnoticed because no
        trace any gate uses contains a single `char` record: text needs input, and every
        gate's trace is input-free so its opcode stream stays deterministic. With autoplay
        on, the protection screen draws 2,378 glyphs in 400 frames.

        THE GEOMETRY IS A DECISION, not arithmetic. drawChar takes x in CHARACTER CELLS
        with x <= 39 (video.cpp:299) - forty cells across the original's 320 pixels, eight
        each. Ours is 256 wide: thirty-two cells of eight. Forty eight-pixel cells cannot
        fit, so the glyphs were narrowed to six and all forty cells fit in 240 pixels. See
        tools/mkfont6.py, which also says why five glyphs are hand-drawn.

        The cell ORIGIN in y scales like every other coordinate. The glyph does not: a
        vertically scaled 8-row glyph is an unreadable glyph.
        """
        if not 0 <= cx <= 39:
            return
        x0 = cx * 6
        y0 = self.sy(y)
        if x0 + 6 > self.W or y0 < 0 or y0 + 8 > self.H:
            return
        buf = self.pages[self.cur1]
        ft = (ch - 0x20) * 8
        for j in range(8):
            row = font[ft + j]
            base = (y0 + j) * self.W + x0
            for i in range(6):
                if row & (0x80 >> i):
                    buf[base + i] = colour

    def _draw_polygon(self, colour, ptx, pty, bbw, bbh, points):
        """The reader's leaf, for the 256x192 geometry: scale, then fill.

        Without this override the base class's version ran, which calls
        fill_polygon directly - so the reader fed 320x200 coordinates into a
        256x192 page unscaled, and a centre at x=314 was rejected as off-screen.
        The machine was right and the reference was blank, which is the second
        time in this project that the reference was the one at fault.
        """
        self.n_reader_polys = getattr(self, "n_reader_polys", 0) + 1
        if self.reader_limit and self.n_reader_polys > self.reader_limit:
            return
        self.fill_polygon_scaled(colour, ptx, pty, bbw, bbh, points)

    def fill_polygon_scaled(self, colour, ptx, pty, bbw, bbh, points):
        """Scale a polygon out of 320x200 space and draw it."""
        return self.fill_polygon(
            colour, self.sx(ptx), self.sy(pty), self.sx(bbw), self.sy(bbh),
            [(self.sx(x), self.sy(y)) for x, y in points])
