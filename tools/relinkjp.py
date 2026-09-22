"""
relinkjp.py - rebuild the `EN ID` column of a Japanese-anchored translation
sheet by aligning it against both builds.

    python relinkjp.py "Shuuen_JP_STORY (8).xlsx"
    python relinkjp.py sheet.xlsx --report work/relink.csv
    python mksheet.py --merge sheet.xlsx --relink --out work/virche_vi.xlsx

THE TWO BUILDS ARE THE SAME SCRIPT
    The English and Japanese scripts were compiled from one source and never
    diverged: 50 of the 54 story files hold exactly the same instructions in
    the same order, and the other four differ by one to three - 302 and 402 by
    one, 605 by two, 601 by three, all on the Japanese side. So instruction N
    of one build is instruction N of the other, and `portjp2us.align()` closes
    the gap on the four that shift.

    That settles a question the sheet raises on its own: the Japanese build
    splits a message box into more lines than the English one, so a
    JP-anchored translation has lines the English sheet has nowhere to put.
    Nothing has to be created for them. The slots are already there.

A BLANK SLOT IS A SLOT, NOT A MISSING ONE
    Where English needed fewer lines than Japanese, the localiser did not
    delete the instruction - they emptied its text block. Counted over the 54
    story files:

        text instructions        EN 82,685     JP 82,692
        of those, holding text   EN 70,787     JP 77,655

    The 5,989 in between are live instructions whose block holds an empty
    string, and every one of them sits in a message box that already draws
    text - 5,935 boxes, not one of which is blank throughout. Filling one adds
    a line to a box that is already on screen; it never makes an empty box
    appear.

    `mksheet.cell_text()` drops those blocks ("blank line used to pad a message
    box"), which is why they carry no id to address and why the translation
    looks like it has 7,000 lines too many.

WHY THE SHIPPED COLUMN DRIFTS
    The `EN ID` column of the incoming sheet was zipped line to line over the
    English rows that DO hold text, so every blank slot it steps over shifts
    the rest of the run by one until something resynchronises it. In 100.DAT
    that reads:

        JP row  順に思い描き始めた。   -> (none)      correct: 4252, a blank slot
        JP row  ……一輪目。             -> 4263        correct: 4263
        JP row  私の人生において...    -> 4269        correct: 4269

    where the sheet gave the first line no id at all and pushed the two after
    it one slot along. Measured over the whole workbook: 95,019 rows carry an id
    this tool agrees with, 557 carry one it does not, and 10,354 carry none -
    7,190 of those last with a translation in them that no tool could place.
    7,243 translated lines in all land on a slot English had left empty.

HOW THE ROWS ARE RE-ADDRESSED
    Not by the sheet's own id column: its offsets resolve against the Japanese
    build for 43% of rows and not at all for the rest, which is what a sheet
    cut from a different dump of that build looks like. Aligned by content
    instead, `difflib` over the sheet's Japanese against the Japanese build's
    own blocks, and the resulting instruction index carried straight across to
    English. That places 105,853 of 105,962 rows, and `between()` hands another
    24 back their own id where the rows either side vouch for it. The 85 left
    over are reported rather than guessed at; 27 of them hold a translation.

    Two details decide whether that alignment is clean or hopeless. The
    comparison key goes through `mksheet.normalise_jp()`, which drops Japanese
    punctuation outright rather than matching it, because the sheet's trip
    through CSV turned `――` into `...` and dropped the 【...】 brackets. And the
    Japanese sequence is built to list exactly what such a sheet lists: `var`
    blocks filtered the way `mksheet` filters them, blank `text` blocks KEPT
    since the sheet carries those too, and chapter titles left out because it
    carries none - 80,729 `text` rows, 22,774 `name`, 2,261 `var` blocks, 144
    `choice`, and not one title.

    Leaving the titles in places 28 more rows and every one of them is wrong:
    with no title row to match, what lands on a title slot is a line of
    dialogue, which is how the shipped column came to address 109 chapter
    titles with `...`. Titles are filled from `dbFlowchart` instead, by
    `filltitles.py`.
"""
import argparse
import collections
import csv
import difflib
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stcm2l import Script                          # noqa: E402
from portjp2us import align                        # noqa: E402
from linebreak import to_game                      # noqa: E402
from mksheet import (STORY_ROLES, TEXT_OP, SINGLE_BLOCK, cell_text,   # noqa: E402
                     detect_delta, normalise_jp, read_sources)

