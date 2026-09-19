"""
exefs.py - read the game's executable, for the text that is not in romfs.

    python tools/exefs.py extract  "Virche ... [USA][v0].nsp" work/exefs
    python tools/exefs.py segments work/exefs/main work/exefs
    python tools/exefs.py strings  work/exefs/main.rodata.bin --grep "\\n \\n"

WHY THIS EXISTS
    The title screen shows a quote from the ending you last cleared. It is not
    in any CPK: every one of the 22 databases in SYSTEM.cpk, all 117 scripts in
    STORY.cpk, SaveUtil and Shader were searched decompressed, and GAME.cpk
    holds nothing but `.tid` textures and `.CL3` sprites. All twelve quotes are
    C strings in the `.rodata` of `exefs/main`, one per ending.

    They are also spelled differently from every other string in the game: the
    line break is a real `\\n`, not the engine's `#n`, and paragraphs are
    separated by `\\n \\n`. That pattern is what `strings --grep` finds them by.

HOW IT GETS AT THE NSP
    Through `nsz`, which bundles a full NCA reader and is already installed for
    unrelated reasons. Keys come from `~/.switch/prod.keys` via its own
    `Keys.load_default()`. The program NCA's section 0 is the ExeFS, a PFS0
    holding `main`, `rtld`, `sdk` and `subsdk0`.

    `main` is an NSO whose three segments are LZ4 block-compressed - the flags
    word at 0x0C says which. The decompressor here is the plain LZ4 block
    format in about thirty lines, which is cheaper than another dependency, and
    it checks its output against the size the header declares.

WRITING IT BACK IS `applyexe.py`
    This is not romfs, so a CPK mod cannot reach it: Ryujinx loads an executable
    from `mods/contents/<title id>/<name>/exefs/` instead. A longer translation
    is not capped, though - the quotes are reached through a pointer table, so
    `applyexe.py` moves one that outgrows its span into the padding between
    `.rodata` and `.data` and re-aims the pointer.
"""
import argparse
import os
import re
import struct
import sys

NSO_MAGIC = b'NSO0'
SEGMENTS = (('text', 0x10), ('rodata', 0x20), ('data', 0x30))


def lz4_block(src, out_size):
    """LZ4 block format, enough for an NSO segment. Raises if the size is off."""
    dst = bytearray()
    i, n = 0, len(src)
    while i < n:
        token = src[i]
        i += 1
        lit = token >> 4
        if lit == 15:
            while True:
                b = src[i]
                i += 1
                lit += b
                if b != 255:
                    break
        dst += src[i:i + lit]
        i += lit
        if i >= n:
            break
        off = src[i] | (src[i + 1] << 8)
        i += 2
        mlen = token & 15
        if mlen == 15:
            while True:
                b = src[i]
                i += 1
                mlen += b
                if b != 255:
                    break
        start = len(dst) - off
        for k in range(mlen + 4):
            dst.append(dst[start + k])
    if len(dst) != out_size:
        raise ValueError('giai nen ra %d byte, header noi %d' % (len(dst), out_size))
    return bytes(dst)


def nso_segments(data):
    """[(name, bytes)] for .text, .rodata and .data, decompressed."""
    if data[:4] != NSO_MAGIC:
        raise ValueError('khong phai NSO (%r)' % data[:4])
    flags = struct.unpack_from('<I', data, 0x0C)[0]
    packed = struct.unpack_from('<3I', data, 0x60)
    out = []
    for idx, (name, hdr) in enumerate(SEGMENTS):
        foff, _moff, dsize = struct.unpack_from('<3I', data, hdr)
        raw = data[foff:foff + packed[idx]]
        out.append((name, lz4_block(raw, dsize) if flags & (1 << idx) else raw))
    return out


def _program_ncas(path):
    """The program NCAs of an .nsp or an .xci.

    An XCI keeps its content in HFS0 partitions and only `secure` holds the
    game - `update` carries system titles whose NCAs are also PROGRAM, so
    filtering on content type alone would pick up a firmware executable.
    """
    from nsz.Fs import Nsp, Xci, Nca, Type

    if path.lower().endswith('.xci'):
        container = Xci.Xci()
        container.open(path, 'rb')
        for partition in container.hfs0:
            if getattr(partition, '_path', '') != 'secure':
                continue
            for f in partition:
                if isinstance(f, Nca.Nca) and f.header.contentType == Type.Content.PROGRAM:
                    yield f
        return

    container = Nsp.Nsp()
    container.open(path, 'rb')
    for f in container:
        if isinstance(f, Nca.Nca) and f.header.contentType == Type.Content.PROGRAM:
            yield f


def cmd_extract(a):
    from nsz.Fs import Pfs0
    from nsz.nut import Keys
    Keys.load_default()

    os.makedirs(a.out, exist_ok=True)
    written = 0
    for f in _program_ncas(a.nsp):
        for fs in f.sectionFilesystems:
            if not isinstance(fs, Pfs0.Pfs0):
                continue
            for sub in fs:
                name = getattr(sub, '_path', None) or getattr(sub, 'name', '?')
                sub.rewind()
                dst = os.path.join(a.out, os.path.basename(name))
                with open(dst, 'wb') as fh:
                    fh.write(sub.read(sub.size))
                print('%-14s %12s byte -> %s' % (name, format(sub.size, ','), dst))
                written += 1
            break                       # section 0 is the ExeFS; the rest is not
    if not written:
        print('!! khong thay ExeFS trong %s' % a.nsp)
        return 1
    return 0


