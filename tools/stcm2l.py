"""
stcm2l.py - parse STCM2L script files (.DAT) used by Otomate / Idea Factory.

    python stcm2l.py <file.DAT>            # structure summary + self-check
    python stcm2l.py <dir> --all           # validate every .DAT in a directory

FILE LAYOUT
    0x00   "STCM2L <build date>"  (0x20 bytes)
    0x20   u32 -> EXPORT_DATA area, u32 ?, u32 export count, u32 -> COLLECTION_LINK
    0x50   "GLOBAL_DATA"
    0x1F0  "CODE_START_"   (label is 12 bytes; code begins right after)
    ...    instruction stream
           "EXPORT_DATA" ... "COLLECTION_LINK"

INSTRUCTION
    u32 global_call
    u32 opcode
    u32 param_count
    u32 length              total size of the instruction, params and data blocks
    param[param_count]      12 bytes each: (value, tag, tag)
    data blocks             fill the rest of `length`, zero-padded between blocks

    `length` is what makes the stream walkable: step by it and the walk lands
    exactly on EXPORT_DATA. That is the self-check this module performs.

DATA BLOCK
    u32 flag        0 or 1
    u32 nwords      length / 4
    u32 one         always 1
    u32 length      payload size in bytes
    u8  data[length]        padded to a multiple of 4

    There is NO type field. A block holding 4 bytes (nwords == 1) is a number;
    text blocks are simply longer. Tell them apart by decoding the payload.

    Blocks are recognised by the invariant `one == 1 and length == nwords * 4`,
    which lets the walker skip the zero padding that sits between them. Do not
    additionally require `flag == 0`: a small number of real blocks carry 1.

WHY NOT SCAN FOR POINTERS
    Trying to spot pointers by their trailing 0x40000000 tag does not work -
    measured on one file: 13155 tagged values point outside the file, while 3033
    genuine in-range pointers carry no tag. Walk the instruction stream instead;
    then every pointer position is known exactly.
"""
import argparse
import glob
import os
import struct
import sys

CODE_LABEL = b'CODE_START_'
END_LABEL = b'EXPORT_DATA'
PARAM_SIZE = 12
INS_HEADER = 16
BLOCK_HEADER = 16


class Block:
    __slots__ = ('hdr_off', 'data_off', 'flag', 'length', 'raw', 'pad')

    def __init__(self, hdr_off, flag, length, raw):
        self.hdr_off = hdr_off
        self.data_off = hdr_off + BLOCK_HEADER
        self.flag = flag
        self.length = length
        self.raw = raw
        self.pad = b''                  # alignment bytes trailing the payload

    def text(self):
        """Payload decoded as UTF-8 up to the first NUL, or None if it is not text."""
        try:
            return self.raw.split(b'\x00')[0].decode('utf-8')
        except UnicodeDecodeError:
            return None

    def __repr__(self):
        return '<Block @%#x len=%d>' % (self.hdr_off, self.length)


class Instruction:
    __slots__ = ('off', 'global_call', 'opcode', 'params', 'length', 'blocks',
                 'segments', 'tail')

    def __init__(self, off, global_call, opcode, params, length, blocks,
                 segments=None, tail=b''):
        self.off = off
        self.global_call = global_call
        self.opcode = opcode
        self.params = params            # [(value, tag1, tag2)]
        self.length = length
        self.blocks = blocks
        # Layout of the data region, in order, so it can be rebuilt exactly:
        # ('blk', Block) or ('pad', bytes). Without this the zero padding
        # between blocks would be lost and the file would not round-trip.
        self.segments = segments or []
        self.tail = tail                # <16 bytes left over at the end

    def __repr__(self):
        return '<Ins @%#x op=%#x params=%d blocks=%d len=%#x>' % (
            self.off, self.opcode, len(self.params), len(self.blocks), self.length)


