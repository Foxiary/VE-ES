"""
exportvar.py - the lines applyvi.py refuses whose markup is REALLY broken.

    python tools/exportvar.py work/virche_vi.xlsx work/virche_var.xlsx
    python tools/exportvar.py work/virche_vi.xlsx out.xlsx --sheet 101

`applyvi.py` refuses 851 story lines for `markup lech`: the inline commands in
the Vietnamese do not match the English block being overwritten. Handing a
translator all 851 would be handing them mostly noise. The check counts
commands PER LINE, and a line is not the unit anyone translated in - so most of
those 851 are the check being too literal, and only about an eighth are text a
player would actually see go wrong. This tool writes out that eighth.

WHAT THE 851 ACTUALLY ARE
    Measured on work/virche_vi.xlsx, 54 script sheets:

    496 `text` lines  the command only MOVED to the neighbouring line of the
                      SAME message box, because the translator re-broke the box.
                      Summed over the box the counts balance exactly - 459 boxes
                      hold these 496 lines. Harmless.
    427 lines         the English spells a `#n` inside the line and the
                      translation merged the two halves into one, and that is
                      the ONLY thing that differs. 431 `#n` dropped in all, 0
                      added, and the width pass clears every merged line.
     37 `text` +
      3 `name` lines  a command genuinely gone or invented, box-wide - usually
                      `#NAME[1]` replaced by a pronoun, or one half of a
                      `#Color[8]...#Color[0]` pair dropped. One per box, in 37
                      boxes.
    315 `var` lines   see below. Not harmless, and not relaxable either.

    (The first two overlap: a line can both merge a `#n` and move a `#Color`,
    which is why they add up past 851.)

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
    the check box-wide - which is right for `text` - would wave it through.

WHICH `var` COMMANDS ARE EXPORTED
    523 var commands carry translatable text; 425 spell `#NAME[1]` on the
    English side. Of those, 341 keep the same number of them, 4 are not fully
    translated, and 80 do not - 59 dropped every one, 20 dropped some, 1 gained
    some. Those 80 are what goes out.

    The remaining 235 refused `var` lines sit in commands whose `#NAME[1]` total
    does balance: the command moved between the lines of one version, the same
    way it does inside a text box. The count cannot tell those apart from a
    version that was genuinely mangled, because it cannot see where one version
    ends and the next begins - the block layout that separates them differs per
    opcode, and one of the three opcodes has no separator block at all. They are
    reported on stdout and deliberately left out rather than guessed at.

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
from applyvi import cell_str, read_scripts            # noqa: E402
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
NAME_RX = re.compile(r'#NAME\[\d+\]')

# Verdicts on one `var` command; the first three are what gets exported.
VAR_LOST = 'MAT HET #NAME[1]'
VAR_PART = 'MAT MOT PHAN #NAME[1]'
VAR_EXTRA = 'THUA #NAME[1]'
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
    return bool(row.vi) and counts(MARKUP_RX, row.vi) != counts(MARKUP_RX, row.en)


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


def box_map(script, delta, sheet):
    """([box], {row id: index of its box}) for the text slots of every box.

    A box is a maximal run of consecutive `text` instructions - the unit the
    translator re-broke, and the only scope in which a moved command is
    harmless. `reflow.boxes_of()` already knows how to find them.
    """
    boxes = boxes_of(script, delta, sheet)
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
    """(verdict, english #NAME count, vietnamese #NAME count) for one command.

    Counted over the whole command, not per line: inside one version the name
    may legitimately sit on a different line in Vietnamese than in English.
    What may not change is how many versions carry a name at all.
    """
    en_n = sum(len(NAME_RX.findall(r.en)) for r in group)
    vi_n = sum(len(NAME_RX.findall(r.vi)) for r in group)
    if not en_n:
        return 'EN khong co #NAME[1]', en_n, vi_n
    if any(not r.vi for r in group):
        return 'chua dich het', en_n, vi_n
    if vi_n == en_n:
        return 'can bang', en_n, vi_n
    if vi_n == 0:
        return VAR_LOST, en_n, vi_n
    return (VAR_PART if vi_n < en_n else VAR_EXTRA), en_n, vi_n


def pick_var(rows, st):
    """{row id: note} for every line of every `var` command that lost a name."""
    out = {}
    for ins, group in var_groups(rows).items():
        verdict, en_n, vi_n = var_verdict(group)
        st['var: ' + verdict] += 1
        if verdict not in VAR_TAKE:
            st['var bo qua (dong)'] += sum(1 for r in group if refused(r))
            continue
        st['var lay'] += 1
        head = 'lenh var %d | %s (EN %d, VI %d)' % (ins, verdict, en_n, vi_n)
        for k, r in enumerate(group, start=1):
            bad = diff(counts(MARKUP_RX, r.en), counts(MARKUP_RX, r.vi))
            out[r.rid] = '%s | dong %d/%d | %s' % (
                head, k, len(group), ('dong nay: ' + bad) if bad else 'dong nay khop')
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
        if not bad:
            st['khung can bang (bo qua)'] += 1
            continue
        st['khung lay'] += 1
        if any(not b.vi for b in box):
            st['khung thieu ban dich'] += 1
        head = 'khung %d | KHUNG LECH: %s' % (box[0].ins, bad)
        for k, b in enumerate(box, start=1):
            mine = diff(counts(MARKUP_RX, b.en), counts(MARKUP_RX, b.vi))
            out[b.rid] = '%s | dong %d/%d | %s' % (
                head, k, len(box), ('dong nay: ' + mine) if mine else 'dong nay khop')
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
        out[r.rid] = 'dong don kind=%s | LECH: %s' % (r.kind, bad)
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
        'Cot "Ghi chu" ghi lenh var so may va dong nay la dong thu may cua lenh.',
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
        'canh. Cot "Ghi chu" ghi ca khung thieu gi va dong nao dang lech.',
        '',
        RULE,
        'CACH DUNG',
        RULE,
        '',
        'Chi sua cot C (Tieng Viet). Khong sua cot A va cot "EN ID": do la dia',
        'chi cua dong trong file game.',
        '',
        'Giu dung so ma lenh so voi cot B, dem THEO TUNG DONG:',
        '  #NAME[1]            ten nu chinh do nguoi choi dat',
        '  #Color[8] #Color[0] mo / dong doan chu doi mau, luon di theo cap',
        '  #n                  xuong dong (trong o Excel la mot lan xuong hang)',
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
        script = Script(data)
        delta = detect_delta(script)
        if delta is None:
            st['sheet khong doc duoc opcode'] += 1
        else:
            boxes, where = box_map(script, delta, name)
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
    print('%-34s %s' % ('applyvi tu choi (markup lech)', format(st['bi tu choi'], ',')))
    print()
    print('lenh var:')
    for key in sorted(k for k in st if k.startswith('var: ')):
        print('   %-31s %s' % (key[5:], format(st[key], ',')))
    print('   %-31s %s' % ('-> lay ra', format(st['var lay'], ',')))
    print('   %-31s %s  (lenh can bang #NAME[1])'
          % ('dong tu choi KHONG lay', format(st['var bo qua (dong)'], ',')))
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
