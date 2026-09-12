"""
cpk.py - read and repack .cpk archives (CRI Middleware).

Usage:
    python cpk.py list   SYSTEM.cpk
    python cpk.py unpack SYSTEM.cpk <filter> <out_dir>
    python cpk.py repack SYSTEM.cpk SYSTEM_vn.cpk <replacement_dir>

On repack, any file whose basename matches one in <replacement_dir> is replaced
and written UNCOMPRESSED (ExtractSize == FileSize). Every other file is copied
across byte-for-byte in its already-compressed form, never decoded or re-encoded.

Only the numeric cells of the @UTF tables are patched in place (FileSize /
ExtractSize / FileOffset / ContentSize / EtocOffset), so the schema and the
string pool stay exactly as they were.
"""
import os
import struct
import sys

# ------------------------------------------------------------------ @UTF table

class UTF:
    """A CRI @UTF table. Records each cell's absolute offset for in-place edits."""

    TYPES = {0: 'B', 1: 'b', 2: 'H', 3: 'h', 4: 'I', 5: 'i',
             6: 'Q', 7: 'q', 8: 'f', 9: 'd'}
    SIZES = {0: 1, 1: 1, 2: 2, 3: 2, 4: 4, 5: 4, 6: 8, 7: 8, 8: 4, 9: 8}

    def __init__(self, buf, off=0):
        assert buf[off:off + 4] == b'@UTF', buf[off:off + 4]
        self.b = buf
        base = off + 8
        (_tsize, rows_off, str_off, data_off, _name_off,
         ncols, _rowlen, nrows) = struct.unpack_from('>IIIIIHHI', buf, off + 4)
        self.rows_off = base + rows_off
        self.str_off = base + str_off
        self.data_off = base + data_off
        self.nrows = nrows

        p = off + 0x20
        self.cols = []
        for _ in range(ncols):
            flags = buf[p]
            p += 1
            noff = struct.unpack_from('>I', buf, p)[0]
            p += 4
            name = self._str(noff)
            storage, typ = flags & 0xf0, flags & 0x0f
            const = None
            if storage == 0x30:
                const, p = self._read(typ, p)
            self.cols.append((name, typ, storage, const))

        self.rows = []
        self.meta = []                    # [{col_name: (offset, type)}]
        p = self.rows_off
        for _ in range(nrows):
            row, meta = {}, {}
            for name, typ, storage, const in self.cols:
                if storage == 0x50:
                    meta[name] = (p, typ)
                    v, p = self._read(typ, p)
                elif storage == 0x30:
                    v = const
                else:
                    v = 0
                row[name] = v
            self.rows.append(row)
            self.meta.append(meta)

    def _str(self, o):
        e = self.b.index(b'\x00', self.str_off + o)
        return self.b[self.str_off + o:e].decode('utf-8', 'replace')

    def _read(self, typ, p):
        if typ == 0x0a:
            o = struct.unpack_from('>I', self.b, p)[0]
            return self._str(o), p + 4
        if typ == 0x0b:
            o, sz = struct.unpack_from('>II', self.b, p)
            return self.b[self.data_off + o:self.data_off + o + sz], p + 8
        f, s = self.TYPES[typ], self.SIZES[typ]
        return struct.unpack_from('>' + f, self.b, p)[0], p + s

    def patch(self, buf, row, name, value):
        """Overwrite one numeric cell in buf (a bytearray) at its own offset."""
        if name not in self.meta[row]:
            return False                  # constant/empty column: not patchable
        off, typ = self.meta[row][name]
        if typ not in self.TYPES:
            return False
        struct.pack_into('>' + self.TYPES[typ], buf, off, value)
        return True


# ----------------------------------------------------------------- CRILAYLA

def crilayla(data):
    """Decompress a CRILAYLA block."""
    assert data[:8] == b'CRILAYLA'
    usize, uh_off = struct.unpack_from('<II', data, 8)
    out = bytearray(usize + 0x100)
    out[0:0x100] = data[0x10 + uh_off:0x10 + uh_off + 0x100]
    ip = len(data) - 0x100 - 1
    oend = 0x100 + usize - 1
    pool = left = done = 0

    def gb(n):
        nonlocal pool, left, ip
        v = 0
        while n > 0:
            if left == 0:
                pool = data[ip]
                ip -= 1
                left = 8
            t = min(left, n)
            v = (v << t) | ((pool >> (left - t)) & ((1 << t) - 1))
            left -= t
            n -= t
        return v

    vle = (2, 3, 5, 8)
    while done < usize:
        if gb(1):
            ref = oend - done + gb(13) + 3
            ln = 3
            t = lvl = 0
            for lvl in range(4):
                t = gb(vle[lvl])
                ln += t
                if t != (1 << vle[lvl]) - 1:
                    break
            if lvl == 3 and t == 255:
                while True:
                    t = gb(8)
                    ln += t
                    if t != 255:
                        break
            for _ in range(ln):
                out[oend - done] = out[ref]
                ref -= 1
                done += 1
        else:
            out[oend - done] = gb(8)
            done += 1
    return bytes(out)


