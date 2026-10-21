"""jpfiles.py - where the Japanese build's archives are in the project folder.

    from jpfiles import find_jp
    find_jp('STORY.cpk')     # -> 'work/jp/CONTENTS/STORY.cpk', another path, or None

They used to have one place, work/jp/CONTENTS/, and every tool assumed it. A
project can lay the Japanese romfs out however it likes, so the tools look for
it instead: that place first, as before, then any other archive of the same name
anywhere in the project folder - not the English one at its root, and not the
build's own output.

A name is not enough to go on. A backup of the English archive or a patched
Vietnamese one is called STORY.cpk too, so a candidate counts only when its
script text is mostly Japanese. Mostly, not merely some: the English build
keeps Japanese keys in its chapter titles (`<japanese key>@<title>`). Measured
on two dialogue scripts each, the Japanese build reads 0.21 CJK characters per
Latin letter and the English and Vietnamese ones 0.01; the cut sits between.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cpk import CPK                                # noqa: E402

DEFAULT_DIR = os.path.join('work', 'jp', 'CONTENTS')
# Folders that hold the build's own output, copies of the tools, or nothing of the game.
SKIP_DIRS = {'.git', 'dist', 'runs', '__pycache__', 'tools', 'Font', 'node_modules'}
SKIP_PATHS = {os.path.join('work', 'out'), os.path.join('work', 'stock')}
TEXT_FILES = ('.dat', '.gstr', '.gbin')
CJK_RX = re.compile('[぀-ヿ一-鿿]')
LATIN_RX = re.compile('[A-Za-z]')
JAPANESE_RATIO = 0.08


def candidates(name, root='.'):
    """Every file called `name` below `root`, except the one at its top level."""
    found = []
    for folder, dirs, files in os.walk(root):
        rel = os.path.relpath(folder, root)
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS
                         and os.path.normpath(os.path.join(rel, d)) not in SKIP_PATHS)
        if rel == '.':
            continue
        found += [os.path.join(folder, f) for f in sorted(files) if f.lower() == name.lower()]
    return found


def japanese_ratio(path, sample=2):
    """CJK characters per Latin letter over a few small text files of the archive.

    The smallest files above 20 KB, skipping init/: those hold flags rather than
    lines, and the archive is CRILAYLA-compressed, so small keeps this quick.
    """
    archive = CPK(path)
    rows = [row for _i, name, row in archive.files()
            if name.lower().endswith(TEXT_FILES) and '/init/' not in name.lower()]
    rows.sort(key=lambda row: row['ExtractSize'])
    cjk = latin = 0
    for row in [r for r in rows if r['ExtractSize'] > 20000][:sample] or rows[:sample]:
        text = archive.read(row).decode('utf-8', 'ignore')
        cjk += len(CJK_RX.findall(text))
        latin += len(LATIN_RX.findall(text))
    return cjk / max(latin, 1)


def is_japanese(path):
    try:
        return japanese_ratio(path) > JAPANESE_RATIO
    except Exception:                          # not an archive this reader knows
        return False


def find_jp(name, root='.'):
    """Path to the Japanese build's `name` in the project folder, or None."""
    default = os.path.join(root, DEFAULT_DIR, name)
    if os.path.exists(default):
        return default
    for path in candidates(name, root):
        if is_japanese(path):
            return path
    return None


if __name__ == '__main__':
    for archive in sys.argv[1:] or ['STORY.cpk', 'SYSTEM.cpk']:
        print('%s: %s' % (archive, find_jp(archive) or 'khong thay ban tieng Nhat'))
