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

### What the English build's Latin actually is

Comparing the USA files against the JP ones settles which glyphs are Japanese
and which the localiser drew:

| | kanji / kana | Latin | cap, EN → JP |
|---|---|---|---|
| sysfont | identical | **identical** | 23 → 23 |
| advfont1–4 | identical | **all 62 differ** | 54→60, 52→62, 52→62, 54→59 |

So Aksys kept every Japanese glyph and re-rendered only the Latin of the four
ADV fonts, at a smaller cap than the JP build. sysfont they left alone: its
Latin is the Japanese mincho's own.

Matching those four against 489 local faces and 1 067 Google Fonts families
(weight swept) identifies them:

| `.ffu` | typeface | fingerprint error | gap to runner-up |
|---|---|---|---|
| advfont1 | Jomolhari | 0.034 | 2.7× |
| advfont2 | **Source Serif 4 Regular** | 0.025 | 4.6× |
| advfont3 | **Open Sans SemiBold** | 0.023 | 3.9× |
| advfont4 | Sawarabi Gothic | 0.044 | 2.9× |

Rebuilding a whole line from Source Serif 4 the way the EN generator lays glyphs
out reproduces the stock bitmap, down to the gap after `f` in "Drifter".

**Only advfont2 and advfont3 are usable as-is.** Jomolhari carries 48 of the 146
Vietnamese characters and Sawarabi Gothic 120, so advfont1 and advfont4 need a
stand-in — Tinos sits in the same Times-derived cluster as Jomolhari, and Open
Sans Regular keeps advfont3/4 a matched weight pair the way the stock files are.

Two caveats on the two identified by name. Jomolhari's runners-up are all
minority-script faces — Scheherazade New, Nuosu SIL, Tai Heritage Pro, Microsoft
Himalaya — which bundle the same Times-derived Latin, so what is established is
that the outlines match, not that Aksys licensed that font rather than a shared
ancestor. The same applies to Sawarabi Gothic.

**Advances carry no typeface information here.** In advfont1–4 `adv - ink` is 2
or 3 px for every one of the 62 Latin glyphs and `lsb` is 0 or 1: the EN
generator threw the typeface's side bearings away and packed each glyph to its
own ink box. Fingerprinting on advances therefore bottoms out around 5% error
and names the wrong faces. Fingerprint on the **ink box** — width, height and
height above baseline per glyph, normalised by cap height. sysfont is the
exception that proves it: `adv - ink` runs 4–8 there, because that file still
has its original bearings.

### The engine draws the ADV font at 0.588

Measured off a screenshot: the word `chống` is 182 px wide in `advfont1.ffu` and
107 px on screen at 1080p. The Glossary and the Options sample box both use it.

This is what decides Vietnamese legibility, and it is not a font problem.
Vietnamese stacks a tone mark over a circumflex or breve, and at these cap
heights the Latin faces leave **0 to 2 blank rows** between the two — 0 for Lora
and Cabin, 1 for Newsreader, Source Serif and Open Sans, 2 for Tinos. Scaled by
0.588 that is under a pixel, so the pair renders as one blunt mark and reads as
a clipped acute. Nothing is clipped: every Vietnamese glyph in a generated
`.ffu` matches its source outline row for row, which is worth re-checking before
believing otherwise.

`ffugen --mark-lift N` is the fix: it raises the topmost ink band of any letter
whose NFD form carries **two** combining marks *above* (class 230), which is
exactly the Vietnamese stack and leaves the Latin-1 set alone. Counting every
combining mark was wrong: `ự ợ` are base + horn + dot below, the horn is joined
to the body, so the "topmost band" was the whole letter and it rose 3 rows off
the baseline, visible in game. The cell has ~16 rows of headroom above
the tallest stacked lowercase letter. At `--mark-lift 3` the blank averages 3.1
to 3.5 rows, about 2 px on screen. Going higher starts clamping: capitals like
`Ế Ổ Ẫ` already sit near the top of the cell, and the lift is capped per glyph
so nothing is pushed out of it. Letters where the tone mark is the only mark on
top — `ớ ờ ứ ừ` and friends, horn at the side — are skipped, having nothing to
be confused with.

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

## Scripts: `.DAT` (STCM2L)

`tools/stcm2l.py`. The dialogue itself, 117 files in `STORY.cpk`.

