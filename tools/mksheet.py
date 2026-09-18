"""
mksheet.py - dump every translatable string in the game into a spreadsheet.

    python mksheet.py --out sheet.xlsx
    python mksheet.py --story work/story-us --system SYSTEM.cpk --out sheet.xlsx
    python mksheet.py --story STORY.cpk --no-system --no-jp --out story.xlsx

Every path argument takes either a .cpk or a directory of files already unpacked
from one. The workbook written here is the one `checksheet.py` and
`applystory.py` read back: one worksheet per script file, columns

    ID | source (EN) | target (VI) | japanese | note | kind | bytes

with the target column left empty.

COLUMN ORDER IS LOAD-BEARING
    `checksheet.rows_of()` reads the source from column B and the target from
    column C by position, and `applystory.py` and `portjp2us.py` both go through
    it. The Japanese column therefore sits in D, after the target, rather than
    next to the source where it would read better: inserting it at C would make
    every one of those tools treat Japanese as the translation and write it into
    the game. Anything from column D rightwards is ignored by them, so notes and
    extra columns are free.

WHAT COUNTS AS TRANSLATABLE
    A script file is mostly asset names, flag names and sprite ids; only a few
    instruction opcodes carry text the player ever sees. Extracting "every block
    that decodes as UTF-8" would pull in 15,000 sprite ids and invite a
    translator to overwrite them, so extraction is driven by an opcode
    whitelist:

        text    one line of a message box
        name    the speaker name above it
        choice  one option of a selection menu
        title   a chapter title, stored as "<japanese key>@<display text>"
        var     a message box shipping several versions of the same lines, one
                per name substitution or highlight state
        ui      menu, option and glossary text out of SYSTEM.cpk

    Audited against the English build (01009CF01BAC4000): no block outside
    these opcodes holds a sentence, and no block inside them holds an asset id.

OPCODES ARE ADDRESSES, NOT CONSTANTS
    `opcode` is a pointer into the file's GLOBAL_DATA area, so its value moves
    with the layout. The whole table moves together, though, so only one number
    has to be recovered per file: the text opcode is found by content - the
    opcode carrying the most prose - and the rest of the table is rebased by
    that same delta. The delta is 0 in 49 of the English scripts and 16 in the
    other 5; on the Japanese build it is 32 throughout. A file whose rebased
    name opcode does not exist is reported and skipped rather than guessed at.

SHORT BLOCKS ARE NOT ALWAYS NUMBERS
    A data block of exactly 4 bytes is usually an integer, but `???` and `Man`
    are real speaker names that also fit in 4 bytes - dropping every 4-byte
    block silently loses 178 of them. The length test is therefore applied only
    inside `var` instructions, where text and numbers are interleaved and every
    real line is far longer. Elsewhere the block is known to be text from the
    opcode it sits under, and only the ideographic-space spacers are dropped.

THE JAPANESE COLUMN IS STRUCTURAL, NOT A CONTENT MATCH
    The same line reads differently in each language, so the two builds can only
    be bridged by structure - the approach `portjp2us.py` already uses to write
    translations across. Both builds compile from the same source: 50 of the 54
    story files have identical instruction counts, and the four that differ by
    one to three instructions are realigned with difflib on a signature of
    (parameter count, block count).

    The Japanese opcode table is recovered from where the English text
    instructions land, not by content - detect_delta() looks for lowercase ASCII
    and would find nothing in Japanese. A cell is filled only when the Japanese
    instruction carries the SAME role, so a misalignment leaves the column empty
    instead of pairing a line with somebody else's. Measured on the English
    build: every one of the 82,685 English text instructions lands on a Japanese
    text instruction, and 99.9% of speaker-name rows agree on their counterpart.

    Line breaks were re-flowed in localisation, so row N holds the same screen
    line slot in both builds, not necessarily the same sentence. Read a Japanese
    cell as context for the box it sits in, not as a word-for-word gloss.

DATABASE RECORDS ARE NOT IN THE SAME ORDER IN BOTH BUILDS
    dbDictionary is sorted alphabetically per language, so record 2 is
    'Allelopathy' in English and 'Arpechele' in Japanese: pairing the databases
    by record index attaches the wrong term to 93 of its 98 entries. db_pairing()
    therefore proves the order before using it - either the record tables are
    identical once the string cells are masked out, or some column is unique on
    both sides and carries the same set of values, and that column becomes the
    key. dbDictionary pairs on its numeric term id; everything else pairs by
    index. A file where neither holds gets no Japanese rather than a wrong one.

DATABASE COLUMNS ARE PICKED BY HAND
    `.gbin` / `.gstr` string columns mix display text with internal keys, and no
    content test separates them: 'YES' is display text, 'sure1' is a flag, and
    both look like identifiers. DB_COLUMNS below therefore names the columns to
    take, per file, read off the schema. Files and columns not named there are
    skipped and listed on stdout, so nothing is dropped quietly.

    Rows are de-duplicated by text because `gbnl.build()` is keyed by text, not
    by cell: one translation of 'Act 1' updates all 450 cells holding it.

THE LINE BUDGET
    Story text is stored one screen line per block and the engine's line buffer
    is fixed: no block in the stock build exceeds 84 bytes, and 98-byte blocks
    crash the main story. The `bytes` column carries the source length so a
    translator can see the budget; Vietnamese diacritics cost 2 bytes each. The
    limit is a script one - `ui` rows go back through `gbnl.py`, which rebuilds
    the string pool and lets text grow.
"""
import argparse
import collections
import os
import re
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stcm2l import Script                          # noqa: E402
from gbnl import GBNL                              # noqa: E402
from cpk import CPK                                # noqa: E402
from portjp2us import align                        # noqa: E402

