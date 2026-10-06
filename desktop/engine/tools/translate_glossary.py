"""
Sample translation of the Glossary screen, used to check how advfont (the
dialogue font) renders, plus the key-prompt bar at the bottom (sysfont).

  python translate_glossary.py <db_dir> <out_dir>
"""
import os
import sys

sys.path.insert(0, 'D:/VE/tools')
from gbnl import GBNL

# --- dbDictionary.gbin: the entries visible on page 1 ------------------------
# Proper nouns (Adolphe, Ankou, Arpechele) are left alone; only terms are translated.
DICT = {
    'Allelopathy': 'Tương khắc thực vật',
    'Analgesia': 'Chứng vô cảm đau',
    'Antibodies': 'Kháng thể',
    "A young man who lived with the#nheroine at the orphanage. He#n"
    "is the leader of the Corps, and#nthe heroine's foster brother.":
        'Chàng trai từng sống cùng nữ chính#ntại trại trẻ mồ côi. Anh là đội#n'
        'trưởng Binh đoàn, đồng thời cũng#nlà anh nuôi của nữ chính.',
}

# --- strKeyHelp.gstr: the key-prompt bar ------------------------------------
KEYHELP = {
    'Confirm': 'Xác nhận',
    'Set': 'Đặt',
    'Toggle': 'Chuyển',
    'Return': 'Quay lại',
    'Play': 'Phát',
    'Select': 'Chọn',
    'Stop': 'Dừng',
    'Play Scene': 'Xem cảnh',
    'Explanation Off': 'Tắt chú thích',
    'Scroll': 'Cuộn',
    'Rewind': 'Tua lại',
    'Toggle Extras': 'Chuyển mục phụ',
}


# --- strOption.gstr: the font preview box (Options > Display > Font) ---------
# Hand-written sample, deliberately packed with all five tone marks plus
# circumflex, breve, horn and D-stroke, including uppercase O+horn+hook - the
# tightest stack in Vietnamese - so all four fonts can be compared on one screen.
OPTION = {
    '"As the people could not resist death,#nthey instead decided to repeat it...'
    '#nTo live beside death for all eternity."':
        'Đêm khuya, kẻ lữ hành dừng bên gốc đa,#n'
        'ngẩng nhìn vầng trăng lặng lẽ trôi...#n'
        'Ở nơi ấy, ước vọng đã hoá thành tro.',
}


def apply(src, dst, repl, label):
    g = GBNL(open(src, 'rb').read())
    have = set(g.strings().values())
    hit = {k: v for k, v in repl.items() if k in have}
    miss = [k for k in repl if k not in have]
    out = g.build(hit)
    open(dst, 'wb').write(out)
    print('%s: replaced %d/%d strings, %d -> %d bytes'
          % (label, len(hit), len(repl), len(g.raw), len(out)))
    for k, v in hit.items():
        print('   %-34r -> %r' % (k[:32], v[:40]))
    if miss:
        print('   NOT FOUND:', miss)


def main():
    srcdir, outdir = sys.argv[1], sys.argv[2]
    os.makedirs(outdir, exist_ok=True)
    apply(os.path.join(srcdir, 'dbDictionary.gbin'),
          os.path.join(outdir, 'dbDictionary.gbin'), DICT, 'dbDictionary')
    apply(os.path.join(srcdir, 'strKeyHelp.gstr'),
          os.path.join(outdir, 'strKeyHelp.gstr'), KEYHELP, 'strKeyHelp')
    apply(os.path.join(srcdir, 'strOption.gstr'),
          os.path.join(outdir, 'strOption.gstr'), OPTION, 'strOption')


if __name__ == '__main__':
    main()
