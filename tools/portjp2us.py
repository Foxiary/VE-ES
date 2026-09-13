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
    113 of 117 files have identical instruction counts, but four differ by 1-3
    instructions, which would put a naive index mapping out of phase from that
    point on. So the two streams are aligned with difflib on a per-instruction
    signature (parameter count, block count, block sizes), and only the runs
    difflib reports as EQUAL are used. Anything in an inserted or replaced run
    is skipped rather than guessed at.

SAFETY
    A block is only overwritten when the target block also decodes as text.
    Writing a translation over a numeric block would corrupt the script, so a
    mismatch there is skipped and counted.
"""
import argparse
import difflib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stcm2l import load as load_script           # noqa: E402
from checksheet import load_sheet, rows_of       # noqa: E402


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


def port_file(ws, jp_path, tgt_path):
    jp = load_script(jp_path)
    tgt = load_script(tgt_path)
    found, stats = locate(jp, ws)
    amap = align(jp, tgt)

    repl = {}
    skipped_align = skipped_type = 0
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
        repl[blk.data_off] = text.encode('utf-8') + b'\x00'
    stats.update(applied=len(repl), skip_align=skipped_align,
                 skip_type=skipped_type, aligned=len(amap),
                 ins_jp=len(jp.instructions), ins_tgt=len(tgt.instructions))
    return tgt, repl, stats


def main():
    ap = argparse.ArgumentParser(description='port a JP-anchored translation to another build')
    ap.add_argument('xlsx')
    ap.add_argument('jp_dir')
    ap.add_argument('target_dir')
    ap.add_argument('out_dir')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--sheet', action='append')
    a = ap.parse_args()

    wb = load_sheet(a.xlsx)
    names = a.sheet or [n for n in wb.sheetnames if n.isdigit()]
    if not a.dry_run:
        os.makedirs(a.out_dir, exist_ok=True)

    tot = dict(rows=0, matched=0, applied=0, skip_align=0, skip_type=0)
    print('%-7s %8s %8s %8s %7s %7s' %
          ('sheet', 'rows', 'matched', 'applied', 'skipA', 'skipT'))
    for n in names:
        jp_p = os.path.join(a.jp_dir, '%s.DAT' % n)
        tg_p = os.path.join(a.target_dir, '%s.DAT' % n)
        if not (os.path.exists(jp_p) and os.path.exists(tg_p)):
            continue
        tgt, repl, st = port_file(wb[n], jp_p, tg_p)
        for k in tot:
            tot[k] += st[k]
        print('%-7s %8d %8d %8d %7d %7d' % (n, st['rows'], st['matched'],
              st['applied'], st['skip_align'], st['skip_type']))
        if not a.dry_run:
            with open(os.path.join(a.out_dir, '%s.DAT' % n), 'wb') as fh:
                fh.write(tgt.build(repl))
    print('-' * 52)
    print('rows %s | matched %s | applied %s | bo qua: lech dong %s, sai kieu %s'
          % (format(tot['rows'], ','), format(tot['matched'], ','),
             format(tot['applied'], ','), format(tot['skip_align'], ','),
             format(tot['skip_type'], ',')))
    return 0


if __name__ == '__main__':
    sys.exit(main())
