"""
textwidth.py - how wide a script line actually draws, in pixels.

    python textwidth.py SYSTEM.cpk STORY.cpk      # measure the stock ceiling

WHY NOT COUNT BYTES
    The text box overflows on WIDTH, and bytes are a poor stand-in for it.
    Vietnamese spends two bytes on every accented letter but draws it as one
    glyph of ordinary width, so the byte count runs ahead of the real size; a
    capital-heavy English line does the opposite. Measured against the shipped
    translation the two disagree badly - 1,359 lines are over 84 bytes while
    7,478 are wider than anything the stock game ever draws, and a line of
    exactly 84 bytes was found 26% wider than the widest stock line.

    So the limit is read off the font: every glyph's advance is in the .ffu
    glyph table, and a line's width is the sum of the advances.

MEASURE WITH THE FONT THAT SHIPS, NOT THE STOCK ONE
    The build replaces SYSTEM.cpk with one carrying regenerated Vietnamese
    fonts, and those have different metrics from the stock English ones. Measure
    the wrong file and every number is wrong: the stock fonts make advfont3 come
    out WIDER than advfont1 (3068 against 2998) for a string that on screen is
    plainly narrower in advfont3, because with the shipped fonts it is 3032
    against 3198. Pass the SYSTEM.cpk that will actually be installed.

WHAT THE CEILING IS
    Not the widest line the stock game draws - that is only a lower bound on the
    box, and using it as a limit flags lines that render perfectly well. A probe
    build put lines of known width on screen and read the limit off directly:

        narration   ~3200   full width, no name panel
        dialogue    ~2990   the message box, name panel on the left
        backlog     ~2430   the history screen - the narrowest, and binding,
                            because every line of dialogue is shown there too

    All four fonts draw at the same cell height, so one ceiling in advance units
    applies to all of them; what differs is how many units a given sentence
    costs in each. A line is safe when it fits under the ceiling in ALL four,
    since the player chooses the font in Options.

WHAT COUNTS AS ONE LINE
    `#n` is a line break, so a block holding one splits into two drawn lines and
    each is measured on its own. `#Color[k]` draws nothing and is removed.
    `#NAME[1]` expands to a name the player types, which has no fixed width, so
    it is measured as the default heroine name.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ffu                                         # noqa: E402
from cpk import CPK                                # noqa: E402

COLOR_RX = re.compile(r'#Color\[\d+\]')
NAME_RX = re.compile(r'#NAME\[\d+\]')
DEFAULT_NAME = 'Ceres'          # what #NAME[1] shows until the player renames
ADV_FONTS = ('advfont1.ffu', 'advfont2.ffu', 'advfont3.ffu', 'advfont4.ffu')

# Box widths in advance units, read off a probe build (see the header). The
# backlog is the one to design against: it replays every line of dialogue, so a
# line that fits the message box but not the backlog is still broken.
NARRATION_CEILING = 3200
DIALOGUE_CEILING = 2990
BACKLOG_CEILING = 2430
CEILING = BACKLOG_CEILING


def display_lines(text):
    """The separate lines a block actually draws, with markup resolved away."""
    t = COLOR_RX.sub('', NAME_RX.sub(DEFAULT_NAME, text or ''))
    return t.split('#n')


class Widths:
    """Line widths under each of the four selectable dialogue fonts."""

    def __init__(self, fonts):
        self.fonts = fonts          # {name: FFU}

    @classmethod
    def from_cpk(cls, path, names=ADV_FONTS):
        c = CPK(path)
        out = {}
        for _i, name, row in c.files():
            base = os.path.basename(name)
            if base in names:
                out[base] = ffu.FFU(c.read(row))
        if not out:
            raise ValueError('no dialogue font in %s' % path)
        return cls(out)

    def width(self, font, s):
        f = self.fonts[font]
        total = 0
        for ch in s:
            i = f.index(ch)
            if i is not None:
                total += f.glyphs[i]['adv']
        return total

    def widest(self, text):
        """{font: width of the widest line this block draws}."""
        lines = display_lines(text)
        return {name: max((self.width(name, s) for s in lines), default=0)
                for name in self.fonts}

    def ceiling(self, texts):
        """{font: the widest line the given text ever draws} - the box width."""
        out = {name: 0 for name in self.fonts}
        for t in texts:
            for name, w in self.widest(t).items():
                if w > out[name]:
                    out[name] = w
        return out

    def over(self, text, ceiling=CEILING):
        """How far past `ceiling` the worst font draws this, or 0 when it fits.

        `ceiling` is a single number, not one per font: every dialogue font has
        the same cell height, so a unit is the same width on screen in all of
        them. What differs is how many units a sentence costs - which is exactly
        what taking the worst font accounts for.
        """
        return max((w - ceiling for w in self.widest(text).values()), default=0)


def stock_texts(story_path):
    """Every dialogue line of the stock build, for measuring the ceiling."""
    from stcm2l import Script
    from mksheet import detect_delta, story_rows
    c = CPK(story_path)
    out = []
    for _i, name, row in c.files():
        if not name.endswith('.DAT'):
            continue
        s = Script(c.read(row))
        delta = detect_delta(s)
        if delta is None:
            continue
        for _rid, t, role, _coord, _cap in story_rows(s, delta):
            if role in ('text', 'var'):
                out.append(t)
    return out


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    w = Widths.from_cpk(sys.argv[1])
    texts = stock_texts(sys.argv[2])
    ceil = w.ceiling(texts)
    print('do tren %s dong goc:' % format(len(texts), ','))
    for name in sorted(ceil):
        print('   %-14s rong nhat %d px' % (name, ceil[name]))
    return 0


if __name__ == '__main__':
    sys.exit(main())
