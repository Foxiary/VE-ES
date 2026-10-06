"""
applyvi.py - write the translation from a mksheet.py workbook into the scripts.

    python applyvi.py work/virche_vi.xlsx STORY.cpk work/story-vi
    python applyvi.py work/virche_vi.xlsx work/story-us out --dry-run
    python applyvi.py work/virche_vi.xlsx STORY.cpk out --fit-width

The script source is a .cpk or a directory of .DAT files; the translation is the
workbook `mksheet.py --merge` produces, whose target column is filled in.

ADDRESSED BY ID, NOT BY SEARCHING
    `applystory.py` finds a row's target by searching the file for its source
    text, then picks among duplicate hits by nearest offset - it has to, because
    the sheet it was written for carries no usable address. A mksheet workbook
    does: the id embeds the exact byte offset of the block in the build it was
    extracted from, so a row names its target outright. 28,141 rows that are
    ambiguous under content matching are exact here.

    The offset is still checked before it is used: the block it names must
    already hold the sheet's source text. A mismatch means the workbook was
    built from a different dump, and the row is skipped and counted rather than
    written blind.

WHY GROWING A BLOCK IS SAFE NOW
    Blocks used to have to keep their exact size. `portjp2us.py` records that a
    same-size replacement runs while one byte more or less crashes, and that a
    change in the very last instruction - with nothing after it to move - runs
    fine. That is the signature of a stale pointer, and it was one: when
    `global_call` is 1 the instruction's second field is not an opcode but the
    ADDRESS of the instruction to call, and `stcm2l.build()` copied it through
    unrebased. Measured on the English build, 350,273 of 718,773 instructions
    are calls, and after growing the text blocks of one file 90.7% of them
    pointed into the middle of the wrong instruction.

    `stcm2l.build()` now rebases them, and `Script.call_targets()` expresses the
    call graph in instruction indices so a rebuild can be compared against the
    original - which this tool does for every file it writes, refusing to write
    one whose graph moved.

THE LIMIT IS WIDTH, NOT BYTES
    The structural limit above is gone, and the byte one turned out never to
    have existed: a probe build put lines of 100, 150, 200, 300, 500 and 800
    bytes into the prologue and the game ran through all of them. What it did
    instead was draw them straight off the right of the screen. The text box
    overflows on WIDTH.

    Bytes are a poor stand-in for width. Vietnamese spends two bytes on every
    accented letter and draws it as one glyph of ordinary width, so the byte
    count runs ahead of the real size; a capital-heavy English line does the
    opposite.

    So the width is measured through `textwidth.py`, which sums the glyph
    advances out of the .ffu font table. Two things about that measurement have
    to be right or every number it produces is wrong:

    MEASURE THE FONT THAT SHIPS. The build replaces SYSTEM.cpk with regenerated
    Vietnamese fonts whose metrics differ from the stock English ones - the same
    sentence measures 1851 units against the stock advfont1 and 2123 against the
    shipped one, 15% apart. `--font` therefore defaults to `dist/SYSTEM.cpk`,
    what `build.py` writes and what gets installed; falling back to the stock
    archive is possible but says so loudly, because the answer is then wrong.

    THE CEILING IS THE BOX, NOT THE WIDEST STOCK LINE. The widest line the stock
    game happens to draw is only a lower bound - English never needed a longer
    one - and using it as a limit flags lines that render perfectly well. The
    real widths come from `textwidth.py`, read off a probe build: 3200 units for
    narration, 2990 for the message box, 2430 for the backlog. The backlog is
    the binding one, since every line of dialogue is replayed there.

    `--fit-width` skips whatever overflows that ceiling in any of the four
    fonts; `--max-width N` is a flat cap for setting a number by hand. Both are
    off by default - the tool reports what would overflow and leaves the call to
    a human. `--max-bytes` still works for the older workflow but measures the
    wrong quantity.

MARKUP MUST SURVIVE
    A line that gains or loses `#NAME[1]` relative to the block it replaces can
    leave the engine resolving a name with no name context, which is what broke
    605.DAT. The commands are counted exactly - `#NAME[k]`, `#Color[k]`, `#n` -
    rather than with a greedy `#\\w+`, which would read `#nto` and `#nand` as
    different commands.

    COUNTED OVER THE BOX, NOT THE LINE. Counting them line by line refused 851
    lines, and most of that was the check being wrong rather than the
    translation. The Vietnamese was written against the Japanese build, which
    divides a message box into different lines than the English one, so a
    `#NAME[1]` routinely sits on the neighbouring slot of the SAME box: the
    commands balance across the box and not along either line of it.

        EN  'Yves was asked about his past with #NAME[1]' | 'in that roundabout way.'
        VI  'Khi anh do hoi mot cach vong vo'             |'ve qua khu voi #NAME[1]...'

    So a `text` line whose own commands balance is written on its own, and one
    that does not asks its box for cover: `reflow.boxes_of` names the slots of
    each box, and the box is written only if it balances as a whole AND every
    slot of it is translated. Half a box cannot be written - a slot that is not
    written keeps its English - so a box with a blank slot is refused entire.

    DROPPING `#n` IS ALLOWED, ADDING ONE IS NOT. `#n` is a line break inside one
    slot, and the translator often joined what English broke in two. Dropping
    one draws fewer lines in the same box, which the width pass has already
    confirmed fits; adding one draws more and can push text out of the box.

    `var` and `name` keep the strict line-by-line count. A `var` instruction
    holds two ALTERNATIVE versions of the same box - one naming 'Ceres'
    outright, one using `#NAME[1]` for a player-named protagonist - not two
    consecutive lines, so there is no box to count over and a half-sentence in
    one of them is a half-sentence on screen.

    THE JAPANESE LINE IS A VALID ANSWER TOO. The translation follows the
    Japanese build, so a line - or, for `text`, a box - whose commands match
    the Japanese at that position is written even where it disagrees with the
    English. The two builds disagree more than one would guess: in 402/11750
    and 500/8343 the Japanese names the heroine in one version of the box and
    deliberately not in the other, while English named her in both. Measured on
    sheet (10) this writes 263 more lines and takes the refusals from 330 to 67.
    `#n` is the exception and still answers to the English block. The Japanese
    column is the one `mksheet.py` fills structurally; a row with no Japanese
    counterpart gets no exception. See keeps_jp().

    A COLOUR MAY MOVE WITHIN ITS VERSION. Vietnamese orders a sentence
    differently, so a highlighted phrase lands a line up or down inside the
    same `var` version, and 22 lines of sheet (10) were refused for nothing
    else. colour_moved() lets them through when the pair closes on its own line,
    the version as a whole carries the English or Japanese colour commands, and
    names stay line for line. The version boundary is what makes that safe: a
    pair moved into the OTHER version is still refused, and one opcode with no
    separator between versions is cut by split_by_repeat(). Of the 45 lines left
    after it, 43 are the same thing with `#NAME[1]` instead of `#Color`, which
    stays strict on purpose.
"""
import argparse
import collections
import csv
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stcm2l import Script                          # noqa: E402
from cpk import CPK                                # noqa: E402
from textwidth import Widths, CEILING, shown       # noqa: E402
from linebreak import to_game                      # noqa: E402
from mksheet import detect_delta                   # noqa: E402
from reflow import boxes_of                        # noqa: E402

