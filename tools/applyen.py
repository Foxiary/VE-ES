"""
applyen.py - write translations into the English build using the sheet's EN ID.

    python applyen.py <sheet.xlsx> <script_dir> <out_dir> [--dry-run]

WHY THIS IS SIMPLER THAN THE OTHER TOOLS
    applystory.py locates a row by searching for its source text, and
    portjp2us.py carries a JP-anchored row across builds by structural
    coordinate. Both exist because the sheet used to hold only Japanese.

    This sheet also carries the English line (column D) and the block it came
    from (column E, "EN ID"), so a row addresses its target directly. Measured
    on all 54 sheets: 95,355 EN IDs point at a block whose text matches column D
    exactly, and none point anywhere wrong. No searching, no duplicate
    resolution, no alignment.

COLUMNS
    A = ID (Japanese build)   B = Japanese   C = Vietnamese
    D = English              E = EN ID      F = EN Note

    Column B says "English" in the header, but holds Japanese - the header is
    wrong, inherited from the original sheet.

SAFETY
    The offset is trusted only after the block's text is confirmed to equal
    column D. A mismatch means the sheet was built against a different dump, so
    the row is skipped and counted rather than written blind.

    Inline markup must also match. A translation that gains or loses #NAME
    relative to the line it replaces can leave the engine resolving a name with
    no name context, which crashes it - that is what broke 605.DAT before.

    --max-bytes caps the written line length. No text block in either stock
    build exceeds 84 bytes - the Japanese and English builds were compiled
    independently and both stop at exactly 84 - which looks like an engine
    constant rather than a coincidence. Vietnamese with diacritics spends two
    bytes per accented letter, so 1,305 lines land above it. Left uncapped by
    default because that ceiling is inferred, not proven; pass --max-bytes 84
    to build the conservative version.
"""
import argparse
import collections
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stcm2l import load as load_script           # noqa: E402
from linebreak import to_game                    # noqa: E402

EN_ID_RX = re.compile(r'^([\d.]+)_+([0-9A-Fa-f]+)_(text|name|var)$')
MARKUP_RX = re.compile(r'#[A-Za-z][A-Za-z0-9]*')

COL_VI = 2          # C
COL_EN = 3          # D
COL_EN_ID = 4       # E


def markup(text):
    return collections.Counter(MARKUP_RX.findall(text))


def plan(ws, script, max_bytes=0, longrows=None):
    """Return (repl, stats). repl maps data_off -> payload bytes."""
    by_off = {off: text.strip() for off, text in script.texts()}
    repl = {}
    st = collections.Counter()
    for r in ws.iter_rows(min_row=2, values_only=True):
        if not r or not r[0]:
            continue
        st['rows'] += 1
        en = to_game(str(r[COL_EN]).strip()) if len(r) > COL_EN and r[COL_EN] else ''
        vi = to_game(str(r[COL_VI]).strip()) if len(r) > COL_VI and r[COL_VI] else ''
        eid = str(r[COL_EN_ID]).strip() if len(r) > COL_EN_ID and r[COL_EN_ID] else ''
        if not vi:
            st['no_translation'] += 1
            continue
        if not en:
            st['no_english'] += 1          # JP-only line, absent from this build
            continue
        m = EN_ID_RX.match(eid)
        if not m:
            st['bad_en_id'] += 1
            continue
        off = int(m.group(2), 16)
        cur = by_off.get(off)
        if cur is None:
            st['offset_not_a_block'] += 1
            continue
        if cur != en:
            st['text_mismatch'] += 1       # sheet built against a different dump
            continue
        if markup(vi) != markup(cur):
            st['markup_mismatch'] += 1
            continue
        if off in repl:
            st['duplicate_target'] += 1
            continue
        payload = vi.encode('utf-8')
        if len(payload) > 84:
            st['over_84'] += 1
            if longrows is not None:
                longrows.append((eid, len(payload), len(en), vi))
            if max_bytes and len(payload) > max_bytes:
                st['too_long'] += 1
                continue
        repl[off] = payload + b'\x00'
        st['applied'] += 1
    return repl, st


def main():
    ap = argparse.ArgumentParser(description='apply translations via EN ID')
    ap.add_argument('xlsx')
    ap.add_argument('script_dir')
    ap.add_argument('out_dir')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--sheet', action='append')
    ap.add_argument('--report', help='write over-length lines to this CSV')
    ap.add_argument('--max-bytes', type=int, default=0,
                    help='skip lines longer than this in UTF-8 bytes; no stock '
                         'block exceeds 84 (0 = no cap)')
    a = ap.parse_args()

    import openpyxl
    wb = openpyxl.load_workbook(a.xlsx, data_only=True)
    names = a.sheet or [n for n in wb.sheetnames if n.isdigit()]
    if not a.dry_run:
        os.makedirs(a.out_dir, exist_ok=True)

    tot = collections.Counter()
    all_long = []
    print('%-7s %8s %8s %9s %9s %9s' %
          ('sheet', 'rows', 'applied', 'no_engl', 'mismatch', 'markup'))
    for n in names:
        src = os.path.join(a.script_dir, '%s.DAT' % n)
        if not os.path.exists(src):
            continue
        script = load_script(src)
        longrows = []
        repl, st = plan(wb[n], script, a.max_bytes, longrows)
        all_long += [(n,) + r for r in longrows]
        tot.update(st)
        print('%-7s %8d %8d %9d %9d %9d' %
              (n, st['rows'], st['applied'], st['no_english'],
               st['text_mismatch'], st['markup_mismatch']))
        if not a.dry_run:
            with open(os.path.join(a.out_dir, '%s.DAT' % n), 'wb') as fh:
                fh.write(script.build(repl))
    print('-' * 56)
    print('rows %s | applied %s' % (format(tot['rows'], ','), format(tot['applied'], ',')))
    for k in ('no_translation', 'no_english', 'bad_en_id', 'offset_not_a_block',
              'text_mismatch', 'markup_mismatch', 'duplicate_target', 'too_long'):
        if tot[k]:
            print('  bo qua - %-20s %s' % (k, format(tot[k], ',')))
    if tot['over_84']:
        print('dai qua 84 byte: %s dong' % format(tot['over_84'], ','))
    if a.report and all_long:
        import csv
        with open(a.report, 'w', newline='', encoding='utf-8-sig') as fh:
            w = csv.writer(fh)
            w.writerow(['sheet', 'en_id', 'vi_bytes', 'en_bytes', 'vietnamese'])
            w.writerows(all_long)
        print('danh sach cau qua dai -> %s' % a.report)
    return 0


if __name__ == '__main__':
    sys.exit(main())
