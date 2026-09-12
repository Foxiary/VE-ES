# CLAUDE.md

Format notes for the Virche Evermore Vietnamese translation. Everything here was
reverse-engineered from the shipped files and verified in-game on Ryujinx.

## What this repository is

A **reusable OTF/TTF → `.ffu` bitmap font generator** for Otomate / Idea Factory
titles, plus the text-patching tools that go with it. Virche Evermore is the
first target, not the only one — `tools/ffugen.py` takes any stock `.ffu` as a
template, so a different game means a different `--template`, not new code.

The repo holds no game content. `SYSTEM.cpk` and friends sit in the working
directory but are gitignored.

## Container: `.cpk` (CRI Middleware)

`tools/cpk.py`. Structure:

```
0x0000  'CPK '  + @UTF table   CpkHeader: TocOffset, ContentOffset, ContentSize,
                               EtocOffset, Align, Files, ...
TocOffset       'TOC '  + @UTF DirName, FileName, FileSize, ExtractSize, FileOffset
ContentOffset   file data, aligned to Align (16)
EtocOffset      'ETOC'  + @UTF (timestamps; copied verbatim)
```

`FileOffset` in the TOC is relative to `min(TocOffset, ContentOffset)`.

A file is compressed when `ExtractSize > FileSize`; the payload then begins with
`CRILAYLA` (LZSS with a backwards bit stream — `cpk.crilayla`).

**Repack strategy.** Replacement files are written **uncompressed**; every other
file is copied byte-for-byte in its existing compressed form and never touched.
Only numeric cells are patched in place — `FileSize`, `ExtractSize`,
`FileOffset` in the TOC, and `ContentSize`, `EtocOffset` in the header — so the
schema and string pool stay identical. That is why `SYSTEM.cpk` grows from 88 MB
to about 460 MB: no CRILAYLA compressor exists here, and writing one in Python
would be too slow to use.

## Fonts: `.ffu`

`tools/ffu.py` reads and writes these; `tools/ffugen.py` generates them.

```
0x00  u16  magic 'UF' (0x4655)
0x02  u16  range count
0x04  u16  glyph count
0x08  u16  low byte 3; high byte 41 (sysfont) / 76 (advfont) — purpose unknown
0x0A  u16  low byte = GLYPH CELL HEIGHT, high byte = 1
0x0E  u16  duplicate of 0x0A
0x14  u32  range table offset       0x18  u32  glyph table offset
0x1C  u32  bitmap data offset
0x28       palette: n * 16 RGBA8888 entries (index 0 transparent, 15 opaque)
           n = (range_offset - 0x28) / 64 — sysfont has 16, advfont has 1
RANGE      12 bytes: (u32 start, u32 end_exclusive, u32 glyph_base)
GTAB        8 bytes: (u8 advance, u8 height, u16 data_size, u32 data_offset)
BMP        4bpp pixels, HIGH NIBBLE FIRST
```

**Character lookup.** A character's UTF-8 bytes are read as a **big-endian
integer** and looked up in the range table:

```
U+1EA4 -> E1 BA A4 -> 0xE1BAA4
glyph_index = glyph_base + (utf8int(ch) - start)
```

So adding Vietnamese needs only new ranges — no code-page hack, no stealing
kanji slots. The table must stay **sorted ascending**; the engine binary-searches it.

**Geometry.** `bitmap_width = data_size * 2 / height`, and width is always a
multiple of 8. Field limits: `advance` and `height` are u8 (≤ 255), `data_size`
is u16 (≤ 65535).

### The five stock fonts

| file | glyphs | cell | cap | stroke ratio | typeface |
|---|---|---|---|---|---|
| sysfont | 7 943 | 37 | 23 | 1.67 | mincho |
| advfont1 | 22 853 | 88 | 54 | 2.43 | mincho, heavy |
| advfont2 | 22 853 | 88 | 52 | 2.00 | mincho, light |
| advfont3 | 22 853 | 88 | 52 | 1.20 | gothic, heavy |
| advfont4 | 22 853 | 88 | 54 | 1.17 | gothic, light |