def cmd_segments(a):
    data = open(a.nso, 'rb').read()
    os.makedirs(a.out, exist_ok=True)
    base = os.path.basename(a.nso)
    for name, body in nso_segments(data):
        dst = os.path.join(a.out, '%s.%s.bin' % (base, name))
        with open(dst, 'wb') as fh:
            fh.write(body)
        print('%-8s %12s byte -> %s' % (name, format(len(body), ','), dst))
    return 0


def c_strings(data, minimum):
    """(offset, text) for every NUL-terminated UTF-8 run of at least `minimum`."""
    out, o = [], 0
    while True:
        e = data.find(b'\x00', o)
        if e < 0:
            break
        if e - o >= minimum:
            try:
                out.append((o, data[o:e].decode('utf-8')))
            except UnicodeDecodeError:
                pass
        o = e + 1
    return out


def cmd_strings(a):
    data = open(a.file, 'rb').read()
    rx = re.compile(a.grep) if a.grep else None
    n = 0
    for off, text in c_strings(data, a.min):
        if rx and not rx.search(text):
            continue
        n += 1
        print('%#08x  %4d byte  %r' % (off, len(text.encode('utf-8')), text))
    print('-- %d chuoi' % n)
    return 0


def cmd_sheet(a):
    """A translation sheet for the strings `--grep` selects.

    Built with mksheet's own Workbook so the columns match every other sheet in
    the project, but the id is deliberately shaped so that NO existing apply
    tool will touch it: `main.rodata___2BD34_exe` fails the regex in
    `checksheet.py`, `applyvi.py` and `applyui.py` alike. These rows do not
    address a .DAT block or a .gbin cell and must never be fed to something that
    thinks they do.
    """
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from mksheet import Workbook                       # noqa: E402

    data = open(a.file, 'rb').read()
    rx = re.compile(a.grep) if a.grep else None
    stem = os.path.basename(a.file).replace('.bin', '')

    rows = []
    for off, text in c_strings(data, a.min):
        if rx and not rx.search(text):
            continue
        rows.append(('%s___%X_exe' % (stem, off), text, None, 'exe', '', ''))

    wb = Workbook(False, False)
    wb.add_readme([
        'BANG DICH - CHU NAM TRONG FILE THUC THI (exefs/main)',
        '',
        'Day KHONG phai romfs. Cac cau nay la chuoi C trong .rodata cua',
        'exefs/main, khong nam trong CPK nao. Mod CPK khong voi toi duoc;',
        'Ryujinx nap file thuc thi tu mods/contents/<title id>/<ten>/exefs/.',
        '',
        'CAU DAI HON BAN GOC VAN DUOC. .rodata xep khit, nhung cac cau nay',
        'duoc tro toi qua mot bang con tro, nen applyexe.py se ghi cau dai ra',
        'vao khoang trong giua .rodata va .data roi chinh con tro. Pool do co',
        '4.056 byte, du cho ca 12 cau dai them ~25%. Cot "bytes" la so byte',
        'ban goc, dung de uoc luong chu khong phai tran cung.',
        '',
        'NGAT DONG O DAY LA XUONG HANG THAT, KHONG PHAI #n. Go Alt+Enter nhu',
        'binh thuong. Dung cho cong cu nao doi no thanh #n - applyui.py va',
        'applyvi.py deu se tu choi ID cua sheet nay, va do la co y.',
        '',
        'Khong co cot tieng Nhat: ban JP khong giu may cau nay trong file thuc',
        'thi (da kiem ca main lan subsdk0 cua hai ban).',
    ])
    n = wb.add(a.sheet_name, rows)
    wb.save(a.out)
    budget = [len(r[1].encode('utf-8')) for r in rows]
    print('%s: %d dong -> %s' % (a.sheet_name, n, a.out))
    if budget:
        print('tran byte: ngan nhat %d, dai nhat %d' % (min(budget), max(budget)))
    return 0


def main():
    ap = argparse.ArgumentParser(description='read text out of the game executable')
    sub = ap.add_subparsers(dest='cmd', required=True)

    p = sub.add_parser("extract", help="pull the ExeFS out of an NSP or XCI (needs prod.keys)")
    p.add_argument("nsp", help="an .nsp or .xci")
    p.add_argument('out')
    p.set_defaults(fn=cmd_extract)

    p = sub.add_parser('segments', help='decompress an NSO into its three segments')
    p.add_argument('nso')
    p.add_argument('out')
    p.set_defaults(fn=cmd_segments)

    p = sub.add_parser('strings', help='NUL-terminated UTF-8 strings in a blob')
    p.add_argument('file')
    p.add_argument('--min', type=int, default=10, help='shortest run to print')
    p.add_argument('--grep', help='keep only strings matching this regex')
    p.set_defaults(fn=cmd_strings)

    p = sub.add_parser('sheet', help='a translation sheet for the matching strings')
    p.add_argument('file', help='a decompressed segment, e.g. main.rodata.bin')
    p.add_argument('--out', default=os.path.join('work', 'title_quotes.xlsx'))
    p.add_argument('--sheet-name', default='title_quotes')
    p.add_argument('--min', type=int, default=10)
    p.add_argument('--grep', help='keep only strings matching this regex')
    p.set_defaults(fn=cmd_sheet)

    a = ap.parse_args()
    return a.fn(a)


if __name__ == '__main__':
    sys.exit(main())