```
0x00   "STCM2L <build date>"          0x20  u32 -> EXPORT_DATA, u32 ?,
                                            u32 export count, u32 -> COLLECTION_LINK
0x50   "GLOBAL_DATA"                  0x1F0 "CODE_START_"
...    instruction stream             then  EXPORT_DATA, COLLECTION_LINK

INSTRUCTION  u32 global_call, u32 opcode, u32 param_count, u32 length
PARAMETER    12 bytes: (value, jump, tag)
DATA BLOCK   u32 flag, u32 nwords, u32 one, u32 length, payload padded to 4
```

**Three fields hold absolute addresses, and none of them look like pointers.**
All three were missing from the rebuild at some point, and each produced a
different symptom, none of which the existing checks could see:

| field | count (EN build) | symptom when stale |
|---|---|---|
| `opcode`, when `global_call == 1` | 350,273 of 718,773 | — |
| parameter word 2, opcodes 3 and 6 | 72,057 | **black screen** |
| `COLLECTION_LINK + 4` = total file size | 1 per file | — |

`global_call == 1` means the second field is not an opcode but the address of
the instruction to CALL. Opcode 3 is a conditional branch and keeps its target
in parameter 3; opcode 6 is a goto and keeps it in parameter 0 — 100% of both
land exactly on an instruction start. Word 3 of a parameter is never an address.

**Anything pointing at an instruction must be written in a second pass.** A
forward jump or call names an instruction whose new offset is not known yet
while the first pass is still laying instructions out, so emitting it there
silently keeps the old address. Doing that fixed only the backward jumps — 15 of
609 in `100.DAT` — and looked like it worked.

**The fan disc (EpiC:Lycoris) has its own opcode table.** Roles sit at
text 81904, name 84024, choice 88556, title 11312, var 253912 / 254832 /
308408 / 308952 — not the main game's table rebased, since text and name moved
by different amounts. Within the fan disc the table moves as one piece again
(delta 0/16/32). `mksheet.detect_table()` picks the table; `detect_delta()`
still answers for the main game only, so `applyvi`, `reflow`, `relinkjp` and
`exportvar` skip fan disc scripts rather than misread them. Its chapter titles
carry **no** `key@` prefix, and 27 of its 150 scripts (`0_init`, `2000`–`2130`,
…) hold only flags.

Its two builds are much less alike than the main game's: Japanese scripts run
up to ~2% longer, and `405.DAT` has 4449 instructions on both sides and still
drifts. `portjp2us.align()` trusts equal counts and pairs on (params, blocks),
which put a name on a text line; `mksheet.jp_story_map()` now falls back to
`role_align()` whenever the index map lands any role on a different role. That
takes the Japanese column from 95.5% to 98.4%. The remaining ~1,500 are lines
English added to a box, with no Japanese instruction at all.

**Rows covered is not text covered.** At 98.4% of rows the column still lacked
3,882 of 77,962 Japanese lines: where a box ran longer in Japanese, English had
deleted the slot, and those lines reached no row, so a translator saw
`「でもお前は……` without the rest of the sentence. `_rescue_boxes()` joins such
a line to its neighbour within the box, and pairs a wholly unaligned Japanese
box with the unfilled English box between the same two anchors; 239 lines are
still lost. A box is a run of text instructions with nothing between them - a
narrow rule ("stop at a speaker name") carried a narration line into the
dialogue before it, since narration has no name row. `1444.DAT` is the
reverse - a whole scene only the JP build ships, although the EN
`dbEntryScript` lists it.

**Growing a block is safe** once all three are rebased: 54 files, +1.13 MB, call
graph and jump graph identical, verified in game. The older note in
`portjp2us.py` that a size change crashes was describing these stale pointers,
not a rule of the format.

## Textures: `.tid`

`tools/tid.py`. GAME.cpk holds nothing else worth reading - 714 `.tid` textures
and 777 `.CL3` sprite archives, no text files at all.

```
0x00  'TID' + format byte       0x04  u32 total size
0x08  u32 data offset (0x80)    0x14  u32 -> name
0x20  file name, NUL-padded
0x40  u32 -> fourcc block       0x44  u32 WIDTH     0x48  u32 HEIGHT
0x58  u32 payload size          0x5C  u32 data offset again
0x64  FOURCC                    0x80  pixel data
```

