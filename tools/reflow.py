"""
reflow.py - re-break a translation across a message box instead of line by line.

    python reflow.py work/virche_vi.xlsx work/virche_vi_reflow.xlsx
    python reflow.py in.xlsx out.xlsx --story STORY.cpk --font SYSTEM.cpk

WHY A BOX AND NOT A LINE
    The Vietnamese was translated against the Japanese build, and the English
    build does not break its text in the same places: where Japanese spends
    three lines, English often spends two. A line-for-line mapping therefore
    drifts inside a box, and everything after the first merged line lands one
    slot late for the rest of that box. Three symptoms in the merged workbook
    are all that one fault:

        cau Nhat lech  3,057   the Vietnamese sits on the wrong English line
        markup lech      852   a #Color[8]...#Color[0] pair split across the
                               boundary leaves each half unbalanced

    A third symptom, `qua rong`, turned out not to exist: it was measured with
    the stock fonts against the widest stock line, and once both were corrected
    exactly 1 line of 72,576 was over the box. Re-breaking does not rescue the
    translation from overflowing, because it was not overflowing.

    A box is the unit that survives the difference: both builds say the same
    thing in the same box, only divided up differently. So the Vietnamese of a
    whole box is joined back into one paragraph and re-broken to fit the lines
    the English build actually has.

WHAT A BOX IS
    A maximal run of consecutive `text` instructions. Measured on the English
    build: 40,479 boxes, ending on opcode 500 in 39,712 of them. Most slots in a
    run hold an ideographic space used as vertical padding, which `mksheet.py`
    does not extract; those are left exactly as they are, so the text keeps its
    vertical position in the box. Only the slots that carry real text are
    rewritten, and a box has at most three of them (16,043 boxes have one,
    16,401 two, 7,314 three).

    The line count is therefore fixed and cannot be negotiated: each line is its
    own data block, and a block that is not written keeps its English. Every
    slot is filled - with an ideographic space if the text runs out early.

WHEN IT WILL NOT FIT
    Against the measured backlog width every box fits - 0 of 39,758 - where the
    first pass, breaking to a ceiling 22% too narrow, stranded 2,157 of them.
    The guard stays anyway: a box that cannot be broken into the lines it has is
    left completely untouched, with the old line-by-line text still in place,
    and counted. Dropping the overflow instead would lose sentences, which is
    worse than leaving a box for a human.

ONLY `text` ROWS
    `var` boxes ship several versions of the same lines in one instruction and
    would need their own treatment; `name`, `choice`, `title` and `ui` are
    single strings with no line breaking to redo. All are passed through
    unchanged.

THE WIDTH IT BREAKS TO
    `textwidth.py` sums glyph advances out of the .ffu table, and a line is
    accepted only if it fits under the ceiling in all four selectable fonts.
    Both halves of that were wrong in the first pass and are worth stating:

    The FONT has to be the one the build ships. This tool used to read the
    project's stock `SYSTEM.cpk`, the English original, while the game draws
    with the regenerated Vietnamese fonts in `dist/SYSTEM.cpk`. They are not
    close: one probe string measures 2651 units in the stock advfont1 and 2981
    in the shipped one, and the stock metrics even put advfont3 above advfont1
    when on screen it is plainly below. So the default is the built font, and
    falling back to the stock file says so loudly rather than quietly
    measuring the wrong thing.

    The CEILING is the backlog, not the widest stock line. The widest line the
    stock game happens to draw (~1896) is only a lower bound on the box, and
    breaking to it splits lines that render perfectly well. A probe build put
    lines of known width on screen instead: narration holds ~3200, the message
    box ~2990, and the backlog ~2430. The backlog is the one to design against,
    because it replays every line of dialogue - a line that fits the message box
    and overflows the backlog is still broken.
"""
import argparse
import collections
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cpk import CPK                                # noqa: E402
from stcm2l import Script                          # noqa: E402
from mksheet import detect_delta, STORY_ROLES, cell_text   # noqa: E402
from textwidth import Widths, CEILING, DEFAULT_NAME        # noqa: E402
from linebreak import to_sheet, to_game                    # noqa: E402

