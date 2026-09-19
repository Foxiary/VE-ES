"""
portjp2us.py - carry a JP-anchored translation over to another region's scripts.

    python portjp2us.py <sheet.xlsx> <jp_dir> <target_dir> <out_dir> [--dry-run]

WHY THIS EXISTS
    The spreadsheet was built against the Japanese build: its source column is
    Japanese, so rows can only be located in the JP scripts. Playing on the
    English build instead means the text has to be moved across.

    Content matching cannot bridge the two - the same line reads differently in
    each language. What does bridge them is structure: both builds compile from
    the same source, so the instruction stream lines up.

HOW ROWS ARE ADDRESSED
    Not by byte offset - those differ between builds. Each translated line is
    reduced to a structural coordinate (instruction index, block index) in the
    JP file, then written at the same coordinate in the target file.

ALIGNMENT
    113 of 117 files have identical instruction counts and map one to one. Four
    differ by 1-3 instructions, which would put a naive index mapping out of
    phase from that point on, so those are aligned with difflib on a
    per-instruction signature of (parameter count, block count) - block sizes
    are excluded because they follow the text, which differs by language.
    Only the runs difflib reports as EQUAL are used.

SAFETY
    Two guards, both of which leave the original text in place rather than risk
    corruption:
      - a block is overwritten only when the target block also decodes as text,
        so a translation never lands on a numeric block;
      - lines longer than --max-bytes are skipped. That cap is a stand-in for
        the real constraint, which is rendered WIDTH, not bytes; `textwidth.py`
        measures the width and CLAUDE.md records the box sizes.
"""
import argparse
import collections
import difflib
import re
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stcm2l import load as load_script           # noqa: E402
from checksheet import load_sheet, rows_of       # noqa: E402


MARKUP_RX = re.compile(r'#[A-Za-z][A-Za-z0-9]*')


def count_markup(text):
    """Multiset of inline engine commands in a line, e.g. {'#NAME': 1}."""
    return collections.Counter(MARKUP_RX.findall(text))


def signature(ins):
    """Structural fingerprint of an instruction.

    Deliberately excludes block sizes: a block's size follows its text, and the
    text is in a different language in each build, so including it makes almost
    every instruction look different and the alignment collapses.
    """
    return (len(ins.params), len(ins.blocks))


