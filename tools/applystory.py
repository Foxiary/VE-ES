"""
applystory.py - apply a translation spreadsheet to STCM2L script files.

    python applystory.py <sheet.xlsx> <script_dir> <out_dir> [--report miss.csv]
    python applystory.py ... --dry-run          # report only, write nothing

The spreadsheet holds one worksheet per script file (100, 101, ...) with
columns: ID | source | target | note.

MATCHING BY CONTENT, NOT BY OFFSET
    The offsets embedded in the IDs do not agree with the shipped files - they
    drift by a different amount per file (+28 in one, 0 in another), so they
    cannot be used to locate a string. Matching is done on the source text
    instead, comparing stripped strings because blocks often start with an
    ideographic space that the sheet dropped.

PICKING AMONG DUPLICATES
    A line can occur in several places. The ID offset is still useful as a
    *hint*: although shifted, the ordering holds, so the candidate nearest the
    hint is chosen and then consumed so two rows never claim one block.
    Rows whose text matches nothing are reported, never guessed at.

The payload written is UTF-8 plus a NUL; stcm2l.build() pads to 4 bytes and
re-offsets everything downstream, so a translation may be longer than the
original.
"""
import argparse
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stcm2l import load as load_script           # noqa: E402
from checksheet import load_sheet, rows_of       # noqa: E402


def build_index(script):
    """{stripped text: [data_off, ...]} in file order."""
    idx = {}
    for off, text in script.texts():
        k = text.strip()
        if k:
            idx.setdefault(k, []).append(off)
    return idx


def plan_sheet(ws, script):
    """Decide which block each translated row should overwrite.

    Returns (repl, stats, misses) where repl maps data_off -> bytes.
    """
    idx = build_index(script)
    used = set()
    repl = {}
    stats = dict(rows=0, translated=0, matched=0, ambiguous=0,
                 missing=0, taken=0)
    misses = []

    for rid, hint, kind, src, tgt in rows_of(ws):
        src, tgt = src.strip(), tgt.strip()
        if not src:
            continue
        stats['rows'] += 1
        cands = idx.get(src)
        if not cands:
            stats['missing'] += 1
            if tgt:
                misses.append((rid, kind, len(src), len(tgt)))
            continue
        stats['matched'] += 1
        if len(cands) > 1:
            stats['ambiguous'] += 1
        free = [o for o in cands if o not in used]
        if not free:
            stats['taken'] += 1          # every copy already claimed
            continue
        # ID offsets are shifted but ordered, so nearest-to-hint is the right pick
        off = min(free, key=lambda o: abs(o - hint))
        used.add(off)
        if not tgt:
            continue
        stats['translated'] += 1
        repl[off] = tgt.encode('utf-8') + b'\x00'
    return repl, stats, misses


def main():
    ap = argparse.ArgumentParser(description='apply a translation sheet to scripts')
    ap.add_argument('xlsx')
    ap.add_argument('script_dir')
    ap.add_argument('out_dir')
    ap.add_argument('--report', help='write unmatched rows to this CSV')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--sheet', action='append', help='limit to these worksheets')
    a = ap.parse_args()

    wb = load_sheet(a.xlsx)
    names = a.sheet or [n for n in wb.sheetnames if n.isdigit()]
    if not a.dry_run:
        os.makedirs(a.out_dir, exist_ok=True)

    tot = dict(rows=0, translated=0, matched=0, ambiguous=0, missing=0, taken=0)
    all_miss = []
    print('%-7s %8s %8s %8s %8s %8s' %
          ('sheet', 'rows', 'matched', 'applied', 'ambig', 'missing'))
    for n in names:
        src = os.path.join(a.script_dir, '%s.DAT' % n)
        if not os.path.exists(src):
            continue
        script = load_script(src)
        repl, st, miss = plan_sheet(wb[n], script)
        for k in tot:
            tot[k] += st[k]
        all_miss += [(n,) + m for m in miss]
        print('%-7s %8d %8d %8d %8d %8d' %
              (n, st['rows'], st['matched'], st['translated'],
               st['ambiguous'], st['missing']))
        if not a.dry_run:
            out = script.build(repl)
            with open(os.path.join(a.out_dir, '%s.DAT' % n), 'wb') as fh:
                fh.write(out)

    print('-' * 52)
    print('rows %s | matched %s (%.1f%%) | applied %s | ambiguous %s | missing %s'
          % (format(tot['rows'], ','), format(tot['matched'], ','),
             tot['matched'] * 100 / tot['rows'] if tot['rows'] else 0,
             format(tot['translated'], ','), format(tot['ambiguous'], ','),
             format(tot['missing'], ',')))
    if tot['taken']:
        print('bo qua vi moi ban sao da bi dong khac chiem: %s' % format(tot['taken'], ','))

    if a.report and all_miss:
        with open(a.report, 'w', newline='', encoding='utf-8-sig') as fh:
            w = csv.writer(fh)
            w.writerow(['sheet', 'id', 'kind', 'source_len', 'target_len'])
            w.writerows(all_miss)
        print('danh sach khong khop -> %s (%s dong)' % (a.report, format(len(all_miss), ',')))
    return 0


if __name__ == '__main__':
    sys.exit(main())
