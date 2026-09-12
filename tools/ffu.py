"""
ffu.py - read/write .ffu bitmap fonts (Otomate / Idea Factory engine).

FILE LAYOUT (little-endian):
  0x00  u16  magic 'UF' (0x4655)
  0x02  u16  range count
  0x04  u16  glyph count
  0x06  u16  ?  (=0 in every file seen)
  0x08  u16  low byte = 3, high byte = 41 (sysfont) / 76 (advfont) - purpose
             unknown; not the cell height. Possibly line advance or baseline.
             Copied verbatim from the template when rebuilding.
  0x0A  u16  low byte = GLYPH CELL HEIGHT, high byte = 1
  0x0C  u16  ?  (=1)
  0x0E  u16  same value as 0x0A
  0x10  u32  total size
  0x14  u32  range table offset  (= 0x28 + n_palette*64)
  0x18  u32  glyph table offset
  0x1C  u32  bitmap data offset
  0x20  u32  ?
  0x24  u32  ?
  0x28       palette: n_palette * 16 RGBA8888 entries
             entry[0] = transparent, entry[15] = opaque
  RANGE      n_range * 12 bytes: (u32 start, u32 end_exclusive, u32 glyph_base)
             start/end = the character's UTF-8 bytes read as a BIG-ENDIAN integer,
             e.g. 'A' -> 0x41 ; U+1EA4 -> E1 BA A4 -> 0xE1BAA4
             glyph_index = glyph_base + (utf8int(ch) - start)
             THE TABLE MUST BE SORTED ASCENDING by start (engine binary-searches it)
  GTAB       n_glyph * 8 bytes: (u8 advance, u8 height, u16 data_size, u32 data_offset)
             bitmap_width = data_size * 2 / height  (always a multiple of 8)
  BMP        4bpp pixel data, HIGH NIBBLE FIRST, contiguous in glyph order

CRASH WARNING: the engine allocates its draw buffer from the height declared at
0x0A / 0x0E. Writing taller glyphs while leaving those fields at the old value
crashes the game. Keep them in sync with the glyph cell height.
"""
import struct


