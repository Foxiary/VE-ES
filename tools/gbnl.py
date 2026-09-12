"""
gbnl.py - read / rebuild .gbin (GBNL) and .gstr (GSTL) data files.

Layout (little-endian):
    [record table]  n * stride bytes, starting at hdr.tbl
    [schema block]  ncol * 4 bytes, right after the table: each column is
                    (u16 type, u16 offset); type 5 = STRING CELL (u64 holding an
                    offset RELATIVE to the pool)
    [string pool]   NUL-terminated UTF-8 strings, starting at hdr.pool
    [footer]        last 64 bytes, magic 'GBNL' (GSTL puts its header up front)

Header / footer fields:
    0x14 tbl   0x18 n_record   0x1c stride   0x20 n_col
    0x24 tbl_end   0x28 n_slot (string CELLS, not distinct strings)   0x2c pool

CRASH WARNING: the schema block sits BETWEEN the table and the pool. Zeroing it
out crashes the game as soon as a screen reads that table - the engine no longer
knows which columns hold strings. Always copy this block into the new file.

Use the schema to locate string cells rather than guessing "does this value
point at the start of a string" - that guess hits false positives on numeric
columns and corrupts them.
"""
import struct
import sys

TYPE_STRING = 5


class GBNL:
    def __init__(self, data):
        self.raw = data
        if data[:4] == b'GSTL':
            self.hdr_off, self.kind = 0, b'GSTL'
        else:
            self.hdr_off = data.rfind(b'GBNL')
            self.kind = b'GBNL'
            if self.hdr_off < 0:
                raise ValueError('not a GBNL/GSTL file')
        h = self.hdr_off
        (self.tbl, self.n, self.stride, self.ncol,
         self.tbl_end, self.n_slot, self.pool) = struct.unpack_from('<7I', data, h + 0x14)
        self.pool_end = self.hdr_off if self.kind == b'GBNL' else len(data)

        # schema: ncol * (u16 type, u16 offset), immediately after the record table
        self.schema = [struct.unpack_from('<HH', data, self.tbl_end + i * 4)
                       for i in range(self.ncol)]
        self.str_cols = [off for typ, off in self.schema if typ == TYPE_STRING]

    # -------------------------------------------------------------- reading
    def _cstr(self, abs_off):
        return self.raw[abs_off:self.raw.index(b'\x00', abs_off)]

    def text(self, rel):
        return self._cstr(self.pool + rel).decode('utf-8', 'replace')

    def strings(self):
        """{rel_offset: text} in pool order."""
        out, o = {}, self.pool
        while o < self.pool_end:
            e = self.raw.index(b'\x00', o)
            out[o - self.pool] = self.raw[o:e].decode('utf-8', 'replace')
            o = e + 1
        return out

    def slots(self):
        """[(record, absolute_offset)] for every string cell, per the schema."""
        return [(i, self.tbl + i * self.stride + col)
                for i in range(self.n) for col in self.str_cols]

    def record(self, i):
        return [self.text(struct.unpack_from('<Q', self.raw, o)[0])
                for _r, o in self.slots() if _r == i]

    # -------------------------------------------------------------- writing
    def build(self, repl):
        """repl: {old_text: new_text}. The pool is rebuilt, so replacements may be
        LONGER than the strings they replace."""
        old = self.strings()
        order = sorted(old)

        pool, remap = bytearray(), {}
        for rel in order:
            remap[rel] = len(pool)
            pool += repl.get(old[rel], old[rel]).encode('utf-8') + b'\x00'

        tbl = bytearray(self.raw[self.tbl:self.tbl_end])
        for _i, abs_off in self.slots():
            v = struct.unpack_from('<Q', self.raw, abs_off)[0]
            if v in remap:
                struct.pack_into('<Q', tbl, abs_off - self.tbl, remap[v])

        out = bytearray(self.raw[:self.tbl])
        out += tbl
        out += self.raw[self.tbl_end:self.pool]      # <- schema block, MUST be kept
        out += pool
        if self.kind == b'GBNL':
            out += self.raw[self.hdr_off:self.hdr_off + 64]
        return bytes(out)


def load(path):
    return GBNL(open(path, 'rb').read())


if __name__ == '__main__':
    g = load(sys.argv[1])
    print('kind=%s tbl=%#x n=%d stride=%d ncol=%d pool=%#x n_slot=%d'
          % (g.kind.decode(), g.tbl, g.n, g.stride, g.ncol, g.pool, g.n_slot))
    print('schema:', g.schema, '-> string columns at offset', g.str_cols)
    rt = g.build({}) == g.raw
    print('round-trip with no edits:', 'BIT-IDENTICAL' if rt else '!! DIFFERS')
    for i in range(min(3, g.n)):
        print('  record %d:' % i, [repr(s)[:44] for s in g.record(i)])
