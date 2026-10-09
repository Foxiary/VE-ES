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
import string
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

# Japanese punctuation drawn with Latin glyphs, under its own character code.
# Translators type ！？～。 out of habit, and with no Latin face carrying them
# those slots keep the template's full-width kana-sized bitmap: taller and wider
# than the Vietnamese around it. Aliasing in the font fixes every line at once
# without touching text. Only punctuation is aliased - a blanket NFKC would also
# rewrite full-width letters and digits. Ported from FFU-Studio's engine.
#   U+3000 is left alone: English fills padding slots with it, and its width is
#   the one thing those slots are for.
#   Quotes go to curly ones, as the translation already uses them, and both
#   dash forms to an em dash, which is what a doubled one stands for.
PUNCTUATION_ALIASES = {chr(ord(ch) + 0xfee0): ch for ch in string.punctuation}
PUNCTUATION_ALIASES.update({
    '、': ',', '。': '.', '・': '·',
    '「': '“', '」': '”', '『': '“', '』': '”',
    '〝': '“', '〞': '”', '〟': '”',
    '〈': '<', '〉': '>', '《': '<', '》': '>',
    '【': '[', '】': ']', '〔': '[', '〕': ']',
    '〖': '[', '〗': ']', '〘': '[', '〙': ']',
    '〚': '[', '〛': ']',
    '〜': '~', '―': '—', '─': '—',
    '…': '...', '‥': '..',
    '‼': '!!', '⁇': '??', '⁈': '?!', '⁉': '!?',
})
ELLIPSES = ('…', '‥')


def source_text(chain, ch, normalize_punctuation=True):
    """The text to draw for `ch`: its Latin alias if the chain has one.

    A character the chain already draws at Latin width - the dashes, in every
    face shipped here - keeps its own designed glyph; only a full-width one, or
    one no face carries, is replaced. The ellipses are the exception and always
    become dots, so a line reads the same whichever form the translator typed.
    """
    import unicodedata
    target = PUNCTUATION_ALIASES.get(ch) if normalize_punctuation else None
    if target is None or chain.pick(target) is None:
        return ch
    if ch not in ELLIPSES and unicodedata.east_asian_width(ch) not in 'WF'             and chain.pick(ch):
        return ch
    return target


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
            # An alias such as '...' must come from one typeface.
            if all(s.has(part) for part in ch):
                return s
        return None


# ------------------------------------------------------------------ rendering

def measure(chain, chars, normalize_punctuation=False):
    """Compute shared (ymin, ymax), measured from ascender = 0."""
    lo, hi = 10 ** 6, -10 ** 6
    for ch in chars:
        ch = source_text(chain, ch, normalize_punctuation)
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


def _lift_tone_mark(im, pad, H, lift):
    """Raise the tone mark of a doubly-accented letter by `lift` rows.

    Vietnamese stacks a tone mark on top of a circumflex or breve, and these
    Latin faces set the two almost touching: measured on the shipped files the
    blank between them is 0 rows (Lora, Cabin), 1 row (Newsreader, Source Serif,
    Open Sans) or 2 (Tinos). The engine then draws the ADV font at 0.588, so
    even 2 rows lands under a pixel and the pair reads on screen as one blunt
    mark - which is what looks like a clipped acute. Nothing is actually cut:
    every glyph matches its source outline row for row.

    The cell has ~16 rows of headroom above the tallest stacked letter, so the
    fix is to move the mark up rather than to change typeface. Only the topmost
    ink band moves, and only when a blank row already separates it from the rest
    of the glyph, so a mark that is drawn joined to its base is left alone.
    """
    a = list(im.getdata())
    rows_ink = [any(a[y * pad + x] for x in range(pad)) for y in range(H)]
    if not any(rows_ink):
        return im
    top = rows_ink.index(True)
    y = top
    while y < H and rows_ink[y]:
        y += 1
    if y >= H or not any(rows_ink[y:]):
        return im                       # single band: nothing stacked to move
    n = min(lift, top)                  # never push ink out of the cell
    if n <= 0:
        return im
    band = a[top * pad: y * pad]
    for i in range(top * pad, y * pad):
        a[i] = 0
    off = (top - n) * pad
    for i, v in enumerate(band):
        if v:
            a[off + i] = max(a[off + i], v)
    im.putdata(a)
    return im


def stroke_margin(stroke):
    """Whole pixels an outline of radius `stroke` reaches past the ink."""
    import math
    return int(math.ceil(stroke)) if stroke > 0 else 0


