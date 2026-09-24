"""
trbatch.py - cut a mksheet workbook into translation batches and fold them back.

    python trbatch.py prefill SHEET.xlsx --ref REF.xlsx --names names.tsv
    python trbatch.py export  SHEET.xlsx OUT_DIR [--rows 600]
    python trbatch.py import  SHEET.xlsx DONE_DIR [--dry-run]
    python trbatch.py status  SHEET.xlsx

Written for the fan disc, whose workbook has a Japanese column but no earlier
translation to merge: the Vietnamese is produced fresh, from the Japanese, by
whoever works through the batches, and this tool only moves text in and out.

PREFILL FIRST, TRANSLATE WHAT IS LEFT
    Speaker names come from a lookup, not a translator: the reference sheet's
    TABLE_NAME maps each Japanese name to the Vietnamese the main game already
    ships, and `--names` adds the fan disc's own. A row with no Japanese cell
    borrows the answer another row gave the same English name. A dialogue line
    whose Japanese occurs verbatim in the reference, with a single translation
    there, can be filled with that translation (`--lines`), but that is OFF by
    default: the reference sheet has runs where its Vietnamese sits one row off
    its Japanese, and matching verbatim carries the wrong line along - 4,115
    were filled that way once and had to be cleared, e.g. 思っていたのだが……。
    given "Hoa than cua hoa lycoris, #NAME[1]." A filled cell is never
    overwritten, so prefill can be re-run without losing work.

A BATCH ENDS AT A BOX BOUNDARY
    `applyvi.py` writes a message box whole or not at all, so the translator of
    one batch must see every slot of the boxes in it. Batches are therefore cut
    only just before a `name` row or a non-text row, never between two `text`
    rows. Name rows ride along already filled, as context: they say who speaks.

EVERY SLOT OF A BOX NEEDS TEXT
    An empty target means "not translated", and a box with an untranslated slot
    is refused entire. About 1,500 English slots have no Japanese counterpart -
    lines English added to a box - and they still need a share of the box's
    Vietnamese. `import` counts them rather than silently leaving them blank.

MARKUP IS CHECKED ON THE WAY IN
    `#NAME[1]`, `#Color[..]` and `#n` must survive translation. `import` checks
    each returned line's commands against its box, the way `applyvi.py` will,
    and reports what does not balance instead of writing it.
"""
import argparse
import collections
import glob
import json
import os
import re
import shutil
import sys

import openpyxl

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from linebreak import to_game, to_sheet            # noqa: E402

COL_ID, COL_EN, COL_VI, COL_JP, COL_NOTE, COL_KIND = range(6)
TRANSLATED = {'text', 'var', 'choice', 'title', 'ui'}
NAME_RX = re.compile(r'#NAME\[\d+\]')
COLOR_RX = re.compile(r'#Color\[\d+\]')


def cell(v):
    return '' if v is None else str(v)


def load_ref(path):
    """(jp name -> vi, jp line -> vi, en ui string -> vi) from the reference."""
    wb = openpyxl.load_workbook(path, read_only=True)
    names = {}
    for r in wb['TABLE_NAME'].iter_rows(values_only=True):
        if r and r[0] and r[1]:
            names[str(r[0]).strip()] = str(r[1]).strip()
    lines = collections.defaultdict(collections.Counter)
    for s in wb.sheetnames:
        if not s[0].isdigit():
            continue
        for r in wb[s].iter_rows(min_row=2, values_only=True):
            if len(r) < 3 or not r[1] or not isinstance(r[2], str):
                continue
            vi = r[2].strip()
            if vi and not vi.startswith('='):          # '=TABLE_NAME!B27' refs
                lines[str(r[1]).strip()][vi] += 1
    # Interface text is keyed by its English: these sheets were extracted from
    # the English build, and the fan disc reuses most of its menus verbatim.
    ui = collections.defaultdict(collections.Counter)
    for s in wb.sheetnames:
        if s.startswith(('db', 'str')):
            for r in wb[s].iter_rows(min_row=2, values_only=True):
                if len(r) > 2 and r[1] and isinstance(r[2], str) and r[2].strip():
                    ui[str(r[1]).strip()][r[2].strip()] += 1

    # A string translated two ways depends on its context; leave it to a person.
    def one(d):
        return {k: v.most_common(1)[0][0] for k, v in d.items() if len(v) == 1}
    return names, one(lines), one(ui)