class Script:
    def __init__(self, data):
        self.raw = data
        if data[:6] != b'STCM2L':
            raise ValueError('not an STCM2L file')
        self.code_start = data.find(CODE_LABEL)
        self.code_end = data.find(END_LABEL)
        if self.code_start < 0 or self.code_end < 0:
            raise ValueError('missing CODE_START_ / EXPORT_DATA label')
        self.code_start += len(CODE_LABEL) + 1     # label is NUL-padded to 12
        self.instructions = []
        self.padding = 0                            # zero bytes between blocks
        self.tail = 0                               # <16 bytes left at instruction end
        self._walk()

    # ------------------------------------------------------------------ walk
    def _walk(self):
        d, p, end = self.raw, self.code_start, self.code_end
        while p < end:
            gcall, opcode, npar, ln = struct.unpack_from('<4I', d, p)
            if ln < INS_HEADER or p + ln > end:
                raise ValueError('bad instruction length %#x at %#x' % (ln, p))
            if INS_HEADER + npar * PARAM_SIZE > ln:
                raise ValueError('params overflow instruction at %#x' % p)
            params = [struct.unpack_from('<3I', d, p + INS_HEADER + i * PARAM_SIZE)
                      for i in range(npar)]
            blocks, segments = [], []
            q, lim = p + INS_HEADER + npar * PARAM_SIZE, p + ln
            while q + BLOCK_HEADER <= lim:
                flag, nwords, one, blen = struct.unpack_from('<4I', d, q)
                if one == 1 and blen == nwords * 4 and blen > 0 \
                        and q + BLOCK_HEADER + blen <= lim:
                    b = Block(q, flag, blen,
                              d[q + BLOCK_HEADER:q + BLOCK_HEADER + blen])
                    step = BLOCK_HEADER + ((blen + 3) & ~3)
                    b.pad = d[q + BLOCK_HEADER + blen:q + step]
                    blocks.append(b)
                    segments.append(('blk', b))
                    q += step
                else:
                    self.padding += 4        # zero padding between blocks
                    segments.append(('pad', d[q:q + 4]))
                    q += 4
            tail = d[q:lim]
            self.tail += len(tail)
            self.instructions.append(
                Instruction(p, gcall, opcode, params, ln, blocks, segments, tail))
            p += ln
        self.landed = (p == end)

    # ----------------------------------------------------------------- query
    def blocks(self):
        for ins in self.instructions:
            for b in ins.blocks:
                yield b

    def texts(self):
        """(offset, text) for every block whose payload decodes as UTF-8."""
        for b in self.blocks():
            t = b.text()
            if t:
                yield b.data_off, t

    # ----------------------------------------------------------------- write
    def build(self, repl=None):
        """Rebuild the file, optionally replacing block payloads.

        repl: {block.data_off: bytes} keyed by the ORIGINAL data offset. The
        replacement may be longer than the original; everything downstream is
        re-offset.

        Three kinds of number move when a payload grows, and all three are
        rewritten here:
          - each block's own `nwords` / `length`
          - the owning instruction's `length`
          - every parameter that points at one of its own data blocks

        Two more live outside the code section and are patched at the end:
          - the u32 slots in EXPORT_DATA that point at instruction starts
          - the header offsets at 0x20 (EXPORT_DATA) and 0x2C (COLLECTION_LINK)

        Parameters pointing into GLOBAL_DATA need no fixing: that section sits
        before the code, so its offsets never shift. There are no jump pointers
        between instructions - verified by classifying every parameter.
        """
        repl = repl or {}
        d = self.raw

        # pass 1: lay out instructions, recording where each one moves to
        moved = {}                       # old instruction offset -> new
        pieces, cur = [], self.code_start
        for ins in self.instructions:
            moved[ins.off] = cur
            body, blk_at = bytearray(), {}
            for kind, item in ins.segments:
                if kind == 'pad':
                    body += item
                    continue
                payload = repl.get(item.data_off, item.raw)
                if len(payload) % 4:
                    payload = payload + b'\x00' * (-len(payload) % 4)
                # Parameters point at the block HEADER, not at its payload.
                # Keying this map by data_off instead silently leaves every
                # parameter unpatched - and an identity round-trip will not
                # catch it, because nothing moves in that case.
                blk_at[item.hdr_off] = cur + INS_HEADER + \
                    len(ins.params) * PARAM_SIZE + len(body)
                body += struct.pack('<4I', item.flag, len(payload) // 4, 1,
                                    len(payload)) + payload
            body += ins.tail
            new_len = INS_HEADER + len(ins.params) * PARAM_SIZE + len(body)

            params = bytearray()
            for v, t1, t2 in ins.params:
                params += struct.pack('<3I', blk_at.get(v, v), t1, t2)

            pieces.append(struct.pack('<4I', ins.global_call, ins.opcode,
                                      len(ins.params), new_len) + bytes(params) + bytes(body))
            cur += new_len

        out = bytearray(d[:self.code_start])
        for piece in pieces:
            out += piece
        new_code_end = len(out)

        # pass 2: the trailer, with its pointers into the code section rebased
        trailer = bytearray(d[self.code_end:])
        for o in range(0, len(trailer) - 4, 4):
            v = struct.unpack_from('<I', trailer, o)[0]
            if v in moved:
                struct.pack_into('<I', trailer, o, moved[v])
        out += trailer

        # pass 3: header offsets that follow the trailer's new position
        shift = new_code_end - self.code_end
        for hoff in (0x20, 0x2C):
            v = struct.unpack_from('<I', out, hoff)[0]
            if v >= self.code_end:
                struct.pack_into('<I', out, hoff, v + shift)
        return bytes(out)

    def check_pointers(self):
        """Count parameters that should address a data block but do not.

        A parameter either names one of its instruction's block headers, or is
        an immediate / a GLOBAL_DATA address. One landing inside the code
        section without hitting a block header means the rebuild mis-offset it.

        This is the check an identity round-trip cannot make: when nothing
        moves, stale pointers still happen to be correct.
        """
        bad = 0
        for ins in self.instructions:
            own = {b.hdr_off for b in ins.blocks}
            for v, _t1, _t2 in ins.params:
                if v in own or v >= 0xffffff00:
                    continue
                if self.code_start <= v < self.code_end:
                    bad += 1            # points into code but not at a block
        return bad

    def check(self):
        """Bytes skipped as padding must all be zero; the walk must land on the label."""
        nonzero = 0
        d = self.raw
        for ins in self.instructions:
            covered = set()
            for b in ins.blocks:
                covered.update(range(b.hdr_off,
                                     b.data_off + ((b.length + 3) & ~3)))
            lo = ins.off + INS_HEADER + len(ins.params) * PARAM_SIZE
            for o in range(lo, ins.off + ins.length):
                if o not in covered and d[o]:
                    nonzero += 1
        return self.landed, nonzero