ID_RX = re.compile(r'^\d+___([0-9A-Fa-f]+)_(text|name|choice|title|var)$')
MARKUP_RX = re.compile(r'#(?:NAME|Color)\[\d+\]|#n')
NL = '#n'                       # a line break inside one slot, not a command

HEAD_ID = 'id'
HEAD_SRC = 'nguon (en)'
HEAD_TGT = 'tieng viet'
HEAD_JP = 'tieng nhat'          # optional: what keeps_jp() compares against

# Why a line's commands were refused. Kept in one place so the per-sheet column
# and the summary cannot drift apart, and listed in the order they are printed.
REFUSED = ('markup lech', 'khung lech lenh', 'khung them #n',
           'khung thieu ban dich')


def markup(text):
    return collections.Counter(MARKUP_RX.findall(text or ''))


def keeps_markup(tgt, cur):
    """Whether a replacement keeps the commands of the text it overwrites.

    Every command has to survive one for one, with `#n` the single exception:
    the replacement may carry fewer of them than the original but never more.
    See "DROPPING `#n` IS ALLOWED" above. Both arguments are `markup()` counts,
    so this works on one line or on a whole box summed together.
    """
    if tgt[NL] > cur[NL]:
        return False
    return all(tgt[k] == cur[k] for k in set(tgt) | set(cur) if k != NL)


