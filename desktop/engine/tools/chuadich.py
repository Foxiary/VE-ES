"""
chuadich.py - the game lines a translation still leaves in English, with where
each one goes in the translators' own sheet.

    python tools/chuadich.py "Shuuen_JP_STORY (6).xlsx" work/virche_vi.xlsx work/chua_dich.xlsx

The first argument is the sheet the translators sent, the second the workbook
`mksheet.py --merge --relink` built from it, the third the file to write.

WHY A SEPARATE LIST
    A line is missing for one of two reasons, and neither shows in the sheet the
    translators work in. English left a slot empty that Japanese fills (see
    `mksheet.story_rows`), or JP 1.0.1 - the script English was made from - has
    a line the sheet's 1.0.0 Japanese does not. Either way no row exists to
    translate, so this writes the line out with the row it belongs after.

WHAT A ROW SAYS
    `chen SAU / TRUOC dong Excel` is the position in the translators' sheet:
    the placed rows either side of the missing line in game order. Where 1.0.1
    reordered a passage the two would contradict each other, so only the one
    before is given and the note says why.

    The Japanese and English are the GAME's, never the sheet's own column,
    and three `Ca khung` columns show the whole message box with the missing
    line marked. The box is what to read: English re-breaks lines, so the
    English of one slot often carries the meaning of the next Japanese line -
    200/5167 reads "could only nod", which is the Japanese of 5168.

    A slot holding only an ideographic space and a `#n` is not a line and is
    left out; 53 of them were listed as missing before that rule.
"""
import bisect, collections, os, sys

import openpyxl
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import relinkjp
from applyvi import ID_RX, cell_str, read_scripts
from linebreak import to_game, to_sheet
from stcm2l import Script
from mksheet import detect_delta, STORY_ROLES
from portjp2us import align
from openpyxl.styles import Alignment, Font, PatternFill

SRC, MERGED, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
merged = openpyxl.load_workbook(MERGED, read_only=True, data_only=True)
src = openpyxl.load_workbook(SRC, read_only=True, data_only=True)
en_raw = dict(read_scripts('STORY.cpk')); jp_raw = dict(read_scripts('work/jp/CONTENTS/STORY.cpk'))
blank = lambda t: not (t or '').replace('#n', '').strip(' \t\u3000\n')

vi_of = {}
for n in merged.sheetnames:
    if n.isdigit():
        for r in merged[n].iter_rows(min_row=2, values_only=True):
            if r[0]: vi_of[(n, str(r[0]).split('___')[1].split('_')[0])] = cell_str(r[2]).strip()

def box(n, e, j, am, roles, eid):
    ins = int(eid.split('___')[0]); off = eid.split('___')[1].split('_')[0]
    if roles.get(e.instructions[ins].opcode) == 'text':
        a = b = ins
        while a > 0 and roles.get(e.instructions[a - 1].opcode) == 'text': a -= 1
        while b + 1 < len(e.instructions) and roles.get(e.instructions[b + 1].opcode) == 'text': b += 1
        cells = [(i, 0) for i in range(a, b + 1)]
    else:
        cells = [(ins, k) for k, bl in enumerate(e.instructions[ins].blocks)
                 if bl.text() is not None and not any(ord(c) < 0x20 for c in bl.text())]
    J, E, V = [], [], []
    for i, k in cells:
        eb = e.instructions[i].blocks[k]; jb = j.instructions[am[i]].blocks
        jt = (jb[k].text() if k < len(jb) else '') or ''; et = eb.text() or ''
        if blank(jt) and blank(et): continue
        mark = '▶ ' if '%X' % eb.data_off == off else '   '
        J.append(mark + to_sheet(jt).strip()); E.append(mark + (to_sheet(et).strip() or '(trong)'))
        V.append(mark + (to_sheet(vi_of.get((n, '%X' % eb.data_off), '')).strip() or '— THIEU —'))
    return '\n'.join(J), '\n'.join(E), '\n'.join(V)