advfont1–4 are the four choices behind Options → Display → Font. Stroke ratio is
the vertical/horizontal stem width of `O`: mincho carries high contrast, gothic
is near-uniform. sysfont measures lower than the other mincho files only because
a horizontal stem cannot go below 1px at cap height 23.

Only 44 of the 146 Vietnamese accented characters ship in the stock fonts (the
Latin-1 ones). advfont additionally has 12 **blank** entries — `Ăă Ĩĩ Ơơ Ũũ Ưư Đđ`
exist in the range table but hold no pixels.

## Data files: `.gbin` (GBNL) and `.gstr` (GSTL)

`tools/gbnl.py`. Same shape, different magic placement: GSTL puts the header at
the start of the file, GBNL puts it in the **last 64 bytes**.

```
[record table]  n * stride bytes at hdr.tbl
[schema block]  ncol * 4 bytes: (u16 type, u16 offset); type 5 = string cell
[string pool]   NUL-terminated UTF-8 at hdr.pool
[footer]        GBNL only
```

String cells hold a u64 offset **relative to the pool**. `n_slot` at `0x28`
counts string *cells*, not distinct strings — several records commonly share one
string.

Text is plain UTF-8 and `#n` is the engine's line break.

## Traps that produce silently wrong results

**Header height out of sync crashes the game.** `0x0A` / `0x0E` is what the
engine sizes its draw buffer from. Writing 108px glyphs while the header still
says 88 crashes on text-heavy screens. `ffugen.py` and `vnfont.serialize()`
both set it; hand edits must too.

**Zeroing the schema block crashes the game.** It sits between the record table
and the string pool, and an early version of `gbnl.py` padded over it — the
Special Scenario screen died instantly because `strKeyHelp.gstr` drives its key
prompt bar. Always copy `raw[tbl_end:pool]` into the rebuilt file.

**Verify tools by round-trip, not by eye.** Rebuild a file with *no* edits and
compare bytes; anything other than bit-identical means the tool is lossy:

```bash
python tools/gbnl.py work/stock/dbDictionary.gbin   # -> BIT-IDENTICAL
```

That is how the schema bug was found, and it holds for all 22 files in `DATABASE/`.

**Guessing which cells are strings hits false positives.** Scanning for values
that happen to point at a string start also matches numeric columns and corrupts
them. Read the schema instead.

**Rendered glyphs must match the template's cap height.** Kanji are kept from
the template, so Latin rendered even slightly larger or smaller reads as two
different fonts on one line. `ffugen.match_px` binary-searches the pixel size to
match; do not hardcode `--px` unless you have a reason.

**Patching `.gstr` in place caps string length.** `tools/patchstr.py` overwrites
the old slot, so a replacement must be ≤ the original in UTF-8 *bytes* —
Vietnamese with diacritics is usually longer than English. Use `gbnl.py`, which
rebuilds the pool and remaps offsets, when the text needs to grow.

## Tooling

See `tools/README.md`. The short version:

- `ffu.py` — read/write `.ffu`, in-place glyph edits
- `ffugen.py` — **the main tool**: render a `.ffu` from OTF/TTF
- `vnfont.py` — older approach, composes diacritics from the stock glyphs
- `cpk.py` — list / unpack / repack `.cpk`
- `gbnl.py` — read/rebuild `.gbin` and `.gstr` (offsets remapped, text may grow)
- `patchstr.py` — in-place `.gstr` edits (length-capped)
- `translate_glossary.py` — the sample translations used to check rendering

## Conventions

Code comments and docstrings in **English**. `AGENTS.md` and the READMEs are in
Vietnamese; this file is English because it documents formats.

No font subsetting yet — every `.ffu` carries the full stock charset, which is
why each one is ~100 MB uncompressed.