def keeps_jp(tgt, cur, jp):
    """Whether a replacement carries the commands of the JAPANESE line instead.

    The translation is made from the Japanese build, not the English one, and
    the two do not always agree on markup: in 402/11750 the Japanese writes one
    version of the box with the heroine's name and the other without it
    (`#NAME[1]嬢` against `死神のお嬢さん`), while English put the name in both.
    A Vietnamese line that follows the Japanese is right, and refusing it for
    disagreeing with English left that version's first line in English inside
    an otherwise Vietnamese box.

    Safe for the same reason the Japanese game runs: the two builds are the
    same script, instruction for instruction, so a block the Japanese build
    resolves `#NAME[1]` in has the name context in English too. What broke
    605.DAT was a `#NAME[1]` landing in the WRONG block - which is what a
    drifted EN ID does, and what `relinkjp.py` removed. `#n` still answers to
    the English count: a break the English block did not have can push text out
    of a box the Japanese one never had to fit.
    """
    if tgt[NL] > cur[NL]:
        return False
    return all(tgt[k] == jp[k] for k in set(tgt) | set(jp) if k != NL)


COLOR_RX = re.compile(r'#Color\[(\d+)\]')
NAME_RX = re.compile(r'#NAME\[\d+\]')
CMD_RX = re.compile(r'#(?:NAME|Color)\[\d+\]')   # what a version must balance


def colour_closes(text):
    """Whether every colour this line opens it also closes, on the same line.

    Required of a line whose colour moved, because nothing shows the engine
    carrying a colour from one line to the next: of the 107 English and 105
    Japanese lines that use `#Color`, not one leaves a pair open.
    """
    depth = 0
    for m in COLOR_RX.finditer(text or ''):
        depth += 1 if m.group(1) != '0' else -1
        if depth not in (0, 1):
            return False
    return depth == 0


def versions(ins):
    """[[block data offset, ...]] - the versions one `var` instruction ships.

    A version is a run of consecutive line blocks, and the runs are separated
    by the number and control-word blocks the instruction carries between them
    - `text() is None`, or a payload with a control character in it. An empty
    block counts as a line: that is what an English slot left blank looks like.
    An opcode that puts no separator between its versions comes back as one run;
    split_by_repeat() then cuts it.
    """
    out, run = [], []
    for b in ins.blocks:
        t = b.text()
        if t is not None and not any(ord(c) < 0x20 for c in t):
            run.append(b.data_off)
        elif run:
            out.append(run)
            run = []
    if run:
        out.append(run)
    return out


def split_by_repeat(run, blocks):
    """[[offset, ...]] - one separator-less run cut into its versions, or None.

    One of the three `var` opcodes puts nothing between its versions, so
    versions() hands back the whole command as a single run, and counting a
    colour over that would pass a pair moved from the coloured version into the
    plain one. The versions are the same English sentence written again with
    different commands, so the English lines repeat with a period equal to one
    version's length: the smallest such period is the cut. Commands are folded
    away before comparing, and `#NAME[1]` read as the default name it replaces.
    None when the lines do not repeat - the caller then relaxes nothing.
    """
    keys = [re.sub(r'\s+', '', COLOR_RX.sub('', NAME_RX.sub(
        'Ceres', blocks[o].text() or ''))) for o in run]
    n = len(keys)
    for p in range(1, n):
        if n % p == 0 and all(keys[i] == keys[i % p] for i in range(n)):
            return [run[i:i + p] for i in range(0, n, p)]
    return None