# Where the fonts the build ships are looked for, in order. `build.py` writes
# the first one; the stock SYSTEM.cpk in the project root is the English
# original and measuring it gives numbers that do not match the screen.
FONT_CANDIDATES = ('dist/SYSTEM.cpk', os.path.join('work', 'out', 'SYSTEM.cpk'))
STOCK_FONT = 'SYSTEM.cpk'

COLOR_RX = re.compile(r'#Color\[(\d+)\]')
TOKEN_RX = re.compile(r'#Color\[\d+\]|#NAME\[\d+\]|\s+|[^\s#]+|#')
SPACER = '　'               # what the game itself puts in an empty slot
COLOR_OFF = '0'                 # #Color[0] restores the default colour


# ------------------------------------------------------------------- atoms

def atoms(text):
    """Split into pieces that may not be broken apart: markup, words, spaces."""
    out = []
    for tok in TOKEN_RX.findall(text or ''):
        if tok.startswith('#Color['):
            out.append(('color', COLOR_RX.match(tok).group(1)))
        elif tok.startswith('#NAME['):
            out.append(('name', tok))
        elif tok.isspace():
            out.append(('space', ' '))
        else:
            out.append(('word', tok))
    return out


def render(items):
    """Atoms back to a string."""
    out = []
    for kind, v in items:
        out.append('#Color[%s]' % v if kind == 'color' else v)
    return ''.join(out)


def visible(items):
    """What the engine draws, for measuring: colours vanish, names expand."""
    out = []
    for kind, v in items:
        if kind == 'color':
            continue
        out.append(DEFAULT_NAME if kind == 'name' else v)
    return ''.join(out)


# ------------------------------------------------------------------ wrapping

class Breaker:
    """Breaks a paragraph into lines that fit the narrowest box on screen.

    `ceiling` is one number in advance units, not one per font: all four
    dialogue fonts draw at the same cell height, so a unit is the same width on
    screen in each. What differs is how many units a sentence costs, which is
    why every line is checked against the font it is widest in.
    """

    def __init__(self, widths, ceiling):
        self.w = widths
        self.ceiling = ceiling
        self._cache = {}

    def fits(self, items):
        s = visible(items).strip()
        if not s:
            return True
        key = s
        got = self._cache.get(key)
        if got is None:
            got = all(self.w.width(f, s) <= self.ceiling for f in self.w.fonts)
            self._cache[key] = got
        return got

    def greedy(self, items):
        """Longest lines that still fit. None if a single word cannot fit."""
        lines, cur = [], []
        for a in items:
            if a[0] == 'space' and not cur:
                continue                      # no leading space on a new line
            trial = cur + [a]
            if self.fits(trial):
                cur = trial
                continue
            if a[0] == 'space':
                lines.append(cur)
                cur = []
                continue
            if not [x for x in cur if x[0] != 'color']:
                return None                   # one atom already too wide
            # step back over a trailing space before breaking
            while cur and cur[-1][0] == 'space':
                cur.pop()
            lines.append(cur)
            cur = [a]
        if cur:
            lines.append(cur)
        return [l for l in lines if l]

    def measure(self, items):
        """Width of a line under the font it is widest in, as a share of ceiling."""
        s = visible(items).strip()
        if not s:
            return 0.0
        return max(self.w.width(f, s) / float(self.ceiling) for f in self.w.fonts)

    def balanced(self, items, n):
        """Split into exactly `n` lines, as even in length as they can be.

        Filling each line to the brim instead - the obvious greedy pass - packs
        the first line and strands whatever is left, which on this translation
        produced 5,950 one-word lines against the 4,191 the sheet already had.
        Choosing the breaks to keep the lines the same length costs a short
        search and reads the way the stock game does.
        """
        stops = [k for k, a in enumerate(items) if a[0] == 'space']
        target = self.measure(items) / n
        best = {}

        def solve(start, left):
            """(cost, [break positions]) for items[start:] cut into `left` lines."""
            key = (start, left)
            if key in best:
                return best[key]
            chunk = items[start:]
            if left == 1:
                got = self.measure(chunk)
                out = ((got - target) ** 2, []) if got <= 1.0 else None
                best[key] = out
                return out
            out = None
            for k in stops:
                if k <= start:
                    continue
                head = items[start:k]
                if not [x for x in head if x[0] == 'word']:
                    continue
                got = self.measure(head)
                if got > 1.0:
                    break                     # and every longer head is worse
                rest = solve(k + 1, left - 1)
                if rest is None:
                    continue
                cost = (got - target) ** 2 + rest[0]
                if out is None or cost < out[0]:
                    out = (cost, [k] + rest[1])
            best[key] = out
            return out

        got = solve(0, n)
        if got is None:
            return None
        lines, prev = [], 0
        for k in got[1]:
            lines.append(items[prev:k])
            prev = k + 1
        lines.append(items[prev:])
        return lines

    def to_lines(self, text, n):
        """Exactly `n` line strings, or None when the text needs more than `n`."""
        items = atoms(text)
        if self.greedy(items) is None:
            return None                       # a single word wider than the box
        lines = None
        for k in range(n, 0, -1):             # as many slots as the text can use
            lines = self.balanced(items, k)
            if lines is not None:
                break
        if lines is None:
            return None
        out = [render(l).strip() for l in balance_colour(lines)]
        out += [SPACER] * (n - len(out))       # fill any slot the text left over
        return out


