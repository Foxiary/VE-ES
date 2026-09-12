"""
ffugen.py - generate .ffu bitmap font files from OTF/TTF fonts.

    python ffugen.py --template stock.ffu --out new.ffu \
        --font "C:/Windows/Fonts/cambria.ttc" --size 64 [--font ...] [--px N]

Idea: .ffu is a 4bpp bitmap font with a lookup table indexed by UTF-8 bytes.
This tool re-renders glyphs from vector fonts and rebuilds the .ffu file while
preserving the structure readable by the engine. It can be reused for any
Otomate game using this format - only the template needs to be changed.

FONT CHAIN (--font may be repeated, in priority order)
    No system font contains both all Vietnamese characters and all kanji, so
    the charset is split across multiple fonts. Characters missing from every
    font
    keep their original bitmap from the template - preserving the game's
    original kanji/kana glyphs.

BASELINE ALIGNMENT
    Newly rendered glyphs and glyphs kept from the template must share a
    baseline, otherwise the text will jump vertically. The template baseline is
    inferred from the bottom of the letter 'A'.

COMMON PITFALLS (verified on Virche Evermore)
  - 4bpp bitmap, HIGH nibble first; the row width MUST be a multiple of 8
  - the range table must be sorted ascending by the big-endian UTF-8 byte value
    - header 0x0A and 0x0E: low byte = glyph cell height. Wrong values ->
        GAME CRASH
  - data_size is u16, while advance and height are u8 -> limits apply
"""
import argparse
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ffu import FFU, load                                    # noqa: E402

# Complete Vietnamese character set (146 accented characters)
_VN = ('A\u00c0\u00c1\u1ea2\u00c3\u1ea0\u0102\u1eb0\u1eae\u1eb2\u1eb4\u1eb6'
       '\u00c2\u1ea6\u1ea4\u1ea8\u1eaa\u1eac'
       'E\u00c8\u00c9\u1eba\u1ebc\u1eb8\u00ca\u1ec0\u1ebe\u1ec2\u1ec4\u1ec6'
       'I\u00cc\u00cd\u1ec8\u0128\u1eca'
       'O\u00d2\u00d3\u1ece\u00d5\u1ecc\u00d4\u1ed2\u1ed0\u1ed4\u1ed6\u1ed8'
       '\u01a0\u1edc\u1eda\u1ede\u1ee0\u1ee2'
       'U\u00d9\u00da\u1ee6\u0168\u1ee4\u01af\u1eea\u1ee8\u1eec\u1eee\u1ef0'
       'Y\u1ef2\u00dd\u1ef6\u1ef8\u1ef4\u0110')
VN_CHARS = [c for ch in _VN for c in (ch, ch.lower())]


# --------------------------------------------------------------- font chain

class Source:
    """A source font in the fallback chain."""

    def __init__(self, path, px, index=0):
        from PIL import ImageFont
        self.path, self.index, self.px = path, index, px
        self.font = ImageFont.truetype(path, px, index=index)
        try:
            from fontTools.ttLib import TTFont, TTCollection
            if path.lower().endswith('.ttc'):
                tt = TTCollection(path).fonts[index]
            else:
                tt = TTFont(path, lazy=True)
            self.cmap = set(tt.getBestCmap().keys())
            self.name = tt['name'].getDebugName(4) or os.path.basename(path)
            tt.close()
        except Exception:
            self.cmap, self.name = None, os.path.basename(path)

    def has(self, ch):
        if self.cmap is not None:
            return ord(ch) in self.cmap
        return self.font.getmask(ch, mode='L').getbbox() is not None

    def __repr__(self):
        return '%s @%dpx' % (self.name, self.px)


class Chain:
    def __init__(self, specs, px):
        self.sources = []
        for s in specs:
            path, _, idx = s.partition('#')
            self.sources.append(Source(path, px, int(idx or 0)))

    def pick(self, ch):
        for s in self.sources:
            if s.has(ch):
                return s
        return None


# ------------------------------------------------------------------ rendering

def measure(chain, chars):
    """Compute shared (ymin, ymax), measured from ascender = 0."""
    lo, hi = 10 ** 6, -10 ** 6
    for ch in chars:
        s = chain.pick(ch)
        if s is None:
            continue
        bb = s.font.getbbox(ch)
        if bb is None or bb[3] <= bb[1]:
            continue
        lo, hi = min(lo, bb[1]), max(hi, bb[3])
    if lo > hi:
        raise SystemExit('no character could be rendered - check --font')
    return lo, hi


