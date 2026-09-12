"""
build.py - one command to go from stock CPK to an installable mod.

    python build.py            # build dist/SYSTEM.cpk
    python build.py --install  # ...and copy it into the Ryujinx mods folder
    python build.py --fonts-only
    python build.py --clean    # drop the extracted stock files and rebuild them

Pipeline:
    1. extract the stock .ffu templates and text files from SYSTEM.cpk -> work/stock/
    2. render each .ffu from the source font named in fonts.json     -> work/out/
    3. apply the translated strings                                  -> work/out/
    4. repack everything back into the CPK                           -> dist/

Step 1 is cached: the stock files only need extracting once. Steps 2-4 always
re-run, since they are what you iterate on.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.join(ROOT, 'tools')
WORK = os.path.join(ROOT, 'work')
STOCK = os.path.join(WORK, 'stock')
OUT = os.path.join(WORK, 'out')
DIST = os.path.join(ROOT, 'dist')

sys.path.insert(0, TOOLS)


def load_config():
    with open(os.path.join(ROOT, 'fonts.json'), encoding='utf-8') as fh:
        return json.load(fh)


def extract_stock(cfg):
    """Pull the stock .ffu templates and text files out of the CPK."""
    from cpk import CPK
    os.makedirs(STOCK, exist_ok=True)
    wanted = set(cfg['fonts']) | set(cfg['text'])
    have = {os.path.basename(p) for p in wanted
            if os.path.exists(os.path.join(STOCK, os.path.basename(p)))}
    if len(have) == len(wanted):
        print('stock : cached (%d files)' % len(have))
        return

    src = os.path.join(ROOT, cfg['cpk'])
    if not os.path.exists(src):
        sys.exit('missing %s - copy the game romfs here first' % cfg['cpk'])
    print('stock : extracting from %s ...' % cfg['cpk'])
    c = CPK(src)
    for _i, full, row in c.files():
        if full in wanted:
            dst = os.path.join(STOCK, os.path.basename(full))
            with open(dst, 'wb') as fh:
                fh.write(c.read(row))
            print('        %s' % os.path.basename(full))


def build_fonts(cfg):
    os.makedirs(OUT, exist_ok=True)
    for path, spec in cfg['fonts'].items():
        name = os.path.basename(path)
        tpl = os.path.join(STOCK, name)
        src = os.path.join(ROOT, spec['source'])
        if not os.path.exists(src):
            sys.exit('missing font %s - see Font/README.md' % spec['source'])
        print('font  : %-14s <- %s' % (name, os.path.basename(src)))
        r = subprocess.run(
            [sys.executable, os.path.join(TOOLS, 'ffugen.py'),
             '--template', tpl, '--out', os.path.join(OUT, name), '--font', src],
            capture_output=True, text=True, encoding='utf-8', errors='replace')
        if r.returncode:
            sys.exit(r.stdout + r.stderr)
        for line in r.stdout.splitlines():
            if line.startswith(('size', 'cell', '  rendered')):
                print('        %s' % line.strip())


def build_text():
    print('text  : applying translations')
    r = subprocess.run(
        [sys.executable, os.path.join(TOOLS, 'translate_glossary.py'), STOCK, OUT],
        capture_output=True, text=True, encoding='utf-8', errors='replace')
    if r.returncode:
        sys.exit(r.stdout + r.stderr)
    for line in r.stdout.splitlines():
        if ': replaced' in line:
            print('        %s' % line.strip())


def repack(cfg):
    os.makedirs(DIST, exist_ok=True)
    dst = os.path.join(DIST, cfg['cpk'])
    print('repack: -> %s' % os.path.relpath(dst, ROOT))
    r = subprocess.run(
        [sys.executable, os.path.join(TOOLS, 'cpk.py'), 'repack',
         os.path.join(ROOT, cfg['cpk']), dst, OUT],
        capture_output=True, text=True, encoding='utf-8', errors='replace')
    if r.returncode:
        sys.exit(r.stdout + r.stderr)
    for line in r.stdout.splitlines():
        if 'replaced' in line:
            print('        %s' % line.strip())
    return dst


def install(cfg, built):
    appdata = os.environ.get('APPDATA')
    if not appdata:
        sys.exit('APPDATA is not set - cannot locate the Ryujinx mods folder')
    dst_dir = os.path.join(appdata, 'Ryujinx', 'mods', 'contents',
                           cfg['title_id'], cfg['mod_name'], 'romfs')
    os.makedirs(dst_dir, exist_ok=True)
    dst = os.path.join(dst_dir, cfg['cpk'])
    shutil.copy2(built, dst)
    print('install: %s' % dst)


def main():
    ap = argparse.ArgumentParser(description='build the Virche Vietnamese mod')
    ap.add_argument('--install', action='store_true',
                    help='copy the result into the Ryujinx mods folder')
    ap.add_argument('--fonts-only', action='store_true',
                    help='rebuild the fonts but skip the text step')
    ap.add_argument('--clean', action='store_true',
                    help='discard the extracted stock files and re-extract')
    a = ap.parse_args()

    cfg = load_config()
    if a.clean and os.path.isdir(WORK):
        shutil.rmtree(WORK)

    extract_stock(cfg)
    build_fonts(cfg)
    if not a.fonts_only:
        build_text()
    built = repack(cfg)
    if a.install:
        install(cfg, built)
    print('done')


if __name__ == '__main__':
    main()