def align(a, b):
    """Map instruction index in `a` -> index in `b`.

    Equal instruction counts mean the streams correspond one to one, which is
    the case for 113 of 117 files. The rest differ by one to three instructions
    and are aligned with difflib, keeping only the runs it reports as EQUAL.
    """
    if len(a.instructions) == len(b.instructions):
        return {i: i for i in range(len(a.instructions))}
    sa = [signature(i) for i in a.instructions]
    sb = [signature(i) for i in b.instructions]
    out = {}
    sm = difflib.SequenceMatcher(a=sa, b=sb, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == 'equal':
            for k in range(i2 - i1):
                out[i1 + k] = j1 + k
    return out


def locate(jp, ws):
    """{(ins_idx, blk_idx): translated text} using content matching on JP."""
    index = {}
    for ins_i, ins in enumerate(jp.instructions):
        for blk_i, b in enumerate(ins.blocks):
            t = b.text()
            if t and t.strip():
                index.setdefault(t.strip(), []).append((ins_i, blk_i, b.data_off))

    used = set()
    found = {}
    stats = dict(rows=0, matched=0, missing=0)
    for _rid, hint, _kind, src, tgt in rows_of(ws):
        src, tgt = src.strip(), tgt.strip()
        if not src:
            continue
        stats['rows'] += 1
        cands = index.get(src)
        if not cands:
            stats['missing'] += 1
            continue
        stats['matched'] += 1
        free = [c for c in cands if c[:2] not in used]
        if not free:
            continue
        ins_i, blk_i, _off = min(free, key=lambda c: abs(c[2] - hint))
        used.add((ins_i, blk_i))
        if tgt:
            found[(ins_i, blk_i)] = tgt
    return found, stats


def port_file(ws, jp_path, tgt_path, max_bytes=0, fit_only=False):
    jp = load_script(jp_path)
    tgt = load_script(tgt_path)
    found, stats = locate(jp, ws)
    amap = align(jp, tgt)

    repl = {}
    skipped_align = skipped_type = skipped_long = skipped_markup = 0
    for (ins_i, blk_i), text in found.items():
        if ins_i not in amap:
            skipped_align += 1
            continue
        t_ins = tgt.instructions[amap[ins_i]]
        if blk_i >= len(t_ins.blocks):
            skipped_align += 1
            continue
        blk = t_ins.blocks[blk_i]
        if not blk.text():                      # target block is not text
            skipped_type += 1
            continue
        # The markup must match the block being overwritten. Content matching
        # can pick the neighbouring line when two are near-identical, which
        # swaps a pair of adjacent lines. Harmless-looking, except that it can
        # drop #NAME[1] into a block whose instruction has no name context -
        # the engine then resolves a name from a garbage pointer and strcmp
        # walks off the end of memory. That is the crash seen on 605.DAT.
        if count_markup(text) != count_markup(blk.text() or ''):
            skipped_markup += 1
            continue
        payload = text.encode('utf-8')
        # Changing a block's size is safe. The rule this flag was built for was
        # real as an observation - same size ran, one byte either way did not -
        # but the cause was not the size. `stcm2l.build()` copied three absolute
        # addresses through without rebasing them: the call target in `opcode`
        # when global_call is 1, the jump target in each parameter's second word
        # for opcodes 3 and 6, and the file size at COLLECTION_LINK+4. All three
        # are rebased now, and the English build runs with 94,641 lines written
        # at full length.
        #
        # An intermediate explanation - that the crashes came from misalignment
        # writing the right text in the wrong place - does not survive either:
        # a build differing from stock by ONE line in the correct slot, eight
        # bytes longer, still went to a black screen. Nothing was misaligned.
        #
        # --fit-only is kept because it is still the safest way to patch a build
        # whose row addressing is uncertain, not because sizes are fixed.
        if fit_only:
            cap = len(blk.raw)
            if len(payload) + 1 > cap:
                skipped_long += 1
                continue
            payload = payload + b'\x00' * (cap - len(payload) - 1)
        # There is no byte limit: a probe build drew lines of 100 up to 800
        # bytes and the game ran through all of them. 84 bytes is only where
        # the stock text happens to stop. What a long line does is overflow the
        # box on WIDTH - see `textwidth.py`, which measures that directly.
        # --max-bytes is a blunt stand-in, kept for callers that have no font.
        if max_bytes and len(payload) > max_bytes:
            skipped_long += 1
            continue
        repl[blk.data_off] = payload + b'\x00'
    stats.update(applied=len(repl), skip_align=skipped_align,
                 skip_type=skipped_type, skip_long=skipped_long,
                 skip_markup=skipped_markup,
                 aligned=len(amap), ins_jp=len(jp.instructions),
                 ins_tgt=len(tgt.instructions))
    return tgt, repl, stats


def main():
    ap = argparse.ArgumentParser(description='port a JP-anchored translation to another build')
    ap.add_argument('xlsx')
    ap.add_argument('jp_dir')
    ap.add_argument('target_dir')
    ap.add_argument('out_dir')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--sheet', action='append')
    ap.add_argument('--fit-only', action='store_true',
                    help='only write lines that fit the original block, padded '
                         'with NUL so block sizes never change; a fallback for '
                         'uncertain addressing, not an engine requirement')
    ap.add_argument('--max-bytes', type=int, default=84,
                    help='skip lines longer than this in UTF-8 bytes; the stock '
                         'build never exceeds 84 (0 disables the cap)')
    a = ap.parse_args()

    wb = load_sheet(a.xlsx)
    names = a.sheet or [n for n in wb.sheetnames if n.isdigit()]
    if not a.dry_run:
        os.makedirs(a.out_dir, exist_ok=True)

    tot = dict(rows=0, matched=0, applied=0, skip_align=0, skip_type=0,
               skip_long=0, skip_markup=0)
    print('%-7s %8s %8s %8s %7s %7s %7s' %
          ('sheet', 'rows', 'matched', 'applied', 'skipA', 'skipT', 'skipL'))
    for n in names:
        jp_p = os.path.join(a.jp_dir, '%s.DAT' % n)
        tg_p = os.path.join(a.target_dir, '%s.DAT' % n)
        if not (os.path.exists(jp_p) and os.path.exists(tg_p)):
            continue
        tgt, repl, st = port_file(wb[n], jp_p, tg_p, a.max_bytes, a.fit_only)
        for k in tot:
            tot[k] += st[k]
        print('%-7s %8d %8d %8d %7d %7d %7d' % (n, st['rows'], st['matched'],
              st['applied'], st['skip_align'], st['skip_type'], st['skip_long']))
        if not a.dry_run:
            with open(os.path.join(a.out_dir, '%s.DAT' % n), 'wb') as fh:
                fh.write(tgt.build(repl))
    print('-' * 52)
    print('rows %s | matched %s | applied %s | bo qua: lech dong %s, sai kieu %s, qua dai %s'
          % (format(tot['rows'], ','), format(tot['matched'], ','),
             format(tot['applied'], ','), format(tot['skip_align'], ','),
             format(tot['skip_type'], ','), format(tot['skip_long'], ',')))
    print('bo qua vi markup khong khop block goc: %s' % format(tot['skip_markup'], ','))
    return 0


if __name__ == '__main__':
    sys.exit(main())