# Opcode -> role, as laid out in the English build. Rebased per file; see above.
STORY_ROLES = {
    72948: 'text',
    74780: 'name',
    77820: 'choice',
    10128: 'title',
    223020: 'var',
    223732: 'var',
    291308: 'var',
    291692: 'var',
}
TEXT_OP = 72948                 # the anchor the delta is measured against
NAME_OP = 74780                 # used to confirm a delta before trusting it

# Roles whose instruction holds exactly one text block, at index 0. `var` is the
# exception: its blocks alternate text and numbers, so all of them are examined.
SINGLE_BLOCK = {'text', 'name', 'choice', 'title'}

# String columns worth translating, as (cell offset, role) per file. A column
# absent here is internal - an asset id, a flag name or an IDS_ lookup key.
DB_COLUMNS = {
    'dbDictionary.gbin': [(8, 'ui'), (16, 'ui'), (24, 'ui')],
    'dbFlowchart.gbin': [(32, 'ui'), (40, 'title')],
    'dbLogFace.gbin': [(0, 'name')],     # speaker names in the backlog
    'strDebug.gstr': [(16, 'ui')],
    'strGame.gstr': [(16, 'ui')],
    'strKeyHelp.gstr': [(16, 'ui')],
    'strNameEntry.gstr': [(16, 'ui')],
    'strOption.gstr': [(16, 'ui')],
    'strSystem.gstr': [(16, 'ui')],
}

PROSE_RX = re.compile(r'[a-z]')
SPACERS = ' \t　'

COLUMNS_HEAD = [('ID', 26), ('Nguon (EN)', 60), ('Tieng Viet', 60)]
COLUMNS_JP = [('Tieng Nhat', 50)]
COLUMNS_TAIL = [('Ghi chu', 22), ('kind', 8), ('bytes', 7)]


# --------------------------------------------------------------------- story

def detect_delta(script):
    """How far this file's opcode table sits from the table above, or None.

    The text opcode is the one carrying the most prose - a run of characters
    with a space and a lowercase letter in it, which no asset id has.
    """
    score = collections.Counter()
    for ins in script.instructions:
        if len(ins.blocks) != 1:
            continue
        t = ins.blocks[0].text()
        if t and len(t) > 8 and ' ' in t and PROSE_RX.search(t):
            score[ins.opcode] += 1
    if not score:
        return None
    delta = score.most_common(1)[0][0] - TEXT_OP
    # A delta recovered from one opcode is only believable if it also lands the
    # name opcode on something the file actually uses.
    if not any(i.opcode == NAME_OP + delta for i in script.instructions):
        return None
    return delta


