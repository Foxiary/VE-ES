"""
exportvar.py - the lines applyvi.py refuses whose markup is REALLY broken.

    python tools/exportvar.py work/virche_vi.xlsx work/virche_var.xlsx
    python tools/exportvar.py work/virche_vi.xlsx out.xlsx --sheet 101

The inline commands in the Vietnamese do not match the English block being
overwritten, and the per-line check says so about 861 lines. `applyvi.py`
already forgives most of them - it counts over the message box, not the line -
and refuses 343: 319 `var`, 3 `name`, 18 lines of boxes that do not balance and
3 of boxes missing a translation. Handing a translator all 343 is still handing
them mostly noise, because the box is not the widest unit either. This tool
narrows it to 89 lines, and reading those 89 turns up six real defects.

WHAT THE REFUSALS ACTUALLY ARE
    Measured on work/virche_vi.xlsx, 54 script sheets, 103,382 rows:

    472 boxes        the command only MOVED to the neighbouring line of the
                     SAME message box, because the translator re-broke it.
                     Summed over the box the counts balance exactly. Harmless,
                     and `applyvi.py` writes them.
     18 boxes        a command genuinely gone or invented box-wide - usually
                     `#NAME[1]` replaced by a pronoun, or the reverse. 45 lines.
      3 `name` rows  `#NAME[1] & Salome & Jean` translated as `Ba nguoi`.
    510 var commands balance over the whole command. 307 of the 319 refused
                     `var` lines sit in these; see below.
      8 var commands do not balance. 41 lines.

WHY `var` CANNOT BE FORGIVEN THE WAY A BOX CAN
    A `var` instruction ships SEVERAL VERSIONS of one message box and the engine
    picks one: version A writes the default name `Ceres` out, version B spells
    it `#NAME[1]` for a player who renamed the heroine. They are ALTERNATIVES,
    not consecutive lines - the player sees exactly one of them.

    Read as consecutive lines they look like a box with a repeated first half,
    and that is how they were translated: sheet 101, var 8782 ships

        "Ceres... What happened here...?"       <- version A, a whole sentence
        "#NAME[1]... What happened here...?"    <- version B, a whole sentence

    and came back cut in half, the first slot holding the opening clause and the
    second the rest. Whichever version the engine picks, half the sentence is
    gone. So a `var` line that loses `#NAME[1]` is a real defect, and relaxing
    the check command-wide - which is right for a text box - would wave it
    through.

WHICH `var` COMMANDS ARE EXPORTED
    The eight whose commands do not balance: 2 dropped every one, 3 dropped
    some, 3 gained some. Reading them, five are real - 302/9909 and 404/4280
    still say `Ceres` in the version meant for a renamed heroine, 500/8343 and
    402/11750 drop the name from one version, and 201/6810 writes `#Color[0`
    without its closing bracket - and three only break the line differently
    than English did.

    The 510 that balance are left out on purpose. The count cannot tell a
    command that moved between the lines of ONE version from a version that was
    genuinely mangled, because it cannot see where one version ends and the next
    begins - the block layout that separates them differs per opcode, and one of
    the three opcodes has no separator block at all. They are reported on stdout
    rather than guessed at.

    Every line of a chosen command is exported, not just the offending one: the
    fix is to make each version a whole sentence again, which cannot be done
    without both versions in front of you.

WHAT A ROW IS ADDRESSED BY
    Column A keeps mksheet's row id verbatim, so `applyvi.py` can be pointed
    straight at this workbook, and the sheets are named after the script the way
    mksheet names them. `mksheet.load_merge()` keys a returning sheet on a
    column headed `EN ID` instead and never looks at column A, so that copy is
    appended as the last column - without it `--merge` matches zero rows.
"""
import argparse
import collections
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from applyvi import cell_str, read_scripts, keeps_jp  # noqa: E402
from linebreak import to_game, to_sheet               # noqa: E402
from mksheet import Workbook as SheetWorkbook         # noqa: E402
from mksheet import detect_delta, sheet_name          # noqa: E402
from reflow import boxes_of                           # noqa: E402
from stcm2l import Script                             # noqa: E402

ID_RX = re.compile(r'^(\d+)___([0-9A-Fa-f]+)_(text|name|choice|title|var)$')