def render(chain, ch, H, y_off):
    """Return (advance, width, rows), or None. rows = list[list[0..15]]."""
    from PIL import Image, ImageDraw
    s = chain.pick(ch)
    if s is None:
        return None
    adv = int(round(s.font.getlength(ch)))
    bb = s.font.getbbox(ch)
    ink_r = max(bb[2], adv) if bb else adv
    w = max(8, ((ink_r + 7) // 8) * 8)
    im = Image.new('L', (w, H), 0)
    ImageDraw.Draw(im).text((0, y_off), ch, font=s.font, fill=255)
    px = list(im.getdata())
    rows = [[(px[y * w + x] + 8) // 17 for x in range(w)] for y in range(H)]
    return adv, w, rows


# ------------------------------------------------------------------- build

def cap_height(f, ch='A'):
    """Measure the template's uppercase letter height in pixels."""
    gi = f.index(ch)
    if gi is None:
        return None
    _w, _h, rows = f.bitmap(gi)
    ys = [y for y, r in enumerate(rows) if any(r)]
    return (ys[-1] - ys[0] + 1) if ys else None


def match_px(path, index, target_cap, ch='A', lo=4, hi=400):
    """Find the pixel size that makes the uppercase letter as tall as
    target_cap.

    An exact match is required: kanji are kept from the template, so Latin
    glyphs that render larger or smaller would be visibly misaligned beside
    them.
    """
    from PIL import ImageFont
    best, best_err = lo, 10 ** 9
    while lo <= hi:
        mid = (lo + hi) // 2
        bb = ImageFont.truetype(path, mid, index=index).getbbox(ch)
        cap = (bb[3] - bb[1]) if bb else 0
        err = abs(cap - target_cap)
        if err < best_err:
            best, best_err = mid, err
        if cap < target_cap:
            lo = mid + 1
        elif cap > target_cap:
            hi = mid - 1
        else:
            return mid
    return best


def baseline_of(f):
    """Get the template baseline: the bottom of 'A' + 1."""
    gi = f.index('A')
    if gi is None:
        return f.glyphs[0]['h']
    _w, _h, rows = f.bitmap(gi)
    ys = [y for y, r in enumerate(rows) if any(r)]
    return (ys[-1] + 1) if ys else f.glyphs[gi]['h']


def pack(rows):
    out = bytearray()
    for row in rows:
        for x in range(0, len(row), 2):
            value = ((min(15, row[x]) & 0xf) << 4) | \
                (min(15, row[x + 1]) & 0xf)
            out.append(value)
    return bytes(out)


def build(tpl, chain, H, y_off, base_new, add_vn=True, verbose=True):
    """Build a new .ffu from rendered and template bitmaps."""
    base_old = baseline_of(tpl)
    shift = base_new - base_old          # shift old glyphs to the new baseline

    # charset = template characters + Vietnamese
    chars = {}
    for s, e, b in tpl.ranges:
        for t in range(s, e):
            nb = (t.bit_length() + 7) // 8
            try:
                ch = t.to_bytes(nb, 'big').decode('utf-8')
            except Exception:
                continue
            chars[ch] = b + (t - s)
    if add_vn:
        for ch in VN_CHARS:
            chars.setdefault(ch, None)

    entries, order = [], sorted(chars, key=FFU.u8i)
    n_new = n_kept = n_skip = 0
    for ch in order:
        r = render(chain, ch, H, y_off)
        if r is not None:
            adv, w, rows = r
            entries.append((ch, adv, H, pack(rows)))
            n_new += 1
            continue
        # Missing from fonts -> keep the template bitmap.
        gi = chars[ch]
        if gi is None:
            n_skip += 1
            continue
        g = tpl.glyphs[gi]
        _w, _h, rows = tpl.bitmap(gi)
        box = [[0] * g['w'] for _ in range(H)]
        for y, row in enumerate(rows):
            ty = y + shift
            if 0 <= ty < H:
                box[ty] = row[:]
        entries.append((ch, g['adv'], H, pack(box)))
        n_kept += 1

    if verbose:
        print('  rendered: %d | kept from template: %d | skipped: %d'
              % (n_new, n_kept, n_skip))

    # range table: merge consecutive characters
    ranges, gtab, bmp = [], bytearray(), bytearray()
    for i, (ch, adv, h, data) in enumerate(entries):
        t = FFU.u8i(ch)
        if ranges and ranges[-1][1] == t:
            ranges[-1][1] = t + 1
        else:
            ranges.append([t, t + 1, i])
        if adv > 255 or h > 255 or len(data) > 0xffff:
            raise SystemExit('%r exceeds field limits (adv=%d h=%d size=%d)'
                             % (ch, adv, h, len(data)))
        gtab += struct.pack('<BBHI', adv, h, len(data), len(bmp))
        bmp += data

    pal = tpl.raw[0x28:tpl.off_range]
    off_range = 0x28 + len(pal)
    off_gtab = off_range + len(ranges) * 12
    off_bmp = off_gtab + len(entries) * 8

    head = bytearray(0x28)
    hfield = (1 << 8) | (H & 0xff)        # low byte = glyph cell height
    struct.pack_into('<8H', head, 0, 0x4655, len(ranges), len(entries),
                     tpl._r6, tpl._r8, hfield, tpl._rC, hfield)
    struct.pack_into('<6I', head, 0x10, off_bmp + len(bmp) - 0x1a,
                     off_range, off_gtab, off_bmp, tpl._r20, tpl._r24)
    return (bytes(head) + pal
            + b''.join(struct.pack('<3I', *r) for r in ranges)
            + bytes(gtab) + bytes(bmp))


def main():
    ap = argparse.ArgumentParser(description='generate .ffu from an OTF/TTF font')
    ap.add_argument('--template', required=True, help='stock .ffu used as the template')
    ap.add_argument('--out', required=True)
    ap.add_argument('--font', action='append', required=True,
                    help='source font; repeat in priority order. For .ttc use '
                    '"path/to.ttc#0" to pick a face in '
                    'the collection')
    ap.add_argument('--px', type=int, default=None,
                    help='pixel size; omit to AUTO-FIT the template uppercase '
                    'height (recommended - see --match-char)')
    ap.add_argument('--match-char', default='A',
                    help='character used to match the template size (default A)')
    ap.add_argument('--pad', type=int, default=2, help='extra padding above and below')
    ap.add_argument('--no-vn', action='store_true',
                    help='do not add the Vietnamese charset')
    a = ap.parse_args()

    tpl = load(a.template)
    hs = [g['h'] for g in tpl.glyphs]
    tpl_h = max(set(hs), key=hs.count)
    cap = cap_height(tpl, a.match_char)

    if a.px:
        px = a.px
        note = '(given explicitly)'
    else:
        p0, _, i0 = a.font[0].partition('#')
        px = match_px(p0, int(i0 or 0), cap, a.match_char)
        note = '(auto-fit to template %r height of %dpx)' % (a.match_char, cap)

    chain = Chain(a.font, px)
    print('template : %s  (%d glyphs, cell %d, baseline %d, %r height %s)'
          % (os.path.basename(a.template), tpl.n_glyph, tpl_h,
             baseline_of(tpl), a.match_char, cap))
    print('size     : %d px %s' % (px, note))
    for s in chain.sources:
        print('font     : %s' % s)

    chars = set()
    for s, e, _b in tpl.ranges:
        for t in range(s, e):
            nb = (t.bit_length() + 7) // 8
            try:
                chars.add(t.to_bytes(nb, 'big').decode('utf-8'))
            except Exception:
                pass
    if not a.no_vn:
        chars.update(VN_CHARS)

    lo, hi = measure(chain, chars)
    H = (hi - lo) + 2 * a.pad
    y_off = a.pad - lo                    # PIL draw origin (y=0 is the ascender line)
    base_new = y_off + chain.sources[0].font.getmetrics()[0]
    print('o glyph  : cao %d px (ink %d..%d), baseline %d'
          % (H, lo, hi, base_new))
    if H > 255:
        raise SystemExit('cell height %d > 255, lower --px' % H)

    data = build(tpl, chain, H, y_off, base_new, add_vn=not a.no_vn)
    with open(a.out, 'wb') as fh:
        fh.write(data)
    print('-> %s (%s byte)' % (a.out, format(len(data), ',')))


if __name__ == '__main__':
    main()