# The sheet's own anchor: `26___4AAF0_text`, `359___50110_text10` for one block
# of a `var`, `0.001_346028` for a row its tool could not address. Only the role
# is wanted here; the offset is not usable (see HOW THE ROWS ARE RE-ADDRESSED).
ROW_ID_RX = re.compile(r'^[\d.]+_+[0-9A-F]*_?([a-z]+)\d*$')
EN_ID_RX = re.compile(r'^(\d+)___([0-9A-F]+)_(\w+)$')

# The statuses that mean the row came out with an address on it.
PLACED = ('ok', 'lech', 'moi', 'giu theo bang')

ROLES = set(STORY_ROLES.values())
HEAD_EN_ID = 'en id'
HEAD_VI = 'vietnamese'


def fold(role, text):
    """The key two lines are compared on: role, then Japanese stripped bare.

    `normalise_jp()` drops punctuation outright, which is what makes this work
    at all: the sheet's Japanese lost its 【...】 brackets and had its dashes
    turned into dots on the way through CSV, so a key that kept either would
    miss the opening line of all 54 files.
    """
    return role + '\x00' + normalise_jp(text)


def jp_sequence(script, delta):
    """[(ins index, block index, role, text)] - what a JP-anchored sheet lists.

    Titles are left out and `var` blocks are filtered the way `mksheet` filters
    them, because that is what the incoming sheet holds. Blank `text` blocks are
    kept: the sheet lists those as well, and dropping them would put the
    alignment back exactly where the shipped id column already is.
    """
    roles = {op + delta: role for op, role in STORY_ROLES.items()}
    out = []
    for i, ins in enumerate(script.instructions):
        role = roles.get(ins.opcode)
        if role is None or role == 'title':
            continue
        if role in SINGLE_BLOCK:
            # `text() is None` is a number or a control word, not a line; the
            # sheet does not list those either.
            if ins.blocks and ins.blocks[0].text() is not None:
                out.append((i, 0, role, ins.blocks[0].text()))
            continue
        for blk_i, b in enumerate(ins.blocks):
            t = cell_text(b, allow_short=False)
            if t is not None:
                out.append((i, blk_i, role, t))
    return out


def en_slots(script, delta):
    """{(ins index, block index): (role, block)} for every addressable block."""
    roles = {op + delta: role for op, role in STORY_ROLES.items()}
    out = {}
    for i, ins in enumerate(script.instructions):
        role = roles.get(ins.opcode)
        if role is None:
            continue
        blocks = ins.blocks[:1] if role in SINGLE_BLOCK else ins.blocks
        for blk_i, b in enumerate(blocks):
            out[(i, blk_i)] = (role, b)
    return out


def jp_delta_of(en, jp, en_delta, amap):
    """The Japanese build's opcode offset, or None.

    Found the way `mksheet.jp_story_map` finds it - by where the English text
    instructions land - because a content test would look for lowercase ASCII
    and find none in Japanese.
    """
    landed = collections.Counter()
    for i, ins in enumerate(en.instructions):
        if ins.opcode == TEXT_OP + en_delta and i in amap:
            landed[jp.instructions[amap[i]].opcode] += 1
    if not landed:
        return None
    return landed.most_common(1)[0][0] - TEXT_OP


def pair_rows(seq, rows):
    """{row index: sequence index} - the sheet aligned to the Japanese build.

    difflib's equal runs, plus the `replace` runs that swap the same number of
    lines on both sides: those are lines the sheet's Japanese no longer matches
    verbatim - 血の匂い for 血の臭い, a stray ellipsis - sitting between two
    runs that do match, so their position is not in doubt. A run whose two
    sides are different lengths is left alone and reported.
    """
    a = [fold(role, text) for _i, _b, role, text in seq]
    b = [fold(role, text) for _rid, role, text, _vi, _en in rows]
    out = {}
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(
            None, a, b, autojunk=False).get_opcodes():
        if tag == 'equal' or (tag == 'replace' and i2 - i1 == j2 - j1):
            for k in range(i2 - i1):
                out[j1 + k] = i1 + k
    return out


