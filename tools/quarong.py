"""
quarong.py - the translated lines that draw wider than the window they appear
in, with the empty slot each box can be re-broken into.

    python tools/quarong.py work/virche_vi.xlsx work/qua_rong.xlsx
    python tools/quarong.py work/virche_vi.xlsx work/qua_rong.xlsx "Shuuen_JP_STORY (8).xlsx"

The third argument is the sheet the translators work in; given, every row also
carries its line number there.

WHY THESE LINES AND NOT THE ONES `applyvi --report` LISTS
    Both measure the same way. The difference is the ceiling: `applyvi` held
    every line to the backlog's 2430 units, and against that nothing overflows.
    But the story does not draw every box in the dialogue window - a box opens
    with a window routine, and the framed monologue window is narrower. Its
    width was read off a probe build at 2069 units (2175 is where a line
    touches the frame); see `textwidth.WINDOW_CEILING`.

    So these rows are not new mistakes. They were measured against the wrong
    screen, and the line photographed running over the border - 600 /
    4131___48888_text, 2316 units - is one of them.

WHAT A ROW OFFERS
    A box in this window is padded: five slots holding an ideographic space sit
    above the text, and `mksheet.py` does not extract them because they hold no
    text to translate. They are live instructions all the same, so the box can
    be re-broken over one more line than it uses today, and the text simply
    starts a line higher.

    `o dem dung duoc` is the id of the padding slot that becomes that line.
    `Ca khung` shows the box as it stands and as it would read re-broken, slot
    by slot, so the suggestion can be copied straight into the sheet. Nothing
    here edits anything: the split is the translators' call, because where a
    sentence breaks is a translation decision.
"""
import collections
import os
import sys

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import relinkjp                                            # noqa: E402
from applyvi import cell_str, read_scripts                 # noqa: E402
from linebreak import to_game, to_sheet                    # noqa: E402
from mksheet import detect_delta                           # noqa: E402
from reflow import Breaker, boxes_with_window, resolve_font, STOCK_FONT  # noqa: E402
from stcm2l import Script                                  # noqa: E402
from textwidth import Widths, CEILING, ceiling_for, ceilings_source  # noqa: E402

HEAD = ['sheet', 'dong Excel', 'ID', 'o dem dung duoc', 'so o dem con trong',
        'be rong', 'tran cua khung', 'vuot', 'JP trong file game',
        'Tieng Viet hien tai', 'Ca khung - hien tai', 'Ca khung - goi y tach',
        'Ghi chu']
WIDTHS = (7, 10, 22, 22, 9, 8, 8, 7, 34, 40, 46, 46, 26)


def excel_rows(ws):
    """The Excel line number of each row `relinkjp.sheet_rows()` returns.

    sheet_rows() drops genuinely empty rows, so its list index is not a line
    number. This walks the sheet with the same test - an id, or Japanese or
    Vietnamese that survives stripping - so the two lists stay in step. A
    looser test (any non-empty cell) counts a row whose only content is an
    ideographic space, which sheet_rows() skips, and every line number after
    it comes out one too high.
    """
    it = ws.iter_rows(values_only=True)
    head = [str(c).strip().lower() if c else '' for c in next(it, ())]
    c_vi = head.index(relinkjp.HEAD_VI) if relinkjp.HEAD_VI in head else 2

    def cell(r, i):
        return str(r[i]).strip() if i < len(r) and r[i] is not None else ''

    out = []
    for excel_row, r in enumerate(it, start=2):
        if not r:
            continue
        if cell(r, 0) or to_game(cell(r, 1)) or to_game(cell(r, c_vi)):
            out.append(excel_row)
    return out