# What `applyvi.plan()` compares, and the two halves of it. They fail
# differently: a dropped `#n` merged two lines of one box and the width pass
# says the merged line still fits, while a dropped `#NAME[1]` is a name the
# player never sees. Only the second half decides what is exported.
MARKUP_RX = re.compile(r'#(?:NAME|Color)\[\d+\]|#n')
CMD_RX = re.compile(r'#(?:NAME|Color)\[\d+\]')


# Verdicts on one `var` command; the first three are what gets exported.
VAR_LOST = 'MAT HET LENH'
VAR_PART = 'MAT MOT PHAN LENH'
VAR_EXTRA = 'THUA LENH'
VAR_TAKE = (VAR_LOST, VAR_PART, VAR_EXTRA)

NOTE_WIDTH = 54
EN_ID_COLUMN = [('EN ID', 26)]

# A horizontal rule for the _README. Dashes and not `=`, because openpyxl types
# any cell whose text starts with `=` as a FORMULA: a row of equals signs is
# then written as `<f>=====...</f>`, which is not a formula Excel can parse, and
# Excel opens the whole workbook in repair mode and drops the sheet.
RULE = '-' * 68

Row = collections.namedtuple('Row', 'rid ins kind en vi jp')


def counts(rx, text):
    return collections.Counter(rx.findall(text or ''))


# Every inline command the two shipped builds actually spell, and nothing else.
# `#Ruby` is in here because the JAPANESE build uses it 605 times - furigana,
# `#Ruby[base,reading]` - while the English build uses it not once, so a
# translator who copies one across from the Japanese source has no English row
# to copy the shape from.
WELL_FORMED = re.compile(r'#(?:NAME|Color)\[\d+\]|#PosX\[[^\]]*\]'
                         r'|#Ruby\[[^\],]+,[^\]]+\]|#n')
COMMAND_START = re.compile(r'#[A-Za-z]')

# What a malformed command looks like, most specific first.
MALFORMED = (
    (re.compile(r'#(?:NAME|Color|Ruby|PosX)\[[^\]]*$'),
     'thieu dau ] dong lenh'),
    (re.compile(r'#Ruby\[[^\],]+\]'),
     'lenh #Ruby thieu tham so thu hai - phai la #Ruby[chu nen,chu doc]'),
    (re.compile(r'#(?:NAME|Color)\[\D'),
     'trong ngoac phai la so'),
)


def malformed(text):
    """Why this line's inline commands are not well formed, or '' when they are.

    A check nobody else makes. `MARKUP_RX` only matches a WELL FORMED command,
    so a broken one is invisible to every count in this file and to
    `applyvi.py`: `#Color[0` without its bracket simply does not register as a
    command, and the line sails through and is written into the game. Two lines
    of the shipped translation are like that, and neither was refused.
    """
    if not text or '#' not in text:
        return ''
    for rx, why in MALFORMED:
        m = rx.search(text)
        if m:
            return '%s -> %r' % (why, m.group(0)[:16])
    rest = WELL_FORMED.sub('', text)
    m = COMMAND_START.search(rest)
    return 'lenh khong doc duoc -> %r' % rest[m.start():m.start() + 16] if m else ''


# Why a missing command matters, keyed by the command itself.
BOX_WHY = {
    '#NAME[1]': 'Bo #NAME[1] la mat ten nu chinh do nguoi choi tu dat, tren '
                'man hinh se khong con ten do nua.',
    '#Color[8]': 'Thieu #Color[8] thi doan chu le ra phai doi mau se hien mau '
                 'thuong.',
    '#Color[0]': 'Thieu #Color[0] thi mau KHONG BAO GIO DUOC DONG, chu phia '
                 'sau doi mau cho den het khung thoai.',
    '': 'Ma lenh thieu se lam khung thoai hien sai.',
}


def why_of(bad):
    """The plain sentence for whichever command `diff()` says went missing.

    `diff()` phrases it as `mat 1 #NAME[1]`, so the command is the third word,
    not the second - reading the second answered `1` and every row fell back to
    the generic line.
    """
    parts = (bad or '').split()
    return BOX_WHY.get(parts[2] if len(parts) > 2 else '', BOX_WHY[''])


