"""
filltitles.py - compose the scripts' chapter titles from ones already translated.

    python tools/filltitles.py prefixes "Shuuen_JP_STORY.xlsx" work/virche_vi.xlsx
    python tools/filltitles.py fill     "Shuuen_JP_STORY.xlsx" work/virche_vi.xlsx \\
                                        --prefixes work/title_prefixes.xlsx

THE SAME TITLE IS STORED TWICE, AND ONLY ONE COPY GOT TRANSLATED
    A chapter title lives in the `.DAT` that plays the scene and again in
    `dbFlowchart`, both spelled `<japanese key>@<display text>`. The incoming
    sheet carries the dbFlowchart copy and not the script copy, so 341 script
    titles arrived with no translation at all - not skipped by the translators,
    simply never in front of them.

    They are not new work. Matched on the Japanese key, 340 of the 341 have a
    body that is already translated; the two copies differ only by a chapter
    prefix the script version carries and dbFlowchart does not:

        script       死神の呪い@Act 1: The Curse of Death
        dbFlowchart  死神の呪い@The Curse of Death     -> ...@Lời nguyền của Tử thần
        composed     死神の呪い@Màn 1: Lời nguyền của Tử thần

    There are 41 distinct prefixes behind all 341 rows, which is the whole of
    the remaining work. `prefixes` writes them out; `fill` reads them back and
    composes the titles into the merged workbook, ready for `applyvi.py`.

THE PREFIX IS FOUND BY THE TAIL, NOT BY THE PUNCTUATION
    Splitting the display text on its first colon is wrong - `Yves: Salvation -
    Bouquet of Black Salvation` splits into a prefix of `Yves`. The dbFlowchart
    body is known, so the prefix is simply whatever precedes it, and a row whose
    display does not end with that body is reported rather than guessed at.

WHY IT WRITES INTO THE MERGED WORKBOOK
    These titles are derived, not authored: re-running `mksheet.py --merge`
    regenerates the workbook and drops them, and that is correct, because
    re-running this tool puts them back. The authored half - the 41 prefixes -
    lives in its own file and survives.

THE KEY MUST SURVIVE
    `applyvi.py` refuses a title whose `<japanese key>@` prefix is missing,
    because the flowchart looks the scene up by it and losing it corrupts the
    scene table rather than just the text. Everything composed here keeps the
    key verbatim from the source, and `fill` re-checks that before writing.
"""
import argparse
import collections
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from applyvi import cell_str                          # noqa: E402

PREFIX_SHEET = 'title_prefix'

# Names that stay as they are in Vietnamese. Confirmed against the sheet's own
# TABLE_NAME, where every one of them maps to itself.
CHARACTERS = {'Yves', 'Lucas', 'Mathis', 'Scien', 'Adolphe', 'Ankou', 'Salome'}


def flowchart_titles(incoming):
    """{japanese key: (english body, vietnamese body)} from the sheet's dbFlowchart."""
    out = {}
    if 'dbFlowchart' not in incoming.sheetnames:
        return out
    rows = incoming['dbFlowchart'].iter_rows(values_only=True)
    next(rows, None)
    for r in rows:
        if not r or not r[0]:
            continue
        en, vi = cell_str(r[1]).strip(), cell_str(r[2]).strip()
        if '@' not in en or not vi:
            continue
        out[en.split('@', 1)[0]] = (en.split('@', 1)[1],
                                    vi.split('@', 1)[1] if '@' in vi else vi)
    return out


def needs_filling(vi, key):
    """True when this row would produce nothing today.

    Either untranslated, or carrying something that `applyvi.py` refuses - a
    title that lost its `<key>@`, which in this sheet means the cell was filled
    with an ellipsis placeholder.
    """
    if not vi:
        return 'trong'
    if not vi.startswith(key + '@'):
        return 'mat khoa'
    return None