def colour_moved(script, var_rows):
    """{row id} for `var` lines whose only fault is a command on another line.

    `var_rows` is [(row id, block offset, vietnamese, english, japanese)] for
    every translated `var` row of the file that addresses its block. Vietnamese
    orders a sentence differently, so a highlighted phrase regularly lands one
    line up or down inside the SAME version - 67 lines of sheet (10), all of
    them refused line by line although nothing is lost:

        JP  予めその人の【血】から得られる | #Color[8]【遺伝子】#Color[0]を保存……」
        VI  chúng ta phải lưu trữ sẵn #Color[8]mã gen#Color[0] | được trích xuất...

    A line is let through when all of this holds: its colour pairs close on the
    line; it adds no `#n`; and its version, taken whole, carries the same
    `#Color` AND `#NAME` commands as the English or the Japanese version, with
    every line of that version translated so that none of it keeps its English.

    `#NAME[1]` MAY MOVE TOO, BUT ONLY INSIDE ITS VERSION. It was held to its line
    at first, because a name that moves from one version to another is exactly
    the damage the per-line rule guards against - the version a renamed player
    sees would lose the name. What made that safe to lift is the version
    boundary: versions() and split_by_repeat() cut the command so that a
    command moved into the other version fails its version's total. That left
    44 lines of sheet (6) refused, English on screen, for a name placed one line
    down in the same sentence - 201/7932 is `giong em #NAME[1] nhu duc.` on
    line 3 where English put the name on line 2.
    """
    ok = set()
    by_ins = collections.defaultdict(dict)
    for rid, off, tgt, cur, jp in var_rows:
        by_ins[int(rid.split('___')[0])][off] = (rid, tgt, cur, jp)
    blocks = {b.data_off: b for b in script.blocks()}
    for ins_i, rows in by_ins.items():
        runs = versions(script.instructions[ins_i])
        if len(runs) == 1:
            runs = split_by_repeat(runs[0], blocks)
            if runs is None:
                continue                   # versions not located: relax nothing
        for run in runs:
            need = [o for o in run if o in rows or (blocks[o].text() or '').strip()]
            if not need or any(o not in rows for o in need):
                continue                   # half a version would keep English
            here = [rows[o] for o in need]
            if not all(colour_closes(t) for _r, t, _c, _j in here):
                continue
            if any(markup(t)[NL] > markup(c)[NL] for _r, t, c, _j in here):
                continue

            def colours(i):
                return sum((collections.Counter(
                    m.group(0) for m in CMD_RX.finditer(x[i] or ''))
                    for x in here), collections.Counter())
            vi, en = colours(1), colours(2)
            jp = None if any(x[3] is None for x in here) else colours(3)
            if vi == en or vi == jp:
                ok.update(x[0] for x in here)
    return ok


def fits(tgt, cur, jp):
    """keeps_markup() against English, or keeps_jp() against Japanese."""
    return keeps_markup(tgt, cur) or (jp is not None and keeps_jp(tgt, cur, jp))


def box_verdicts(boxes, info):
    """{row id: reason} for every `text` row that may not be written.

    `info` is {row id: (vietnamese, english, japanese)} for the text rows that
    got as far as the command check, japanese None when the sheet has no such
    column; `boxes` is `reflow.boxes_of` output, the real text
    slots of each message box in order, or None when the file's opcode table
    could not be located.

    A line that balances on its own is written on its own - it is never held
    back by a sibling. Only a line that does not balance asks its box for
    cover, and a box gives it on two conditions: the box balances as a whole,
    and every slot of the box is translated. A slot that is not written keeps
    its English, so half a rescued box would leave the commands of the box
    worse off than refusing all of it.

    A box that does not balance rescues nobody and is left exactly where the
    line-by-line check left it: the lines that balance are still written.
    Refusing the whole box there would hold back 34 more lines that are correct
    on their own, to no end - nothing is being carried across them.
    """
    out = {rid: 'markup lech' for rid, (tgt, cur, jp) in info.items()
           if not fits(markup(tgt), markup(cur),
                       None if jp is None else markup(jp))}
    for rids in boxes or ():
        if not any(rid in out for rid in rids):
            continue                       # every line of the box balances
        if not all(rid in info for rid in rids):
            for rid in rids:
                if rid in info:
                    out[rid] = 'khung thieu ban dich'
            continue
        tgt = sum((markup(info[rid][0]) for rid in rids), collections.Counter())
        cur = sum((markup(info[rid][1]) for rid in rids), collections.Counter())
        jp = (None if any(info[rid][2] is None for rid in rids) else
              sum((markup(info[rid][2]) for rid in rids), collections.Counter()))
        if fits(tgt, cur, jp):
            for rid in rids:
                out.pop(rid, None)         # the box covers every line in it
            continue
        # The box does not balance either: a command really was dropped or
        # invented. Nothing is being carried across lines any more, so this
        # falls back to the old outcome - the lines that balance are written,
        # the ones that do not are refused - and only the reason is restated.
        why = 'khung them #n' if tgt[NL] > cur[NL] else 'khung lech lenh'
        for rid in rids:
            if rid in out:
                out[rid] = why
    return out