def outline_palette(pal):
    """Check that a palette can draw a dark outline, and return it as
    premultiplied (value, alpha) pairs in 0..1.

    The ADV fonts' palette is not a coverage ramp: indices 1-3 are BLACK at
    27/60/93% opacity, 4 is opaque near-black and 5-15 run opaque grey to white.
    That is a white letter on a black border, and the stock glyphs use it so -
    a 2 px band of index 4 and a 1 px fringe of 1-3 round every stroke. sysfont's
    palette is white at rising alpha and has no dark entry, so it cannot
    outline anything.
    """
    out = [((r + g + b) / 765.0 * a / 255.0, a / 255.0) for r, g, b, a in pal]
    if not any(al > 0.9 and v < 0.2 for v, al in out):
        raise SystemExit('--stroke needs a palette with a dark opaque entry; '
                         'this template has none (sysfont-style alpha ramp)')
    return out


def _stroke(im, stroke, pal):
    """Outline the coverage in `im` and quantise it to palette indices.

    The outline is solid out to `stroke` px past the letter's 50% contour and
    fades over one more pixel, drawn black under it: alpha = c + o(1 - c),
    premultiplied value = c. Each pixel takes the palette entry nearest that
    pair, alpha weighted double so a solid border lands on opaque near-black
    (index 4, as stock does) rather than on 93% black.
    """
    import math
    import numpy as np
    c = np.asarray(im, dtype=np.float32) / 255.0
    H, W = c.shape
    m = stroke_margin(stroke) + 1
    # Dilate the hardened shape, not the coverage: dilating a glowed edge
    # carries its partial values outward and the border comes out grey and a
    # pixel thin - 9% of ink on index 4 against stock's 33%.
    src = np.pad(np.minimum(1.0, 2.0 * c), m)
    o = np.zeros_like(c)
    for dy in range(-m, m + 1):
        for dx in range(-m, m + 1):
            w = min(1.0, max(0.0, stroke + 1.0 - math.hypot(dx, dy)))
            if w > 0:
                o = np.maximum(o, w * src[m + dy:m + dy + H, m + dx:m + dx + W])
    a = c + o * (1.0 - c)
    pv = np.array([p[0] for p in pal], dtype=np.float32)
    pa = np.array([p[1] for p in pal], dtype=np.float32)
    d = (c[..., None] - pv) ** 2 + (2.0 * (a[..., None] - pa)) ** 2
    return d.argmin(axis=-1).astype(np.uint8)


