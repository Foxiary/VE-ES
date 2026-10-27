"""
applyexe.py - write a sheet's `exe` rows back into exefs/main.

    python tools/applyexe.py work/title_quotes.xlsx work/exefs/main work/exefs-vi/main
    python tools/applyexe.py work/title_quotes.xlsx work/exefs/main out/main --dry-run
    python tools/applyexe.py work/title_quotes.xlsx work/exefs/main out/main --install

The third apply tool, for the third place text lives. `applyvi.py` patches
`.DAT` blocks, `applyui.py` rebuilds the `.gbin` / `.gstr` databases, and this
one patches the executable - the twelve title-screen quotes that are not in
romfs at all.

IT SHIPS SOMEWHERE ELSE
    A CPK mod cannot reach an executable. Ryujinx loads one from
    `mods/contents/<title id>/<name>/exefs/`, which is a different directory
    from the `romfs/` that `build.py --install` writes `SYSTEM.cpk` into, and
    the two are independent: installing this does not disturb the font and
    database mod, and rebuilding that one does not carry these quotes.
    `--install` puts the file in the right place.

A LONGER TRANSLATION IS MOVED, NOT REFUSED
    `.rodata` is a packed run of NUL-terminated strings with nothing spare
    between them, so a translation that outgrows the English cannot be written
    where the English was. Vietnamese spends two bytes on an accented letter and
    the shortest quote is 124 bytes, so this is the normal case, not the corner
    one: two sentences translated naturally came out 20-35% over.

    It is escapable because of how the quotes are reached. They are NOT
    addressed by an ADRP/ADD pair baked into `.text` - searched for, and there
    are none. Each one is held as a 64-bit pointer in a 24-byte-stride table
    near the start of `.rodata`, at `+0x08` of its record. So a string can be
    written anywhere and the pointer aimed at it.

    Where it goes is the padding between segments. `.rodata` is mapped at
    0x203000 and ends at 0x2B3028; `.data` begins at 0x2B4000, and those 4,056
    bytes in between are page alignment that nothing uses. Re-copying all twelve
    quotes at +25% needs about 2,857 of them.

    In-place is still preferred whenever the translation fits, because it leaves
    the pointer table alone and keeps the diff small. Relocation only happens
    when it must, is refused rather than truncated if the pool runs out, and is
    refused outright for a string this cannot find a pointer for.

THE FILE IS REBUILT UNCOMPRESSED
    All three NSO segments ship LZ4-compressed, and there is no compressor here.
    There does not need to be: the format has a per-segment "is compressed" flag
    (bits 0-2 of the word at 0x0C), so the rebuild clears those and writes the
    segments raw. The file grows from 1.8 MB to about 2.9 MB, which matters to
    nothing.

    What does have to be right is the rest of the header. Each segment carries a
    file offset and a size-in-file that both change when it stops being
    compressed, and bits 3-5 say all three segments are SHA256-checked, with the
    hashes at 0xA0, 0xC0 and 0xE0 taken over the DECOMPRESSED bytes. Patching
    `.rodata` without rewriting its hash produces a file that looks fine and is
    rejected on load.

    That the hash fields mean what this assumes was checked before anything was
    written: decompressing the shipped `main` and hashing the three segments
    reproduces all three stored digests exactly.

VERIFIED BY READING THE RESULT BACK
    A clean write proves nothing - the whole repo's history is clean checks over
    broken files. So `verify()` re-parses the finished NSO from disk and
    compares: `.text` and `.data` byte-identical to the original, `.rodata`
    differing only inside the spans that were patched, every patched offset
    reading back the new string, and all three hashes agreeing with the bytes
    they cover.
"""
import argparse
import collections
import hashlib
import os
import re
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from exefs import nso_segments, SEGMENTS                # noqa: E402
from applyvi import sheet_columns, cell_str             # noqa: E402
from linebreak import canon                             # noqa: E402

# `main.rodata___2BD34_exe`. Deliberately unlike every other id in the project:
# these rows address a segment offset, not a .DAT block or a .gbin cell, and no
# other apply tool should ever match them.
ID_RX = re.compile(r'^(\w+)\.(text|rodata|data)___([0-9A-Fa-f]+)_exe$')

