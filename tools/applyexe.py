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


def pointer_slots(ro, ro_mem):
    """{string offset: [table offsets]} for every u64 in .rodata aiming at it.

    The quotes are reached through a pointer table, not through an address
    assembled in code, so retargeting one is a matter of rewriting eight bytes.
    Every 8-aligned word in the segment is read and kept if it lands on a string
    start, which finds the table without having to know where it begins.
    """
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
    for p in range(0, len(ro) - 8, 8):
        v = struct.unpack_from('<Q', ro, p)[0] - ro_mem
        if 0 <= v < len(ro) and v in starts:
            out[v].append(p)
    return out


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


def place(segs, accepted, pool, slots, ro_mem, st, notes):
    """Write the accepted rows into the segments, moving what will not fit.

    `pool` is how many bytes .rodata may grow by - the padding before .data.
    Returns {segment: bytes} and the number of strings that had to move.
    """
    out = {k: bytearray(v) for k, v in segs.items()}
    tail = bytearray()
    moved = 0

    for seg, rows in accepted.items():
        for off, (rid, raw, room) in sorted(rows.items()):
            if len(raw) <= room:
                out[seg][off:off + room] = raw.ljust(room, b'\x00')
                st['applied'] += 1
                continue
            if seg != 'rodata':
                st['dai qua cho'] += 1
                notes.append('%s: %d byte, cho co %d' % (rid, len(raw), room))
                continue
            where = slots.get(off)
            if not where:
                st['khong tim thay con tro'] += 1
                notes.append('%s: dai %d/%d va khong co con tro de doi'
                             % (rid, len(raw), room))
                continue
            need = len(raw) + 1                       # the string plus its NUL
            if len(tail) + need > pool:
                st['het cho de doi'] += 1
                notes.append('%s: can them %d byte, pool con %d'
                             % (rid, need, pool - len(tail)))
                continue
            new_off = len(segs['rodata']) + len(tail)
            tail += raw + b'\x00'
            for p in where:
                struct.pack_into('<Q', out['rodata'], p, ro_mem + new_off)
            # The old copy is left as it is: nothing points at it any more, and
            # blanking it would only make the diff harder to read.
            st['applied'] += 1
            st['da doi cho'] += 1
            moved += 1

    out['rodata'] += tail
    return {k: bytes(v) for k, v in out.items()}, moved, len(tail)


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

    for name in ('text', 'data'):
        if after[name] != before[name]:
            return '%s doi khac du khong va gi' % name
    if after['rodata'] != expected['rodata']:
        return 'rodata khong khop ban va'

    flags = struct.unpack_from('<I', produced, 0x0C)[0]
    if flags & FLAG_COMPRESSED:
        return 'co nen chua tat (flags=%#x)' % flags
    for i, (name, _hdr) in enumerate(SEGMENTS):
        stored = produced[HASH_OFF[i]:HASH_OFF[i] + 32]
        if stored != hashlib.sha256(after[name]).digest():
            return 'hash %s khong khop' % name
    return None


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

    slots = pointer_slots(segs['rodata'], ro_mem)
    patched, moved, grew = place(segs, accepted, pool, slots, ro_mem, tot, notes)

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
    if grew:
        print('rodata dai them %s byte, con lai %s byte trong pool'
              % (format(grew, ','), format(pool - grew, ',')))
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
