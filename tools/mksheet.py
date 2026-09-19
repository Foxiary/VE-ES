"""
mksheet.py - dump every translatable string in the game into a spreadsheet.

    python mksheet.py --out sheet.xlsx
    python mksheet.py --story work/story-us --system SYSTEM.cpk --out sheet.xlsx
    python mksheet.py --story STORY.cpk --no-system --no-jp --out story.xlsx
    python mksheet.py --merge Shuuen_JP_STORY.xlsx --out sheet.xlsx

Every path argument takes either a .cpk or a directory of files already unpacked
from one. The workbook written here is the one `checksheet.py` and
`applystory.py` read back: one worksheet per script file, columns

    ID | source (EN) | target (VI) | japanese | note | kind | bytes

with the target column left empty - or filled in from an existing translation,
plus `vi_bytes` and `canh bao`, when `--merge` is given.

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

THE LINE BUDGET IS A WIDTH, AND THERE IS NO BYTE LIMIT
    A probe build put lines of 100 to 800 bytes into the prologue and the game
    ran through every one of them. What it did was draw them off the right of
    the screen: the box overflows on WIDTH, and the "84 bytes" this file used to
    warn about was only the widest line stock English happened to need.

    Width is measured through `textwidth.py`, and two things have to be right or
    the answer is silently wrong. Measure the fonts that will SHIP, not the
    stock ones - the same sentence is 1851 units in stock advfont1 and 2123 in
    the shipped one. And compare against the box, not against the widest stock
    line: 3200 units for narration, 2990 for the message box, 2430 for the
    backlog, all read off the probe. `qua rong` uses the backlog, because every
    line of dialogue is replayed there.

    The `bytes` column is kept as a rough guide, and `qua dai` only appears when
    no font could be loaded. `ui` rows have no width limit worth enforcing here:
    they go back through `gbnl.py`, which rebuilds the string pool.

MERGING AN EXISTING TRANSLATION
    `--merge` takes a sheet that already carries the EN ID column this tool
    writes, fills its Vietnamese into the target column and flags what needs a
    second look. Rows are keyed by that id, not by content: the ids are exact
    byte offsets into the build being extracted, so the fill is exact and needs
    none of the content matching `applystory.py` falls back on.
"""
import argparse
import collections
import os
import re
import struct
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stcm2l import Script                          # noqa: E402
from gbnl import GBNL                              # noqa: E402
from cpk import CPK                                # noqa: E402
from portjp2us import align                        # noqa: E402
from textwidth import Widths, CEILING              # noqa: E402
from linebreak import to_sheet, to_game            # noqa: E402

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

# Where build.py writes the archive that actually gets installed. The stock one
# carries different fonts: the same sentence measures 1851 units against stock
# advfont1 and 2123 against the shipped one, so measuring the wrong file puts
# every width out by 15%.
SHIPPED_FONT = os.path.join('dist', 'SYSTEM.cpk')
STOCK_FONT = 'SYSTEM.cpk'

PROSE_RX = re.compile(r'[a-z]')
SPACERS = ' \t　'

# The inline commands the engine parses. A greedy `#[A-Za-z]+` swallows the word
# after a #n line break, making `#nto` and `#nand` read as different commands.
# On the shipped text the two spellings disagree about only one row either way,
# so this is correctness rather than a fix for a real miscount.
MARKUP_RX = re.compile(r'#(?:NAME|Color)\[\d+\]|#n')

# Byte budget for one script line; see THE LINE BUDGET above.
MAX_LINE_BYTES = 84