def src_rows(src_path, en_raw):
    """{(sheet, en id): line number in the translators' sheet}, or {}.

    Re-derived through `relinkjp.relink()`, the same alignment `--relink` uses,
    not read off the sheet's `EN ID` column: that column drifts a slot every
    time it steps over an empty English line (CLAUDE.md), and a translator sent
    to the wrong row edits the wrong line.
    """
    if not src_path:
        return {}
    wb = openpyxl.load_workbook(src_path, read_only=True, data_only=True)
    jp_raw = dict(read_scripts('work/jp/CONTENTS/STORY.cpk'))
    out = {}
    for name in wb.sheetnames:
        if not name.isdigit() or name + '.DAT' not in en_raw:
            continue
        en = Script(en_raw[name + '.DAT'])
        jp = Script(jp_raw[name + '.DAT'])
        delta = detect_delta(en)
        if delta is None:
            continue
        rows = relinkjp.sheet_rows(wb[name])
        lines = excel_rows(wb[name])
        if len(rows) != len(lines):
            print('!! %s: %d hang doc duoc, %d so dong - bo qua cot dong Excel'
                  % (name, len(rows), len(lines)))
            continue
        for k, (_row, eid, _status) in enumerate(
                relinkjp.relink(en, jp, delta, rows)):
            if eid:
                out.setdefault((name, eid), lines[k])
    return out


def regroup(br, have, slots):
    """(lines, extra slots used) for the box re-broken to fit, or (None, 0).

    The same line count is tried FIRST, and often works: the box overflows
    because its text sits unevenly across the lines it already has, not because
    it needs another one. That costs nothing on screen - the text neither moves
    nor shifts up. Only when it genuinely will not fit does this reach for a
    padding slot, and then for as few as possible.
    """
    joined = ' '.join(t for t in have if t)
    for n in range(len(have), len(slots) + 1):
        lines = br.to_lines(joined, n)
        if lines is not None:
            return lines, n - len(have)
    return None, 0


