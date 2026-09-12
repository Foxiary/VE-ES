"""
vnfont.py - add Vietnamese glyphs to a .ffu font by COMPOSING them from the
game's own glyphs, so stroke weight, style and anti-aliasing stay untouched.

Mark sources - every one is cut from the stock font itself:
  - stem       : the most-composed precomposed glyph already present
                 (e.g. the font's own e-circumflex rather than a bare e)
  - grave / acute / tilde / circumflex : cut from a-grave / a-acute / a-tilde /
                 a-circumflex, and their uppercase counterparts
  - breve      : the bowl of o, squeezed into the circumflex box
  - hook above : the COMMA, mirrored horizontally
  - dot below  : the period
  - horn       : the right single quotation mark (U+2019)
  - D-stroke   : a bar drawn across the stem of D / d

Cell height: every glyph gains EXTRA_TOP blank rows ABOVE, with the artwork
pushed to the bottom of the cell. That is safe whether the engine aligns glyphs
by their top or their baseline, because every glyph shifts by the same amount,
so they stay aligned with one another.

NOTE: when EXTRA_TOP changes the cell height, the header fields at 0x0A / 0x0E
must change with it or the game crashes - serialize() handles that.
"""
import sys, struct, unicodedata

sys.path.insert(0, 'D:/VE/tools')
from ffu import FFU, load

# ---------------------------------------------------------------- bitmap utils
# rows = list[list[int 0..15]]

def bbox(rows):
    ys = [y for y, r in enumerate(rows) if any(r)]
    if not ys:
        return None
    xs = [x for x in range(len(rows[0])) if any(r[x] for r in rows)]
    return ys[0], ys[-1], xs[0], xs[-1]


def crop(rows, bb):
    y0, y1, x0, x1 = bb
    return [r[x0:x1 + 1] for r in rows[y0:y1 + 1]]


def blank(w, h):
    return [[0] * w for _ in range(h)]


def paste(dst, src, ox, oy):
    H, W = len(dst), len(dst[0])
    for y, row in enumerate(src):
        ty = oy + y
        if not (0 <= ty < H):
            continue
        drow = dst[ty]
        for x, v in enumerate(row):
            tx = ox + x
            if v and 0 <= tx < W and v > drow[tx]:
                drow[tx] = v


def flip_v(rows):
    return [r[:] for r in rows[::-1]]