def note(loi, sua, vi_tri):
    """The `Ghi chu` cell: what is wrong, what to do, where this line sits.

    Three labelled lines rather than one run of tool output. The column used to
    read `lenh var 6810 | MAT MOT PHAN LENH (EN 2, VI 1) | dong 1/6 | dong nay:
    mat 1 #Color[0]`, which names the instruction index, an internal verdict
    slug and two raw counters - true, and unreadable by the person who has to
    act on it. A translator needs the defect in a sentence and the repair in
    another; the instruction index is the last thing they need, so it goes last.
    """
    return 'LOI: %s\nSUA: %s\n(%s)' % (loi, sua, vi_tri)


def diff(en, vi):
    """'mat 1 #NAME[1]; thua 2 #n' - how `vi` fails to match `en`."""
    out = []
    for cmd in sorted(set(en) | set(vi)):
        d = vi[cmd] - en[cmd]
        if d < 0:
            out.append('mat %d %s' % (-d, cmd))
        elif d > 0:
            out.append('thua %d %s' % (d, cmd))
    return '; '.join(out)


def refused(row):
    """True when applyvi.py would drop this row for `markup lech`.

    Its own earlier checks - the block offset, the source text, the title key -
    are not repeated here; a row that fails one of those is refused for that
    reason instead and is a different problem.
    """
    if not row.vi:
        return False
    vi, en = counts(MARKUP_RX, row.vi), counts(MARKUP_RX, row.en)
    if vi == en:
        return False
    # The same exception applyvi.py makes: a line carrying exactly the Japanese
    # line's commands follows its source and is written. See applyvi.keeps_jp().
    return not (row.jp and keeps_jp(vi, en, counts(MARKUP_RX, row.jp)))


def jp_total(rows):
    """Commands the Japanese side carries over `rows`, or None if any is missing."""
    if any(not r.jp for r in rows):
        return None
    return sum((counts(CMD_RX, r.jp) for r in rows), collections.Counter())


# ------------------------------------------------------------------- reading

def read_rows(ws):
    """[Row] for one script worksheet, in sheet order.

    The Japanese column is found by its header rather than assumed at D,
    because `mksheet.py --no-jp` leaves it out and everything after it shifts.
    """
    it = ws.iter_rows(values_only=True)
    head = [cell_str(c).strip().lower() for c in next(it, ())]
    jp_col = head.index('tieng nhat') if 'tieng nhat' in head else -1
    out = []
    for r in it:
        if not r or not r[0]:
            continue
        m = ID_RX.match(cell_str(r[0]).strip())
        if not m:
            continue
        text = [to_game(cell_str(r[k]).strip()) if 0 <= k < len(r) else ''
                for k in (1, 2, jp_col)]
        out.append(Row(m.group(0), int(m.group(1)), m.group(3), *text))
    return out


def box_map(script, delta, sheet, known=None):
    """([box], {row id: index of its box}) for the text slots of every box.

    A box is a maximal run of consecutive `text` instructions - the unit the
    translator re-broke, and the only scope in which a moved command is
    harmless. `reflow.boxes_of()` already knows how to find them.

    `known` is the set of `text` row ids this sheet carries, and the boxes are
    cut down to it exactly as `applyvi.plan()` cuts them down. That has to
    match or the two tools disagree: a slot English left empty is a line of the
    box, so it counts when the sheet has a row for it and must not when it does
    not.
    """
    boxes = boxes_of(script, delta, sheet, keep_blank=known is not None)
    if known is not None:
        boxes = [[rid for rid in box if rid in known] for box in boxes]
        boxes = [box for box in boxes if box]
    where = {rid: bi for bi, rows in enumerate(boxes) for rid in rows}
    return boxes, where


# ---------------------------------------------------------------- classifying

def var_groups(rows):
    """{instruction index: [Row]} - the versions one `var` instruction ships."""
    out = collections.OrderedDict()
    for r in rows:
        if r.kind == 'var':
            out.setdefault(r.ins, []).append(r)
    return out


def var_verdict(group):
    """(verdict, english command count, vietnamese command count) for one command.

    Counted over the whole command, not per line: inside one version a command
    may legitimately sit on a different line in Vietnamese than in English.
    What may not change is how many the whole thing carries.

    EVERY command counts, not `#NAME[1]` alone. Counting only the name called
    201/6810 balanced while it drops one half of a `#Color[8]...#Color[0]`
    pair, which leaves the rest of that version coloured to the end of the box.
    `#n` stays out, as everywhere else here: merging two lines of one version
    drops one and changes nothing a player sees.
    """
    en = sum((counts(CMD_RX, r.en) for r in group), collections.Counter())
    vi = sum((counts(CMD_RX, r.vi) for r in group), collections.Counter())
    en_n, vi_n = sum(en.values()), sum(vi.values())
    if any(not r.vi for r in group):
        return 'chua dich het', en_n, vi_n
    if en == vi or jp_total(group) == vi:
        return 'can bang', en_n, vi_n
    if vi_n == 0:
        return VAR_LOST, en_n, vi_n
    if not en_n or vi_n > en_n:
        return VAR_EXTRA, en_n, vi_n
    return VAR_PART, en_n, vi_n