def cell_text(block, allow_short):
    """The block's payload as translatable text, or None if it is not text."""
    t = block.text()
    if not t:
        return None
    if any(ord(c) < 0x20 for c in t):
        return None                      # a little-endian number, not a string
    if not allow_short and block.length <= 4:
        return None
    if not t.strip(SPACERS):
        return None                      # blank line used to pad a message box
    return t


def story_rows(script, delta):
    """(id, source, role, (ins_i, blk_i)) for every translatable block."""
    roles = {op + delta: role for op, role in STORY_ROLES.items()}
    for i, ins in enumerate(script.instructions):
        role = roles.get(ins.opcode)
        if role is None:
            continue
        blocks = ins.blocks[:1] if role in SINGLE_BLOCK else ins.blocks
        for blk_i, b in enumerate(blocks):
            t = cell_text(b, allow_short=role in SINGLE_BLOCK)
            if t is None:
                continue
            yield '%d___%X_%s' % (i, b.data_off, role), t, role, (i, blk_i)


def jp_story_map(en, jp, en_delta):
    """{(ins_i, blk_i): japanese text} for blocks that line up across builds.

    See "THE JAPANESE COLUMN IS STRUCTURAL" above. Returns {} when the Japanese
    opcode table cannot be located, which leaves the column empty instead of
    filling it from an unverified alignment.
    """
    amap = align(en, jp)
    landed = collections.Counter()
    for i, ins in enumerate(en.instructions):
        if ins.opcode == TEXT_OP + en_delta and i in amap:
            landed[jp.instructions[amap[i]].opcode] += 1
    if not landed:
        return {}
    jp_delta = landed.most_common(1)[0][0] - TEXT_OP

    en_roles = {op + en_delta: r for op, r in STORY_ROLES.items()}
    jp_roles = {op + jp_delta: r for op, r in STORY_ROLES.items()}
    out = {}
    for i, ins in enumerate(en.instructions):
        role = en_roles.get(ins.opcode)
        j = amap.get(i)
        if role is None or j is None:
            continue
        jins = jp.instructions[j]
        if jp_roles.get(jins.opcode) != role:
            continue                     # not the same kind of line; skip it
        blocks = jins.blocks[:1] if role in SINGLE_BLOCK else jins.blocks
        for blk_i, b in enumerate(blocks):
            t = cell_text(b, allow_short=role in SINGLE_BLOCK)
            if t is not None:
                out[(i, blk_i)] = t
    return out


# ------------------------------------------------------------------ database