HEADER = 0x100
FLAG_COMPRESSED = 0b111            # bits 0-2, one per segment
HASH_OFF = (0xA0, 0xC0, 0xE0)


def pointer_slots(seg, ro_mem, ro=None):
    """{string offset: [offsets in `seg`]} for every u64 in `seg` aiming at it.

    The quotes are reached through a pointer table, not through an address
    assembled in code, so retargeting one is a matter of rewriting eight bytes.
    Every 8-aligned word in the segment is read and kept if it lands on a string
    start in .rodata (`ro`, `seg` itself when not given), which finds the table
    without having to know where it begins.
    """
    ro = seg if ro is None else ro
    starts = {}
    o = 0
    while True:
        e = ro.find(b'\x00', o)
        if e < 0:
            break
        if e > o:
            starts[o] = True
        o = e + 1
    out = collections.defaultdict(list)
    for p in range(0, len(seg) - 8, 8):
        v = struct.unpack_from('<Q', seg, p)[0] - ro_mem
        if 0 <= v < len(ro) and v in starts:
            out[v].append(p)
    return out


def image(original, segs):
    """(memory image, {segment: base address}) - the three segments laid out."""
    mem = {name: struct.unpack_from('<I', original, hdr + 4)[0]
           for name, hdr in SEGMENTS}
    img = bytearray(mem['data'] + len(segs['data']))
    for name in mem:
        img[mem[name]:mem[name] + len(segs[name])] = segs[name]
    return img, mem


def relr_slots(img):
    """Every address the loader relocates through DT_RELR.

    RELR keeps the addend in the slot itself, so a pointer in one of these can
    be retargeted by rewriting the eight bytes - the loader adds the module base
    to whatever it finds there. A word outside this set is not relocated, and
    rewriting it would aim at an absolute address that does not exist.
    """
    mod0 = struct.unpack_from('<I', img, 4)[0]
    if img[mod0:mod0 + 4] != b'MOD0':
        return set()
    p = mod0 + struct.unpack_from('<i', img, mod0 + 4)[0]
    tags = {}
    while True:
        t, v = struct.unpack_from('<qQ', img, p)
        p += 16
        if t == 0:
            break
        tags.setdefault(t, v)
    if 36 not in tags:                       # DT_RELR
        return set()
    out, where = set(), 0
    for q in range(tags[36], tags[36] + tags.get(35, 0), 8):
        e = struct.unpack_from('<Q', img, q)[0]
        if e & 1 == 0:
            out.add(e)
            where = e + 8
        else:
            for i in range(63):
                if e >> (i + 1) & 1:
                    out.add(where + 8 * i)
            where += 63 * 8
    return out


