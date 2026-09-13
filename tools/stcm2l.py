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
    __slots__ = ('hdr_off', 'data_off', 'flag', 'length', 'raw')

    def __init__(self, hdr_off, flag, length, raw):
        self.hdr_off = hdr_off
        self.data_off = hdr_off + BLOCK_HEADER
        self.flag = flag
        self.length = length
        self.raw = raw

    def text(self):
        """Payload decoded as UTF-8 up to the first NUL, or None if it is not text."""
        try:
            return self.raw.split(b'\x00')[0].decode('utf-8')
        except UnicodeDecodeError:
            return None

    def __repr__(self):
        return '<Block @%#x len=%d>' % (self.hdr_off, self.length)


class Instruction:
    __slots__ = ('off', 'global_call', 'opcode', 'params', 'length', 'blocks')

    def __init__(self, off, global_call, opcode, params, length, blocks):
        self.off = off
        self.global_call = global_call
        self.opcode = opcode
        self.params = params            # [(value, tag1, tag2)]
        self.length = length
        self.blocks = blocks

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
            blocks, q, lim = [], p + INS_HEADER + npar * PARAM_SIZE, p + ln
            while q + BLOCK_HEADER <= lim:
                flag, nwords, one, blen = struct.unpack_from('<4I', d, q)
                if one == 1 and blen == nwords * 4 and blen > 0 \
                        and q + BLOCK_HEADER + blen <= lim:
                    blocks.append(Block(q, flag, blen,
                                        d[q + BLOCK_HEADER:q + BLOCK_HEADER + blen]))
                    q += BLOCK_HEADER + ((blen + 3) & ~3)
                else:
                    self.padding += 4        # zero padding between blocks
                    q += 4
            self.tail += lim - q
            self.instructions.append(
                Instruction(p, gcall, opcode, params, ln, blocks))
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