def cell_str(v):
    """A cell as the text it was meant to be.

    Excel stores a cell holding `1` as a number, and openpyxl hands it back as
    the float 1.0 - so a save-slot label that reads "1" in the sheet arrives as
    "1.0" and matches nothing. Nine rows of strSystem were refused for that
    reason on the first real translation sheet. An integral float is written
    back as an integer; everything else is left alone.
    """
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return '' if v is None else str(v)


def sheet_columns(header):
    """Locate the id / source / target columns, by header then by position."""
    low = [str(c).strip().lower() if c else '' for c in header]
    def find(name, fallback):
        return low.index(name) if name in low else fallback
    return find(HEAD_ID, 0), find(HEAD_SRC, 1), find(HEAD_TGT, 2)


def plan(ws, script, max_bytes=0, longrows=None, fit_only=False,
         widths=None, ceiling=CEILING, max_width=0, fit_width=False,
         boxes=None):
    """{block data offset: payload} plus a tally of everything left out.

    With `fit_only`, a line is written only if it fits the block it replaces and
    is padded with NUL to exactly that size, so no block changes length and
    nothing in the file moves. That makes the write the exact inverse of the
    read: the same walk that found the text puts it back, and an untouched
    rebuild is already known to be byte-identical.

    `widths` turns on the width measurement: every line is compared against
    `ceiling`, the width of the narrowest box it can appear in, and one that
    would spill out of it is counted.

    `fit_width` skips a line that overflows that ceiling in any of the four
    dialogue fonts, since the player chooses between them. `max_width` is a flat
    cap on the worst font instead, for setting a number by hand.

    `boxes` are the message boxes of this file from `reflow.boxes_of`, which is
    what the command check counts over for `text` rows. The sheet has to be read
    to the end before any of them can be judged, so this runs in two passes: one
    to read and address every row, one to write the rows their box allows.
    """
    rows = ws.iter_rows(values_only=True)
    head = next(rows, ())
    c_id, c_src, c_tgt = sheet_columns(head)
    low = [str(c).strip().lower() if c else '' for c in head]
    c_jp = low.index(HEAD_JP) if HEAD_JP in low else None
    by_off = {b.data_off: b for b in script.blocks()}
    repl, st = {}, collections.Counter()
    queue = []                  # rows that name a block holding their source
    info = {}                   # text rows only: id -> (vietnamese, english)
    seen = set()                # every text row this sheet names, translated or not
    var_rows = []               # var rows addressing their block, for colour_moved()

    for r in rows:
        if not r or c_id >= len(r) or not r[c_id]:
            continue
        rid = str(r[c_id]).strip()
        m = ID_RX.match(rid)
        if not m:
            st['id khong doc duoc'] += 1
            continue
        st['rows'] += 1
        kind = m.group(2)
        if kind == 'text':
            seen.add(rid)
        # Stripped first, then converted: a trailing newline left in a cell
        # is invisible in Excel and would come back as a trailing #n.
        src = to_game(str(r[c_src]).strip()) if c_src < len(r) and r[c_src] else ''
        tgt = to_game(str(r[c_tgt]).strip()) if c_tgt < len(r) and r[c_tgt] else ''
        # An empty Japanese cell means no counterpart was found, not that the
        # Japanese line carries no commands - so it is None, and keeps_jp() is
        # not asked. Treating it as '' would let a line drop every command.
        jp = (to_game(str(r[c_jp]).strip())
              if c_jp is not None and c_jp < len(r) and r[c_jp] else None)
        if not tgt:
            st['chua dich'] += 1
            continue
        # A chapter title is "<japanese key>@<display text>" and the key is what
        # the flowchart looks the scene up by. Every translated title in the
        # sheet had lost it - and carried a line of dialogue from somewhere else
        # rather than a title - so the whole row is refused, not repaired. This
        # is the one place a wrong string is not merely wrong on screen.
        if kind == 'title' and '@' in src:
            if not tgt.startswith(src.split('@', 1)[0] + '@'):
                st['title mat khoa'] += 1
                continue
        off = int(m.group(1), 16)
        blk = by_off.get(off)
        if blk is None:
            st['offset khong phai block'] += 1
            continue
        cur = blk.text()
        if cur is None or cur.strip() != src:
            st['van ban khong khop'] += 1        # workbook built from another dump
            continue
        queue.append((rid, kind, src, tgt, off, blk, cur, jp))
        if kind == 'var':
            var_rows.append((rid, off, tgt, cur, jp))
        if kind == 'text':
            info[rid] = (tgt, cur, jp)

    # A box is only as wide as the slots this sheet carries: one it does not
    # name cannot be translated, so counting it would refuse the box for a
    # missing translation that was never owed.
    if boxes is not None:
        boxes = [[rid for rid in box if rid in seen] for box in boxes]
    refused = box_verdicts(boxes, info)
    moved = colour_moved(script, var_rows)
    for rid, kind, src, tgt, off, blk, cur, jp in queue:
        if kind == 'text':
            # Counted over the whole message box; see MARKUP MUST SURVIVE.
            why = refused.get(rid)
            if why:
                st[why] += 1
                continue
        elif markup(tgt) != markup(cur):
            # Strict against English, line by line - but a line that carries
            # exactly the Japanese line's commands follows its source.
            if jp is not None and keeps_jp(markup(tgt), markup(cur), markup(jp)):
                st['theo ban Nhat'] += 1
            elif rid in moved:
                st['mau doi dong'] += 1
            else:
                st['markup lech'] += 1
                continue
        if off in repl:
            st['trung dich'] += 1
            continue
        payload = tgt.encode('utf-8')
        # How far past the box this line draws, and how wide it is at its worst
        # across the four dialogue fonts. Both are 0 when no font was loaded.
        over_px = widest_px = 0
        if widths is not None:
            drawn = shown(tgt, kind)
            over_px = widths.over(drawn, ceiling)
            widest_px = max(widths.widest(drawn).values(), default=0)
        if over_px > 0:
            st['rong hon khung backlog'] += 1
        if len(payload) > 84:
            st['dai hon 84B'] += 1
        # The report is the list of lines someone has to shorten, so only the
        # width puts a row in it. Byte count is counted above and printed, but
        # it is not a limit: a probe build drew lines of 100 to 800 bytes and
        # the game ran through every one. Filing those here buried the rows
        # that do overflow under 1,209 that do not - on the current sheet, ALL
        # of them, since nothing overflows the backlog any more.
        if over_px > 0 and longrows is not None:
            longrows.append((rid, len(payload), len(src),
                             widest_px, over_px, tgt))
        if max_bytes and len(payload) > max_bytes:
            st['bo vi qua dai'] += 1
            continue
        if fit_width and over_px > 0:
            st['bo vi qua rong'] += 1
            continue
        if max_width and widest_px > max_width:
            st['bo vi qua rong'] += 1
            continue
        if fit_only:
            cap = len(blk.raw)
            if len(payload) + 1 > cap:
                st['khong vua block'] += 1
                continue
            payload = payload + b'\x00' * (cap - len(payload))
            repl[off] = payload
        else:
            repl[off] = payload + b'\x00'
        st['applied'] += 1
    return repl, st