class FFU:
    def __init__(self, data):
        self.raw = data
        m, self.n_range, self.n_glyph, self._r6, self._r8, self._rA, self._rC, self._rE = \
            struct.unpack_from('<8H', data, 0)
        assert m == 0x4655, f'not a .ffu file (magic={m:#x})'
        self.total, self.off_range, self.off_gtab, self.off_bmp, self._r20, self._r24 = \
            struct.unpack_from('<6I', data, 0x10)
        self.n_pal = (self.off_range - 0x28) // 64
        self.palettes = [
            [struct.unpack_from('<4B', data, 0x28 + p*64 + i*4) for i in range(16)]
            for p in range(self.n_pal)
        ]
        self.ranges = [struct.unpack_from('<3I', data, self.off_range + i*12)
                       for i in range(self.n_range)]
        self.glyphs = []
        for i in range(self.n_glyph):
            adv, hgt, size, off = struct.unpack_from('<BBHI', data, self.off_gtab + i*8)
            self.glyphs.append({'adv': adv, 'h': hgt, 'size': size, 'off': off,
                                'w': (size*2)//hgt if hgt else 0})

    @staticmethod
    def u8i(ch):
        """Character -> its UTF-8 bytes read as a big-endian integer."""
        return int.from_bytes(ch.encode('utf-8'), 'big')

    def index(self, ch):
        """Glyph index for a character, or None if the font lacks it."""
        t = self.u8i(ch)
        lo, hi = 0, self.n_range - 1
        while lo <= hi:
            mid = (lo + hi) // 2
            s, e, b = self.ranges[mid]
            if t < s:   hi = mid - 1
            elif t >= e: lo = mid + 1
            else:       return b + (t - s)
        return None

    def bitmap(self, gi):
        """Return (width, height, list[list[int 0..15]])."""
        g = self.glyphs[gi]
        px = self.raw[self.off_bmp + g['off'] : self.off_bmp + g['off'] + g['size']]
        w, h = g['w'], g['h']
        rows = []
        for y in range(h):
            row = []
            for x in range(w):
                b = px[(y*w + x) // 2]
                row.append((b >> 4) if x % 2 == 0 else (b & 0xf))
            rows.append(row)
        return w, h, rows

    def to_png(self, ch, path, scale=1):
        from PIL import Image
        gi = self.index(ch)
        if gi is None: raise KeyError(f'font has no {ch!r}')
        w, h, rows = self.bitmap(gi)
        im = Image.new('L', (w, h))
        im.putdata([v*17 for r in rows for v in r])
        if scale > 1: im = im.resize((w*scale, h*scale), Image.NEAREST)
        im.save(path)
        return gi, w, h

    @staticmethod
    def pack_bitmap(rows):
        """list[list[int 0..15]] -> 4bpp bytes, high nibble first."""
        out = bytearray()
        for row in rows:
            assert len(row) % 2 == 0, 'width must be even'
            for x in range(0, len(row), 2):
                out.append(((row[x] & 0xf) << 4) | (row[x+1] & 0xf))
        return bytes(out)

    def build(self, new_glyphs):
        """
        new_glyphs: dict {char: (advance, rows)}, rows = list[list[int 0..15]]
        An existing character replaces its glyph; a new one appends a glyph and
        a range entry. Returns the bytes of the new .ffu file.

        Note: this keeps every glyph at its original height, so it only suits
        in-place glyph edits. To change the cell height, use ffugen.py, which
        also updates the height fields at 0x0A / 0x0E.
        """
        # 1. collect existing glyphs, then apply the new ones
        entries = []           # (adv, h, rows_bytes) indexed by glyph index
        for i, g in enumerate(self.glyphs):
            off = self.off_bmp + g['off']
            entries.append([g['adv'], g['h'], self.raw[off:off+g['size']]])
        ranges = [list(r) for r in self.ranges]

        replace, append = {}, {}
        for ch, (adv, rows) in new_glyphs.items():
            gi = self.index(ch)
            (replace if gi is not None else append)[ch] = (gi, adv, rows)

        for ch, (gi, adv, rows) in replace.items():
            entries[gi] = [adv, len(rows), self.pack_bitmap(rows)]

        for ch in sorted(append, key=self.u8i):
            gi, adv, rows = append[ch]
            t = self.u8i(ch)
            new_i = len(entries)
            entries.append([adv, len(rows), self.pack_bitmap(rows)])
            # extend an adjacent range if possible, otherwise start a new one
            merged = False
            for r in ranges:
                if r[1] == t and r[2] + (r[1] - r[0]) == new_i:
                    r[1] = t + 1; merged = True; break
            if not merged:
                ranges.append([t, t + 1, new_i])
        ranges.sort(key=lambda r: r[0])

        # 2. serialise
        pal = self.raw[0x28:self.off_range]
        off_range = 0x28 + len(pal)
        off_gtab  = off_range + len(ranges)*12
        off_bmp   = off_gtab + len(entries)*8

        gtab, bmp = bytearray(), bytearray()
        for adv, h, data in entries:
            gtab += struct.pack('<BBHI', adv, h, len(data), len(bmp))
            bmp += data

        head = bytearray(0x28)
        struct.pack_into('<8H', head, 0, 0x4655, len(ranges), len(entries),
                         self._r6, self._r8, self._rA, self._rC, self._rE)
        body_len = off_bmp + len(bmp)
        struct.pack_into('<6I', head, 0x10, body_len - 0x1a, off_range, off_gtab,
                         off_bmp, self._r20, self._r24)
        rbuf = b''.join(struct.pack('<3I', *r) for r in ranges)
        return bytes(head) + pal + rbuf + bytes(gtab) + bytes(bmp)


def load(path):
    return FFU(open(path, 'rb').read())


if __name__ == '__main__':
    import sys
    f = load(sys.argv[1])
    print(f'ranges={f.n_range} glyphs={f.n_glyph} palettes={f.n_pal}')
    print(f'cell height (0x0A)={f._rA & 0xff}')
    hs = {}
    for g in f.glyphs: hs[g['h']] = hs.get(g['h'], 0) + 1
    print('height:', sorted(hs.items(), key=lambda x: -x[1])[:5])
    for ch in sys.argv[2] if len(sys.argv) > 2 else '':
        gi = f.index(ch)
        if gi is None:
            print(f'{ch}: MISSING'); continue
        w, h, rows = f.bitmap(gi)
        ys = [y for y, r in enumerate(rows) if any(r)] or [-1, -1]
        print(f'{ch}: gi={gi} {w}x{h} adv={f.glyphs[gi]["adv"]} top={ys[0]} bot={ys[-1]}')
