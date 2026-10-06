"""
tid.py - read the `.tid` textures in GAME.cpk and write them out as PNG.

    python tools/tid.py list   GAME.cpk
    python tools/tid.py list   GAME.cpk TITLE
    python tools/tid.py unpack GAME.cpk TITLE work/tid
    python tools/tid.py unpack work/tid/title_menu.tid work/tid

Not every string the player reads is text. The title screen's menu - Start,
Load, Flowchart, Scene List, Special, Options - is painted into one texture
atlas, three states per item, and so are the logo, "Press Any Button" and the
copyright line. None of it is reachable through `mksheet.py`, because none of it
is a string: it lives in GAME.cpk, which holds nothing but `.tid` textures and
`.CL3` sprites.

THE HEADER, READ OFF THE SHIPPED FILES

    0x00  'TID' + format byte   0x04  u32 total size
    0x08  u32 data offset (128) 0x14  u32 -> name
    0x20  file name, NUL-padded
    0x40  u32 -> fourcc block   0x44  u32 WIDTH   0x48  u32 HEIGHT
    0x58  u32 payload size      0x5C  u32 data offset again
    0x64  FOURCC: 'DXT1' | 'DXT5' | 'BC7 '
    0x80  block data

    The format byte at 0x03 agrees with the fourcc - 0x90 for the 8-byte-block
    DXT1, 0x80 for the 16-byte-block DXT5 and BC7 - but the fourcc is what this
    reads, being the unambiguous one of the two.

THE PAYLOAD IS LINEAR, NOT SWIZZLED
    Switch textures are usually stored block-linear and have to be untiled
    before a decoder will touch them. These are not: decoding the bytes in plain
    raster order produces the right picture, which is what makes this file short
    enough to be worth having. It was checked rather than assumed - the first
    blocks of `title_bg1.tid` read as coherent neighbouring colours instead of
    the scattered ones tiling would give, and the decode was then confirmed by
    eye against a screenshot.

    So Pillow's own BCn decoder does all the work, and the only thing here is
    the header.

SIZE IS THE CHECK
    width x height x bytes-per-pixel has to equal the payload exactly - half a
    byte per pixel for DXT1, one for DXT5 and BC7. `list` prints that comparison
    for every texture, so a file whose header this misreads shows up as a
    mismatch rather than as a silently wrong picture.

WRITING THEM BACK IS NOT DONE HERE
    Pillow decodes BCn and does not encode it, so putting a redrawn menu back
    needs a compressor this repo does not have. Unpacking is still the half that
    unblocks the work: it says exactly which art carries text and what has to be
    redrawn.
"""
import argparse
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cpk import CPK                                  # noqa: E402

HEADER = 128

# fourcc -> (Pillow bcn index, bytes per pixel). A fourcc of four NUL bytes is
# not a block format at all: those textures are stored as raw 32-bit pixels,
# which is why `bcn` is None for that entry.
RAW = b'\x00\x00\x00\x00'
FORMATS = {
    b'DXT1': (1, 0.5),
    b'DXT3': (2, 1.0),
    b'DXT5': (3, 1.0),
    b'BC7 ': (7, 1.0),
    RAW: (None, 4.0),
}


class TID:
    def __init__(self, data, name=None):
        if data[:3] != b'TID':
            raise ValueError('not a TID')
        self.raw = data
        self.fmt_byte = data[3]
        self.width, self.height = struct.unpack_from('<2I', data, 0x44)
        self.payload_size = struct.unpack_from('<I', data, 0x58)[0]
        self.data_off = struct.unpack_from('<I', data, 0x5C)[0]
        self.fourcc = data[0x64:0x68]
        self.name = name or data[0x20:0x40].split(b'\x00')[0].decode('ascii', 'replace')

    @property
    def expected(self):
        """Payload size the width, height and format imply, or None if unknown."""
        if self.fourcc not in FORMATS:
            return None
        return int(self.width * self.height * FORMATS[self.fourcc][1])

    def body(self):
        return self.raw[self.data_off:self.data_off + self.payload_size]

    def image(self):
        """Decode to an RGBA Pillow image."""
        from PIL import Image
        if self.fourcc not in FORMATS:
            raise ValueError('unknown format %r' % self.fourcc)
        n = FORMATS[self.fourcc][0]
        if n is None:
            return Image.frombytes('RGBA', (self.width, self.height),
                                   self.body(), 'raw', 'BGRA')
        return Image.frombytes('RGBA', (self.width, self.height),
                               self.body(), 'bcn', (n,))