def db_rows(g, cols):
    """(id, source, role, (record, col)) for each distinct string in `cols`.

    Keyed by text, not by cell, to match how `gbnl.build()` applies a
    translation back - it rewrites every cell pointing at the string, so one
    row per distinct string is both sufficient and free of conflicts.
    """
    seen = set()
    for i in range(g.n):
        for col, role in cols:
            off = g.tbl + i * g.stride + col
            rel = struct.unpack_from('<Q', g.raw, off)[0]
            t = g.text(rel)
            if not t.strip(SPACERS) or t in seen:
                continue
            seen.add(t)
            yield '%d.%d___%X_%s' % (i, col // 8, rel, role), t, role, (i, col)


def col_spans(g):
    """{cell offset: width in bytes}, taken from the gaps between columns.

    Reading the widths off the schema's own layout avoids a table of type sizes
    that would have to be right for every type the format can carry.
    """
    offs = sorted(o for _t, o in g.schema)
    return {o: (offs[k + 1] if k + 1 < len(offs) else g.stride) - o
            for k, o in enumerate(offs)}


def _cells(g, col, size):
    """Every record's value in one column: text for string cells, raw bytes else."""
    if col in g.str_cols:
        return [g.text(struct.unpack_from('<Q', g.raw, g.tbl + i * g.stride + col)[0])
                for i in range(g.n)]
    base = g.tbl + col
    return [bytes(g.raw[base + i * g.stride: base + i * g.stride + size])
            for i in range(g.n)]


def db_pairing(gu, gj):
    """{english record -> japanese record}, or None when order cannot be proven.

    See "DATABASE RECORDS ARE NOT IN THE SAME ORDER" above.
    """
    if (gu.n, gu.ncol, gu.stride, gu.str_cols) != (gj.n, gj.ncol, gj.stride, gj.str_cols):
        return None, 'shape khac nhau'

    # Everything but the string cells is copied from the same source data, so if
    # that part matches record for record the two tables are in the same order.
    same = True
    for i in range(gu.n):
        a = bytearray(gu.raw[gu.tbl + i * gu.stride: gu.tbl + (i + 1) * gu.stride])
        b = bytearray(gj.raw[gj.tbl + i * gj.stride: gj.tbl + (i + 1) * gj.stride])
        for col in gu.str_cols:
            a[col:col + 8] = b'\x00' * 8
            b[col:col + 8] = b'\x00' * 8
        if a != b:
            same = False
            break
    if same:
        return {i: i for i in range(gu.n)}, 'cung thu tu'

    # Otherwise look for a column that is unique on both sides and holds the
    # same set of values - an id the two builds share. A localised column fails
    # the set test on its own, so it cannot be picked by mistake.
    for col, size in sorted(col_spans(gu).items()):
        u, j = _cells(gu, col, size), _cells(gj, col, size)
        if len(set(u)) == gu.n and len(set(j)) == gj.n and set(u) == set(j):
            where = {v: k for k, v in enumerate(j)}
            return {k: where[v] for k, v in enumerate(u)}, 'khoa = cot %d' % col
    return None, 'khong tim duoc khoa chung'


def jp_db_map(gj, cols, pairs):
    """{(english record, col): japanese text} through the proven record pairing."""
    out = {}
    for i, j in pairs.items():
        for col, _role in cols:
            off = gj.tbl + j * gj.stride + col
            t = gj.text(struct.unpack_from('<Q', gj.raw, off)[0])
            if t.strip(SPACERS):
                out[(i, col)] = t
    return out


# --------------------------------------------------------------------- input

def read_sources(path, suffixes):
    """[(basename, bytes)] from a .cpk or from a directory of unpacked files."""
    if os.path.isdir(path):
        names = sorted(n for n in os.listdir(path) if n.endswith(suffixes))
        return [(n, open(os.path.join(path, n), 'rb').read()) for n in names]
    c = CPK(path)
    out = []
    for _i, name, row in c.files():
        base = os.path.basename(name)
        if base.endswith(suffixes):
            out.append((base, c.read(row)))
    return sorted(out)


def read_map(path, suffixes):
    """{basename: bytes}, or {} when the path is not there."""
    if not path or not os.path.exists(path):
        return {}
    return dict(read_sources(path, suffixes))


# -------------------------------------------------------------------- output

def sheet_name(basename):
    """Worksheet name for a source file, kept off Excel's reserved characters."""
    stem = os.path.splitext(basename)[0]
    return re.sub(r'[\[\]:*?/\\]', '_', stem)[:31]


class Workbook:
    """Thin wrapper so the row loops stay free of openpyxl detail."""

    def __init__(self, with_jp):
        import openpyxl
        from openpyxl.cell import WriteOnlyCell
        from openpyxl.styles import Alignment, Font
        self.wb = openpyxl.Workbook(write_only=True)
        self._cell = WriteOnlyCell
        self.head_font = Font(bold=True)
        self.wrap = Alignment(wrap_text=True, vertical='top')
        self.with_jp = with_jp
        self.columns = COLUMNS_HEAD + (COLUMNS_JP if with_jp else []) + COLUMNS_TAIL

    def add(self, name, rows):
        """One worksheet; `rows` is an iterable of (id, source, japanese, kind)."""
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
        for rid, src, jp, kind in rows:
            cells = [rid, self._wrapped(ws, src), self._wrapped(ws, None)]
            if self.with_jp:
                cells.append(self._wrapped(ws, jp))
            cells += [None, kind, len(src.encode('utf-8'))]
            ws.append(cells)
            n += 1
        if n:
            last = chr(ord('A') + len(self.columns) - 1)
            ws.auto_filter.ref = 'A1:%s%d' % (last, n + 1)
        return n

    def _wrapped(self, ws, value):
        c = self._cell(ws, value=value)
        c.alignment = self.wrap
        return c

    def add_readme(self, lines):
        ws = self.wb.create_sheet('_README')
        ws.column_dimensions['A'].width = 100
        for line in lines:
            ws.append([line])

    def save(self, path):
        self.wb.save(path)


def readme(with_jp):
    out = [
        'BANG DICH VIRCHE EVERMORE - ban tieng Anh 01009CF01BAC4000',
        '',
        'Moi sheet so (100, 101, ...) la mot file kich ban; sheet ten chu',
        '(strSystem, dbDictionary, ...) la van ban giao dien va tu dien trong',
        'SYSTEM.cpk.',
        '',
        'Chi dien cot C (Tieng Viet). KHONG doi thu tu cot va khong sua cot A -',
        'cong cu ghi ban dich vao game doc cot theo VI TRI, cot A la dia chi.',
        'Cot "Ghi chu" ghi thoai mai.',
        '',
        'GIU NGUYEN CAC MA LENH TRONG CAU:',
        '  #NAME[1]            ten nhan vat chinh do nguoi choi dat',
        '  #Color[8] #Color[0] mo / dong doan chu doi mau',
        '  #n                  xuong dong',
        '',
        'kind = title: chuoi co dang "<khoa tieng Nhat>@<chu hien ra>". Chi dich',
        'phan sau dau @, giu nguyen phan truoc va chinh dau @.',
        '',
        'kind = name: ten nhan vat. Dich thong nhat giua sheet kich ban va sheet',
        'dbLogFace (ten hien trong lich su hoi thoai), neu khong se lech nhau.',
        '',
        'kind = var: mot khung thoai duoc game luu san nhieu ban (mot ban dung ten',
        'mac dinh, mot ban dung #NAME[1], hoac khac nhau o doan to mau). Cac ban do',
        'nam gan nhau trong sheet va phai duoc dich giong het nhau, chi khac o ma',
        'lenh.',
    ]
    if with_jp:
        out += [
            '',
            'COT TIENG NHAT la cau goc o dung vi tri do trong ban tieng Nhat, doi',
            'chieu theo CAU TRUC file chu khong phai theo nghia. Ban tieng Anh co',
            'ngat dong lai, nen dong N cua hai ban la cung mot DONG TREN MAN HINH',
            'chu chua chac cung mot cau. Dung de tham khao sac thai va ten rieng,',
            'nhat la khi ban tieng Anh dich thoang.',
        ]
    out += [
        '',
        'DO DAI DONG: moi dong thoai la mot dong tren man hinh, do chieu dai theo',
        'BYTE UTF-8 (cot "bytes" la so byte cua cau goc tieng Anh). Ban goc khong',
        'co dong nao qua 84 byte; dong 98 byte lam treo game. Chu Viet co dau ton',
        '2 byte moi chu, nen cau 40 ky tu co the da la 55 byte - ngat cau thanh',
        'nhieu dong thay vi viet dai.',
        '',
        'Gioi han 84 byte chi ap cho sheet kich ban. Cac sheet ten chu (kind = ui)',
        'duoc dung lai toan bo vung chuoi khi ghi vao game nen dai bao nhieu cung',
        'duoc - vi du mo ta trong dbDictionary von da dai 120-170 byte.',
    ]
    return out


def main():
    ap = argparse.ArgumentParser(
        description='build a translation spreadsheet from the game files')
    ap.add_argument('--story', default='STORY.cpk',
                    help='STORY.cpk or a directory of .DAT scripts')
    ap.add_argument('--system', default='SYSTEM.cpk',
                    help='SYSTEM.cpk or a directory of .gbin/.gstr files')
    ap.add_argument('--jp-story', default='work/jp/CONTENTS/STORY.cpk',
                    help='the Japanese build, for the reference column')
    ap.add_argument('--jp-system', default='work/jp/CONTENTS/SYSTEM.cpk')
    ap.add_argument('--out', required=True, help='spreadsheet to write')
    ap.add_argument('--no-story', action='store_true')
    ap.add_argument('--no-system', action='store_true')
    ap.add_argument('--no-jp', action='store_true',
                    help='leave out the Japanese reference column')
    ap.add_argument('--sheet', action='append',
                    help='limit to these script files (repeatable)')
    a = ap.parse_args()

    jp_story = {} if a.no_jp else read_map(a.jp_story, ('.DAT',))
    jp_system = {} if a.no_jp else read_map(a.jp_system, ('.gbin', '.gstr'))
    with_jp = bool(jp_story or jp_system)
    if not a.no_jp and not with_jp:
        print('!! khong thay ban tieng Nhat (%s) - bo cot tieng Nhat' % a.jp_story)

    wb = Workbook(with_jp)
    wb.add_readme(readme(with_jp))
    kinds = collections.Counter()
    skipped = []
    total = jp_filled = jp_total = 0

    if not a.no_story:
        print('%-14s %8s %8s %8s %8s %8s %7s %7s' %
              ('script', 'text', 'name', 'choice', 'title', 'var', 'delta', 'JP'))
        for base, data in read_sources(a.story, ('.DAT',)):
            if a.sheet and sheet_name(base) not in a.sheet:
                continue
            try:
                script = Script(data)
            except ValueError as e:
                skipped.append('%s: %s' % (base, e))
                continue
            delta = detect_delta(script)
            if delta is None:
                skipped.append('%s: khong co thoai' % base)
                continue
            rows = list(story_rows(script, delta))
            if not rows:
                skipped.append('%s: khong co thoai' % base)
                continue

            jmap = {}
            if base in jp_story:
                try:
                    jmap = jp_story_map(script, Script(jp_story[base]), delta)
                except ValueError as e:
                    skipped.append('%s (JP): %s' % (base, e))
            got = sum(1 for _r, _s, _k, c in rows if c in jmap)
            jp_filled += got
            jp_total += len(rows)

            per = collections.Counter(r[2] for r in rows)
            kinds.update(per)
            total += wb.add(sheet_name(base),
                            ((rid, src, jmap.get(coord), role)
                             for rid, src, role, coord in rows))
            print('%-14s %8d %8d %8d %8d %8d %7d %6.1f%%' %
                  (base, per['text'], per['name'], per['choice'], per['title'],
                   per['var'], delta, got * 100.0 / len(rows)))

    if not a.no_system:
        print()
        print('%-24s %8s  %s' % ('database', 'strings', 'ghep voi ban Nhat'))
        for base, data in read_sources(a.system, ('.gbin', '.gstr')):
            cols = DB_COLUMNS.get(base)
            if not cols:
                skipped.append('%s: khong co cot can dich' % base)
                continue
            try:
                g = GBNL(data)
            except ValueError as e:
                skipped.append('%s: %s' % (base, e))
                continue

            jmap, how = {}, '-'
            if base in jp_system:
                gj = GBNL(jp_system[base])
                pairs, how = db_pairing(g, gj)
                if pairs:
                    jmap = jp_db_map(gj, cols, pairs)

            taken = {c for c, _role in cols}
            unknown = [c for c in g.str_cols if c not in taken]
            rows = list(db_rows(g, cols))
            got = sum(1 for _r, _s, _k, c in rows if c in jmap)
            jp_filled += got
            jp_total += len(rows)
            kinds.update(r[2] for r in rows)
            total += wb.add(sheet_name(base),
                            ((rid, src, jmap.get(coord), role)
                             for rid, src, role, coord in rows))
            print('%-24s %8d  %-22s%s' %
                  (base, len(rows), how,
                   '(bo qua cot %s)' % unknown if unknown else ''))

    wb.save(a.out)

    print()
    print('tong: %s dong can dich  (%s)' %
          (format(total, ','),
           ', '.join('%s %s' % (k, format(v, ',')) for k, v in kinds.most_common())))
    if with_jp and jp_total:
        print('co doi chieu tieng Nhat: %s / %s dong (%.1f%%)' %
              (format(jp_filled, ','), format(jp_total, ','),
               jp_filled * 100.0 / jp_total))
    if skipped:
        print('bo qua %d file khong co van ban nguoi choi doc duoc:' % len(skipped))
        for s in skipped[:6]:
            print('   ', s)
        if len(skipped) > 6:
            print('    ... va %d file nua' % (len(skipped) - 6))
    print('-> %s' % a.out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