def verify(original, rebuilt, same_size=False):
    """Everything that must still hold after a rebuild. Returns [] when clean."""
    bad = []
    if same_size:
        # In fit-only mode nothing may move at all, so this is checkable exactly
        # rather than by proxy: same length, and every block still where it was.
        if len(rebuilt.raw) != len(original.raw):
            bad.append('kich thuoc file doi: %d -> %d'
                       % (len(original.raw), len(rebuilt.raw)))
        if [b.data_off for b in original.blocks()] != \
                [b.data_off for b in rebuilt.blocks()]:
            bad.append('offset block bi dich')
        if [i.off for i in original.instructions] != \
                [i.off for i in rebuilt.instructions]:
            bad.append('offset lenh bi dich')
    landed, nonzero = rebuilt.check()
    if not landed:
        bad.append('walk khong dung EXPORT_DATA')
    if nonzero:
        bad.append('%d byte khac 0 bi bo qua' % nonzero)
    if len(rebuilt.instructions) != len(original.instructions):
        bad.append('so lenh doi: %d -> %d' % (len(original.instructions),
                                              len(rebuilt.instructions)))
    n = rebuilt.check_calls()
    if n:
        bad.append('%d con tro goi tro sai' % n)
    n = rebuilt.check_pointers()
    if n:
        bad.append('%d tham so tro lac' % n)
    if original.call_targets() != rebuilt.call_targets():
        bad.append('do thi goi ham bi doi')
    if original.jump_targets() != rebuilt.jump_targets():
        bad.append('do thi nhay bi doi')
    return bad


