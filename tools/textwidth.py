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

ONE CEILING IS NOT ENOUGH: THE SCRIPT PICKS THE WINDOW
    The backlog is the narrowest screen a line of DIALOGUE appears on, but the
    story does not draw every box in the dialogue window. Each box opens with a
    `global_call == 1` instruction whose second field is the address of a window
    routine - no parameters, no data block, just a mode switch - and the mode
    STICKS, so a box calling none keeps what the last one set. Four of them
    carry the whole game:

        74780    37,750 boxes   the message box, with or without a name panel
        72660       709 boxes   the framed monologue screen
        212744      783 boxes   two narrower windows, not yet measured
        209872      431 boxes

    `72660` appears before 88.4% of boxes padded with four or more blank slots
    and before 0.0% of unpadded ones, which is what first gave it away.

    Its width was then read off a probe build the same way the three above
    were. Nineteen ruler lines labelled with their own advance width were
    written into the three `72660` boxes that open the prologue, and their ends
    measured on the screenshots:

        mep phai = 379.9 + 0.5583 * width          (1080p, +-0.5px over 8 lines)

    The text is left-aligned at x=384 and the frame's inner gold line is at
    x=1594 - so 2175 units is where a line touches the border, and 2069 is
    where it keeps the 59px margin it has on the left. NOTHING IS CLIPPED: the
    engine draws straight over the frame art, so these are design limits, not
    limits the engine enforces. Two checks agree: the widest Japanese line in
    this window (1908) lands 149px clear of the border, and the Vietnamese line
    photographed running over the ornament (2316) lands at x=1673, past both
    the inner line and the outer bar at 1619.

    That probe also measured the scale for this window at 0.5583 px per unit,
    not the 0.588 recorded in CLAUDE.md - which was read off the Glossary. The
    two screens really do scale differently; the older number is not wrong.

WHAT COUNTS AS ONE LINE
    `#n` is a line break, so a block holding one splits into two drawn lines and
    each is measured on its own. `#Color[k]` draws nothing and is removed.
    `#NAME[1]` expands to a name the player types, which has no fixed width, so
    it is measured as the default heroine name.

    `#Ruby[base,reading]` is furigana: the base sits on the line and the reading
    is set small above it, so only the base is measured. Counting the command
    as literal text flagged 14 lines of the translation as overflowing the
    backlog, by up to 356 units, and not one does - they clear it by 412 to 853
    measured on the base, and still by 109 or more with the reading laid inline
    at full size beside it, which is the worst the engine could do with it. The
    English build never uses `#Ruby`; the Japanese one does, 605 times, and the
    English executable carries the same `Ruby[` token in the same 20-token set
    of inline commands, so the parser knows it.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ffu                                         # noqa: E402
from cpk import CPK                                # noqa: E402

COLOR_RX = re.compile(r'#Color\[\d+\]')
NAME_RX = re.compile(r'#NAME\[\d+\]')
RUBY_RX = re.compile(r'#Ruby\[([^\],]*),[^\]]*\]')
DEFAULT_NAME = 'Ceres'          # what #NAME[1] shows until the player renames
ADV_FONTS = ('advfont1.ffu', 'advfont2.ffu', 'advfont3.ffu', 'advfont4.ffu')

# The window routine each message box opens with. See "ONE CEILING IS NOT
# ENOUGH" in the header: these are call ADDRESSES, shared across the main
# game's files and written in the same numbering as `mksheet.STORY_ROLES`, so
# a file whose table sits at a delta has to subtract it before looking up here.
WINDOW_DIALOGUE = 74780         # the message box - the great majority of boxes
WINDOW_FRAMED = 72660           # the framed monologue screen
WINDOW_NARROW_A = 212744        # two narrower windows, not yet probed
WINDOW_NARROW_B = 209872
WINDOW_OPS = (WINDOW_DIALOGUE, WINDOW_FRAMED, WINDOW_NARROW_A, WINDOW_NARROW_B)

# Box widths in advance units come from windows.json in the project folder - the
# working directory these tools run in - written by the desktop app's "Measure
# text boxes" page from a screenshot. Every game measures its own, Virche
# Evermore included (its numbers are in tools/README.md). Each `ceiling` is the
# furthest a line may reach on that screen, as clicked on the screenshot, so any
# margin is already in it. A screen nobody measured has no ceiling: the width
# checks say so and skip it rather than borrow another game's number.
#
# The backlog is the one to design against: it replays every line of dialogue,
# so a line that fits the message box but not the backlog is still broken.
WINDOWS_FILE = 'windows.json'


def measured_windows(path=WINDOWS_FILE):
    """{screen: ceiling} from windows.json, or {} when there is none or it is unreadable."""
    try:
        with open(path, encoding='utf-8') as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    windows = data.get('windows') if isinstance(data, dict) else None
    out = {}
    for screen, entry in (windows if isinstance(windows, dict) else {}).items():
        ceiling = entry.get('ceiling') if isinstance(entry, dict) else None
        if isinstance(ceiling, (int, float)) and not isinstance(ceiling, bool) and ceiling > 0:
            out[screen] = int(round(ceiling))
    return out


# Read before ceiling_for() is defined: its default is bound then.
MEASURED = measured_windows()
NARRATION_CEILING = MEASURED.get('narration')
DIALOGUE_CEILING = MEASURED.get('dialogue')
BACKLOG_CEILING = MEASURED.get('backlog')
FRAMED_CEILING = MEASURED.get('framed')
CEILING = BACKLOG_CEILING

# Only the windows that have been measured go in. Any other window falls
# through to the backlog.
WINDOW_CEILING = {window: ceiling for window, ceiling in
                  ((WINDOW_FRAMED, FRAMED_CEILING), (WINDOW_DIALOGUE, DIALOGUE_CEILING))
                  if ceiling is not None}

UNMEASURED = ('chua do khung chu (%s) - bo qua kiem tra be rong; do bang man '
              '"Do khung chu" cua app hoac truyen --ceiling' % WINDOWS_FILE)


def ceilings_source():
    """One line saying where the box widths come from, for the tools to print."""
    if not MEASURED:
        return 'kich thuoc khung: ' + UNMEASURED
    return 'kich thuoc khung: %s (%s)' % (
        WINDOWS_FILE, ', '.join('%s %d' % item for item in sorted(MEASURED.items())))


def ceiling_for(window, default=CEILING):
    """How wide a line may draw in `window`, in advance units, or None if unmeasured.

    Never wider than `default`: a dialogue line is replayed in the backlog
    whatever window it was spoken in, so the backlog still binds. A window
    narrower than the backlog - the framed one is - binds instead.
    """
    known = [c for c in (WINDOW_CEILING.get(window), default) if c is not None]
    return min(known) if known else None


def display_lines(text):
    """The separate lines a block actually draws, with markup resolved away."""
    t = COLOR_RX.sub('', NAME_RX.sub(DEFAULT_NAME, text or ''))
    t = RUBY_RX.sub(lambda m: m.group(1), t)
    return t.split('#n')


def shown(text, kind=None):
    """The part of a row that actually reaches the screen.

    A chapter title is stored as `<japanese key>@<display text>` and only the
    half after the `@` is drawn - the key is what the flowchart looks the scene
    up by. Measuring the whole cell made 26 composed titles look like they
    overflowed the backlog box when not one of them does: the Japanese key was
    being counted as if it were on screen.
    """
    if kind == 'title' and '@' in (text or ''):
        return text.split('@', 1)[1]
    return text or ''


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
        if ceiling is None:
            return 0                # no measured box to overflow
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