def load_names(path):
    out = {}
    if path:
        for line in open(path, encoding='utf-8'):
            parts = line.rstrip('\n').split('\t')
            if len(parts) >= 2 and parts[0] and parts[1]:
                out[parts[0].strip()] = parts[1].strip()
    return out


def sheets(wb):
    return [s for s in wb.sheetnames if not s.startswith('_')]


def cmd_prefill(a):
    names, lines, ui = load_ref(a.ref)
    names.update(load_names(a.names))
    wb = openpyxl.load_workbook(a.sheet)
    # English name -> Vietnamese, learned from rows that do have Japanese.
    by_en = {}
    for s in sheets(wb):
        for row in wb[s].iter_rows(min_row=2):
            if cell(row[COL_KIND].value) == 'name':
                jp = cell(row[COL_JP].value).strip()
                if jp in names:
                    by_en.setdefault(cell(row[COL_EN].value).strip(), names[jp])
    st = collections.Counter()
    for s in sheets(wb):
        for row in wb[s].iter_rows(min_row=2):
            kind = cell(row[COL_KIND].value)
            if cell(row[COL_VI].value).strip():
                st['da co'] += 1
                continue
            jp = cell(row[COL_JP].value).strip()
            en = cell(row[COL_EN].value).strip()
            vi = None
            if kind == 'name':
                vi = names.get(jp) if jp else by_en.get(en)
                vi = vi or (en if not jp else None)
                st['name' if vi else 'name thieu'] += 1
            elif a.lines and kind in ('text', 'var', 'choice') and jp and jp in lines:
                vi = lines[jp]
                st['cau trung ban tham chieu'] += 1
            elif kind == 'ui' and en in ui:
                vi = ui[en]
                st['ui trung ban goc'] += 1
            if vi:
                row[COL_VI].value = vi
    save(wb, a.sheet)
    for k, n in sorted(st.items()):
        print('%-28s %7d' % (k, n))


def rows_of(ws):
    for row in ws.iter_rows(min_row=2, values_only=True):
        if row and row[COL_ID]:
            yield row


def cmd_export(a):
    wb = openpyxl.load_workbook(a.sheet, read_only=True)
    os.makedirs(a.out, exist_ok=True)
    n_batch = n_rows = 0
    for s in sheets(wb):
        rows = list(rows_of(wb[s]))
        cur, todo = [], 0

        def flush():
            nonlocal cur, todo, n_batch, n_rows
            if todo:
                path = os.path.join(a.out, '%s_%03d.jsonl' % (s, n_batch))
                with open(path, 'w', encoding='utf-8') as f:
                    for r in cur:
                        f.write(json.dumps(r, ensure_ascii=False) + '\n')
                n_batch += 1
                n_rows += todo
            cur, todo = [], 0

        for i, r in enumerate(rows):
            kind = cell(r[COL_KIND])
            nxt = cell(rows[i + 1][COL_KIND]) if i + 1 < len(rows) else None
            rec = {'id': cell(r[COL_ID]), 'k': kind, 'jp': cell(r[COL_JP]),
                   'en': cell(r[COL_EN])}
            vi = cell(r[COL_VI]).strip()
            if vi:
                rec['vi'] = vi
            elif kind in TRANSLATED:
                todo += 1
            cur.append(rec)
            # Cut only where the next row starts a new box.
            if todo >= a.rows and nxt != 'text':
                flush()
        flush()
    print('%d lo, %d dong can dich -> %s' % (n_batch, n_rows, a.out))


def markup_ok(vi, sources):
    """Do the commands in `vi` match those of any one of `sources`?

    The same test `applyvi.py` applies: the Japanese line is as valid an answer
    as the English one, since the translation follows the Japanese. `#Color`
    is only asked to open and close in pairs, because a translator moves the
    highlight onto the Vietnamese word wherever that falls.
    """
    got = len(NAME_RX.findall(vi))
    if not any(got == len(NAME_RX.findall(src)) for src in sources if src):
        return False
    return len(COLOR_RX.findall(vi)) % 2 == 0