COLUMNS_HEAD = [('ID', 26), ('Nguon (EN)', 60), ('Tieng Viet', 60)]
COLUMNS_JP = [('Tieng Nhat', 50)]
COLUMNS_TAIL = [('Ghi chu', 22), ('kind', 8), ('bytes', 7)]
COLUMNS_MERGE = [('vi_bytes', 9), ('canh bao', 26)]


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
    """(id, source, role, (ins_i, blk_i), capacity) for every translatable block.

    `capacity` is the block's payload size as shipped, which is how many bytes a
    replacement can use without the block having to grow. See THE LINE BUDGET.
    """
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
            yield ('%d___%X_%s' % (i, b.data_off, role), t, role, (i, blk_i),
                   len(b.raw))


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
    """(id, source, role, (record, col), None) for each distinct string in `cols`.

    Capacity is None because `gbnl.build()` rebuilds the whole string pool and
    remaps the offsets, so these strings are free to grow.

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
            yield ('%d.%d___%X_%s' % (i, col // 8, rel, role), t, role, (i, col),
                   None)


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


# ---------------------------------------------------------------- merging in

ID_CELL_RX = re.compile(r'^\d+___[0-9A-F]+_(?:text|name|choice|title|var)$')
DOTS_RX = re.compile(r'[.]{2,}')
SPACE_RX = re.compile(r'[\s　]+')


def normalise_jp(s):
    """Fold a Japanese line down to what survives a CSV round-trip.

    A sheet that has been through CSV comes back with its punctuation mangled -
    `……` flattened to `...`, `――` and the closing `」` dropped. Comparing raw
    text would call 3,058 sound rows a mismatch, so both sides are folded before
    they are compared and only real differences are flagged.
    """
    s = unicodedata.normalize('NFKC', s or '')
    for a, b in (('…', '...'), ('―', '-'), ('─', '-'), ('‐', '-')):
        s = s.replace(a, b)
    return SPACE_RX.sub('', DOTS_RX.sub('...', s))


def load_merge(path):
    """{worksheet: {english id: (vietnamese, japanese)}} from a translation sheet.

    The sheet is anchored to the Japanese build - its own ID column addresses
    the Japanese scripts - and carries a second column of the English ids this
    tool wrote, which is what the rows are keyed by here.

    That column is found by its HEADER. Finding it by content does not work:
    a Japanese anchor reads `1___48EFC_text` and an English one
    `4150___48F08_text`, the same shape, so a content scan locks onto whichever
    column comes first - the Japanese one - and then nothing resolves. The
    fallback for a sheet with no `EN ID` header is a content scan that skips the
    sheet's own anchor in column A.
    """
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    out, guessed = {}, []
    for name in wb.sheetnames:
        if not name.isdigit():
            continue
        rows = wb[name].iter_rows(values_only=True)
        header = [str(c).strip().lower() if c else '' for c in next(rows, ())]
        vi_col = header.index('vietnamese') if 'vietnamese' in header else 2
        id_col = header.index('en id') if 'en id' in header else None

        table = {}
        for r in rows:
            if id_col is None:
                for k, c in enumerate(r):
                    if k and c and ID_CELL_RX.match(str(c).strip()):
                        id_col = k
                        guessed.append('%s:%s' % (name, k))
                        break
                if id_col is None:
                    continue
            if id_col >= len(r) or not r[id_col]:
                continue
            eid = str(r[id_col]).strip()
            if not ID_CELL_RX.match(eid):
                continue
            vi = to_game(str(r[vi_col]).strip()) if vi_col < len(r) and r[vi_col] else ''
            jp = to_game(str(r[1]).strip()) if len(r) > 1 and r[1] else ''
            table[eid] = (vi, jp)
        out[name] = table
    if guessed:
        print('   !! khong co cot "EN ID", doan theo noi dung: %s'
              % ', '.join(guessed[:8]))
    return out


def load_fonts(path):
    """Dialogue fonts for measuring, or None. Says when it is measuring stock.

    Duplicated in applyvi.py rather than shared: putting it in textwidth.py
    would tie that module to a build layout it does not otherwise know about,
    and the policy is eight lines.
    """
    if not os.path.exists(path):
        if path == SHIPPED_FONT and os.path.exists(STOCK_FONT):
            print('!! khong thay %s - do bang font GOC %s, so se KHONG dung '
                  'voi font se ship' % (path, STOCK_FONT))
            path = STOCK_FONT
        else:
            print('!! khong thay font (%s) - bo qua phep do be rong' % path)
            return None
    try:
        return Widths.from_cpk(path)
    except ValueError as e:
        print('!! khong do duoc be rong: %s' % e)
        return None


def warnings_for(vi, en, jp_theirs, jp_mine, cap, widths=None, ceiling=CEILING):
    """[(code, text)] saying why this row needs a human look before it ships.

    `khong vua block` the line needs more bytes than the block it replaces, so
                   that block has to grow. `stcm2l.build()` can do that and
                   re-offsets everything downstream, but `portjp2us.py` records
                   the opposite from testing on hardware: a block that changes
                   size shifts every later instruction and the engine crashes,
                   while a same-size replacement runs. Flagged rather than
                   silently trusted, because the two findings disagree
    `qua rong`     the line draws wider than the box it has to fit, measured
                   through the fonts that will ship and against the backlog -
                   the narrowest of the three screens, and the one every line
                   of dialogue is replayed in. Bytes only stand in for this
                   when no font is at hand, and stand in badly
    `qua dai`      the byte fallback, used only without a font
    `markup lech`  the inline commands differ from the block being overwritten,
                   which is what crashed 605.DAT - a #NAME[1] landing in a block
                   whose instruction carries no name context makes the engine
                   resolve a name through a garbage pointer
    `cau Nhat lech` the Japanese this was translated from is not the Japanese
                   that sits at this position in the Japanese build, so the two
                   builds split the box into a different number of lines here
    """
    if not vi:
        return [('chua dich', 'chua dich')]
    out = []
    n = len(vi.encode('utf-8'))
    if cap and n + 1 > cap:
        out.append(('khong vua block', 'khong vua block (%dB > %dB)' % (n + 1, cap)))
    # Width is what actually overflows the box; bytes only stand in for it when
    # no font is at hand, and they disagree in both directions.
    if widths is not None:
        overshoot = widths.over(vi, ceiling)
        if overshoot > 0:
            out.append(('qua rong', 'qua rong +%dpx' % overshoot))
    elif n > MAX_LINE_BYTES:
        out.append(('qua dai', 'qua dai %dB' % n))
    if collections.Counter(MARKUP_RX.findall(vi)) != \
            collections.Counter(MARKUP_RX.findall(en or '')):
        out.append(('markup lech', 'markup lech'))
    if jp_theirs and jp_mine and normalise_jp(jp_theirs) != normalise_jp(jp_mine):
        out.append(('cau Nhat lech', 'cau Nhat lech'))
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

    def __init__(self, with_jp, with_merge):
        import openpyxl
        from openpyxl.cell import WriteOnlyCell
        from openpyxl.styles import Alignment, Font
        self.wb = openpyxl.Workbook(write_only=True)
        self._cell = WriteOnlyCell
        self.head_font = Font(bold=True)
        self.wrap = Alignment(wrap_text=True, vertical='top')
        self.with_jp = with_jp
        self.with_merge = with_merge
        self.columns = (COLUMNS_HEAD + (COLUMNS_JP if with_jp else []) +
                        COLUMNS_TAIL + (COLUMNS_MERGE if with_merge else []))

    def add(self, name, rows):
        """One worksheet; `rows` yields (id, source, japanese, kind, vi, warning)."""
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
        for rid, src, jp, kind, vi, warn in rows:
            # Byte counts are the game's and are taken BEFORE #n becomes a
            # newline: the break costs two bytes on disk and one in a cell.
            src_bytes = len(src.encode('utf-8'))
            vi_bytes = len(vi.encode('utf-8')) if vi else None
            cells = [rid, self._wrapped(ws, to_sheet(src)),
                     self._wrapped(ws, to_sheet(vi) or None)]
            if self.with_jp:
                cells.append(self._wrapped(ws, to_sheet(jp)))
            cells += [None, kind, src_bytes]
            if self.with_merge:
                cells += [vi_bytes, warn or None]
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


def readme(with_jp, with_merge=False):
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
    if with_merge:
        out += [
            '',
            'COT "canh bao" danh dau dong can soat lai truoc khi dua vao game:',
            '  khong vua block  cau dich can nhieu byte hon block goc. stcm2l.py',
            '                 dung lai duoc file khi block phinh ra, nhung',
            '                 portjp2us.py ghi nhan thu tren may that thi doi kich',
            '                 thuoc block lam treo game. Hai ket luan nay dang',
            '                 mau thuan, nen day la dong rui ro nhat - viet ngan',
            '                 lai cho vua la chac chan an toan',
            '  qua rong +Npx  cau ve ra rong hon khung backlog (man hep nhat,',
            '                 noi moi cau thoai deu duoc chieu lai). Do bang font',
            '                 se ship that, khong phai font goc.',
            '  qua dai NNB    chi hien khi khong nap duoc font de do be rong',
            '  markup lech    ma lenh trong cau dich khac voi block tieng Anh bi',
            '                 ghi de - dung loi da lam treo 605.DAT, khi #NAME[1]',
            '                 roi vao block khong co ngu canh ten',
            '  cau Nhat lech  cau tieng Nhat dung de dich khong phai cau nam o vi',
            '                 tri nay ben ban Nhat: doan do hai ban ngat so dong',
            '                 khac nhau, nen doc ca khung thoai roi chinh lai',
            '  chua dich      chua co ban dich cho dong nay',
            '',
            'Sua xong thi xoa noi dung cot "canh bao" de biet dong nao da soat.',
        ]
    out += [
        '',
        'DO DAI DONG: moi dong thoai la mot dong tren man hinh. Gioi han KHONG',
        'phai so byte ma la BE RONG khi ve ra - da thu dong 800 byte, game van',
        'chay, chi la chu tran ra ngoai man hinh. Cot "canh bao" ghi ro tran bao',
        'nhieu (vi du "qua rong +174px"), nen biet duoc la chi can bot mot chu',
        'hay phai ngat dong.',
        '',
        'Chu Viet co dau ton 2 byte moi chu nhung ve ra van la mot chu, nen dem',
        'byte khong noi len dieu gi ve be rong - dung tin cot "bytes".',
        '',
        'Gioi han nay chi ap cho sheet kich ban. Cac sheet ten chu (kind = ui)',
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
    ap.add_argument('--font', default=SHIPPED_FONT,
                    help='the SYSTEM.cpk that will be INSTALLED, whose fonts '
                         'the game draws with; the stock archive measures a '
                         'different font and gives wrong widths')
    ap.add_argument('--ceiling', type=int, default=CEILING,
                    help='box width in advance units (default %d, the backlog, '
                         'narrowest of the three screens)' % CEILING)
    ap.add_argument('--merge',
                    help='a translation sheet carrying this tool\'s EN ID column; '
                         'its Vietnamese is filled in and flagged for review')
    ap.add_argument('--sheet', action='append',
                    help='limit to these worksheets, script or database '
                         '(repeatable). It used to filter the scripts only, so '
                         'asking for one database still wrote all nine.')
    a = ap.parse_args()

    jp_story = {} if a.no_jp else read_map(a.jp_story, ('.DAT',))
    jp_system = {} if a.no_jp else read_map(a.jp_system, ('.gbin', '.gstr'))
    with_jp = bool(jp_story or jp_system)
    if not a.no_jp and not with_jp:
        print('!! khong thay ban tieng Nhat (%s) - bo cot tieng Nhat' % a.jp_story)

    merge = load_merge(a.merge) if a.merge else {}
    if a.merge:
        print('ban dich: %s sheet, %s dong co EN ID' %
              (len(merge), format(sum(len(v) for v in merge.values()), ',')))

    widths, ceiling = None, a.ceiling
    if merge:
        widths = load_fonts(a.font)
        if widths is not None:
            print('do be rong bang %s | tran %d don vi (khung backlog)'
                  % (a.font, ceiling))

    wb = Workbook(with_jp, bool(merge))
    wb.add_readme(readme(with_jp, bool(merge)))
    kinds = collections.Counter()
    warned = collections.Counter()
    skipped = []
    total = jp_filled = jp_total = translated = 0

    def finish(rows, jmap, table):
        """Extracted rows -> worksheet rows, filling in and flagging the merge."""
        out = []
        for rid, src, role, coord, cap in rows:
            jp_mine = jmap.get(coord)
            vi, jp_theirs = table.get(rid, ('', ''))
            flags = warnings_for(vi, src, jp_theirs, jp_mine, cap,
                                 widths, ceiling) if merge else []
            for code, _text in flags:
                warned[code] += 1
            out.append((rid, src, jp_mine, role, vi,
                        ', '.join(t for _c, t in flags)))
        return out

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
            got = sum(1 for r in rows if r[3] in jmap)
            jp_filled += got
            jp_total += len(rows)

            per = collections.Counter(r[2] for r in rows)
            kinds.update(per)
            final = finish(rows, jmap, merge.get(sheet_name(base), {}))
            translated += sum(1 for f in final if f[4])
            total += wb.add(sheet_name(base), final)
            print('%-14s %8d %8d %8d %8d %8d %7d %6.1f%%' %
                  (base, per['text'], per['name'], per['choice'], per['title'],
                   per['var'], delta, got * 100.0 / len(rows)))

    if not a.no_system:
        print()
        print('%-24s %8s  %s' % ('database', 'strings', 'ghep voi ban Nhat'))
        for base, data in read_sources(a.system, ('.gbin', '.gstr')):
            if a.sheet and sheet_name(base) not in a.sheet:
                continue
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
            got = sum(1 for r in rows if r[3] in jmap)
            jp_filled += got
            jp_total += len(rows)
            kinds.update(r[2] for r in rows)
            final = finish(rows, jmap, merge.get(sheet_name(base), {}))
            translated += sum(1 for f in final if f[4])
            total += wb.add(sheet_name(base), final)
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
    if merge:
        print('da co ban dich: %s / %s dong (%.1f%%)' %
              (format(translated, ','), format(total, ','),
               translated * 100.0 / total))
        print('can soat lai truoc khi dua vao game:')
        for code, n in warned.most_common():
            print('   %-16s %s dong' % (code, format(n, ',')))
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