def render(chain, ch, H, y_off, tracking=0, glow=0.0, mark_lift=0,
           stroke=0.0, palette=None):
    """Return (advance, width, rows), or None. rows = list[list[0..15]].

    The glyph is spaced by its own typeface, plus `tracking` columns. See the
    two comments below for what that is and for two spacing rules tried here
    that were wrong.

    With `stroke`, the letter gets a dark outline of that radius in pixels,
    quantised against `palette` (see outline_palette()). The outline is drawn
    inside the glyph's own advance, which grows by the margin on both sides,
    because stock glyphs never let one letter's border fall on the next one.
    """
    import unicodedata
    from PIL import Image, ImageDraw
    s = chain.pick(ch)
    if s is None:
        return None
    bb = s.font.getbbox(ch)
    ox = stroke_margin(stroke)
    # Draw into a scratch wide enough for the ink wherever the typeface puts it,
    # then find where the ink really is; the source metrics are only a hint.
    guess = max(int(round(s.font.getlength(ch))), bb[2] if bb else 0)
    pad = max(8, guess + 16 + 2 * ox)
    im = Image.new('L', (pad, H), 0)
    ImageDraw.Draw(im).text((ox, y_off), ch, font=s.font, fill=255)
    # Two marks ABOVE (combining class 230) is exactly the Vietnamese stack -
    # tone over circumflex or breve. Counting every combining mark also caught
    # the horn (216) and the dot below (220): in u+horn+dot the horn is joined
    # to the body, so the "top band" was the whole letter and it rose off the
    # baseline. One mark above (the Latin-1 set, and o/u-horn + tone) is left
    # alone.
    if mark_lift and sum(1 for c in unicodedata.normalize('NFD', ch)
                         if unicodedata.combining(c) == 230) >= 2:
        im = _lift_tone_mark(im, pad, H, mark_lift)
    if glow:
        # A straight render has a hard edge, and quantising it to 4bpp
        # stair-steps. Blurring the coverage first softens that. This was once
        # justified by the stock 'o' reading 2 4 4 4 4 6 a d f f f, taken for a
        # five-pixel soft ramp - but in the ADV palette 1-4 are black, so that
        # run is the stock glyph's dark OUTLINE, which is what `stroke` draws.
        from PIL import ImageFilter
        im = im.filter(ImageFilter.GaussianBlur(glow))

    # Outline last: the lift needs the blank row between the marks to find
    # them, and the outline is what fills it in.
    idx = _stroke(im, stroke, palette).ravel().tolist() if stroke else None
    px = idx if stroke else list(im.getdata())
    cols = [x for x in range(pad)
            if any(px[y * pad + x] for y in range(H))]

    if not cols:                     # space, or a glyph that draws nothing
        adv = max(1, int(round(s.font.getlength(ch))) + tracking + 2 * ox)
        w = max(8, ((adv + 7) // 8) * 8)
        return adv, w, [[0] * w for _ in range(H)]

    # Space the glyph exactly as its typeface says, overhang included.
    #
    # Two earlier rules here were both wrong, for the same reason. Measuring the
    # stock font showed its ink never runs past its own advance, and that looked
    # like a rule to enforce - first by re-spacing every glyph off its ink, then
    # by widening the advance only where the ink overflowed. Both break letters
    # whose overhang is deliberate: an `f` hook is drawn to reach over the next
    # letter, so forcing the advance to clear it opens a hole and "Drifter"
    # renders as "Drif ter". The heavier the weight, the bigger the hook and the
    # wider the hole.
    #
    # Nothing clips a glyph to its advance - text overflows the message box
    # freely - so an overhang costs nothing. The stock font simply has no
    # overhangs; that is a property of that typeface, not a constraint of the
    # format. The bitmap is still sized to hold the ink.
    # `tracking` widens every advance by a fixed number of columns. It defaults
    # to 0 and should normally stay there: at 0 the generated .ffu reproduces
    # the source font's own spacing to within rounding - measured at +0% on
    # sysfont and -1.4% on the larger cells, the latter being the per-glyph
    # round to whole pixels. An earlier note here claimed small cells lose their
    # side bearings to rounding and need tracking to put them back; that was
    # wrong. A generated font looks narrower than the stock one because these
    # Latin typefaces ARE narrower than the game's mincho at the same cap
    # height, which tracking cannot fix without distorting the typeface.
    hi = cols[-1]
    adv = max(1, int(round(s.font.getlength(ch))) + tracking + 2 * ox)
    w = max(8, ((max(adv, hi + 1) + 7) // 8) * 8)
    q = (lambda v: v) if stroke else (lambda v: (v + 8) // 17)
    rows = [[q(px[y * pad + x]) if x <= hi else 0
             for x in range(w)] for y in range(H)]
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


def build(tpl, chain, H, y_off, base_new, add_vn=True, verbose=True,
          tracking=0, space_ratio=0.0, glow=0.0, mark_lift=0, stroke=0.0,
          normalize_punctuation=True):
    """Build a new .ffu from rendered and template bitmaps."""
    palette = outline_palette(tpl.palettes[0]) if stroke else None
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
    if normalize_punctuation:
        for ch in PUNCTUATION_ALIASES:
            chars.setdefault(ch, None)

    entries, order = [], sorted(chars, key=FFU.u8i)
    n_new = n_kept = n_skip = 0
    aliased, missing = [], []
    for ch in order:
        text = source_text(chain, ch, normalize_punctuation)
        if normalize_punctuation and ch in PUNCTUATION_ALIASES and text == ch                 and chain.pick(ch) is None:
            missing.append(ch)
        r = render(chain, text, H, y_off, tracking, glow, mark_lift,
                   stroke, palette)
        if r is not None:
            adv, w, rows = r
            entries.append((ch, adv, H, pack(rows)))
            n_new += 1
            if text != ch:
                aliased.append(ch)
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

    # The word space is the one glyph worth overriding. It is faithful to the
    # source font at 0, but these Latin faces set it at 0.31-0.44 of the 'n'
    # advance while every stock game font sits at 0.56-0.59, and at that width
    # words run together on screen. Letter spacing is left exactly as designed.
    if space_ratio:
        adv_n = next((a for c, a, _h, _d in entries if c == 'n'), None)
        if adv_n:
            want = max(1, int(round(adv_n * space_ratio)))
            for k, (c, a, hh, d) in enumerate(entries):
                if c == ' ':
                    entries[k] = (c, want, hh, d)
                    if verbose:
                        print('  dau cach: %d -> %d (%.2f x chu n)' % (a, want, space_ratio))

    if verbose:
        print('  rendered: %d | kept from template: %d | skipped: %d'
              % (n_new, n_kept, n_skip))
        if normalize_punctuation:
            print('  Japanese punctuation drawn as Latin: %d' % len(aliased))
            if missing:
                print('  WARNING: no Latin equivalent in the font chain for %s'
                      % ' '.join('U+%04X' % ord(c) for c in missing))

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
    ap.add_argument('--cell', type=int, default=0,
                    help='force the glyph cell height instead of fitting it to the '
                         'tallest glyph; the template value keeps the text at the '
                         "stock scale, at the cost of clipping whatever does not fit")
    ap.add_argument('--space-ratio', type=float, default=0.0,
                    help="word space as a fraction of the 'n' advance; 0 keeps "
                         "the source font's own. The stock fonts sit at 0.56-0.59 "
                         "while these Latin faces give 0.31-0.44, which is what "
                         "glues words together on screen")
    ap.add_argument('--glow', type=float, default=0.0,
                    help='blur the glyph coverage before quantising, to get the '
                         'soft edge ramp the stock fonts have; without it a 4bpp '
                         'render stair-steps. About 1.0 matches advfont1')
    ap.add_argument('--mark-lift', type=int, default=0,
                    help='raise the tone mark of doubly-accented Vietnamese '
                         'letters by this many rows, so the pair survives the '
                         'engine scaling the ADV font down to 0.588')
    ap.add_argument('--stroke', type=float, default=0.0,
                    help='draw a dark outline of this radius in pixels around '
                         'every rendered glyph, as the stock ADV fonts have: solid '
                         'for N px, then a 1 px soft edge. 2 matches them. Needs a '
                         'template whose palette has a dark entry - not sysfont')
    ap.add_argument('--tracking', type=int, default=0,
                    help='extra columns added to every advance; small cells lose '
                         'the source font side bearings to rounding, so the stock '
                         'sysfont spacing needs about 5 put back')
    ap.add_argument('--no-normalize-punctuation', action='store_true',
                    help='keep the template bitmaps for Japanese punctuation; by '
                         'default ？！。「」… and the rest are drawn with the '
                         'Latin glyph at their own character code')
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
    norm = not a.no_normalize_punctuation
    if norm:
        chars.update(PUNCTUATION_ALIASES)

    lo, hi = measure(chain, chars, norm)
    ox = stroke_margin(a.stroke)          # the outline reaches past the ink
    H = (hi - lo) + 2 * a.pad + 2 * ox
    y_off = a.pad + ox - lo                    # PIL draw origin (y=0 is the ascender line)
    if a.cell:
        # Pin the baseline to where the template puts it and cut the cell to the
        # requested height. Letters keep their position and only what sticks out
        # above the cell - the stacked Vietnamese tone marks - is lost. Without
        # re-anchoring, forcing the height alone drops the whole glyph to the
        # bottom of the cell and shears 11 px off every descender.
        H = a.cell
        y_off = baseline_of(tpl) - chain.sources[0].font.getmetrics()[0]
        # The template's baseline leaves only 16 rows beneath it, and these
        # Latin faces cut a deeper descender than the game's own: at cap 54
        # Newsreader runs to row 91 and loses the tails of g y q p j. The whole
        # lowercase set does fit the cell - 83 rows of 88 - just not at that
        # baseline, so slide it up until the tails clear. What is pushed off the
        # top is the stacked tone marks on CAPITALS, which reach 0.1% of the
        # translated lines, against descenders that are in almost every word.
        lower = [c for c in VN_CHARS if not c.isupper()]
        lower += list('abcdefghijklmnopqrstuvwxyz')
        lo_ink, hi_ink = measure(chain, lower)
        overflow = (y_off + hi_ink + ox) - (H - 1)
        if overflow > 0:
            y_off -= overflow
            print('chan chu : day len %d hang de duoi chu khong bi cat' % overflow)
    base_new = y_off + chain.sources[0].font.getmetrics()[0]
    print('o glyph  : cao %d px (ink %d..%d), baseline %d'
          % (H, lo, hi, base_new))
    if H > 255:
        raise SystemExit('cell height %d > 255, lower --px' % H)

    data = build(tpl, chain, H, y_off, base_new, add_vn=not a.no_vn,
                 tracking=a.tracking, space_ratio=a.space_ratio,
                 glow=a.glow, mark_lift=a.mark_lift, stroke=a.stroke,
                 normalize_punctuation=norm)
    with open(a.out, 'wb') as fh:
        fh.write(data)
    print('-> %s (%s byte)' % (a.out, format(len(data), ',')))


if __name__ == '__main__':
    main()