def cmd_import(a):
    # Keyed by (sheet, id): an id is an instruction index and a byte offset,
    # unique within one script but not across them - 471 ids recur in two or
    # more sheets, and keying on the id alone once wrote one script's lines
    # into another. The sheet comes from the batch file name, <sheet>_<n>.
    got = collections.defaultdict(dict)
    for path in sorted(glob.glob(os.path.join(a.done, '*.jsonl'))):
        done = got[os.path.basename(path).rsplit('_', 1)[0]]
        for n, line in enumerate(open(path, encoding='utf-8'), 1):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                print('%s:%d: JSON hong' % (path, n))
                continue
            if rec.get('id') and isinstance(rec.get('vi'), str):
                done[rec['id']] = rec['vi']
    wb = openpyxl.load_workbook(a.sheet)
    st = collections.Counter()
    bad = []
    for s in sheets(wb):
        done = got.get(s, {})
        rows = list(wb[s].iter_rows(min_row=2))
        # Group text rows into boxes: a run of text rows between other rows.
        box = []

        def settle():
            lines = [(r, done[cell(r[COL_ID].value)])
                     for r in box if cell(r[COL_ID].value) in done]
            if not lines:
                return
            # Balanced over the whole box, prefilled slots included: a #NAME[1]
            # routinely moves to the neighbouring slot in translation.
            vi = ''.join(done.get(cell(r[COL_ID].value)) or cell(r[COL_VI].value)
                         for r in box)
            jp = ''.join(cell(r[COL_JP].value) for r in box)
            en = ''.join(cell(r[COL_EN].value) for r in box)
            if not markup_ok(vi, [jp, en]):
                st['markup lech (bo qua)'] += len(lines)
                bad.append((s, cell(box[0][COL_ID].value)))
                return
            for r, v in lines:
                write(r, v)

        def write(r, vi):
            if cell(r[COL_VI].value).strip() and not a.overwrite:
                st['da co, giu nguyen'] += 1
                return
            r[COL_VI].value = to_sheet(to_game(vi.strip()))
            st['ghi'] += 1

        for r in rows:
            kind = cell(r[COL_KIND].value)
            if kind == 'text':
                box.append(r)
                continue
            settle()
            box = []
            rid = cell(r[COL_ID].value)
            if rid in done and kind in TRANSLATED:
                vi = done[rid]
                if not markup_ok(vi, [cell(r[COL_JP].value),
                                      cell(r[COL_EN].value)]):
                    st['markup lech (bo qua)'] += 1
                    bad.append((s, rid))
                    continue
                write(r, vi)
        settle()
    for k, n in sorted(st.items()):
        print('%-28s %7d' % (k, n))
    for s, rid in bad[:30]:
        print('   lech: %s %s' % (s, rid))
    if not a.dry_run:
        save(wb, a.sheet)


def cmd_status(a):
    wb = openpyxl.load_workbook(a.sheet, read_only=True)
    tot, filled = collections.Counter(), collections.Counter()
    for s in sheets(wb):
        for r in rows_of(wb[s]):
            k = cell(r[COL_KIND])
            tot[k] += 1
            filled[k] += bool(cell(r[COL_VI]).strip())
    for k in sorted(tot):
        print('%-8s %7d / %7d' % (k, filled[k], tot[k]))
    print('%-8s %7d / %7d' % ('tong', sum(filled.values()), sum(tot.values())))


def save(wb, path):
    bak = path + '.bak'
    if not os.path.exists(bak):
        shutil.copyfile(path, bak)
    wb.save(path)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[1])
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('prefill')
    p.add_argument('sheet')
    p.add_argument('--ref', required=True)
    p.add_argument('--names')
    p.add_argument('--lines', action='store_true',
                   help='also fill dialogue whose Japanese matches the reference '
                        'verbatim - off by default, see PREFILL FIRST')
    p = sub.add_parser('export')
    p.add_argument('sheet')
    p.add_argument('out')
    p.add_argument('--rows', type=int, default=600)
    p = sub.add_parser('import')
    p.add_argument('sheet')
    p.add_argument('done')
    p.add_argument('--dry-run', action='store_true')
    p.add_argument('--overwrite', action='store_true')
    p = sub.add_parser('status')
    p.add_argument('sheet')
    a = ap.parse_args()
    {'prefill': cmd_prefill, 'export': cmd_export, 'import': cmd_import,
     'status': cmd_status}[a.cmd](a)


if __name__ == '__main__':
    main()