out = []
for name in sorted(n for n in merged.sheetnames if n.isdigit()):
    rows = [list(r) + [None] * 9 for r in merged[name].iter_rows(min_row=2, values_only=True) if r and r[0]]
    missing = [r for r in rows if ID_RX.match(str(r[0]).strip()) and not cell_str(r[2]).strip()]
    if not missing: continue
    e = Script(en_raw[name + '.DAT']); j = Script(jp_raw[name + '.DAT']); am = align(e, j)
    roles = {op + detect_delta(e): r for op, r in STORY_ROLES.items()}
    srows = relinkjp.sheet_rows(src[name])
    excel = [k for k, r in enumerate(src[name].iter_rows(min_row=2, values_only=True), start=2)
             if r and (r[0] or r[1] or (len(r) > 2 and r[2]))]
    landed = sorted((int(eid.split('___')[0]), excel[k], rid) for k, ((rid, _r, _j, _v, _o), eid, _s)
                    in enumerate(relinkjp.relink(e, j, detect_delta(e), srows)) if eid)
    keys = [x[0] for x in landed]
    for r in missing:
        ins = int(str(r[0]).split('___')[0]); p = bisect.bisect_left(keys, ins) - 1
        prev = landed[p] if p >= 0 else None; nxt = landed[p + 1] if p + 1 < len(landed) else None
        note = r[4] or ''
        if prev and nxt and nxt[1] < prev[1]:
            # The game and the sheet run this passage in different orders
            # (1.0.1 moved lines), so "after X, before Y" would contradict
            # itself. Only the line it follows in the game is meaningful.
            nxt = None
            note = (note + ' ' if note else '') + 'bang va game khac thu tu o doan nay - chen ngay sau dong o cot B'
        if r[5] == 'title': note = (note + ' ' if note else '') + 'tieu de chuong - filltitles khong ghep duoc'
        out.append([name, prev[1] if prev else None, nxt[1] if nxt else None, prev[2] if prev else '',
                    str(r[0]), r[5], cell_str(r[3]), cell_str(r[1])] + list(box(name, e, j, am, roles, str(r[0]))) + [note, None])

wb = openpyxl.Workbook(); ws = wb.active; ws.title = 'chua dich'
ws.append(['sheet', 'chen SAU dong Excel', 'va TRUOC dong Excel', 'ID dong truoc (cot A)', 'EN ID', 'kind',
           'JP trong file game', 'EN trong file game', 'Ca khung - JP trong game', 'Ca khung - EN trong game',
           'Ca khung - Tieng Viet hien tai', 'Ghi chu', 'Tieng Viet (dien vao day)'])
for c in ws[1]: c.font = Font(bold=True)
wrap = Alignment(wrap_text=True, vertical='top'); fill = PatternFill('solid', fgColor='E2EFDA')
for o in out:
    ws.append(o[:6] + [to_sheet(to_game(o[6])), to_sheet(to_game(o[7]))] + o[8:])
    for c in ws[ws.max_row]: c.alignment = wrap
    ws.cell(ws.max_row, 13).fill = fill
for col, w in zip('ABCDEFGHIJKLM', (7, 10, 10, 24, 22, 7, 34, 38, 38, 44, 44, 22, 40)): ws.column_dimensions[col].width = w
ws.freeze_panes = 'A2'; ws.auto_filter.ref = 'A1:M%d' % ws.max_row
rd = wb.create_sheet('_README', 0); rd.column_dimensions['A'].width = 100
per = collections.Counter(o[0] for o in out)
for line in [
    'CAC DONG TRONG GAME CHUA CO BAN DICH', '',
    '%d dong. Neu de trong, trong game cac dong nay hien TIENG ANH.' % len(out), '',
    'Cot "JP / EN trong file game" la cau that su o dong do trong game, khong phai cot tieng Nhat',
    'cua bang dich - hai ben co cho khac nhau (xem cau_nhat_lech_10.xlsx).', '',
    'Ba cot "Ca khung" hien ca khung thoai chua dong do, dong thieu danh dau ▶. Ban Anh hay chia',
    'cau khac ban Nhat (vd 200 / 5167: ban Anh dua cau "gat dau" len dong nay, ban Nhat de no o dong',
    'sau), nen doc cot JP cua ca khung de biet dong thieu la cau nao.', '',
    'CACH THEM VAO BANG DICH: chen mot hang giua hai "dong Excel" o cot B/C.',
    '  - Cot A (ID) de trong duoc.',
    '  - Cot tieng Nhat PHAI la cau trong cot "JP trong file game" - tool dung chinh cau nay de biet',
    '    hang thuoc o nao.',
    '  - Cot EN ID khong bat buoc.', '',
    'Theo sheet: ' + ', '.join('%s: %d' % kv for kv in sorted(per.items())),
]: rd.append([line])
wb.save(OUT)
print(len(out), collections.Counter(o[5] for o in out), '->', OUT)