FOURCC is `DXT1` (0.5 bytes/px), `DXT5` or `BC7 ` (1.0), or **four NUL bytes**,
which is not a block format at all but raw 32-bit **BGRA**. The format byte at
0x03 agrees - 0x90 for DXT1, 0x80 for the rest - but the fourcc is the
unambiguous one. `width * height * bytes-per-pixel` equals the payload exactly,
and `tid.py list` prints that comparison per file so a misread header shows up
as a mismatch instead of a wrong picture.

**The payload is linear, not swizzled.** Switch textures are normally stored
block-linear and have to be untiled first. These are not, so Pillow's own `bcn`
decoder reads them directly and `tid.py` is only a header parser. That was
checked, not assumed: the first blocks of `title_bg1.tid` hold coherent
neighbouring colours rather than the scattered ones tiling would give, and the
decode was then confirmed against a screenshot.

**A lot of interface text is painted into these, not drawn from a string.** The
title screen's whole menu - Start, Load, Flowchart, Scene List, Special, Options
- is one 2048x1024 BC7 atlas at three states per item, together with the logo,
"Press Any Button" and the copyright line. The Glossary screen's own title, its
`Notes` label and the `-NEW-` badge are in `dictionary_parts.tid`; character
names are painted into `chsel_face*.tid`. None of it is reachable through
`mksheet.py`, and translating it means redrawing art.

**Writing them back is not solved.** Pillow decodes BCn and does not encode it,
so a redrawn atlas needs a compressor this repo does not have.

## Text that is not in romfs: `exefs/main`

`tools/exefs.py`. The title screen shows a quote from the ending you last
cleared, and all **twelve** of them are C strings in the `.rodata` of
`exefs/main` - not in any CPK. That was established by elimination: every one of
the 22 databases in SYSTEM.cpk, all 117 scripts in STORY.cpk, `SaveUtil/` and
`Shader/` were searched decompressed, and GAME.cpk holds only `.tid` and `.CL3`.

They are spelled unlike every other string in the game - the break is a real
`
`, not `#n`, and paragraphs are separated by `
 
`, which is what finds
them. 124 to 252 bytes each; `work/title_quotes.xlsx` carries them with that
budget. There is no Japanese column: the JP build keeps none of these in its
executable, in `main` or in `subsdk0`, so the quotes look like something the
localisation added.

```bash
python tools/exefs.py extract  "...[USA][v0].nsp" work/exefs   # needs prod.keys
python tools/exefs.py segments work/exefs/main work/exefs      # LZ4 segments
python tools/exefs.py strings  work/exefs/main.rodata.bin --grep "
 
"
python tools/exefs.py sheet    work/exefs/main.rodata.bin --grep "
 
"
```

The sheet's id is shaped `main.rodata___2BD34_exe` **so that nothing applies
it by accident**: it fails the regex in `checksheet.py`, `applyvi.py` and
`applyui.py` alike, because these rows address neither a `.DAT` block nor a
`.gbin` cell. The break in them is a real newline and must stay one -
`linebreak.to_game()` would turn it into `#n`, which is wrong here.

**Patching this ships somewhere else.** A CPK mod cannot reach an executable;
Ryujinx loads one from `mods/contents/<title id>/<name>/exefs/`, independent of
the `romfs/` that `build.py --install` writes. `tools/applyexe.py` does the
write.

**A longer translation is moved, not refused.** `.rodata` is packed with no
slack, but the quotes are reached through a **64-bit pointer table** at the
start of the segment - not through an ADRP/ADD pair in `.text`, which was
searched for and does not exist. So a string that outgrows its span is written
into the 4,056 bytes of page padding between `.rodata` and `.data` and its
pointer re-aimed; all twelve at +25% need about 2,857 of those bytes. In-place
is still preferred when the translation fits.

**The NSO is rebuilt uncompressed**, clearing bits 0-2 of the flags at 0x0C
rather than carrying an LZ4 compressor - 1.8 MB becomes 2.9 MB. Bits 3-5 say all
three segments are SHA256-checked, with the digests at 0xA0/0xC0/0xE0 taken over
the *decompressed* bytes, so those have to be rewritten too. That this is what
the fields mean was confirmed before anything was written: hashing the three
decompressed segments of the shipped `main` reproduces all three stored digests.

## Text limits: width, not bytes

