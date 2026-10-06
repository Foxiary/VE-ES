"""
linebreak.py - the engine's `#n` on one side, a real newline on the other.

`#n` is what the engine breaks a line on. It survives a hex dump well and a
spreadsheet cell badly: a four-line glossary description arrives as one long run
of text with the breaks buried in it, and a translator deciding where to re-break
is counting characters they cannot see. `to_sheet()` turns each `#n` into a real
newline so the cell shows the shape of the box, and `to_game()` puts them back
on the way in.

THE SWAP IS LOSSLESS, AND THAT WAS MEASURED BEFORE IT WAS USED
    Both directions are only safe if the two spellings cannot collide, and both
    halves of that were counted over the whole shipped text rather than assumed:

    - NO STRING THE GAME SHIPS CONTAINS A RAW CONTROL CHARACTER. All 97,110 rows
      `mksheet.py` extracts from STORY.cpk and SYSTEM.cpk were scanned and the
      count is zero. So a newline in a cell can only have come from `to_sheet()`
      or from the translator, and turning it back into `#n` cannot invent a
      break that was never there. (Scanning every UTF-8-decodable block instead
      does find control bytes - those are asset ids and flag data, not text, and
      none of them reach a sheet.)

    - `#n` IS THE ONLY COMMAND SPELLED WITH A LOWERCASE N. The full set in the
      shipped text is `#NAME[1]`, `#Color[0]`, `#Color[8]`, `#PosX[%d]`,
      `#ERROR` and `#n`, so replacing those two characters cannot bite into a
      longer command. A greedy `#[A-Za-z]+` disagrees and reads `#nto` as one
      command, but that is the regex swallowing the word after the break -
      `mksheet.MARKUP_RX` has the same note.

SPACING AROUND A BREAK IS LEFT ALONE
    54 stock lines put a space before `#n` and 4 put one after. Trimming each
    line would read better in the cell and would change the text, so neither
    direction touches anything but the break itself.

    Callers strip the cell as a whole BEFORE calling `to_game()`. That ordering
    is what stops a stray trailing newline - invisible in Excel - from arriving
    as a trailing `#n`; converting first and stripping after would leave it in.
"""
import re

MARK = '#n'

# Whitespace hugging a line break. Used only for COMPARING a sheet's source
# column against the game, never for what gets written back.
_AROUND_BREAK = re.compile('[ \t　]*(?:\n|#n)[ \t　]*')
# Any other run of spacing. An editor that rewrites an ideographic space as an
# ordinary one turned `や　ゆ　よ` into `や ゆ よ` and lost two more rows.
_RUN = re.compile('[ \t　]+')


def canon(s):
    """Fold the spaces around every break, for an is-this-the-same-string test.

    A sheet that has been round-tripped through another editor comes back with
    its breaks padded - one workbook arrived with a space inserted after every
    single `\n`, which made 149 rows fail an exact-match check against text they
    plainly were. Folding both sides before comparing accepts that and still
    refuses a string that is actually different.

    Both spellings of a break fold to the same thing, because a caller may reach
    here on either side of `to_game()` and would otherwise be comparing `#n`
    against a newline and finding them different.

    This is for comparison only. The text written back into the game is what the
    translator typed, not this.
    """
    return _RUN.sub(' ', _AROUND_BREAK.sub('\n', s or ''))


def to_sheet(s):
    """Game text -> spreadsheet cell. None and '' pass through untouched."""
    if not s:
        return s
    return s.replace(MARK, '\n')


def to_game(s):
    """Spreadsheet cell -> game text.

    Excel hands back '\n', but a cell pasted in from a browser or an editor can
    carry '\r\n' or a bare '\r', so both are folded to one break first.
    """
    if not s:
        return s
    return s.replace('\r\n', '\n').replace('\r', '\n').replace('\n', MARK)