def scale(rows, nw, nh):
    from PIL import Image
    h, w = len(rows), len(rows[0])
    nw, nh = max(1, nw), max(1, nh)
    im = Image.new('L', (w, h))
    im.putdata([v * 17 for r in rows for v in r])
    im = im.resize((nw, nh), Image.LANCZOS)
    d = list(im.getdata())
    return [[min(15, max(0, (d[y * nw + x] + 8) // 17)) for x in range(nw)]
            for y in range(nh)]


def scale_to_h(rows, nh):
    return scale(rows, max(2, round(len(rows[0]) * nh / len(rows))), nh)


# Hook stroke profile: (position along the curve, thickness). Thin at the
# entry, heaviest at the shoulder, tapering to the tail - imitating the
# thick/thin modulation of the stock mincho. A fixed-width arc gives a flat,
# solid stroke that stands out badly next to the acute.
HOOK_PROFILE = ((0.0, 0.32), (0.25, 1.0), (0.60, 0.66), (1.0, 0.10))
HOOK_A0, HOOK_SWEEP, HOOK_WR, HOOK_R = 172, 232, 0.85, 0.15


def draw_hook(h, ss=16):
    """Draw a hook-above mark. Fallback only, for fonts with no comma:
    cutting one from the question mark drags along its vertical stem, and at
    sysfont size (~7px) it turns to mush. Drawn at ss times size, then
    downsampled."""
    import math
    from PIL import Image, ImageDraw
    w = max(4, round(h * HOOK_WR))
    W, H = w * ss, h * ss
    im = Image.new('L', (W, H), 0)
    d = ImageDraw.Draw(im)
    rmax = min(W, H) * HOOK_R
    cx, cy = W / 2, H / 2
    rx, ry = W / 2 - rmax, H / 2 - rmax

    def r_at(t):
        for i in range(len(HOOK_PROFILE) - 1):
            t0, v0 = HOOK_PROFILE[i]
            t1, v1 = HOOK_PROFILE[i + 1]
            if t0 <= t <= t1:
                return (v0 + (v1 - v0) * (t - t0) / (t1 - t0)) * rmax
        return HOOK_PROFILE[-1][1] * rmax

    n = 600
    for i in range(n + 1):
        t = i / n
        a = math.radians(HOOK_A0 + HOOK_SWEEP * t)
        x, y, r = cx + rx * math.cos(a), cy + ry * math.sin(a), r_at(t)
        d.ellipse([x - r, y - r, x + r, y + r], fill=255)

    im = im.resize((w, h), Image.LANCZOS)
    px = list(im.getdata())
    rows = [[min(15, (px[y * w + x] + 8) // 17) for x in range(w)]
            for y in range(h)]
    bb = bbox(rows)                      # trim blank border, else the gap grows
    return crop(rows, bb) if bb else rows


# ------------------------------------------------------------ mark extraction

MARK_ABOVE = {
    '\u0300': 'grave', '\u0301': 'acute', '\u0303': 'tilde',
    '\u0302': 'circum', '\u0306': 'breve', '\u0309': 'hook',
}
MARK_BELOW = {'\u0323': 'dot'}
MARK_HORN = '\u031b'

# Shrink factor for a mark on a second tier (e.g. acute above circumflex)
TIER2_SCALE = 0.76


class Marks:
    """Extract every mark needed, all from the stock font itself."""

    def __init__(self, f):
        self.f = f

        def rows(ch):
            gi = f.index(ch)
            if gi is None:
                return None
            _w, _h, r = f.bitmap(gi)
            return r if bbox(r) else None

        self.rows = rows

        def above(accented, plain):
            """The part of an accented glyph sitting ABOVE the plain letter top."""
            ra, rp = rows(accented), rows(plain)
            top = bbox(rp)[0]
            part = ra[:top]
            bb = bbox(part)
            if bb is None:
                raise ValueError('could not extract a mark from %r' % accented)
            return crop(part, bb)

        self.grave = above('\u00e0', 'a')      # a + grave
        self.acute = above('\u00e1', 'a')      # a + acute
        self.tilde = above('\u00e3', 'a')      # a + tilde
        self.circum = above('\u00e2', 'a')     # a + circumflex
        self.GRAVE = above('\u00c0', 'A')
        self.ACUTE = above('\u00c1', 'A')
        self.TILDE = above('\u00c3', 'A')
        self.CIRCUM = above('\u00c2', 'A')

        # breve = the bowl of o (a U shape - a better match than a flipped caron)
        def bowl(ch, ref):
            r = rows(ch)
            y0, y1, x0, x1 = bbox(r)
            cut = y1 - max(3, int((y1 - y0 + 1) * 0.22))
            part = [row[x0:x1 + 1] for row in r[cut:y1 + 1]]
            # force the circumflex box; scaling by aspect ratio makes it far too wide
            return scale(part, len(ref[0]), len(ref))

        self.breve = bowl('o', self.circum)
        self.BREVE = bowl('O', self.CIRCUM)

        # hook above = the COMMA, MIRRORED. The comma already has the right
        # shape: a round heavy head on top tapering into a curved tail.
        # Mirrored it is exactly a hook, and it keeps the stock thick/thin
        # modulation and anti-aliased edges that a hand-drawn arc lacks.
        cm = rows(',')
        if cm is not None:
            mirror = [r[::-1] for r in crop(cm, bbox(cm))]
            self.hook = scale_to_h(mirror, max(6, round(len(self.acute) * 1.25)))
            self.HOOK = scale_to_h(mirror, max(6, round(len(self.ACUTE) * 1.25)))
        else:                                    # no comma in the font -> draw one
            self.hook = draw_hook(max(6, round(len(self.acute) * 1.25)))
            self.HOOK = draw_hook(max(6, round(len(self.ACUTE) * 1.25)))

        # dot below = the period
        d = rows('.')
        self.dot = crop(d, bbox(d))

        # horn = the right single quotation mark
        ap = rows('\u2019')
        self.horn = crop(ap, bbox(ap))

    def get(self, name, upper):
        return getattr(self, name.upper() if upper else name)


# ------------------------------------------------------------------- compose

def compose(f, M, ch, H):
    """Compose the glyph for ch in a cell of height H. Returns (advance, rows)."""
    nfd = unicodedata.normalize('NFD', ch)
    base, marks = nfd[0], list(nfd[1:])
    upper = base.isupper()

    # 1. pick the stem: prefer the most-composed form the font already has
    stem, used = base, []
    for k in range(len(marks), 0, -1):
        cand = unicodedata.normalize('NFC', base + ''.join(marks[:k]))
        if len(cand) != 1:
            continue
        gi = f.index(cand)
        if gi is None:
            continue
        _w, _h, r = f.bitmap(gi)
        if bbox(r):
            stem, used = cand, marks[:k]
            break

    gi = f.index(stem)
    if gi is None:
        return None
    w, h, rows0 = f.bitmap(gi)
    if bbox(rows0) is None:
        return None
    adv = f.glyphs[gi]['adv']
    rest = [m for m in marks[len(used):]]

    # the horn overhangs the stem -> widen by 8px (width stays a multiple of 8)
    has_horn = MARK_HORN in rest
    ow = w + 8 if has_horn else w
    out = blank(ow, H)
    paste(out, rows0, 0, H - h)          # noi dung nam sat DAY o

    # 2. attach the horn to the right shoulder of o / u
    if has_horn:
        rest.remove(MARK_HORN)
        adv += 4
        y0, y1, x0, x1 = bbox(out)
        xh = y1 - y0 + 1                        # stem height
        hn = scale_to_h(M.horn, max(5, int(xh * 0.42)))
        paste(out, hn, x1 - max(1, len(hn[0]) // 3),
              y0 + int(xh * 0.18) - len(hn))

    # 3. below-mark (dot)
    for m in [x for x in rest if x in MARK_BELOW]:
        rest.remove(m)
        dot = M.dot
        if upper:
            dot = scale(dot, int(len(dot[0]) * 1.15), int(len(dot) * 1.15))
        y0, y1, x0, x1 = bbox(out)
        cx = (x0 + x1) // 2 - len(dot[0]) // 2
        dy = min(y1 + 3, H - len(dot))
        paste(out, dot, cx, dy)

    # 4. above-marks, stacked on whatever is already there
    # a mark on the SECOND tier is shrunk - standard practice in Vietnamese
    # type design: it reads better and costs less cell height
    n_above = sum(1 for m in used if m in MARK_ABOVE)
    for m in rest:
        name = MARK_ABOVE.get(m)
        if name is None:
            continue
        mk = M.get(name, upper)
        if n_above:
            mk = scale_to_h(mk, max(6, int(len(mk) * TIER2_SCALE)))
        n_above += 1
        y0, y1, x0, x1 = bbox(out)
        # the gap must scale with the mark: a fixed 3px is fine on advfont (108px)
        # but on sysfont (49px) it leaves the mark visibly detached
        gap = max(1, round(len(mk) * 0.18))
        cx = (x0 + x1) // 2 - len(mk[0]) // 2
        dy = y0 - len(mk) - gap
        if dy < 0:                       # out of room -> squeeze the mark to fit
            nh = max(6, y0 - gap)
            mk = scale_to_h(mk, nh)
            cx = (x0 + x1) // 2 - len(mk[0]) // 2
            dy = max(0, y0 - len(mk) - gap)
        paste(out, mk, cx, dy)

    return adv, out


def make_dstroke(f, M, ch, H):
    """D-ngang: ve thanh ngang de len D / d."""
    upper = ch == '\u0110'
    src = 'D' if upper else 'd'
    gi = f.index(src)
    w, h, rows0 = f.bitmap(gi)
    adv = f.glyphs[gi]['adv']
    out = blank(w + 8, H)                # room for the bar to overhang
    paste(out, rows0, 4 if upper else 0, H - h)
    y0, y1, x0, x1 = bbox(out)
    span = x1 - x0
    by = (y0 + y1) // 2 if upper else y0 + int((y1 - y0) * 0.14)
    # measure the vertical stem on the row to be crossed, then overhang evenly
    cols = [x for x in range(len(out[0])) if any(out[yy][x] for yy in
                                                 range(by, min(by + 4, H)))]
    run = []                             # FIRST vertical stem only (left stem of D)
    for x in cols:
        if run and x > run[-1] + 1:
            break
        run.append(x)
    pad = max(4, span // 9)
    if run:
        bx0, bx1 = run[0] - pad, run[-1] + pad
    elif upper:
        bx0, bx1 = x0 - pad, x0 + int(span * 0.40)
    else:
        bx0, bx1 = x1 - int(span * 0.42), x1 + pad
    bx1 = min(len(out[0]) - 1, bx1)
    th = max(3, (y1 - y0) // 24)
    for yy in range(by, min(by + th, H)):
        for xx in range(max(0, bx0), bx1 + 1):
            out[yy][xx] = 15
    return adv, out


# ---------------------------------------------------------------- serializer

def serialize(f, new_glyphs, extra_top):
    """Rebuild the .ffu, adding extra_top blank rows above every existing glyph."""
    entries = []
    for g in f.glyphs:
        off = f.off_bmp + g['off']
        raw = f.raw[off:off + g['size']]
        pad = (g['w'] // 2) * extra_top
        entries.append([g['adv'], g['h'] + extra_top, b'\x00' * pad + raw])

    ranges = [list(r) for r in f.ranges]

    for ch in sorted(new_glyphs, key=FFU.u8i):
        adv, rows = new_glyphs[ch]
        data = FFU.pack_bitmap(rows)
        gi = f.index(ch)
        if gi is not None:
            entries[gi] = [adv, len(rows), data]
            continue
        t = FFU.u8i(ch)
        ni = len(entries)
        entries.append([adv, len(rows), data])
        for r in ranges:                 # extend an adjacent range where possible
            if r[1] == t and r[2] + (r[1] - r[0]) == ni:
                r[1] = t + 1
                break
        else:
            ranges.append([t, t + 1, ni])
    ranges.sort(key=lambda r: r[0])

    pal = f.raw[0x28:f.off_range]
    off_range = 0x28 + len(pal)
    off_gtab = off_range + len(ranges) * 12
    off_bmp = off_gtab + len(entries) * 8

    gtab, bmp = bytearray(), bytearray()
    for adv, h, data in entries:
        gtab += struct.pack('<BBHI', adv, h, len(data), len(bmp))
        bmp += data

    # 0x0A and 0x0E: low byte = glyph cell height, high byte = 1.
    # The engine sizes its draw buffer from this. Leaving the old value while
    # writing taller glyphs CRASHES the game (e.g. the Special Scenario screen).
    hs = [g['h'] for g in f.glyphs]
    new_h = max(set(hs), key=hs.count) + extra_top
    hfield = (1 << 8) | (new_h & 0xff)
    assert new_h <= 0xff, 'cell height %d exceeds one byte' % new_h

    head = bytearray(0x28)
    struct.pack_into('<8H', head, 0, 0x4655, len(ranges), len(entries),
                     f._r6, f._r8, hfield, f._rC, hfield)
    struct.pack_into('<6I', head, 0x10, off_bmp + len(bmp) - 0x1a,
                     off_range, off_gtab, off_bmp, f._r20, f._r24)
    return bytes(head) + pal + b''.join(struct.pack('<3I', *r) for r in ranges) \
        + bytes(gtab) + bytes(bmp)


# ------------------------------------------------------------------- driver

_VN_UPPER = ('A\u00c0\u00c1\u1ea2\u00c3\u1ea0\u0102\u1eb0\u1eae\u1eb2\u1eb4'
             '\u1eb6\u00c2\u1ea6\u1ea4\u1ea8\u1eaa\u1eac'
             'E\u00c8\u00c9\u1eba\u1ebc\u1eb8\u00ca\u1ec0\u1ebe\u1ec2\u1ec4\u1ec6'
             'I\u00cc\u00cd\u1ec8\u0128\u1eca'
             'O\u00d2\u00d3\u1ece\u00d5\u1ecc\u00d4\u1ed2\u1ed0\u1ed4\u1ed6\u1ed8'
             '\u01a0\u1edc\u1eda\u1ede\u1ee0\u1ee2'
             'U\u00d9\u00da\u1ee6\u0168\u1ee4\u01af\u1eea\u1ee8\u1eec\u1eee\u1ef0'
             'Y\u1ef2\u00dd\u1ef6\u1ef8\u1ef4\u0110')
VN_ALL = [c for ch in _VN_UPPER for c in (ch, ch.lower())]


def generate(src, dst, extra_top=14, verbose=True):
    f = load(src)
    M = Marks(f)
    hs = [g['h'] for g in f.glyphs]
    base_h = max(set(hs), key=hs.count)
    H = base_h + extra_top

    def has_real(ch):
        gi = f.index(ch)
        if gi is None:
            return False
        _w, _h, r = f.bitmap(gi)
        return bbox(r) is not None

    new, made, failed = {}, [], []
    for ch in VN_ALL:
        if has_real(ch):
            continue
        try:
            r = make_dstroke(f, M, ch, H) if ch in '\u0110\u0111' \
                else compose(f, M, ch, H)
        except Exception as e:
            failed.append((ch, repr(e)))
            continue
        if r is None:
            failed.append((ch, 'no stem glyph'))
            continue
        new[ch] = r
        made.append(ch)

    data = serialize(f, new, extra_top)
    with open(dst, 'wb') as fh:
        fh.write(data)

    # tightest glyph: top == 0 means a mark touches the cell ceiling already,
    # so extra_top is still too small
    tight = min(((bbox(r)[0], c) for c, (_a, r) in new.items() if bbox(r)),
                default=(99, ''))
    if verbose:
        import os
        print('%s: height %d -> %d' % (os.path.basename(src), base_h, H))
        print('  created %d glyphs: %s' % (len(made), ''.join(made)))
        if failed:
            print('  FAILED %d: %s' % (len(failed), failed))
        print('  tightest: %r has %d blank rows above' % (tight[1], tight[0]))
        if tight[0] == 0:
            print('  !! WARNING: marks touch the cell ceiling, raise extra_top')
        print('  -> %s (%s byte)' % (dst, format(len(data), ',')))
    return made, failed


if __name__ == '__main__':
    _src, _dst = sys.argv[1], sys.argv[2]
    _n = int(sys.argv[3]) if len(sys.argv) > 3 else 14
    generate(_src, _dst, _n)