def main():
    src, out_path = sys.argv[1], sys.argv[2]
    en_raw = dict(read_scripts('STORY.cpk'))
    sheet_row = src_rows(sys.argv[3] if len(sys.argv) > 3 else None, en_raw)
    print('dong Excel tim duoc: %s' % format(len(sheet_row), ','))

    font, is_stock = resolve_font(None)
    if is_stock:
        print('!! dang do bang %s - font tieng Anh goc, moi so deu sai' % STOCK_FONT)
    print('font do: %s' % font)
    print(ceilings_source())
    widths = Widths.from_cpk(font)
    breakers = {}

    wb = openpyxl.load_workbook(src, read_only=True, data_only=True)
    vi = {}
    for n in wb.sheetnames:
        if n.isdigit():
            vi[n] = {str(r[0]).strip(): cell_str(r[2]).strip()
                     for r in wb[n].iter_rows(min_row=2, values_only=True)
                     if r and r[0] and len(r) > 2 and r[2]}
    jp = {}
    for n in wb.sheetnames:
        if n.isdigit():
            jp[n] = {str(r[0]).strip(): cell_str(r[3]).strip()
                     for r in wb[n].iter_rows(min_row=2, values_only=True)
                     if r and r[0] and len(r) > 3 and r[3]}

    rows, st = [], collections.Counter()
    for name in sorted(n for n in wb.sheetnames if n.isdigit()):
        data = en_raw.get(name + '.DAT')
        if data is None:
            continue
        script = Script(data)
        delta = detect_delta(script)
        if delta is None:
            continue
        for slots, window in boxes_with_window(script, delta, name,
                                               keep_blank=True):
            limit = ceiling_for(window, CEILING)
            # Unmeasured windows are skipped, and so is anything the backlog
            # already holds - this tool lists only the narrower windows.
            if limit is None or (CEILING is not None and limit >= CEILING):
                continue
            st['khung'] += 1
            filled = [rid for rid in slots if vi[name].get(rid)]
            over = [rid for rid in filled
                    if widths.over(to_game(vi[name][rid]), limit) > 0]
            if not over:
                continue
            st['khung co dong vuot'] += 1
            if limit not in breakers:
                breakers[limit] = Breaker(widths, limit)
            have = [to_game(vi[name][rid]) for rid in filled]
            spare = [rid for rid in slots if rid not in filled]
            lines, extra = regroup(breakers[limit], have, slots)
            # Full ids, not just the offset: this column is what gets copied
            # into column A of the sheet, and a half id addresses nothing.
            now = '\n'.join('%s  %s' % (r, to_sheet(t))
                            for r, t in zip(filled, have))
            if lines is None:
                nxt, note = '', 'khong tach duoc - phai rut ngan cau'
                st['khong tach duoc'] += 1
            else:
                used = (spare + filled)[-len(lines):]
                nxt = '\n'.join('%s  %s' % (r, to_sheet(t))
                                for r, t in zip(used, lines))
                if extra:
                    note = ('ngat lai thanh %d dong (them %d o dem), '
                            'chu len cao hon %d dong'
                            % (len(lines), extra, extra))
                    st['can them o'] += 1
                else:
                    note = 'chi can ngat lai %d dong cho deu - chu khong xe dich' % len(lines)
                    st['ngat lai tai cho'] += 1
            for rid in over:
                text = to_game(vi[name][rid])
                st['dong'] += 1
                rows.append([
                    name, sheet_row.get((name, rid)), rid,
                    spare[-1] if spare else '', len(spare),
                    max(widths.widest(text).values(), default=0), limit,
                    widths.over(text, limit),
                    to_sheet(to_game(jp[name].get(rid, ''))),
                    to_sheet(text), now, nxt, note])

    rows.sort(key=lambda r: -r[7])
    book = openpyxl.Workbook()
    ws = book.active
    ws.title = 'qua rong'
    ws.append(HEAD)
    for c in ws[1]:
        c.font = Font(bold=True)
    wrap = Alignment(wrap_text=True, vertical='top')
    fill = PatternFill('solid', fgColor='E2EFDA')
    for r in rows:
        ws.append(r)
        for c in ws[ws.max_row]:
            c.alignment = wrap
        ws.cell(ws.max_row, 12).fill = fill
    for col, w in zip('ABCDEFGHIJKLM', WIDTHS):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = 'A2'
    ws.auto_filter.ref = 'A1:M%d' % ws.max_row

    rd = book.create_sheet('_README', 0)
    rd.column_dimensions['A'].width = 100
    per = collections.Counter(r[0] for r in rows)
    for line in [
        'CAC DONG VE RONG HON KHUNG DOC THOAI CO VIEN', '',
        '%d dong trong %d khung. Trong game chu chay de len hoa van vien khung'
        % (len(rows), st['khung co dong vuot']),
        '- game khong cat chu, no cu ve tiep ra ngoai.', '',
        'VI SAO TRUOC DAY KHONG BAO: cac tool do moi dong theo khung backlog',
        '(2430 don vi). Nhung man doc thoai co vien hep hon - do tren ban probe',
        'duoc 2069 don vi, 2175 la luc chu cham vien. Nhung dong nay khong phai',
        'moi dich sai, chi la truoc day do nham man hinh.', '',
        'CO BA TRUONG HOP, cot "Ghi chu" noi ro tung dong thuoc loai nao:', '',
        '1. "chi can ngat lai ... cho deu" - khung da du dong, chi la chu dang',
        '   don khong deu. Sua lai chu cac dong trong khung, KHONG them hang.',
        '   Chu khong xe dich chut nao. Day la phan lon.', '',
        '2. "ngat lai thanh N dong (them o dem)" - khung thieu dong that. Loai',
        '   khung nay con 4-5 o de trong (goi la o dem) nam NGAY TREN phan chu;',
        '   do la lenh that, ghi chu vao duoc. Them hang voi ma o do thi chu chi',
        '   nhich LEN mot dong, khong tran ra ngoai.',
        '   Khi them hang: cot A dien ma o, cot nguon (EN) DE TRONG.', '',
        '3. "khong tach duoc - phai rut ngan cau" - khung het o, dich ngan lai.', '',
        'Cot "Ca khung - goi y tach" la ca khung sau khi sua, moi dong ghi kem ma',
        'o cua no, copy thang vao cot A duoc. Day chi la goi y may tinh ngat -',
        'ngat o dau cho xuoi cau la viec cua nguoi dich.', '',
        'Theo sheet: ' + ', '.join('%s: %d' % kv for kv in sorted(per.items())),
    ]:
        rd.append([line])

    book.save(out_path)
    print('khung kiem tra %s | khung co dong vuot %s | dong %s'
          % (format(st['khung'], ','), format(st['khung co dong vuot'], ','),
             format(st['dong'], ',')))
    print('  ngat lai tai cho (chu khong xe dich) %s khung'
          % format(st['ngat lai tai cho'], ','))
    print('  can muon them o dem               %s khung'
          % format(st['can them o'], ','))
    if st['khong tach duoc']:
        print('!! %s khung khong tach duoc, phai rut ngan cau'
              % format(st['khong tach duoc'], ','))
    print('-> %s' % out_path)


if __name__ == '__main__':
    main()