def read_scripts(path):
    """[(name, bytes)] from a .cpk or a directory of .DAT files."""
    if os.path.isdir(path):
        names = sorted(n for n in os.listdir(path) if n.endswith('.DAT'))
        return [(n, open(os.path.join(path, n), 'rb').read()) for n in names]
    c = CPK(path)
    return sorted((os.path.basename(n), c.read(r))
                  for _i, n, r in c.files() if n.endswith('.DAT'))


# Where build.py writes the archive that actually gets installed. Measuring the
# stock one instead silently answers a different question - its advfont1 makes
# the same sentence 1851 units where the shipped font makes it 2123.
SHIPPED_FONT = os.path.join('dist', 'SYSTEM.cpk')
STOCK_FONT = 'SYSTEM.cpk'


def load_fonts(path):
    """Dialogue fonts for measuring, or None. Says when it is measuring stock.

    Duplicated in mksheet.py rather than shared: putting it in textwidth.py
    would make that module import-order dependent on a build layout it does not
    otherwise know about, and the policy is eight lines.
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


def main():
    ap = argparse.ArgumentParser(
        description='apply a mksheet workbook to the scripts, addressed by id')
    ap.add_argument('xlsx')
    ap.add_argument('scripts', help='STORY.cpk or a directory of .DAT files')
    ap.add_argument('out_dir')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--sheet', action='append', help='limit to these worksheets')
    ap.add_argument('--fit-only', action='store_true',
                    help='only write lines that fit the original block, padded '
                         'with NUL so no block changes size and nothing in the '
                         'file moves')
    ap.add_argument('--font', default=SHIPPED_FONT,
                    help='the SYSTEM.cpk that will be INSTALLED, whose fonts '
                         'the game draws with; the stock archive measures a '
                         'different font and gives wrong widths')
    ap.add_argument('--ceiling', type=int, default=CEILING,
                    help='box width in advance units (default %d, the backlog, '
                         'narrowest of the three screens)' % CEILING)
    ap.add_argument('--fit-width', action='store_true',
                    help='skip every line that draws wider than the box in any '
                         'of the four dialogue fonts')
    ap.add_argument('--max-width', type=int, default=0,
                    help='skip lines that draw wider than this many pixels in '
                         'the widest font; a flat cap set by hand, unlike '
                         '--fit-width (0 = no cap)')
    ap.add_argument('--max-bytes', type=int, default=0,
                    help='skip lines longer than this many UTF-8 bytes. Bytes '
                         'are not what overflows the box - see --max-width '
                         '(0 = no cap)')
    ap.add_argument('--report', help='write over-wide / over-long lines to this CSV')
    a = ap.parse_args()

    import openpyxl
    wb = openpyxl.load_workbook(a.xlsx, read_only=True, data_only=True)
    scripts = dict(read_scripts(a.scripts))
    if not a.dry_run:
        os.makedirs(a.out_dir, exist_ok=True)

    widths = load_fonts(a.font)
    ceiling = a.ceiling
    if widths is not None:
        print('do be rong bang %s | tran %d don vi (khung backlog)'
              % (a.font, ceiling))

    names = a.sheet or [n for n in wb.sheetnames if n.isdigit()]
    tot = collections.Counter()
    longrows, broken, nodelta = [], [], []
    print('%-8s %8s %8s %9s %9s %9s' %
          ('sheet', 'rows', 'applied', 'chua dich', 'lenh', 'byte+'))
    for n in names:
        data = scripts.get('%s.DAT' % n)
        if data is None:
            continue
        script = Script(data)
        # The message boxes this file's commands are counted over. Without a
        # readable opcode table there are none, and every text line falls back
        # to being judged on its own.
        delta = detect_delta(script)
        # Every slot of the box, including the ones English left empty; `plan`
        # then drops whichever the sheet does not name. See boxes_of().
        boxes = (None if delta is None
                 else boxes_of(script, delta, n, keep_blank=True))
        if boxes is None:
            nodelta.append(n)
        mine = []
        repl, st = plan(wb[n], script, a.max_bytes, mine, a.fit_only,
                        widths, ceiling, a.max_width, a.fit_width, boxes)
        longrows += [(n,) + r for r in mine]
        tot.update(st)

        out = script.build(repl)
        problems = verify(script, Script(out), a.fit_only)
        if problems:
            broken.append((n, '; '.join(problems)))
        elif not a.dry_run:
            with open(os.path.join(a.out_dir, '%s.DAT' % n), 'wb') as fh:
                fh.write(out)
        print('%-8s %8d %8d %9d %9d %+9d%s' %
              (n, st['rows'], st['applied'], st['chua dich'],
               sum(st[k] for k in REFUSED),
               len(out) - len(data), '  <-- LOI' if problems else ''))

    print('-' * 58)
    print('rows %s | da ghi %s' % (format(tot['rows'], ','),
                                   format(tot['applied'], ',')))
    for k in ('chua dich', 'khong vua block', 'title mat khoa',
              'van ban khong khop') + REFUSED + (
              'trung dich', 'offset khong phai block', 'id khong doc duoc',
              'bo vi qua rong', 'bo vi qua dai'):
        if tot[k]:
            print('  bo qua - %-24s %s' % (k, format(tot[k], ',')))
    if tot['theo ban Nhat']:
        print('  ghi - lenh lech ban Anh nhung khop ban Nhat  %s'
              % format(tot['theo ban Nhat'], ','))
    if tot['mau doi dong']:
        print('  ghi - lenh doi sang dong khac cung phien ban  %s'
              % format(tot['mau doi dong'], ','))
    if nodelta:
        print('!! %d file khong doc duoc bang opcode, dem lenh theo tung dong: %s'
              % (len(nodelta), ' '.join(nodelta[:12])))
    if tot['rong hon khung backlog']:
        print('tran khung backlog (>%d don vi): %s dong%s' %
              (ceiling, format(tot['rong hon khung backlog'], ','),
               '' if (a.fit_width or a.max_width)
               else '  (van ghi - dung --fit-width de bo)'))
    if tot['dai hon 84B']:
        print('dai hon 84 byte: %s dong  (byte khong phai thu lam tran khung)'
              % format(tot['dai hon 84B'], ','))
    if broken:
        print('\n!! %d file KHONG duoc ghi vi kiem tra that bai:' % len(broken))
        for n, why in broken[:8]:
            print('   %s: %s' % (n, why))
    else:
        print('kiem tra sau khi dung lai: tat ca file deu dat')

    if a.report and longrows:
        with open(a.report, 'w', newline='', encoding='utf-8-sig') as fh:
            w = csv.writer(fh)
            w.writerow(['sheet', 'id', 'vi_bytes', 'en_bytes', 'vi_px',
                        'over_px', 'vietnamese'])
            w.writerows(longrows)
        print('danh sach cau qua rong -> %s (%s dong)'
              % (a.report, format(len(longrows), ',')))
    return 1 if broken else 0


if __name__ == '__main__':
    sys.exit(main())