def between(en, delta, out):
    """Give an unplaced row back its own EN ID when the rows around it agree.

    The alignment leaves behind the runs whose two sides are different lengths,
    and 51 of those rows hold a translation. An id the sheet already carries can
    be handed back to one of them safely when it names a block of the right role
    AND its instruction sits strictly between the ids the alignment gave the
    nearest placed row either side - a drifted id cannot pass that, because the
    drift is exactly what moves a row past its neighbours.

    24 rows come back this way. The other 27 stay unplaced and are reported: 19
    never carried an id at all, and 8 carry one that lands outside its
    neighbours, which is the drift itself.
    """
    roles = {op + delta: role for op, role in STORY_ROLES.items()}
    placed = [int(eid.split('___')[0]) if eid else None for _r, eid, _s in out]
    for k, (row, eid, status) in enumerate(out):
        if eid is not None or not row[3]:
            continue
        m = EN_ID_RX.match(row[4] or '')
        if not m:
            continue
        i, off = int(m.group(1)), int(m.group(2), 16)
        if i >= len(en.instructions):
            continue
        ins = en.instructions[i]
        if roles.get(ins.opcode) != m.group(3):
            continue
        if not any(b.data_off == off for b in ins.blocks):
            continue
        lo = next((p for p in reversed(placed[:k]) if p is not None), -1)
        hi = next((p for p in placed[k + 1:] if p is not None),
                  len(en.instructions))
        if lo < i < hi:
            out[k] = (row, row[4], 'giu theo bang')
    return out


def relink(en, jp, en_delta, rows):
    """[(row, new en id, status)] for one script file, in the sheet's order.

    `rows` is the sheet's own rows as `sheet_rows()` reads them. Status is
    `ok` / `lech` / `moi` when the alignment placed the row - against what the
    sheet already said - `giu theo bang` when `between()` handed its own id
    back, and the reason when it was not placed at all.
    """
    amap = align(en, jp)                       # {en index: jp index}
    jp_delta = jp_delta_of(en, jp, en_delta, amap)
    if jp_delta is None:
        return [(r, None, 'khong doc duoc bang opcode Nhat') for r in rows]

    jp2en = {v: k for k, v in amap.items()}
    seq = jp_sequence(jp, jp_delta)
    slots = en_slots(en, en_delta)
    pairs = pair_rows(seq, rows)

    out = []
    for k, row in enumerate(rows):
        if k not in pairs:
            out.append((row, None, 'khong khop duoc vi tri'))
            continue
        ins_i, blk_i, role, _text = seq[pairs[k]]
        en_i = jp2en.get(ins_i)
        if en_i is None:
            out.append((row, None, 'ban Anh khong co lenh tuong ung'))
            continue
        slot = slots.get((en_i, blk_i))
        if slot is None or slot[0] != role:
            out.append((row, None, 'o ben Anh khac loai'))
            continue
        eid = '%d___%X_%s' % (en_i, slot[1].data_off, role)
        old = row[4]
        status = 'moi' if not old else ('ok' if old == eid else 'lech')
        out.append((row, eid, status))
    return between(en, en_delta, out)


# ------------------------------------------------------------------ the sheet

def sheet_rows(ws):
    """[(row id, role, japanese, vietnamese, en id)] for one worksheet.

    Column A is the sheet's own Japanese anchor, B the Japanese, C the
    Vietnamese; the English id is found by its header and falls back to column
    E. Line breaks come back in the game's spelling, as everywhere else that
    reads a sheet.
    """
    it = ws.iter_rows(values_only=True)
    head = [str(c).strip().lower() if c else '' for c in next(it, ())]
    c_vi = head.index(HEAD_VI) if HEAD_VI in head else 2
    c_en = head.index(HEAD_EN_ID) if HEAD_EN_ID in head else 4

    def cell(r, i):
        return str(r[i]).strip() if i < len(r) and r[i] is not None else ''

    out = []
    for r in it:
        if not r or not r[0]:
            continue
        rid = str(r[0]).strip()
        m = ROW_ID_RX.match(rid)
        role = m.group(1) if m and m.group(1) in ROLES else 'text'
        out.append((rid, role, to_game(cell(r, 1)),
                    to_game(cell(r, c_vi)), cell(r, c_en)))
    return out


def read_workbook(path):
    """{worksheet: [row]} for the numbered script sheets of a translation."""
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    return {n: sheet_rows(wb[n]) for n in wb.sheetnames if n.isdigit()}


def read_scripts(path):
    """{sheet name: Script} from a .cpk or a directory of .DAT files."""
    out = {}
    for base, data in read_sources(path, ('.DAT',)):
        name = os.path.splitext(base)[0]
        if name.isdigit():
            out[name] = data
    return out