def balance_colour(lines):
    """Close an open colour at the end of a line and reopen it on the next.

    A `#Color[8]...#Color[0]` pair that straddles a line break leaves both lines
    with an odd number of colour commands, which is what `applyvi.py` refuses as
    a markup mismatch. Closing and reopening keeps every line balanced and draws
    the same.
    """
    out, open_colour = [], None
    for line in lines:
        cur = list(line)
        if open_colour is not None:
            cur = [('color', open_colour)] + cur
        state = open_colour
        for kind, v in cur:
            if kind == 'color':
                state = None if v == COLOR_OFF else v
        if state is not None:
            cur = cur + [('color', COLOR_OFF)]
        out.append(cur)
        open_colour = state
    return out


# --------------------------------------------------------------------- boxes

def boxes_of(script, delta, sheet):
    """[[row id, ...]] - the real text slots of each message box, in order."""
    roles = {op + delta: role for op, role in STORY_ROLES.items()}
    ins = script.instructions
    out, i = [], 0
    while i < len(ins):
        if roles.get(ins[i].opcode) != 'text':
            i += 1
            continue
        j, rows = i, []
        while j < len(ins) and roles.get(ins[j].opcode) == 'text':
            if ins[j].blocks:
                b = ins[j].blocks[0]
                if cell_text(b, True) is not None:
                    rows.append('%d___%X_text' % (j, b.data_off))
            j += 1
        if rows:
            out.append(rows)
        i = j
    return out


def letters(s):
    """Characters that carry meaning, for checking nothing was lost."""
    return re.sub(r'#Color\[\d+\]|#NAME\[\d+\]|\s|　', '', s or '')


def resolve_font(explicit):
    """(path to the fonts to measure, whether it is the wrong one).

    The stock SYSTEM.cpk is a last resort, not a default: its metrics are the
    English originals and differ from the shipped Vietnamese fonts by more than
    10%, which is enough to break every line-breaking decision made from them.
    """
    if explicit:
        return explicit, False
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            return path, False
    return STOCK_FONT, True