def load(path):
    return Script(open(path, 'rb').read())


def main():
    ap = argparse.ArgumentParser(description='parse STCM2L script files')
    ap.add_argument('target')
    ap.add_argument('--all', action='store_true', help='target is a directory')
    a = ap.parse_args()

    files = sorted(glob.glob(os.path.join(a.target, '*.DAT'))) if a.all else [a.target]
    tot_ins = tot_blk = tot_txt = bad = 0
    for f in files:
        try:
            s = load(f)
        except ValueError as e:
            print('%-14s LOI: %s' % (os.path.basename(f), e))
            bad += 1
            continue
        landed, nonzero = s.check()
        nblk = sum(len(i.blocks) for i in s.instructions)
        ntxt = sum(1 for _o, _t in s.texts())
        tot_ins += len(s.instructions); tot_blk += nblk; tot_txt += ntxt
        if not landed or nonzero:
            bad += 1
        if not a.all:
            print('instructions : %s' % format(len(s.instructions), ','))
            print('data blocks  : %s  (text: %s)' % (format(nblk, ','), format(ntxt, ',')))
            print('padding      : %s byte, tail %s byte' % (format(s.padding, ','),
                                                            format(s.tail, ',')))
            print('lands on EXPORT_DATA : %s' % ('yes' if landed else 'NO'))
            print('non-zero bytes skipped: %d' % nonzero)
    if a.all:
        print('files          : %d (loi: %d)' % (len(files), bad))
        print('instructions   : %s' % format(tot_ins, ','))
        print('data blocks    : %s' % format(tot_blk, ','))
        print('text blocks    : %s' % format(tot_txt, ','))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
