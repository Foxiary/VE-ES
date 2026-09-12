"""
patchstr.py - edit strings inside a .gstr (GSTL) file in place.

A .gstr holds key/value UTF-8 strings, each NUL-terminated, in a string pool at
the end of the file. The offset table uses ABSOLUTE offsets, so a replacement
may only be written over the old slot: the new string must be <= the old one in
UTF-8 BYTES, with the remainder padded with NULs. That keeps the offset table
valid without rebuilding it.

For replacements that need to be LONGER, use gbnl.py instead - it rebuilds the
pool and remaps every offset.
"""
import sys

POOL_OFF = 0x2c          # u32 here = start offset of the string pool


def read_pairs(d):
    """Return [(key, val_offset, val_bytes)] in pool order."""
    import struct
    pool = struct.unpack_from('<I', d, POOL_OFF)[0]
    out, off, prev = [], pool, None
    while off < len(d):
        e = d.index(b'\x00', off)
        s = d[off:e]
        if prev is None:
            prev = (off, s)
        else:
            out.append((prev[1].decode('utf-8', 'replace'), off, s))
            prev = None
        off = e + 1
    return out


def patch(d, repl, verbose=True):
    """repl: {key: new_text}. Returns (new_bytes, number_of_edits)."""
    buf = bytearray(d)
    pairs = {k: (o, v) for k, o, v in read_pairs(d)}
    done, skipped = 0, []
    for key, new in repl.items():
        if key not in pairs:
            skipped.append((key, 'no such key'))
            continue
        off, old = pairs[key]
        nb = new.encode('utf-8')
        if len(nb) > len(old):
            skipped.append((key, 'too long: %d > %d bytes' % (len(nb), len(old))))
            continue
        buf[off:off + len(old)] = nb + b'\x00' * (len(old) - len(nb))
        done += 1
        if verbose:
            print('  %-28s %2d/%2d byte  %r' % (key, len(nb), len(old), new))
    for k, why in skipped:
        print('  SKIP %-26s (%s)' % (k, why))
    return bytes(buf), done


# Probe strings: all shown on the title / boot screens, and together they
# cover all five tone marks plus circumflex, breve, horn and D-stroke.
TEST = {
    'IDS_MC_TITLE_NEWGAME':  'Bắt đầu từ đầu',
    'IDS_MC_TITLE_CONTINUE': 'Tiếp tục ván đã lưu',
    'IDS_MC_TITLE_FLOWCHART': 'Tiến trình',
    'IDS_MC_TITLE_ALBUM':    'Thư viện',
    'IDS_MC_TITLE_OPTION':   'Tùy chọn',
    'IDS_MC_CHECK_START':    'Đang kiểm tra...',
    'IDS_MC_CHECK_LOAD':     'Đã tìm thấy dữ liệu.',
    'IDS_MC_CHECK_NODATA':   'Không tìm thấy dữ liệu.',
    'IDS_ENTER':             'Chọn',
    'IDS_BACK':              'Quay',
    'IDS_CANCEL':            'Hủy',
    'IDS_MC_ALBUM_GALLERY':  'Xem CG',
    'IDS_MC_ALBUM_BGM':      'Nghe nhạc',
    'IDS_MC_ALBUM_MOVIE':    'Xem phim',
    'IDS_SUB_REWIND_LOG':    'Tua',
    'IDS_NOVEL_LOG':         'Độc thoại',
}


def main():
    src, dst = sys.argv[1], sys.argv[2]
    d = open(src, 'rb').read()
    out, n = patch(d, TEST)
    open(dst, 'wb').write(out)
    print('edited %d/%d strings -> %s' % (n, len(TEST), dst))


if __name__ == '__main__':
    main()