**There is no byte limit.** A probe build put lines of 100, 150, 200, 300, 500
and 800 bytes on screen; the game ran through all of them. The "84 bytes" that
both stock builds happen to stop at is not an engine constant — it is just how
wide English needed to be.

**What overflows is the rendered width**, and bytes are a bad proxy for it:
Vietnamese spends two bytes on an accented letter and draws it as one ordinary
glyph. Measured on the translation the two disagree in both directions, and a
line of exactly 84 bytes was found 26% wider than the widest stock line.

`tools/textwidth.py` sums the glyph advances out of the `.ffu` table. Box widths
were read off a probe build rather than guessed:

| screen | advance units |
|---|---|
| narration (full width) | ~3200 |
| message box | ~2990 |
| **backlog** | **~2430** |

Design against the backlog: it replays every line of dialogue, so a line that
fits the message box and not the backlog is still broken. One ceiling covers all
four fonts — they share a cell height, so a unit is the same on screen in each;
what differs is how many units a sentence costs, which is why a line is only
safe when it fits under the ceiling in *all four*.

**Measure with the font that ships, not the stock one.** The build replaces
`SYSTEM.cpk` with regenerated Vietnamese fonts whose metrics differ. Measuring
the stock file makes advfont3 come out wider than advfont1 (3068 vs 2998) for a
string that is plainly narrower in advfont3 on screen — with the shipped fonts
it is 3032 vs 3198. Every width number taken from the wrong file is wrong.

## Traps that produce silently wrong results

**Structural checks cannot see a stale pointer.** `Script.check()` and
`check_pointers()` both pass on a file whose 6,539 call targets all point into
the middle of the wrong instruction — neither one reads the `opcode` field or a
parameter's jump word. Clean checks are not evidence the game runs; only running
it is. Compare `call_targets()` and `jump_targets()` across a rebuild instead,
in instruction indices, and confirm on hardware.

**Reproduce minimally before theorising.** Three separate fixes were shipped on
the strength of clean structural checks and all three still crashed. What found
the real cause in one pass was a build differing from stock by eight bytes and
one line: the diff was small enough to read in full, and the 26 words that
should have moved and had not were all in the same field.

**A text-keyed replacement must be keyed on the file's own string.**
`gbnl.build()` looks each pool string up in the replacement dict verbatim, so a
key taken from a sheet's source column instead of from `g.text(rel)` matches
nothing when the two differ by so much as a space - and the row still counts as
applied. That shipped once: every multi-line glossary description stayed English
while the single-line names translated fine, and the build's own `verify()`
agreed with itself because it used the same wrong key. Compare tolerantly
(`linebreak.canon()`), but key exactly. Address-keyed writes - `applyvi.py` and
`applyexe.py`, which patch a byte offset - cannot hit this.

**A spreadsheet holds real newlines; the game holds `#n`.** Every sheet is
written with `linebreak.to_sheet()` and must be read back through
`linebreak.to_game()` — `mksheet`, `glossary`, `checksheet`, `applyvi`,
`applyen` and `reflow` all do. A reader that skips it sees a source column
that no longer matches any block and silently applies nothing. The swap is
lossless because no shipped string contains a raw control character (checked
over all 97,110 extractable rows) and `#n` is the only command spelled with a
lowercase `n`. Byte counts are taken before the swap: a break is two bytes in
the game and one in a cell. Sheets written before this carry literal `#n` and
still apply unchanged — `to_game()` leaves them alone.

**Fitting a font on one dimension distorts every other one.** `ffugen` sizes the
source to the template's cap height, and that is the only measure it then
matches. Three attempts at closing the visible gap each fixed one number and
broke another: matching cap height left the strokes 36% thinner than stock;
matching the vertical stem made the face read as bold, because the stock stem
ratio is 1.33 and the Latin serifs are near 2.0, so equal stems mean much
thinner horizontals; forcing every glyph to a uniform side bearing opened a hole
after `f`, whose hook is drawn to overhang on purpose. Measure the ratio and the
dimensions not being fitted - stem vertical/horizontal, x-height, the width of a
reference string - before concluding a font matches.

**A generated font is narrower than the stock one because the typeface is,
not because anything was lost.** This was got wrong once and the wrong version
was written down, so the measurement is here: summing advances over a sentence,
a generated `.ffu` matches its own source font to **+0.0%** at sysfont's cap
height of 23 and at advfont1's 54. Nothing rounds away.