# --------------------------------------------------------------------- CPK

class CPK:
    def __init__(self, path):
        self.path = path
        self.raw = bytearray(open(path, 'rb').read())
        self.head = UTF(self.raw, 0x10)
        h = self.head.rows[0]
        self.hdr = h
        self.toc_off = h['TocOffset']
        self.content_off = h['ContentOffset']
        self.align = h['Align'] or 16
        self.toc = UTF(self.raw, self.toc_off + 0x10)
        # TOC FileOffset is relative to the start of the TOC (or content, if lower)
        self.base = min(self.toc_off, self.content_off)

    def files(self):
        for i, r in enumerate(self.toc.rows):
            d = r['DirName']
            yield i, (d + '/' + r['FileName'] if d else r['FileName']), r

    def read(self, row, decompress=True):
        off = self.base + row['FileOffset']
        d = bytes(self.raw[off:off + row['FileSize']])
        if decompress and row['ExtractSize'] > row['FileSize'] \
                and d[:8] == b'CRILAYLA':
            d = crilayla(d)
        return d

    # ------------------------------------------------------------- repack
    def repack(self, out_path, replacements, verbose=True):
        """replacements: {'path/inside/cpk': bytes}. Written UNCOMPRESSED."""
        if self.hdr.get('TocCrc'):
            print('  !! TocCrc is non-zero - the game may verify the CRC')

        new = bytearray(self.raw[:self.content_off])
        cur = self.content_off
        used = set()

        for i, full, r in self.files():
            if full in replacements:
                data, used = replacements[full], used | {full}
                extract = size = len(data)
            else:
                data = bytes(self.raw[self.base + r['FileOffset']:
                                      self.base + r['FileOffset'] + r['FileSize']])
                size, extract = r['FileSize'], r['ExtractSize']

            pad = (-cur) % self.align
            new += b'\x00' * pad
            cur += pad

            self.toc.patch(new, i, 'FileOffset', cur - self.base)
            self.toc.patch(new, i, 'FileSize', size)
            self.toc.patch(new, i, 'ExtractSize', extract)

            new += data
            cur += len(data)

        missing = set(replacements) - used
        if missing:
            raise KeyError('not present in cpk: %s' % sorted(missing))

        content_size = cur - self.content_off
        pad = (-cur) % self.align
        new += b'\x00' * pad
        cur += pad

        etoc_off = self.hdr['EtocOffset']
        if etoc_off:
            etoc = self.raw[etoc_off:etoc_off + self.hdr['EtocSize']]
            self.head.patch(new, 0, 'EtocOffset', cur)
            new += etoc

        self.head.patch(new, 0, 'ContentSize', content_size)
        self.head.patch(new, 0, 'EnabledPackedSize', content_size)
        self.head.patch(new, 0, 'EnabledDataSize', content_size)

        with open(out_path, 'wb') as fh:
            fh.write(new)
        if verbose:
            print('  %s -> %s' % (os.path.basename(self.path),
                                  os.path.basename(out_path)))
            print('  replaced %d files, content %s -> %s bytes' % (
                len(replacements), format(self.hdr['ContentSize'], ','),
                format(content_size, ',')))
        return len(new)


# -------------------------------------------------------------------- CLI

def main():
    cmd = sys.argv[1]
    c = CPK(sys.argv[2])
    if cmd == 'list':
        for _i, full, r in c.files():
            print('%-42s %10d %10d' % (full, r['FileSize'], r['ExtractSize']))
    elif cmd == 'unpack':
        pat, outdir = sys.argv[3].lower(), sys.argv[4]
        os.makedirs(outdir, exist_ok=True)
        for _i, full, r in c.files():
            if pat not in full.lower():
                continue
            p = os.path.join(outdir, os.path.basename(full))
            with open(p, 'wb') as fh:
                fh.write(c.read(r))
            print('->', p)
    elif cmd == 'repack':
        out, srcdir = sys.argv[3], sys.argv[4]
        have = {n.lower(): os.path.join(srcdir, n) for n in os.listdir(srcdir)}
        rep = {}
        for _i, full, _r in c.files():
            key = os.path.basename(full).lower()
            if key in have:
                rep[full] = open(have[key], 'rb').read()
                print('  thay %s (%s byte)' % (full, format(len(rep[full]), ',')))
        if not rep:
            print('no replaceable file found in', srcdir)
            return
        c.repack(out, rep)
    else:
        print(__doc__)


if __name__ == '__main__':
    main()