def main():
    ap = argparse.ArgumentParser(
        description='re-break a translation box by box instead of line by line')
    ap.add_argument('src', help='workbook from mksheet.py --merge')
    ap.add_argument('out')
    ap.add_argument('--story', default='STORY.cpk')
    ap.add_argument('--font', default=None,
                    help='SYSTEM.cpk whose fonts the build ships; defaults to '
                         'dist/SYSTEM.cpk, NOT the stock English one')
    ap.add_argument('--ceiling', type=int, default=CEILING,
                    help='box width in advance units (default: the backlog, the '
                         'narrowest screen a line has to fit)')
    ap.add_argument('--report', help='write boxes that did not fit to this CSV')
    a = ap.parse_args()

    import openpyxl
    font, is_stock = resolve_font(a.font)
    if is_stock:
        print('!! ' + '=' * 68)
        print('!! KHONG THAY FONT DA DUNG (dist/SYSTEM.cpk), dang do bang %s'
              % STOCK_FONT)
        print('!! Day la font tieng Anh goc, metric lech hon 10%% so voi font')
        print('!! se ship - moi quyet dinh ngat dong tu no deu sai.')
        print('!! ' + '=' * 68)
    ceiling = a.ceiling
    print('font do: %s' % font)
    print('tran: %d don vi (backlog - khung hep nhat)' % ceiling)
    widths = Widths.from_cpk(font)
    br = Breaker(widths, ceiling)

    wb = openpyxl.load_workbook(a.src)
    cu = CPK(a.story)

    st = collections.Counter()
    changed = {}                     # (sheet, row id) -> new Vietnamese
    misfit = []
    for _i, name, row in cu.files():
        if not name.endswith('.DAT'):
            continue
        sheet = os.path.splitext(os.path.basename(name))[0]
        if sheet not in wb.sheetnames:
            continue
        script = Script(cu.read(row))
        delta = detect_delta(script)
        if delta is None:
            continue
        vi = {}
        for r in wb[sheet].iter_rows(min_row=2, values_only=True):
            if r and r[0] and len(r) > 2 and r[2]:
                # Re-breaking works in the game's spelling: the breaker
                # counts #n, and what it emits goes back through to_sheet.
                vi[str(r[0]).strip()] = to_game(str(r[2]).strip())
        for rows in boxes_of(script, delta, sheet):
            st['khung'] += 1
            have = [vi.get(rid, '') for rid in rows]
            if not all(have):
                st['khung thieu ban dich'] += 1
                continue
            joined = ' '.join(have)
            lines = br.to_lines(joined, len(rows))
            if lines is None:
                st['khung khong du cho'] += 1
                misfit.append((sheet, rows[0], len(rows), joined))
                continue
            if letters(''.join(lines)) != letters(joined):
                st['khung lech ky tu'] += 1     # never expected; reported not written
                continue
            st['khung da ghep lai'] += 1
            for rid, line in zip(rows, lines):
                changed[(sheet, rid)] = line

    # rewrite only the target column of the rows a box actually re-broke
    n_rows = 0
    for sheet in wb.sheetnames:
        if not sheet.isdigit():
            continue
        ws = wb[sheet]
        for r in ws.iter_rows(min_row=2):
            rid = str(r[0].value).strip() if r[0].value else ''
            key = (sheet, rid)
            if key not in changed:
                continue
            new = changed[key]
            if to_game(str(r[2].value or '').strip()) != new:
                n_rows += 1
            r[2].value = to_sheet(new)
            if len(r) > 7:
                r[7].value = len(new.encode('utf-8'))
            if len(r) > 8:
                over = widths.over(new, ceiling)
                r[8].value = ('qua rong +%dpx' % over) if over > 0 else None
    wb.save(a.out)

    print('khung: %s | ghep lai %s | thieu ban dich %s | khong du cho %s'
          % (format(st['khung'], ','), format(st['khung da ghep lai'], ','),
             format(st['khung thieu ban dich'], ','),
             format(st['khung khong du cho'], ',')))
    if st['khung lech ky tu']:
        print('!! %s khung bi lech ky tu, da bo qua' % format(st['khung lech ky tu'], ','))
    print('dong da doi: %s' % format(n_rows, ','))
    if a.report and misfit:
        import csv
        with open(a.report, 'w', newline='', encoding='utf-8-sig') as fh:
            w = csv.writer(fh)
            w.writerow(['sheet', 'id', 'so_dong', 'ban_dich'])
            w.writerows(misfit)
        print('khung khong du cho -> %s (%s khung)' % (a.report, format(len(misfit), ',')))
    print('-> %s' % a.out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