def tables(sheets, en_path, jp_path, on_file=None):
    """({sheet: {en id: (vietnamese, japanese)}}, tally, [unplaced rows]).

    The first return value is the shape `mksheet.load_merge()` produces, so a
    relinked sheet drops into the merge in its place.
    """
    en_raw, jp_raw = read_scripts(en_path), read_scripts(jp_path)
    out, st, loose = {}, collections.Counter(), []
    for name in sorted(sheets):
        rows = sheets[name]
        st['dong'] += len(rows)
        if name not in en_raw or name not in jp_raw:
            st['khong co file'] += len(rows)
            continue
        en = Script(en_raw[name])
        delta = detect_delta(en)
        if delta is None:
            st['khong doc duoc bang opcode Anh'] += len(rows)
            continue
        result = relink(en, Script(jp_raw[name]), delta, rows)

        table, per = {}, collections.Counter()
        for (rid, _role, jp, vi, old), eid, status in result:
            per[status] += 1
            if eid is None:
                if vi:
                    per['mat ban dich'] += 1
                    loose.append((name, rid, status, old, jp, vi))
                continue
            # Several sheet rows can land on one slot - a `var` instruction
            # ships the same box twice. Last one wins, as the merge does.
            table[eid] = (vi, jp)
        out[name] = table
        st.update(per)
        if on_file:
            on_file(name, len(rows), per)
    return out, st, loose


def main():
    ap = argparse.ArgumentParser(
        description='rebuild the EN ID column of a Japanese-anchored sheet')
    ap.add_argument('xlsx', help='the translation sheet to re-address')
    ap.add_argument('--story', default='STORY.cpk',
                    help='the English STORY.cpk or a directory of .DAT files')
    ap.add_argument('--jp-story', default='work/jp/CONTENTS/STORY.cpk',
                    help='the Japanese build the sheet is anchored to')
    ap.add_argument('--report', help='CSV of every row that could not be placed')
    ap.add_argument('--map', help='CSV of the whole mapping, row id -> EN ID')
    a = ap.parse_args()

    sheets = read_workbook(a.xlsx)
    print('%s: %d sheet kich ban, %s dong'
          % (os.path.basename(a.xlsx), len(sheets),
             format(sum(len(v) for v in sheets.values()), ',')))
    print()
    print('%-8s %8s %8s %8s %8s %8s %9s' %
          ('sheet', 'dong', 'giu', 'sua', 'them', 'theo bang', 'khong dat'))

    def show(name, n, per):
        print('%-8s %8d %8d %8d %8d %8d %9d' %
              (name, n, per['ok'], per['lech'], per['moi'],
               per['giu theo bang'], n - sum(per[k] for k in PLACED)))

    table, st, loose = tables(sheets, a.story, a.jp_story, on_file=show)

    print()
    print('EN ID giu nguyen      %s' % format(st['ok'], ','))
    print('EN ID sua lai         %s' % format(st['lech'], ','))
    print('EN ID them moi        %s' % format(st['moi'], ','))
    print('giu theo bang         %s (khong khop duoc nhung ID cu nam dung giua)'
          % format(st['giu theo bang'], ','))
    print('khong dat duoc        %s dong, trong do %s dong co ban dich'
          % (format(st['dong'] - sum(st[k] for k in PLACED), ','),
             format(st['mat ban dich'], ',')))
    for k, v in sorted(st.items()):
        if k not in ('dong', 'mat ban dich') + PLACED:
            print('   %-32s %s' % (k, format(v, ',')))

    if a.report:
        with open(a.report, 'w', newline='', encoding='utf-8-sig') as fh:
            w = csv.writer(fh)
            w.writerow(['sheet', 'row id', 'ly do', 'EN ID cu',
                        'tieng Nhat', 'tieng Viet'])
            w.writerows(loose)
        print('-> %s (%d dong khong dat duoc)' % (a.report, len(loose)))

    if a.map:
        with open(a.map, 'w', newline='', encoding='utf-8-sig') as fh:
            w = csv.writer(fh)
            w.writerow(['sheet', 'EN ID', 'tieng Viet'])
            for name in sorted(table):
                for eid, (vi, _jp) in table[name].items():
                    w.writerow([name, eid, vi])
        print('-> %s' % a.map)
    return 0


if __name__ == '__main__':
    sys.exit(main())