What the earlier note mistook for lost side bearings is a real gap - the stock
sysfont leaves 4.8 blank columns around the average Latin glyph where Newsreader
leaves none - but that is the two typefaces being drawn differently, and eight
source families all measuring 22-34% narrower than stock is what a genuinely
narrower design looks like, not eight coincidences.

So `--tracking` and `--space-ratio` fix nothing and distort the typeface:
`--space-ratio 0.58` on sysfont, meant to widen a word space that looked tight,
made it **42% wider than the font designs it**. Both default to 0 and should
stay there unless the goal is deliberately to depart from the source font.

If the text still reads cramped after that, the causes that were real are
elsewhere in this file: a cell taller than the template (the engine scales the
glyph by `88/cell`), and an edge that has not been softened before the 4bpp
quantise.

**A line the English build "does not have" is a slot it left empty.** The two
builds run the same script — 50 of the 54 story files hold identical
instructions and the other four differ by one to three, all on the Japanese
side. Where English needed fewer lines in a box the localiser emptied the text
block instead of deleting the instruction: 82,685 English `text` instructions
against 82,692 Japanese, but 70,787 holding text against 77,655. The 5,989 in
between are live instructions with an empty block, and every one of them sits in
a box that already draws text, so filling one adds a line to a box already on
screen. `mksheet.cell_text()` drops them as "blank line used to pad a message
box", which is why a JP-anchored translation looks like it has 7,000 lines the
English build has nowhere to put. It has nowhere to put them only because they
carry no id; `story_rows(..., filled)` emits the ones Japanese fills, and
`relinkjp.py` re-addresses the sheet onto them.

**A `EN ID` column zipped over non-blank rows drifts, and the drift is silent.**
The incoming sheet's column was built by pairing its Japanese lines with the
English lines that hold text, so every empty slot it steps over shifts the rest
of the run by one until something resynchronises it — 557 rows one slot off,
10,277 with no id at all. Nothing downstream can see this: the ids are valid,
they address real blocks, and `applyvi.py` writes them. What it looks like from
outside is 109 chapter titles carrying `...` instead of a title. Re-derive the
address from the two builds (`mksheet.py --merge --relink`) rather than trusting
the column.

**The translation is made from JP 1.0.0; the English build is JP 1.0.1.** The
incoming sheet's Japanese column matches the base cartridge (`[01005B9014BE0000]
.xci`), while `work/jp` is that plus the `v65536` update, and English was
localised from the updated script: `206.DAT` has 5215 instructions in 1.0.0 and
5260 in both 1.0.1 and English. 1.0.1 rewrote about 350 lines across 42 of the
54 story files - 332 edited, 7 added, 11 removed - and 70 of those in one scene
of `206`. Those are the rows where a sheet's Japanese disagrees with the game
(`cau Nhat lech`) and where a box in the game has lines no row covers, and the
fix is always to translate the 1.0.1 line. Compare against `work/jp`, never
against the sheet's own Japanese. `STORY.cpk` of the cartridge was checked
byte for byte against `work/jp`: same size, different content.

**Placing a 1.0.0 sheet on 1.0.1 takes four passes, in trust order, and the
order matters.** `relinkjp.relink()` runs the ordered alignment, then the
sheet's own EN ID where both neighbours vouch for it (`between()`), then
content alone for rows 1.0.1 moved (`reordered()` - 206 moved a whole `var`
command past three lines of narration), then `rescue_boxes()` for a box where
English deleted one Japanese line and moved its text up into a spacer slot
(601 `"HATRED"`, 605/4522). Running `reordered()` before `between()` stole a
row `between()` would have kept and put a line of dialogue on the wrong slot.
Verify any change here by diffing every slot of the merged workbook before and
after - the correct version changed exactly the slots it meant to, 5 of them.
An empty row must never overwrite a translated one on the same slot; a spacer
row did exactly that to 601/10723 after it had been rescued.

**Rows the translators insert have no id.** Skipping rows with an empty column A
threw every such fix away silently. They are read, keyed `+<excel row>`, and
placed by their Japanese - so an inserted row's Japanese must be the game's
line verbatim; `一` typed for `――` no longer matches.

**`#Color` and `#NAME[1]` may move between lines of the same `var` version**,
never across versions: `applyvi.colour_moved()` checks each version's totals
against English or Japanese. The version boundary comes from separator blocks,
and for the one opcode that has none, from `split_by_repeat()` - the versions
are the same English sentence, so its lines repeat with the version's length as
period. Without that cut, a colour moved from the coloured version into the
plain one passes. Tested both ways on 101/6701 and 201/7932. Sheet (6) went
from 103,187 to 103,327 of 103,329 lines written. A line whose commands match
the Japanese line is also accepted (`keeps_jp()`); 402/11750 names the heroine
in one Japanese version and deliberately not in the other.