def code_refs(text, base=0):
    """Addresses .text builds with ADRP followed by ADD on the same register.

    That is how AArch64 code names a string, so a string whose span one of
    these lands in is still read by code and cannot be overwritten. Matched
    loosely - the ADD may come up to eight instructions later - because a
    reference missed here is a string clobbered under code that still uses it.
    """
    out = set()
    words = struct.unpack_from('<%dI' % (len(text) // 4), text)
    for i, w in enumerate(words):
        if w & 0x9F000000 != 0x90000000:
            continue
        rd = w & 0x1F
        imm = ((w >> 29) & 3) | (((w >> 5) & 0x7FFFF) << 2)
        if imm & (1 << 20):
            imm -= 1 << 21
        page = ((base + 4 * i) & ~0xFFF) + (imm << 12)
        for x in words[i + 1:i + 9]:
            if x & 0xFFC00000 == 0x91000000 and (x >> 5) & 0x1F == rd:
                out.add(page + ((x >> 10) & 0xFFF))
                break
    return out


CRI_MESSAGE_RX = re.compile(rb'^[EW]\d{8,}[A-Z]*:')


def free_spans(original, segs, moving, reuse_cri):
    """[(rodata offset, size)] that relocated strings may be written into.

    Three sources, each only where nothing else can still read the bytes:
      - the page padding after .rodata, as before;
      - the old span of every string being moved, once its pointer is
        re-aimed - the fan disc keeps ~800 gallery and profile strings in
        `main`, and a Vietnamese translation runs ~1.6x the English bytes, far
        past the 3 KB of padding;
      - with `reuse_cri`, the CRI middleware's error messages
        (`E2010012613:Failed to ...`), which are only ever formatted into an
        error log. Code still names their first byte, so an error raised after
        this reads a Vietnamese line instead of the message. Off by default.
    A span is refused if code or any relocated pointer lands inside it, other
    than the very pointers being re-aimed.
    """
    img, mem = image(original, segs)
    ro, ro_mem = segs['rodata'], mem['rodata']
    relr = relr_slots(img)
    retargeted = {mem[seg] + p for slots in moving.values() for seg, p in slots}
    refs = collections.Counter(code_refs(segs['text'], mem['text']))
    for s in relr:
        if s not in retargeted:
            refs[struct.unpack_from('<Q', img, s)[0]] += 1

    def clear(lo, hi):
        return not any(ro_mem + o in refs for o in range(lo, hi + 1))

    spans = [(len(ro), mem['data'] - (ro_mem + len(ro)))]
    for off in moving:
        end = ro.find(b'\x00', off)
        if clear(off, end):
            spans.append((off, end + 1 - off))
    if reuse_cri:
        o = 0
        while True:
            end = ro.find(b'\x00', o)
            if end < 0:
                break
            if CRI_MESSAGE_RX.match(ro[o:end]) and o not in moving \
                    and clear(o + 1, end):
                spans.append((o, end + 1 - o))
            o = end + 1
    # Neighbours merge. Each old span is only as long as its English, and the
    # Vietnamese that has to move is by definition longer, so unmerged spans fit
    # nothing - but the gallery strings sit packed together in runs.
    merged = []
    for o, n in sorted(spans):
        if merged and merged[-1][0] + merged[-1][1] == o:
            merged[-1] = (merged[-1][0], merged[-1][1] + n)
        else:
            merged.append((o, n))
    return merged, relr


def plan(ws, segs):
    """({segment: {offset: new bytes}}, tally, [refusals])."""
    rows = ws.iter_rows(values_only=True)
    c_id, c_src, c_tgt = sheet_columns(next(rows, ()))
    out = collections.defaultdict(dict)
    st, notes = collections.Counter(), []

    for r in rows:
        if not r or c_id >= len(r) or not r[c_id]:
            continue
        rid = str(r[c_id]).strip()
        m = ID_RX.match(rid)
        if not m:
            st['id khong doc duoc'] += 1
            continue
        st['rows'] += 1
        seg, off = m.group(2), int(m.group(3), 16)

        # NOT passed through linebreak.to_game(): a break in the executable is a
        # real newline, and turning it into #n here would be the bug.
        src = cell_str(r[c_src]).strip() if c_src < len(r) else ''
        tgt = cell_str(r[c_tgt]).strip() if c_tgt < len(r) else ''
        tgt = tgt.replace('\r\n', '\n').replace('\r', '\n')

        if not tgt:
            st['chua dich'] += 1
            continue
        body = segs.get(seg)
        if body is None:
            st['segment la'] += 1
            continue
        end = body.find(b'\x00', off)
        if end < 0:
            st['offset khong phai chuoi'] += 1
            continue
        try:
            cur = body[off:end].decode('utf-8')
        except UnicodeDecodeError:
            st['offset khong phai chuoi'] += 1
            continue
        if canon(cur) != canon(src):
            st['van ban khong khop'] += 1       # sheet built from another dump
            notes.append('%s: file giu %r' % (rid, cur[:48]))
            continue
        if tgt == src:
            st['giong ban goc'] += 1
            continue

        if off in out[seg]:
            st['trung offset'] += 1
            continue
        # Placement is decided later, by `place()`: it needs the whole set
        # before it can tell whether the relocation pool is big enough.
        out[seg][off] = (rid, tgt.encode('utf-8'), end - off)
        st['nhan'] += 1

    return out, st, notes


def string_slots(original, segs):
    """{rodata offset: [(segment, offset)]} - every pointer that can be re-aimed.

    Searched in .rodata (the main game's quote table) and .data (the fan disc's
    gallery and profile tables). Where the module relocates through DT_RELR,
    only slots RELR covers count - the loader adds the base to those and to
    nothing else. The main game has no RELR, and keeps the old rule.
    """
    img, mem = image(original, segs)
    relr = relr_slots(img)
    ro_mem = mem['rodata']
    out = collections.defaultdict(list)
    for seg in ('rodata', 'data'):
        for off, ps in pointer_slots(segs[seg], ro_mem,
                                     segs['rodata']).items():
            out[off] += [(seg, p) for p in ps
                         if not relr or mem[seg] + p in relr]
    return out


def place(original, segs, accepted, reuse_cri, st, notes):
    """Write the accepted rows into the segments, moving what will not fit.

    A row that fits its own span is written there. One that does not is moved
    into a free span (see free_spans) and every pointer to it re-aimed; the
    largest strings are placed first, each into the smallest span that holds
    it. Returns ({segment: bytes}, strings moved, bytes .rodata grew by, pool).
    """
    ro_mem = struct.unpack_from('<I', original, 0x24)[0]
    slots = string_slots(original, segs)
    out = {k: bytearray(v) for k, v in segs.items()}

    moving, written = {}, {}
    for seg, rows in accepted.items():
        for off, (rid, raw, room) in sorted(rows.items()):
            if len(raw) <= room:
                out[seg][off:off + room] = raw.ljust(room, b'\x00')
                written[(seg, off)] = raw
                st['applied'] += 1
                continue
            if seg != 'rodata':
                st['dai qua cho'] += 1
                notes.append('%s: %d byte, cho co %d' % (rid, len(raw), room))
                continue
            if not slots.get(off):
                st['khong tim thay con tro'] += 1
                notes.append('%s: dai %d/%d va khong co con tro de doi'
                             % (rid, len(raw), room))
                continue
            moving[off] = (rid, raw)

    spans, _relr = free_spans(original, segs,
                              {o: slots[o] for o in moving}, reuse_cri)
    pool = sum(n for _o, n in spans)
    tail_end = len(segs['rodata'])
    free = sorted(spans, key=lambda s: s[1])
    placed = {}
    for off, (rid, raw) in sorted(moving.items(), key=lambda kv: -len(kv[1][1])):
        need = len(raw) + 1                           # the string plus its NUL
        k = next((i for i, (_o, n) in enumerate(free) if n >= need), None)
        if k is None:
            st['het cho de doi'] += 1
            notes.append('%s: can %d byte, khong con khoang trong nao du lon'
                         % (rid, need))
            continue
        at, n = free.pop(k)
        placed[off] = (at, raw)
        if n > need:
            free.append((at + need, n - need))
            free.sort(key=lambda s: s[1])
    if len(placed) < len(moving):
        # All or nothing: a string left behind still has its pointer on its old
        # span, and that span may already have been handed to another string.
        st['het cho de doi'] += len(placed)
        notes.append('khong du cho cho %d chuoi - khong doi cho chuoi nao '
                     '(thu --reuse-cri)' % (len(moving) - len(placed)))
        placed = {}

    # Old spans are blanked before anything is written into them, so a span
    # reused by another string never keeps a stale tail of the first. One that
    # is still read from elsewhere was not offered as free, and keeps its text.
    freed = {o for o, _n in spans}
    for off in placed:
        if off not in freed:
            continue
        end = segs['rodata'].find(b'\x00', off)
        out['rodata'][off:end] = b'\x00' * (end - off)
    grew = max([at + len(raw) + 1 for at, raw in placed.values()
                if at >= tail_end] + [tail_end]) - tail_end
    out['rodata'] += b'\x00' * grew
    for off, (at, raw) in placed.items():
        out['rodata'][at:at + len(raw) + 1] = raw + b'\x00'
        for seg, p in slots[off]:
            struct.pack_into('<Q', out[seg], p, ro_mem + at)
        written[('rodata', off)] = raw
        st['applied'] += 1
        st['da doi cho'] += 1
    return ({k: bytes(v) for k, v in out.items()}, len(placed), grew, pool,
            written)


def build(original, segs):
    """A new NSO carrying `segs`, written with every segment uncompressed."""
    head = bytearray(original[:HEADER])
    flags = struct.unpack_from('<I', head, 0x0C)[0]
    struct.pack_into('<I', head, 0x0C, flags & ~FLAG_COMPRESSED)

    body = bytearray()
    for i, (name, hdr) in enumerate(SEGMENTS):
        data = segs[name]
        struct.pack_into('<I', head, hdr, HEADER + len(body))   # file offset
        struct.pack_into('<I', head, hdr + 8, len(data))        # decompressed size
        struct.pack_into('<I', head, 0x60 + 4 * i, len(data))   # size in file
        struct.pack_into('32s', head, HASH_OFF[i], hashlib.sha256(data).digest())
        body += data
    return bytes(head) + bytes(body)


def verify(original, produced, expected):
    """Re-read the finished file and prove it holds exactly what was intended.

    A clean write proves nothing on its own - this repo's history is full of
    clean checks over broken files - so the result is parsed back from the bytes
    that will ship. `.text` and `.data` have to be untouched, `.rodata` has to
    equal what `place()` built, and all three stored hashes have to agree with
    the segments they cover.
    """
    before = dict(nso_segments(original))
    after = dict(nso_segments(produced))

    if after['text'] != before['text']:
        return 'text doi khac du khong va gi'
    for name in ('rodata', 'data'):
        if after[name] != expected[name]:
            return '%s khong khop ban va' % name
    # .data may differ only in whole pointer slots, each aiming into .rodata.
    ro_mem = struct.unpack_from('<I', produced, 0x24)[0]
    a, b = before['data'], after['data']
    for p in range(0, len(a), 8):
        if a[p:p + 8] != b[p:p + 8]:
            v = struct.unpack_from('<Q', b, p)[0] - ro_mem
            if not 0 <= v < len(after['rodata']):
                return 'data %#x khong tro vao rodata' % p

    flags = struct.unpack_from('<I', produced, 0x0C)[0]
    if flags & FLAG_COMPRESSED:
        return 'co nen chua tat (flags=%#x)' % flags
    for i, (name, _hdr) in enumerate(SEGMENTS):
        stored = produced[HASH_OFF[i]:HASH_OFF[i] + 32]
        if stored != hashlib.sha256(after[name]).digest():
            return 'hash %s khong khop' % name
    return None


def readback(original, produced, written):
    """[(offset, text read)] for every written string the result does not show.

    Each one is followed the way the game reaches it: through its pointers when
    it has any, at its own offset when it has none. A string moved into a span
    another string also landed in would read back wrong here.
    """
    before = dict(nso_segments(original))
    after = dict(nso_segments(produced))
    ro_mem = struct.unpack_from('<I', produced, 0x24)[0]
    slots = string_slots(original, before)
    bad = []
    for (seg, off), raw in written.items():
        targets = [struct.unpack_from('<Q', after[s], p)[0] - ro_mem
                   for s, p in slots.get(off, ())] if seg == 'rodata' else []
        for t in targets or [off]:
            got = after[seg][t:after[seg].find(b'\x00', t)]
            if got != raw:
                bad.append((off, got.decode('utf-8', 'replace')))
    return bad


def install(path, title_id, mod_name):
    appdata = os.environ.get('APPDATA')
    if not appdata:
        return '!! khong co APPDATA - khong tim duoc thu muc mods cua Ryujinx'
    dst_dir = os.path.join(appdata, 'Ryujinx', 'mods', 'contents',
                           title_id, mod_name, 'exefs')
    os.makedirs(dst_dir, exist_ok=True)
    dst = os.path.join(dst_dir, 'main')
    with open(dst, 'wb') as fh:
        fh.write(open(path, 'rb').read())
    return dst


def main():
    ap = argparse.ArgumentParser(
        description='write a sheet\'s exe rows back into exefs/main')
    ap.add_argument('xlsx', help='a workbook from `exefs.py sheet`')
    ap.add_argument('nso', help='the stock exefs/main')
    ap.add_argument('out', help='where to write the patched main')
    ap.add_argument('--sheet', action='append', help='limit to these worksheets')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--install', action='store_true',
                    help='also copy into the Ryujinx exefs mod folder')
    ap.add_argument('--reuse-cri', action='store_true',
                    help='also write moved strings over the CRI middleware '
                         'error messages; only an error log reads them')
    ap.add_argument('--title-id', default='01009cf01bac4000')
    ap.add_argument('--mod-name', default='vn-translation')
    a = ap.parse_args()

    import openpyxl
    original = open(a.nso, 'rb').read()
    segs = dict(nso_segments(original))
    _, ro_mem, ro_size = struct.unpack_from('<3I', original, 0x20)
    _, data_mem, _ = struct.unpack_from('<3I', original, 0x30)
    pool = data_mem - (ro_mem + ro_size)
    print('%s: text %s | rodata %s | data %s byte'
          % (os.path.basename(a.nso), *(format(len(segs[n]), ',')
                                        for n, _h in SEGMENTS)))
    print('cho trong sau rodata: %s byte (den %#x, dau .data)'
          % (format(pool, ','), data_mem))

    wb = openpyxl.load_workbook(a.xlsx, read_only=True, data_only=True)
    names = a.sheet or wb.sheetnames
    accepted = collections.defaultdict(dict)
    tot, notes = collections.Counter(), []
    for name in names:
        if name == '_README':
            continue
        got, st, note = plan(wb[name], segs)
        if not st['rows']:
            continue
        tot.update(st)
        notes += note
        for seg, rows in got.items():
            accepted[seg].update(rows)
        print('%-20s %4d dong, nhan %d' % (name, st['rows'], st['nhan']))

    patched, moved, grew, free, written = place(original, segs, accepted,
                                                a.reuse_cri, tot, notes)

    for n in notes[:8]:
        print('    !! %s' % n)
    if len(notes) > 8:
        print('    !! ... va %d dong nua' % (len(notes) - 8))

    if not tot['applied']:
        print('khong co dong nao de ap dung')
        for k, v in sorted(tot.items()):
            if k not in ('rows', 'nhan') and v:
                print('  %-26s %s' % (k, v))
        return 0

    produced = build(original, patched)
    bad = verify(original, produced, patched)
    if bad:
        print('!! KIEM TRA HONG - %s' % bad)
        return 1

    print('-' * 60)
    print('ap dung %d chuoi (%d viet tai cho, %d phai doi cho)'
          % (tot['applied'], tot['applied'] - moved, moved))
    if moved:
        print('khoang trong de doi cho: %s byte | rodata dai them %s / %s byte'
              % (format(free, ','), format(grew, ','), format(pool, ',')))
    for off, text in readback(original, produced, written):
        print('    !! doc lai sai: %#x %r' % (off, text[:40]))
        return 1
    print('file: %s -> %s byte (bo nen)'
          % (format(len(original), ','), format(len(produced), ',')))
    for k in ('chua dich', 'giong ban goc', 'dai qua cho', 'het cho de doi',
              'khong tim thay con tro', 'van ban khong khop',
              'offset khong phai chuoi', 'trung offset', 'id khong doc duoc'):
        if tot[k]:
            print('  bo qua - %-24s %s' % (k, tot[k]))
    print('kiem tra: doc lai file, text/data nguyen ven, rodata dung, 3 hash dung')

    if a.dry_run:
        print('(dry-run, khong ghi gi)')
        return 0

    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, 'wb') as fh:
        fh.write(produced)
    print('-> %s' % a.out)
    if a.install:
        print('install: %s' % install(a.out, a.title_id, a.mod_name))
    return 0


if __name__ == '__main__':
    sys.exit(main())