def read_sources(path, needle=''):
    """[(name, bytes)] from a .cpk, a directory, or a single .tid."""
    if os.path.isfile(path) and not path.lower().endswith('.cpk'):
        return [(os.path.basename(path), open(path, 'rb').read())]
    if os.path.isdir(path):
        out = []
        for root, _d, files in os.walk(path):
            for n in sorted(files):
                if n.lower().endswith('.tid') and needle.lower() in n.lower():
                    out.append((n, open(os.path.join(root, n), 'rb').read()))
        return out
    c = CPK(path)
    return [(full, c.read(row)) for _i, full, row in c.files()
            if full.lower().endswith('.tid') and needle.lower() in full.lower()]


def cmd_list(a):
    rows = read_sources(a.src, a.filter or '')
    print('%-46s %6s %6s %-6s %11s %s'
          % ('file', 'w', 'h', 'fmt', 'payload', 'khop'))
    bad = 0
    for name, data in rows:
        try:
            t = TID(data)
        except ValueError as e:
            print('%-46s  !! %s' % (name, e))
            bad += 1
            continue
        exp = t.expected
        ok = 'OK' if exp == t.payload_size else '!! can %s' % exp
        bad += exp != t.payload_size
        print('%-46s %6d %6d %-6s %11s %s'
              % (name, t.width, t.height, t.fourcc.decode().strip(),
                 format(t.payload_size, ','), ok))
    print('-' * 92)
    print('%d texture, %d khong khop kich thuoc' % (len(rows), bad))
    return 1 if bad else 0


def cmd_unpack(a):
    rows = read_sources(a.src, a.filter or '')
    os.makedirs(a.out, exist_ok=True)
    done = skipped = 0
    for name, data in rows:
        try:
            t = TID(data)
            img = t.image()
        except (ValueError, OSError) as e:
            print('!! %-44s %s' % (name, e))
            skipped += 1
            continue
        dst = os.path.join(a.out, os.path.splitext(os.path.basename(name))[0] + '.png')
        img.save(dst)
        done += 1
        if a.verbose:
            print('%-46s %dx%d %s' % (name, t.width, t.height, t.fourcc.decode().strip()))
    print('giai ma %d texture -> %s%s'
          % (done, a.out, ', bo qua %d' % skipped if skipped else ''))
    return 1 if skipped else 0


def main():
    ap = argparse.ArgumentParser(description='read .tid textures out of GAME.cpk')
    sub = ap.add_subparsers(dest='cmd', required=True)

    p = sub.add_parser('list', help='header of every texture, with a size check')
    p.add_argument('src', help='a .cpk, a directory, or one .tid')
    p.add_argument('filter', nargs='?', help='only paths containing this')
    p.set_defaults(fn=cmd_list)

    p = sub.add_parser('unpack', help='decode to PNG')
    p.add_argument('src', help='a .cpk, a directory, or one .tid')
    p.add_argument('filter', nargs='?', default='', help='only paths containing this')
    p.add_argument('out', help='directory for the PNGs')
    p.add_argument('-v', '--verbose', action='store_true')
    p.set_defaults(fn=cmd_unpack)

    a = ap.parse_args()
    return a.fn(a)


if __name__ == '__main__':
    sys.exit(main())