def named(group):
    """The name a `#NAME[1]` stands in for in the other version, or ''.

    Worth the trouble because `thay "Ceres" bang #NAME[1]` is an instruction
    while `thay ten mac dinh bang #NAME[1]` is a riddle.

    Taken as the capitalised word the versions WITHOUT `#NAME[1]` carry and the
    ones with it do not - the two differ only where the name is, so the
    difference is the name. Reading the first capitalised word instead answered
    `St`, off the front of `"St-Stop...! Brother,` in 302/9909.
    """
    def caps(lines):
        return set(re.findall(r'[A-Z][A-Za-z]{2,}', ' '.join(lines)))
    plain = caps([r.en for r in group if '#NAME[' not in r.en])
    with_name = caps([r.en for r in group if '#NAME[' in r.en])
    only = sorted(plain - with_name)
    return only[0] if len(only) == 1 else ''


VAR_LOI = {
    VAR_LOST: 'Khung nay game luu %d ban thay the nhau, ban dich viet thang '
              'ten nhan vat o CA %d ban. Ban goc danh mot ban cho #NAME[1] - '
              'ten nu chinh do nguoi choi tu dat. Nguoi doi ten se van thay '
              'ten mac dinh tren man hinh.',
    VAR_PART: 'Khung nay game luu %d ban thay the nhau, va ban dich thieu '
              'lenh o mot trong so do (%d lenh ben Anh, %d ben Viet). Ban nao '
              'thieu thi nguoi choi roi vao ban do se mat ten hoac mat doan '
              'chu doi mau.',
    VAR_EXTRA: 'Ban dich them lenh so voi ban goc (%d lenh ben Anh, %d ben '
               'Viet). Neu hai ban dich ra giong het nhau thi game mat kha '
               'nang phan biet nguoi choi co doi ten hay khong.',
}

VAR_SUA = {
    VAR_LOST: 'Moi ban phai la MOT CAU TRON VEN. Giu nguyen ban viet ten '
              'that, roi o ban con lai thay ten %sbang #NAME[1].',
    VAR_PART: 'Doi chieu tung ban voi cot B: ban nao ben Anh co lenh thi ben '
              'Viet cung phai co, dat o dung cho trong cau.',
    VAR_EXTRA: 'Xem lai co that su can them khong. Neu ban goc phan biet hai '
               'ban thi ban dich cung phai phan biet.',
}