**A malformed command passes every check.** `MARKUP_RX` matches well-formed
commands only, so `#Color[0` without its bracket is not counted, the line
balances, and it is written into the game. `exportvar.malformed()` is the only
check for it. `#Ruby[base,reading]` is furigana: 605 uses in Japanese, none in
English, but the English executable carries the same 20-token command set
(`NAME[`, `Color[`, `Ruby[`, …), so the parser knows it. `textwidth` measures
only the base. Not yet seen running on the English build.

**A slot holding `　#n` is padding, not a line.** 53 English slots hold an
ideographic space and a line break and nothing else; `cell_text()` now treats
them as blank.

**A chapter title is `<japanese key>@<display text>`.** The key is what the
flowchart looks the scene up by; losing it corrupts the scene table rather than
just the text. Every translated title in the imported sheet had lost it, and
carried a line of dialogue from elsewhere instead of a title, so `applyvi.py`
refuses a title row whose `key@` prefix does not survive rather than repairing
it.



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

**PIL's `getbbox` on text is the layout box, not the ink box.** Its right edge
is the advance, so measuring glyph widths with it silently mixes the bearings
into every number. That is what broke the first font matcher: it ranked Arial
Narrow Italic first for an upright face and put the real Times second behind a
Tibetan font. Measure ink from an actual render and threshold it.

**A font matcher needs a positive control before its output means anything.**
Feed it a face you already know — render Corbel, Constantia and Calibri at the
target cap height and ask it to find them. With the layout-box bug all three
failed; once ink was measured properly each came back first at an error of
0.029-0.032 with the next candidate three to four times away. That number is
what makes a result readable: a real match lands near 0.03 with about 1% width
deviation, and anything at 0.10 or above is not a match, however tidy its
ranking looks.

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
- `tid.py` — read `.tid` textures out of GAME.cpk as PNG
- `exefs.py` — read the executable: NSP → ExeFS → NSO segments → strings
- `gbnl.py` — read/rebuild `.gbin` and `.gstr` (offsets remapped, text may grow)
- `patchstr.py` — in-place `.gstr` edits (length-capped)
- `translate_glossary.py` — the sample translations used to check rendering

The text pipeline, in the order it runs:

- `stcm2l.py` — read/rebuild `.DAT`; `check_calls()` and `jump_targets()` are
  the checks that matter after a rebuild
- `mksheet.py` — extract every translatable string to `.xlsx`; `--merge` folds
  in an existing translation and flags what needs review, `--relink` works out
  where its rows belong instead of trusting its `EN ID` column
- `relinkjp.py` — what `--relink` runs: aligns a JP-anchored sheet against both
  builds and re-addresses it
- `chuadich.py` — the game lines still left in English, with where each goes in
  the translators' sheet and the whole box around it
- `glossary.py` — the same thing for the Glossary screen alone
- `linebreak.py` — `#n` on the way out of a sheet, a real newline on the way in
- `textwidth.py` — how wide a line actually draws, and the measured ceilings
- `reflow.py` — re-break a message box's lines to fit, without losing text
- `applyvi.py` — write the workbook back into the scripts, addressed by id
- `applyui.py` — the same for the `ui` rows, rebuilding the SYSTEM databases
- `applyexe.py` — and for the `exe` rows, rebuilding `exefs/main`
- `checksheet.py` / `applystory.py` / `portjp2us.py` — the older sheet-driven
  path, kept for sheets with no `EN ID` column

## Conventions

Code comments and docstrings in **English**. `AGENTS.md` and the READMEs are in
Vietnamese; this file is English because it documents formats.

No font subsetting yet — every `.ffu` carries the full stock charset, which is
why each one is ~100 MB uncompressed.