def scan(merged, flow):
    """[(sheet, row index, key, prefix, vi body, why)] for every fillable title."""
    out, odd = [], []
    for name in merged.sheetnames:
        if not name.isdigit():
            continue
        ws = merged[name]
        for i, row in enumerate(ws.iter_rows(min_row=2), start=2):
            vals = [c.value for c in row]
            if not vals or not vals[0]:
                continue
            if len(vals) < 6 or cell_str(vals[5]) != 'title':
                continue
            en = cell_str(vals[1]).strip()
            if '@' not in en:
                continue
            key, disp = en.split('@', 1)
            why = needs_filling(cell_str(vals[2]).strip(), key)
            if not why:
                continue
            hit = flow.get(key)
            if not hit:
                odd.append((name, en, 'khoa khong co trong dbFlowchart'))
                continue
            body_en, body_vi = hit
            if not disp.endswith(body_en):
                odd.append((name, en, 'than khac dbFlowchart (%r)' % body_en[:40]))
                continue
            prefix = disp[:-len(body_en)]
            # A real prefix ends on its separator. One that ends in a bare word
            # means dbFlowchart holds only part of the body - `A Place Sought`
            # against `Place Sought` - and composing would silently drop or
            # misplace that word, so the row is reported instead.
            if prefix and prefix.rstrip()[-1:] not in ':-–—':
                odd.append((name, en, 'than thieu dau (%r vs %r)'
                            % (disp[:44], body_en[:34])))
                continue
            out.append((name, i, key, prefix, body_vi, why))
    return out, odd


def word_map(incoming):
    """{english word: vietnamese word} learned from the sheet's own short rows.

    The prefixes are built from words the translation has already settled -
    `Act 1` is `Màn 1` and `Chapter 3` is `Chương 3` in dbFlowchart. Rather than
    decide what `Act` should be, this reads pairs that differ by exactly one
    word and takes the substitution from them, so a suggestion is the team's own
    wording or nothing at all.
    """
    pairs = collections.Counter()
    for name in incoming.sheetnames:
        if name.isdigit() or name not in ('dbFlowchart', 'strGame', 'strSystem'):
            continue
        rows = incoming[name].iter_rows(values_only=True)
        next(rows, None)
        for r in rows:
            if not r or not r[0]:
                continue
            en, vi = cell_str(r[1]).strip(), cell_str(r[2]).strip()
            if '@' in en:
                en, vi = en.split('@', 1)[1], (vi.split('@', 1)[1] if '@' in vi else vi)
            we, wv = en.split(), vi.split()
            if not vi or len(we) != len(wv) or not 1 <= len(we) <= 3:
                continue
            for x, y in zip(we, wv):
                if x != y and x.isalpha():
                    pairs[(x, y)] += 1
    out = {}
    for (x, y), n in pairs.most_common():
        # Seen once is a coincidence: one stray row aligned `Common` with
        # `tuyen` and the suggestion came out wrong. Two independent rows
        # agreeing is the bar for calling a rendering settled.
        if n >= 2 and x not in out:
            out[x] = y
    return out


def suggest(prefix, words, names):
    """The prefix in Vietnamese, or '' when any word is still an open question.

    Only substitutes words the sheet has already settled and leaves character
    names alone. A prefix carrying anything else - `Common`, `Salvation`,
    `Despair`, `Evermore` - comes back empty, because how a route or ending is
    labelled is a decision for the translators, not a lookup.
    """
    out = []
    for tok in prefix.split(' '):
        bare = tok.strip('-:,')
        if not bare or bare.isdigit() or not bare.isalpha() or bare in names:
            out.append(tok)
        elif bare in words:
            out.append(tok.replace(bare, words[bare]))
        else:
            return ''
    return ' '.join(out)


def cmd_prefixes(a):
    import openpyxl
    from mksheet import Workbook                       # noqa: E402

    incoming = openpyxl.load_workbook(a.incoming, read_only=True, data_only=True)
    merged = openpyxl.load_workbook(a.merged, read_only=True, data_only=True)
    flow = flowchart_titles(incoming)
    rows, odd = scan(merged, flow)

    count = collections.Counter(r[3] for r in rows)
    sample = {}
    for _s, _i, key, pre, body, _w in rows:
        sample.setdefault(pre, '%s@%s%s' % (key, pre, body))

    wb = Workbook(False, False)
    wb.add_readme([
        'TIEN TO CHUONG - phan con thieu de dich %d tieu de trong kich ban' % len(rows),
        '',
        'Than tieu de DA duoc dich roi, nam o sheet dbFlowchart. Ban kich ban',
        'chi khac o cai tien to dang truoc, va chi co %d tien to khac nhau.' % len(count),
        '',
        'Dien cot C. Giu nguyen dau cach va dau cau o cuoi (": ", " - ") vi',
        'no la mot phan cua tien to, khong phai ngat cau.',
        '',
        'Xong thi chay:',
        '  python tools/filltitles.py fill <bang dich> work/virche_vi.xlsx \\',
        '         --prefixes <file nay>',
        'roi applyvi.py nhu binh thuong.',
    ])
    words = word_map(incoming)
    names = {n for n in words} | set(CHARACTERS)
    names |= {w for _s, _i, _k, pre, _b, _w in rows
              for w in pre.split() if w.istitle() and w not in words}
    filled = 0
    body = []
    for i, (pre, _n) in enumerate(count.most_common()):
        vi = suggest(pre, words, CHARACTERS)
        filled += bool(vi)
        body.append(('%d___0_prefix' % i, pre, None, 'prefix', vi,
                     '%s | %d tieu de | vd %s'
                     % ('DA GOI Y - soat lai' if vi else 'CAN DICH',
                        count[pre], sample[pre][:64])))
    wb.add(PREFIX_SHEET, body)
    wb.save(a.out)

    print('%d tieu de can ghep, %d tien to khac nhau -> %s'
          % (len(rows), len(count), a.out))
    print('   %d tien to da goi y san tu chinh bang dich, %d con phai dich'
          % (filled, len(count) - filled))
    for why, n in collections.Counter(r[5] for r in rows).most_common():
        print('   %-10s %d' % (why, n))
    for s, en, msg in odd:
        print('   !! %s %s: %s' % (s, en[:46], msg))
    return 0