def pick_var(rows, st):
    """{row id: note} for every line of every `var` command whose commands moved."""
    out = {}
    for ins, group in var_groups(rows).items():
        verdict, en_n, vi_n = var_verdict(group)
        st['var: ' + verdict] += 1
        if verdict not in VAR_TAKE:
            st['var bo qua (dong)'] += sum(1 for r in group if refused(r))
            continue
        st['var lay'] += 1
        # How many versions the command ships: the same line count repeats once
        # per version, so the whole group divided by the longest repeat.
        n_ban = max(2, len(group) // max(1, len(set(r.en for r in group))))
        name = named(group)
        loi = VAR_LOI[verdict] % ((n_ban, n_ban) if verdict == VAR_LOST
                                  else (n_ban, en_n, vi_n) if verdict == VAR_PART
                                  else (en_n, vi_n))
        sua = VAR_SUA[verdict] % (('"%s" ' % name,) if verdict == VAR_LOST and name
                                  else ('',) if verdict == VAR_LOST else ())
        for k, r in enumerate(group, start=1):
            bad = malformed(r.vi) or diff(counts(MARKUP_RX, r.en),
                                          counts(MARKUP_RX, r.vi))
            where = ('dong %d/%d cua nhom - %s' %
                     (k, len(group),
                      'DONG NAY LECH: ' + bad if bad else 'dong nay khop'))
            out[r.rid] = note(loi, sua, where)
    return out


def pick_text(rows, where, boxes, by_id, st):
    """{row id: note} for every line of every box that lost a real command.

    `#n` is left out of the comparison on purpose. Merging two lines of a box
    into one drops a `#n` and changes nothing the player sees - 431 lines do it
    and the width pass clears all of them - whereas a `#NAME[1]` or half a
    colour pair going missing is a defect however the box is broken.
    """
    out = {}
    done = set()
    for r in rows:
        if r.kind != 'text' or not refused(r):
            continue
        bi = where.get(r.rid)
        if bi is None:
            st['text khong thuoc khung nao'] += 1
            continue
        if bi in done:
            continue
        done.add(bi)
        box = [by_id[rid] for rid in boxes[bi] if rid in by_id]
        en = collections.Counter()
        vi = collections.Counter()
        for b in box:
            en += counts(CMD_RX, b.en)
            vi += counts(CMD_RX, b.vi)
        bad = diff(en, vi)
        if not bad or jp_total(box) == vi:
            st['khung can bang (bo qua)'] += 1
            continue
        st['khung lay'] += 1
        if any(not b.vi for b in box):
            st['khung thieu ban dich'] += 1
        loi = ('Cong ca khung %d dong nay lai thi ban dich %s so voi ban goc. '
               '%s' % (len(box), bad, why_of(bad)))
        sua = ('Doc ca khung roi dat lai lenh cho dung cho trong cau tieng '
               'Viet. Chuyen lenh sang dong ben canh TRONG CUNG KHUNG thi '
               'khong sao - cho nay la thieu hoac thua han.')
        for k, b in enumerate(box, start=1):
            mine = malformed(b.vi) or diff(counts(MARKUP_RX, b.en),
                                           counts(MARKUP_RX, b.vi))
            out[b.rid] = note(loi, sua, 'dong %d/%d cua khung - %s'
                              % (k, len(box),
                                 'DONG NAY LECH: ' + mine if mine
                                 else 'dong nay khop'))
    return out


def pick_single(rows, st):
    """{row id: note} for refused `name` / `choice` / `title` lines.

    These are one string on their own - no box to spread a command across - so a
    mismatch in anything but `#n` is the whole story.
    """
    out = {}
    for r in rows:
        if r.kind in ('text', 'var') or not refused(r):
            continue
        bad = diff(counts(CMD_RX, r.en), counts(CMD_RX, r.vi))
        if not bad:
            st['dong don chi lech #n (bo qua)'] += 1
            continue
        st['dong don lay'] += 1
        loi = ('Dong nay dung mot minh, khong co khung nao de san se lenh, nen '
               'ban dich %s la mat han. %s' % (bad, why_of(bad)))
        sua = ('Dua lenh tro lai cau tieng Viet. Voi kind=name day la TEN '
               'NGUOI NOI hien tren khung thoai, nen bo #NAME[1] la mat ten '
               'nguoi choi da dat.')
        out[r.rid] = note(loi, sua, 'dong le, kind=%s' % r.kind)
    return out


def pick_malformed(rows, st):
    """{row id: note} for a line whose Vietnamese spells a command wrong.

    These are NOT among the refusals - that is the point of exporting them.
    `applyvi.py` counts commands it can recognise, and a command written wrong
    is not one, so the line balances, passes every check and is written into the
    game. Nothing else in the toolchain looks for them.
    """
    out = {}
    for r in rows:
        why = malformed(r.vi)
        if not why:
            continue
        st['ma lenh viet sai'] += 1
        out[r.rid] = note(
            'Ma lenh trong cau tieng Viet VIET SAI: %s. Game khong nhan ra no '
            'la lenh nen se in thang ra man hinh nhu chu binh thuong, va tac '
            'dung cua lenh thi mat. Dong nay KHONG bi tu choi - no da duoc ghi '
            'vao game roi.' % why,
            'Viet lai cho dung. Doi chieu cot B (ban Anh) va cot tieng Nhat de '
            'lay dung dang lenh.',
            'loi cu phap, khong lien quan den khung hay lenh var')
    return out


# -------------------------------------------------------------------- output

class Workbook(SheetWorkbook):
    """mksheet's workbook, with the note column filled and an `EN ID` column.

    Both additions are the reason this sheet exists, and both are done by
    overriding `add()` rather than by changing mksheet, whose column order the
    rest of the toolchain reads by position.

    `mksheet.Workbook.add()` writes None into `Ghi chu` - the tool that builds a
    fresh sheet has nothing to say per row - while here the note is the payload,
    naming the box or the var command a line belongs to and how it broke.
    `mksheet.load_merge()` keys a returning sheet on a column headed `EN ID`,
    scanning from column B and never looking at column A, so a sheet without
    that copy merges zero rows.
    """

    def __init__(self, with_jp):
        super().__init__(with_jp, False)
        self.columns = [(label, NOTE_WIDTH if label == 'Ghi chu' else width)
                        for label, width in self.columns] + EN_ID_COLUMN

    def add(self, name, rows):
        """One worksheet; `rows` yields (id, source, japanese, kind, vi, note)."""
        ws = self.wb.create_sheet(name)
        for i, (_label, width) in enumerate(self.columns):
            ws.column_dimensions[chr(ord('A') + i)].width = width
        ws.freeze_panes = 'B2'
        head = []
        for label, _w in self.columns:
            c = self._cell(ws, value=label)
            c.font = self.head_font
            head.append(c)
        ws.append(head)
        n = 0
        for rid, src, jp, kind, vi, note in rows:
            # Byte counts are the game's, taken before #n becomes a newline.
            cells = [rid, self._wrapped(ws, to_sheet(src)),
                     self._wrapped(ws, to_sheet(vi) or None)]
            if self.with_jp:
                cells.append(self._wrapped(ws, to_sheet(jp) or None))
            cells += [self._wrapped(ws, note or None), kind,
                      len(src.encode('utf-8')), rid]
            ws.append(cells)
            n += 1
        if n:
            last = chr(ord('A') + len(self.columns) - 1)
            ws.auto_filter.ref = 'A1:%s%d' % (last, n + 1)
        return n


def readme(st):
    return [
        'CAC DONG applyvi.py TU CHOI VI "markup lech" MA HONG THAT',
        '',
        '%d dong bi tu choi, nhung phan lon KHONG hong: phep kiem dem ma lenh'
        % st['bi tu choi'],
        'theo TUNG DONG, con nguoi dich ngat cau theo CA KHUNG THOAI. File nay',
        'chi giu lai cho hong that: %d lenh var va %d khung / dong le.'
        % (st['var lay'], st['khung lay'] + st['dong don lay']),
        '',
        RULE,
        '1. LENH "var" - MOT KHUNG LUU HAI BAN, KHONG PHAI HAI DONG NOI TIEP',
        RULE,
        '',
        'Day la cho de hieu nham nhat, va gan nhu ca %d lenh var trong file nay'
        % st['var lay'],
        'deu hong vi cung mot ly do.',
        '',
        'Game luu san NHIEU BAN cua cung mot khung thoai roi chon mot ban de',
        'hien ra:',
        '  - mot ban viet thang ten mac dinh "Ceres"',
        '  - mot ban dung #NAME[1], cho nguoi choi tu dat ten nu chinh',
        'Hai ban do THAY THE NHAU. Nguoi choi chi thay DUNG MOT ban, nen moi',
        'ban phai la mot cau tron ven. Chung khong phai hai dong noi tiep nhau.',
        '',
        'Vi du that - sheet 101, lenh var 8782. Ban goc tieng Anh:',
        '  dong 1   "Ceres... What happened here...?"       <- ban A, tron ven',
        '  dong 2   "#NAME[1]... What happened here...?"    <- ban B, tron ven',
        '',
        'Ban dich hien tai lai doc hai dong nay nhu mot khung hai dong, nen cat',
        'doi mot cau:',
        '  dong 1   "Ceres... rốt cuộc chuyện gì,            <- nua dau',
        '  dong 2   đã xảy ra ở đây vậy...?"                 <- nua sau',
        '',
        'Ket qua trong game: ai giu ten mac dinh chi thay nua dau cau, ai doi',
        'ten chi thay nua sau va mat luon cai ten.',
        '',
        'CACH SUA: dich ban A thanh mot cau tron ven, roi chep y nguyen sang',
        'ban B va chi thay ten mac dinh bang #NAME[1]:',
        '  dong 1   "Ceres... rốt cuộc chuyện gì đã xảy ra ở đây vậy...?"',
        '  dong 2   "#NAME[1]... rốt cuộc chuyện gì đã xảy ra ở đây vậy...?"',
        '',
        'Mot ban dai hon mot dong thi chiem nhieu dong lien tiep. Doc cot B se',
        'thay ro: noi dung cua ca lenh lap lai hai lan, chi khac o cho co ten.',
        '',
        'Ca lenh deu duoc xuat ra, khong chi dong hong, vi khong nhin thay ca',
        'hai ban thi khong sua duoc.',
        '',
        RULE,
        '2. DONG kind=text / kind=name - MAT LENH TRONG PHAM VI CA KHUNG',
        RULE,
        '',
        'Voi kind=text, ma lenh chuyen tu dong nay sang dong ben canh TRONG',
        'CUNG MOT KHUNG la binh thuong - nguoi dich ngat lai cau, khong mat gi.',
        'Nhung dong do khong co trong file nay.',
        '',
        'File nay chi giu nhung khung ma cong ca khung lai van THIEU hoac THUA',
        'ma lenh. Thuong gap:',
        '  - bo #NAME[1] va thay bang mot dai tu ("co ay", "em")',
        '  - bo mot ve cua cap #Color[8] ... #Color[0]',
        '',
        'Ca khung deu duoc xuat ra chu khong chi dong hong, de sua theo ngu',
        'canh.',
        '',
        RULE,
        '3. MA LENH VIET SAI CU PHAP - LOI DA NAM TRONG GAME ROI',
        RULE,
        '',
        'Loai nay KHONG bi applyvi.py tu choi, va do moi la van de: phep kiem',
        'chi dem nhung ma lenh no DOC DUOC, nen mot lenh viet sai khong duoc',
        'tinh la lenh, dong van "can bang", qua het moi phep kiem va da duoc',
        'ghi vao game.',
        '',
        'Hai dong trong ban dich hien tai:',
        '',
        '  201 / 6810   #Color[0   -> thieu dau ]',
        '               Mau khong bao gio duoc dong, chu phia sau doi mau cho',
        '               den het khung, va chuoi "#Color[0" in thang ra man hinh.',
        '',
        '  103 / 4914   #Ruby[Khu Nghien Cuu]   -> thieu tham so thu hai',
        '               #Ruby la lenh ghi chu doc (furigana), dang dung la',
        '               #Ruby[chu nen,chu doc]. Ban Nhat dung 605 lan, ban Anh',
        '               KHONG dung lan nao - nen khong co dong tieng Anh nao de',
        '               chep dang lenh. Doi chieu cot tieng Nhat:',
        '                 JP  #Ruby[研究区,セルネヴォル]',
        '                 VI  #Ruby[Khu Nghien Cuu]      <- thieu ve sau',
        '',
        RULE,
        'CACH DUNG',
        RULE,
        '',
        'Chi sua cot C (Tieng Viet). Khong sua cot A va cot "EN ID": do la dia',
        'chi cua dong trong file game.',
        '',
        'Cot "Ghi chu" moi dong viet thanh ba phan:',
        '  LOI:  sai cai gi, va tren man hinh no hong ra sao',
        '  SUA:  phai lam gi',
        '  (...)  dong nay la dong thu may cua khung / cua nhom, va rieng dong',
        '         nay co lech hay khong',
        '',
        'Giu dung so ma lenh so voi cot B, dem THEO TUNG DONG:',
        '  #NAME[1]            ten nu chinh do nguoi choi dat',
        '  #Color[8] #Color[0] mo / dong doan chu doi mau, luon di theo cap',
        '  #Ruby[nen,doc]      ghi chu doc, BAT BUOC co dau phay va hai ve',
        '  #n                  xuong dong (trong o Excel la mot lan xuong hang)',
        '',
        'Ngoac vuong phai dong. Thieu mot dau ] la ca lenh hong, va khong phep',
        'kiem nao bat duoc truoc khi vao game.',
        '',
        'Sheet o day dat ten theo so kich ban giong bang dich chinh, nen ghi',
        'thang vao game duoc:',
        '  python tools/applyvi.py <file nay> STORY.cpk work/story-vi',
        '',
        'Cot "EN ID" la ban sao cot A. mksheet.py --merge tim khoa o cot co',
        'tieu de "EN ID" va khong nhin cot A, thieu no thi merge duoc 0 dong.',
        '',
        'Luu y khi merge: "mksheet.py --merge" dung lai TOAN BO workbook tu mot',
        'bang dich, nen dung merge rieng file nay - lam vay se mat ban dich cua',
        'moi dong khong co o day. Chep phan da sua ve bang dich chinh roi merge,',
        'hoac chay applyvi.py thang tren file nay. Merge file nay cung se bao',
        '"cau Nhat lech" o moi dong, vi mksheet doc cot B nhu cot tieng Nhat.',
    ]


# ---------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(
        description='export the story lines whose markup is really broken')
    ap.add_argument('xlsx', help='the workbook from mksheet.py --merge')
    ap.add_argument('out', help='spreadsheet to write')
    ap.add_argument('--story', default='STORY.cpk',
                    help='STORY.cpk or a directory of .DAT files, for the '
                         'message box boundaries')
    ap.add_argument('--sheet', action='append', help='limit to these worksheets')
    a = ap.parse_args()

    import openpyxl
    wb = openpyxl.load_workbook(a.xlsx, read_only=True, data_only=True)
    scripts = dict(read_scripts(a.story))

    # Everything is classified before a cell is written: the README quotes the
    # tallies, and a write-only workbook streams its sheets in creation order,
    # so _README has to be the first one created.
    st = collections.Counter()
    sheets, with_jp = [], False
    for name in wb.sheetnames:
        if not name.isdigit() or (a.sheet and name not in a.sheet):
            continue
        data = scripts.get('%s.DAT' % name)
        if data is None:
            st['sheet khong co .DAT'] += 1
            continue
        rows = read_rows(wb[name])
        with_jp = with_jp or any(r.jp for r in rows)
        st['dong doc duoc'] += len(rows)
        st['bi tu choi'] += sum(1 for r in rows if refused(r))
        by_id = {r.rid: r for r in rows}

        notes = {}
        notes.update(pick_var(rows, st))
        notes.update(pick_single(rows, st))
        notes.update(pick_malformed(rows, st))
        script = Script(data)
        delta = detect_delta(script)
        if delta is None:
            st['sheet khong doc duoc opcode'] += 1
        else:
            known = {r.rid for r in rows if r.kind == 'text'}
            boxes, where = box_map(script, delta, name, known)
            notes.update(pick_text(rows, where, boxes, by_id, st))
        if notes:
            sheets.append((sheet_name(name),
                           [(r.rid, r.en, r.jp, r.kind, r.vi, notes[r.rid])
                            for r in rows if r.rid in notes]))

    if not st['dong doc duoc']:
        print('!! khong doc duoc sheet kich ban nao trong %s' % a.xlsx)
        return 1

    out = Workbook(with_jp)
    out.add_readme(readme(st))
    for name, body in sheets:
        st['dong xuat ra'] += out.add(name, body)
    out.save(a.out)

    print('%-34s %s' % ('dong doc duoc', format(st['dong doc duoc'], ',')))
    print('%-34s %s  (truoc khi khung go toi)'
          % ('phep kiem tung dong tu choi', format(st['bi tu choi'], ',')))
    print()
    print('lenh var:')
    for key in sorted(k for k in st if k.startswith('var: ')):
        print('   %-31s %s' % (key[5:], format(st[key], ',')))
    print('   %-31s %s' % ('-> lay ra', format(st['var lay'], ',')))
    print('   %-31s %s  (lenh can bang tren toan lenh)'
          % ('dong tu choi KHONG lay', format(st['var bo qua (dong)'], ',')))
    print()
    print('%-34s %s  (KHONG bi tu choi - da vao game)'
          % ('ma lenh viet sai cu phap', format(st['ma lenh viet sai'], ',')))
    print()
    print('khung text / dong le:')
    print('   %-31s %s' % ('khung lech -> lay ra', format(st['khung lay'], ',')))
    print('   %-31s %s' % ('khung can bang (bo qua)',
                           format(st['khung can bang (bo qua)'], ',')))
    print('   %-31s %s' % ('dong le lech -> lay ra', format(st['dong don lay'], ',')))
    print('   %-31s %s' % ('dong le chi lech #n (bo qua)',
                           format(st['dong don chi lech #n (bo qua)'], ',')))
    for key in ('khung thieu ban dich', 'text khong thuoc khung nao',
                'sheet khong doc duoc opcode', 'sheet khong co .DAT'):
        if st[key]:
            print('   !! %-28s %s' % (key, format(st[key], ',')))
    print()
    print('%d sheet, %s dong -> %s'
          % (len(sheets), format(st['dong xuat ra'], ','), a.out))
    return 0


if __name__ == '__main__':
    sys.exit(main())
