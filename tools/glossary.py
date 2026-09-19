"""
glossary.py - build a translation sheet for the Glossary screen alone.

    python tools/glossary.py --out work/glossary.xlsx

The screen draws from three files, and only one of them is entirely its own:

    dbDictionary.gbin   the 98 terms - name and description
    strSystem.gstr      the kana tab strip, the empty-list message, and the two
                        menu hints that lead here
    strGame.gstr        the "all terms unlocked" notice

`mksheet.py --no-story` already extracts dbDictionary in full, but it cannot
narrow the other two: its `--sheet` filter applies to script files only, and
strSystem alone carries 114 rows belonging to every other screen in the game.
This tool takes the whole of dbDictionary and just the five UI keys listed in
UI_KEYS, so the sheet holds the Glossary and nothing else.

WHY IT REUSES mksheet
    Row ids, column order and the worksheet layout all come from mksheet, not
    from a second copy here. `checksheet.rows_of()` reads the source column at B
    and the translation at C BY POSITION, and the id in column A is the address
    a row is written back through - a sheet that drifts from that shape is not
    applicable. Importing the real thing is what keeps the two in step.

NAME AND READING ARE ONE STRING
    dbDictionary has three string columns: name (8), reading (16) and
    description (24). In the English build columns 8 and 16 point at the SAME
    pool entry in all 98 records - the Japanese build puts a kana reading in 16
    to sort by, English has nothing to put there. `db_rows()` is keyed by text
    and `gbnl.build()` rewrites every cell pointing at a string, so one row per
    term covers both cells. That is why the sheet has 196 rows for 294 cells.

THE TAB STRIP IS STILL JAPANESE
    IDS_DICTIONARY_TAB is byte-identical in both builds: ten `#PosX[%d]` stops
    holding the kana rows あ-わ. The u16 at record offset 2 is the kana row of
    the JAPANESE reading - it agrees with the reading in 98 of 98 records - so
    the grouping this screen sorts by has no meaning once the terms are in
    Vietnamese, and translating the strings will not change it. Two of the ten
    tabs (や, わ) are empty even in Japanese. Retabbing means rewriting that
    column, which is a separate job from translating; the row is in the sheet so
    the text is at least accounted for.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mksheet import (DB_COLUMNS, GBNL, Workbook, db_pairing, db_rows,  # noqa: E402
                     jp_db_map, read_map, readme, sheet_name)

# The screen furniture, as {file: {IDS key}}. Every other record in these two
# files belongs to another screen and is left to the full sheet.
UI_KEYS = {
    'strSystem.gstr': {
        'IDS_DICTIONARY_TAB',           # the kana tab strip along the top
        'IDS_DICTIONARY_NOWORD',        # shown on a tab with no terms unlocked
        'IDS_SYS_MENU_EX_DICTIONARY',   # hint under the Extras menu entry
        'IDS_MC_ALBUM_DICTIONARY',      # hint under the in-game menu entry
    },
    'strGame.gstr': {
        'IDS_GAME_FULL_COMP_DICTIONARY',
    },
}
KEY_COL = 0                             # column holding the IDS_ key in a .gstr

# Taken whole: every record on this screen is a Glossary term.
WHOLE = 'dbDictionary.gbin'
FILES = [WHOLE] + sorted(UI_KEYS)


def wanted_records(g, keys):
    """Records whose IDS_ key is in `keys`, and the keys that were not found."""
    found = {}
    for i in range(g.n):
        found[g.text(_cell(g, i, KEY_COL))] = i
    missing = sorted(k for k in keys if k not in found)
    return {found[k] for k in keys if k in found}, missing


def _cell(g, record, col):
    import struct
    return struct.unpack_from('<Q', g.raw, g.tbl + record * g.stride + col)[0]


def rows_for(base, data, jp_data):
    """(worksheet rows, japanese cells filled, keys not found) for one file."""
    g = GBNL(data)
    cols = DB_COLUMNS[base]

    if base == WHOLE:
        keep, missing = None, []
    else:
        keep, missing = wanted_records(g, UI_KEYS[base])

    jmap = {}
    if jp_data:
        pairs, _how = db_pairing(g, GBNL(jp_data))
        if pairs:
            jmap = jp_db_map(GBNL(jp_data), cols, pairs)

    out, filled = [], 0
    for rid, src, role, coord, _cap in db_rows(g, cols):
        if keep is not None and coord[0] not in keep:
            continue
        jp = jmap.get(coord)
        filled += bool(jp)
        out.append((rid, src, jp, role, '', ''))
    return out, filled, missing


def main():
    ap = argparse.ArgumentParser(
        description='build a translation sheet for the Glossary screen')
    ap.add_argument('--system', default='SYSTEM.cpk',
                    help='SYSTEM.cpk or a directory of unpacked .gbin/.gstr')
    ap.add_argument('--jp-system', default='work/jp/CONTENTS/SYSTEM.cpk',
                    help='the Japanese build, for the reference column')
    ap.add_argument('--no-jp', action='store_true')
    ap.add_argument('--out', default=os.path.join('work', 'glossary.xlsx'))
    a = ap.parse_args()

    src = read_map(a.system, ('.gbin', '.gstr'))
    jp = {} if a.no_jp else read_map(a.jp_system, ('.gbin', '.gstr'))
    if not a.no_jp and not jp:
        print('!! khong thay ban tieng Nhat (%s) - bo cot tieng Nhat' % a.jp_system)

    wb = Workbook(bool(jp), False)
    wb.add_readme(readme(bool(jp)))

    total = jp_total = 0
    print('%-24s %8s %8s' % ('file', 'dong', 'co JP'))
    for base in FILES:
        if base not in src:
            print('!! khong thay %s trong %s' % (base, a.system))
            continue
        rows, filled, missing = rows_for(base, src[base], jp.get(base))
        for key in missing:
            print('!! khong thay khoa %s trong %s' % (key, base))
        total += wb.add(sheet_name(base), rows)
        jp_total += filled
        print('%-24s %8d %8d' % (base, len(rows), filled))

    wb.save(a.out)
    print('\ntong: %d dong, %d co doi chieu tieng Nhat (%.1f%%)'
          % (total, jp_total, jp_total * 100.0 / total if total else 0))
    print('-> %s' % a.out)


if __name__ == '__main__':
    main()