def cmd_fill(a):
    import openpyxl

    incoming = openpyxl.load_workbook(a.incoming, read_only=True, data_only=True)
    flow = flowchart_titles(incoming)

    pre_wb = openpyxl.load_workbook(a.prefixes, read_only=True, data_only=True)
    prefixes = {}
    it = pre_wb[PREFIX_SHEET].iter_rows(values_only=True)
    next(it, None)
    for r in it:
        if r and r[1] is not None:
            # Keyed without the trailing space, because Excel strips one on
            # save: all 41 prefixes came back as `Act 1:` where they went out as
            # `Act 1: `. The space separates the prefix from the title body, so
            # it is structure rather than wording - `fill` takes it back off the
            # source prefix below instead of asking anyone to preserve it.
            prefixes[cell_str(r[1]).rstrip()] = cell_str(r[2]).rstrip()
    done = sum(1 for v in prefixes.values() if v.strip())
    print('tien to: %d/%d da dich' % (done, len(prefixes)))

    merged = openpyxl.load_workbook(a.merged)
    rows, odd = scan(merged, flow)
    st = collections.Counter()
    for name, i, key, pre, body, why in rows:
        vi_pre = prefixes.get(pre.rstrip())
        if vi_pre is None:
            st['tien to khong co trong file'] += 1
            continue
        if not vi_pre.strip():
            st['tien to chua dich'] += 1
            continue
        # Whatever spacing the English prefix ended on, the Vietnamese ends on
        # too. See the note where `prefixes` is read.
        composed = '%s@%s%s%s' % (key, vi_pre, pre[len(pre.rstrip()):], body)
        if not composed.startswith(key + '@'):
            st['mat khoa - bo qua'] += 1        # cannot happen, checked anyway
            continue
        if not a.dry_run:
            merged[name].cell(row=i, column=3).value = composed
        st[why] += 1

    for s, en, msg in odd:
        print('   !! %s %s: %s' % (s, en[:46], msg))
    total = st['trong'] + st['mat khoa']
    print('ghep %d tieu de (%d o trong, %d o mat khoa)'
          % (total, st['trong'], st['mat khoa']))
    for k in ('tien to chua dich', 'tien to khong co trong file', 'mat khoa - bo qua'):
        if st[k]:
            print('  bo qua - %-28s %d' % (k, st[k]))
    if a.dry_run:
        print('(dry-run, khong ghi gi)')
        return 0
    if total:
        merged.save(a.merged)
        print('-> %s' % a.merged)
    return 0


def main():
    ap = argparse.ArgumentParser(
        description='compose script chapter titles from the dbFlowchart translation')
    sub = ap.add_subparsers(dest='cmd', required=True)

    p = sub.add_parser('prefixes', help='write out the chapter prefixes to translate')
    p.add_argument('incoming', help='the translation workbook, for its dbFlowchart')
    p.add_argument('merged', help='the mksheet workbook the titles are missing from')
    p.add_argument('--out', default=os.path.join('work', 'title_prefixes.xlsx'))
    p.set_defaults(fn=cmd_prefixes)

    p = sub.add_parser('fill', help='compose the titles into the merged workbook')
    p.add_argument('incoming')
    p.add_argument('merged')
    p.add_argument('--prefixes', default=os.path.join('work', 'title_prefixes.xlsx'))
    p.add_argument('--dry-run', action='store_true')
    p.set_defaults(fn=cmd_fill)

    a = ap.parse_args()
    return a.fn(a)


if __name__ == '__main__':
    sys.exit(main())
