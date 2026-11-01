# AxiTimeline Language Spec

Specification for the `.axitl` language and its layout engine — the description language and how it resolves to physical positions on paper. Companion to the separate hardware spec (plotter/transport electronics) and interpreter CLI spec (`axitime`/`libaxitl`).

Status: working draft, reflecting all decisions taken in design discussion so far.

This file (`docs/language-spec.md` in the AxiTimeline repo) is the **canonical copy** of this spec, and changes are made here alongside the code. The claude.ai artifact it began as is superseded.

History: reconciled 2026-09-19, merging the units section (§14) that originated in the interpreter/CLI spec discussion. Revised 2026-10-12 after a full review pass: text-collision rules, paper-edge handling, clipping at the timeline window, event side selection, `now` reproducibility, removal of standalone illustrations, date-grammar tightening, day-scale ticks, and concrete defaults. Moved into the repo 2026-10-12, then amended the same day: fonts (§3.8), the `baseline` default (§4), event identity for duplicates (§5), broken poles with time labels (§§3.11, 8), flags kept clear of bars (§8.2), groups drawn like spans (§9), and bar labels placed beside their bars or pulled out (§7). Added 2026-10-24: backgrounds, starting with graphs (§15), and a separate pen for fills (§3.7). Added 2026-11-01: the title and credits (§16), outline fonts converted to SVG fonts (§3.8), `illustration(…)` on an indented continuation line (§3.10), and an illustration's filled shapes hatched and its colours drawn in pens of their own (§3.5). Added the same day: notes, paragraphs of free text on the top or bottom edge (§17).

## 1. System overview

Hardware (from the earlier design phase): AxiDraw SE/A3 for pen plotting, a custom paper feed/rewind controller (ESP32/Pico), and multi-pass-per-pen plotting onto a paper roll, orchestrated by a Raspberry Pi — computationally ample, since all real-time motion is offloaded to the EBB and the feed microcontroller.

The software architecture — `libaxitl` (parse → layout → render) and the `axitime` CLI (`check`, `list-pens`, `render`, `plot`), with plotting driven only from frozen per-pen SVGs — is defined in the **interpreter CLI & architecture spec**, not here. This spec defines what that pipeline's parse and layout stages must do: the `.axitl` language (§§2–5, §14) and the layout rules it resolves through (§§6–12).

## 2. Entity types

`person`, `event`, `span`, `group`, `include`, plus the top-level `timeline` directive. Keywords are lowercase. Illustrations are attachments to entities, not entities in their own right (§3.5). A `graph` (§15) isn't an entity either: it is a background, drawn under the entities and taking no part in their layout. Nor are the `title` and `credits` (§16), which sit in two corners of the paper and are kept clear of by everything else, or a `note` (§17), free text on the top or bottom edge, kept clear of in the same way.

## 3. Compact line syntax

``` text
[side][priority]keyword "Label" daterange [pen] [fill=style] [font=name] [font_size=Xmm] [time_label=precision] [illustration(file.svg)]
```

Example:

``` text
^!!person "Isaac Newton" 1642-1727 red illustration(newton.svg)
--person  "John Doe" 1953-2022 blue
```

### 3.1 Priority symbols

- `!` repeated = priority delta upward (closer to baseline), count = magnitude (e.g. `!!` = +2)
- `-` repeated = priority delta downward (further from baseline), count = magnitude
- No symbol = priority 0 (default)
- Mixed `!`/`-` in one run is a parse error

### 3.2 Side symbols — optional override

- `^` = force above baseline, `v` = force below baseline
- Omitted = **automatic** side placement (see §6)
- Forced entities are placed first in the layout pass; their occupied space still counts against auto-placement load for everything else

### 3.3 Dates and times

One date format, usable anywhere a date is expected, with **freely mixable precision** — any entity in a document can be as coarse or as fine as the event actually warrants, from a bare year up to the second:

``` text
1963                        // year
1963-11                     // year-month
1963-11-22                  // year-month-day
1963-11-22T12:30:00         // full datetime, to the second
44BC-03-15                  // BC still works at day precision — the Ides of March, 44 BC
```

- Bare numbers default to **AD**; BCE requires an explicit `BC` or `BCE` suffix (either accepted, case-insensitive), attached directly to the year component before any month/day: `509BC`, `44BC-03-15`
- Timezone is optional on the time component, per ISO 8601 (`Z` for UTC, or an explicit offset like `+03:00`). If omitted, timestamps are literal values on one unified axis with no timezone conversion applied
- Internally, every date normalizes to one continuous representation regardless of the precision it was written at (seconds along a proleptic Gregorian calendar, with no year zero — 1 BC is immediately followed by 1 AD, matching how historical dates are normally spoken about). This is what makes mixed precision within one document work without special-casing

**Range separator:**

- `-` for a range between two **bare years** (optionally BC/BCE-suffixed) — unambiguous, unchanged from before: `1642-1727`, `509BC-27BC`
- `/` required whenever **either side** has month/day/time precision, since that finer date already contains internal hyphens: `1986-04-25T14:00:00/1986-04-25T23:10:00`, `1962-10-16/1962-10-28`
- `/` is otherwise always a range separator — there is no competing meaning for it. Dates are interpreted as **proleptic Gregorian throughout**; the language has no Julian/Gregorian dual-date construct, so an author working from a Julian-dated source is responsible for converting to Gregorian before writing the file (and can note the original dating in the entity's label if it matters, e.g. `person "Isaac Newton (d. 20 Mar 1726 O.S.)" 1642-1727`)

**Ranged entities need a range.** A `person`, `span`, or `group` must be given either a full range or an open-ended start (§3.6); a single date on its own is a parse error. Besides being meaningless for a bar, this catches a silent misparse: `span "X" 1910-12`, written intending 1910–1912, would otherwise read as the single date December 1910. An `event` takes exactly one date and never a range.

**Anchoring truncated dates:** a date's stated precision determines what moment it resolves to, and that resolution differs depending on where it's used:

- As a **range start**: beginning of its stated precision (a bare year → Jan 1, 00:00:00; a year-month → the 1st of that month)
- As a **range end**: end of its stated precision (a bare year → Dec 31, 23:59:59) — this is what makes `1939-1945` still mean "the whole of both years," exactly as it always implicitly did
- As a **single point** (an `event`'s date): beginning of its stated precision, for predictability

Uncertain/approximate dates (e.g. "circa 1600") still get **no special date syntax** — use the plain date for positioning and encode the uncertainty as plain text in the entity's own label, e.g. `event "(c. 1600) Event happened around here" 1600`.

`scale`'s unit (`mm/year`, `mm/hour`, `mm/day`, `mm/minute`, `mm/second`) remains an author convenience matched to a document's typical content, but no longer restricts what precision any individual entity is allowed to use — a `mm/year`-scaled century timeline can still contain a day- or second-precise entity where warranted (as in the worked example below).

Example — a whole timeline at second precision, covering about sixteen hours of the Chernobyl Unit 4 accident:

``` text
timeline start=1986-04-25T14:00:00 end=1986-04-26T06:00:00 length=2m width=210

event "Test delayed" 1986-04-25T14:00:00
span  "Delayed low-power test window" 1986-04-25T14:00:00/1986-04-25T23:10:00
event "Reactor power drops unexpectedly" 1986-04-26T00:28:00
event "AZ-5 emergency shutdown initiated" 1986-04-26T01:23:40
event "First explosion" 1986-04-26T01:23:44
```

### 3.4 Pen (renamed from "colour")

- Positional trailing bare keyword, matched against a closed reserved vocabulary — named "pen" rather than "colour" since it maps to the physical implement the operator swaps in, not a rendering style
- Reserved values, three families:
  - Rainbow + practical additions: `red orange yellow green blue indigo violet black grey`
  - Pencil grades: `<grade>-pencil` where grade ∈ `6B 5B 4B 3B 2B B HB F H 2H 3H 4H 5H 6H`
  - Fountain: `fountain-<colour>` where colour is any of the base set above
- Default when omitted: `black`
- The language deliberately does **not** encode line thickness/nib style (thin/medium/thick/brush) — that choice is left to the plotter operator; the plot orchestrator's per-pass prompt only ever asks "which pen/pencil/fountain colour," generalizing the existing multi-pass-per-colour plotting architecture to multi-pass-per-**pen**

### 3.5 Illustrations

- Attached to an entity with the modifier `illustration(file.svg)`. An illustration always belongs to a `person`, `span`, `group`, or `event` and has no independent existence (standalone, unattached illustrations were dropped in the 2026-10-12 review; they can return later if a use case appears)
- Optional explicit height: `illustration(file.svg height=40mm)`; default height is **2 lanes**. Width follows from the SVG's own aspect ratio, which is always preserved
- **Grid-aligned and lane-reserving**: height is rounded up to a whole number of lanes (`ceil(height_mm / lane_height)`), and that many contiguous lanes are reserved on the parent's side via the generalized band-packing search (§7), so illustrations never overlap bars or each other
  - **Banded parent** (`person`/`span`/`group`): placed in Phase A (§6), left edge aligned with the bar's start, with the search starting immediately outward from the parent's own lane, so it sits as close to its parent as space allows
  - **Event parent**, which has no lane: placed in Phase B once the event's side is known (§6.1), immediately beside the pole (with a small gap) on whichever side has more free space, with the search starting from lane 0
- Never crossed by an event pole (genuine ink collision): an illustration in a pole's path is nudged **horizontally** (§8.1), the minimum distance needed, and only to a position where its whole lane band is still free. If no such position exists, it stays put, the pole is broken where it passes the illustration (§8), and a named build warning is emitted (not fatal)
- Kept inside the finished length (§4.1): an illustration that would overhang either end of the paper is shifted inward, under the same free-lane constraint

**Fills and colours** (added 2026-11-01). A plotter draws lines in one pen at a time, so by default an illustration is drawn as the outlines of its shapes, all in its owner's pen, and its filled shapes come out hollow, with a warning. Two settings inside the parentheses change that, for any illustration, a title's or the credits' included (§16):

``` text
credits illustration(Logo-Colour.svg fill=solid pens=auto) { … }
event "Apollo 11 lands" 1969-07-20 illustration(eagle.svg pens="#ff6600:orange #1a1a1a:fountain-black")
```

- **`fill=`** hatches each filled shape with one of §3.7's patterns, cut to the shape by the SVG's own fill rule (`nonzero`, its default, or `evenodd`), so a letter's counter stays empty. `solid`, the dense hatch, makes a shape look filled; the others shade it. Patterns are anchored to the page, as a bar's are, and pieces of hatching shorter than 0.5mm are left out (none for `dots`). The shape's outline is still drawn, over the hatching's ends. Default `none`. Nothing white is ever hatched: white is the paper.
- **`pens=`** draws the illustration's colours in pens of their own, each plotted in its own pass, instead of all in its owner's pen. `pens=auto` gives each colour the base pen (`red` to `grey`, §3.4; not pencils or fountain pens) whose reference colour is nearest, in CIELAB. Each pen's references are its preview colour and the plain colours its name usually means: `red` #ff0000 and #b22222; `orange` #ff8000 and #ffa500; `yellow` #ffff00 and #ffd700; `green` #00ff00 and #008000; `blue` #0000ff and #000080; `indigo` #4b0082; `violet` #8000ff, #800080 and #ee82ee; `black` #000000; `grey` #808080 and #c0c0c0. So #ff6600 is `orange`. Otherwise `pens=` lists colours and pens, `"#ff6600:orange #000000:black"` (colours as `#rgb`, `#rrggbb` or a common CSS name, separated by spaces or commas), and any colour it leaves out stays in the owner's pen. With `pens=`, a shape's outline is in its stroke's pen, or its fill's if it has no stroke; its hatching is in its fill's pen; and nothing white is drawn.
- Paint that isn't a plain colour (a gradient or pattern) is drawn in the owner's pen, with a warning; so is a colour listed in `pens=` that the drawing doesn't use, since it's probably a typo.
- A shape painted over another doesn't hide it: both are drawn in full, since a plotter can't erase. A drawing that relies on covering one shape with another, typically white over black, needs redrawing as shapes that don't overlap.

### 3.6 Open-ended entities and `now`

- `timeline`'s `end` may be the keyword `now` instead of a literal date. Resolved **once, at build time**, to the current moment truncated to the precision of the timeline's `start` (so a year-precision timeline resolves `now` to the current year), then frozen like any other `end` value
- **Reproducibility:** because the source text still just says `now`, the resolved value must be folded into the interpreter's job hash, and the interpreter must allow pinning it — otherwise re-rendering on a later day (e.g. to reprint a damaged segment) would silently produce a different layout under the same hash, defeating `plot`'s mismatch check. This is an interpreter-side requirement; see §13
- A ranged entity (`person`, `span`, `group` — not `event`, which is a single instant and doesn't support this) can be marked **open/ongoing** with a trailing separator and no end value: `1953-` rather than `1953-2022`, or a trailing `/` when the start has finer than year precision, following §3.3's separator rule: `1953-04-01/`. This is deliberately distinct from an entity whose real end date happens to coincide with the timeline's boundary — coincidence gets a normal closed cap, explicit `-` gets the open treatment
- An open entity's effective end, for lane-packing purposes, is simply the timeline's resolved `end` — no change to the packing algorithm; only the SVG generator's rendering of its far edge differs
- The far edge of an open entity is drawn with a torn/interrupted cap instead of a flat end — style set once for the whole document via `timeline`'s `open_end_style=sawtooth` (default) or `open_end_style=sine`. A per-document default rather than a per-entity choice, since it's a "ran out of paper/data here" convention that should stay visually consistent across the whole piece
- The same cap is drawn wherever a bar is clipped by the timeline window, at either end (§4.2)

### 3.7 Fill (for banded entities — `person`, `span`, `group`)

``` text
!!span "Cold War" 1947-1991 grey fill=diagonal
```

- Named attribute (not positional, to stay unambiguous alongside `pen`): `fill=<style>`
- Reserved styles: `none` (outline only, default), `solid` (in practice implemented as dense hatching — a pen plotter has no true flat-fill primitive, so this carries a real plot-time and pen-wear cost worth being aware of), `diagonal`, `crosshatch`, `wave`, `dots`
- Applies uniformly to all three banded entity types, since they all render as the same kind of bar
- A fill pattern never draws through its bar's label (§7): hatching stops at the label's bounding box plus a small margin. A plotter can't knock a pattern out from behind ink after the fact, and text drawn over hatching is illegible
- `fill_pen=<pen>` draws the pattern in a pen of its own (added 2026-10-24), so the outline and label can be dark ink for legibility and the fill a soft coloured pencil: `span "Cold War" 1947-1991 black fill=diagonal fill_pen=2H-pencil`. Default: the bar's own pen. A group passes it to its members as it does its pen (§9), and a group may give one only to pass on; elsewhere `fill_pen=` without `fill=` is an error
- A fill pen that differs from its bar's pen is plotted straight after the axis pen, with graphs' pens (§15.10), so the fill goes down before the outlines and lettering drawn in the passes after it
- A graph shades under its line, or casts a shadow, with the same patterns, and can do so in its own `fill_pen=` (§15.7)

### 3.8 Font and size

``` text
timeline ... font="HersheySans1" font_size=5mm
!!person "James Watt" 1736-1819 font="robin_handwriting.svg" font_size=7mm
```

- `font` names either a **built-in** font or a **custom font file** (settled 2026-10-12):
  - A bare name is one of the built-in stroke fonts bundled with the library, the same set Hershey Text (the AxiDraw/Inkscape stroke-font tool) ships: `HersheySans1`, `HersheySansMed`, `HersheySerifMed`, `HersheySerifMedItalic`, `HersheySerifBold`, `HersheySerifBoldItalic`, `HersheyScript1`, `HersheyScriptMed`, `HersheyGothEnglish`, `EMSAllure`, `EMSElfin`, `EMSFelix`, `EMSNixish`, `EMSNixishItalic`, `EMSOsmotron`, `EMSReadability`, `EMSReadabilityItalic`, `EMSTech`
  - A name ending `.svg` is a custom SVG stroke font in the format Hershey Text loads (an SVG `<font>` with one `<glyph>` per character), which is what a handwriting-to-font conversion would produce. It is fetched like an include or illustration, relative to the file that names it
  - An unknown built-in name, or a custom font file that can't be fetched or read, is a **parse error**. There is no fallback to the default font, because a substitute font would change every label width the layout measured
- The library draws all text itself, as strokes taken from the font's glyphs (the plotter software does not plot SVG `<text>`), and measures labels from the same glyph data, so measured and drawn text always agree. A label's width is the sum of its glyphs' advance widths; kerning is not applied (none of the built-in fonts has any)
- `font_size` is a physical length (§14) giving the font's **em size**, the meaning Hershey Text and the SVG font format give it. In the built-in fonts capital letters are about two-thirds of the em: at the default 4mm they are about 2.6mm tall
- Vertical metrics (cap height, descender depth) are measured from the glyph shapes, not taken from the font file's declared `cap-height`/`x-height`, which in the bundled fonts are placeholders that don't match the glyphs
- Both settable as a document-wide default on `timeline`, with per-entity override — same inheritance-with-override pattern already used for a group's pen/side
- Defaults: `font="HersheySans1"`, `font_size=4mm`

**Characters a font lacks.** The built-in fonts cover Latin-1 plus a few extras (for example `č š ž`, en and em dashes, curly double quotes, `€`) but not, for example, the curly apostrophe `’`, the ellipsis `…`, or macron letters such as `ō`. A character the font lacks is replaced, trying in order:

1. typographic punctuation by its plain equivalent (`’` → `'`, `…` → `...`, a non-breaking space → a space)
2. a letter by its unaccented base letter (`ō` → `o`, `ł` → `l`, `œ` → `oe`)
3. `?`, so the gap is visible on paper rather than silently blank

Each replacement is a build warning naming the entity and the character. A replaced character never fails the build.

**Outline fonts** (added 2026-11-01). A TrueType, OpenType or Adobe Type 1 font can't be named directly, but `axitime convert-font` turns one into an SVG font in the format above (interpreter spec, "`axitime convert-font`"), which is then named like any custom font: `font="avenir-demi.svg"`. Its glyphs are the font's outlines, so the plotter draws each letter as its outline and the letters come out hollow. That suits large text, such as a title (§16); small text reads better in a single-stroke font such as the built-in ones.

### 3.9 Comments

Line comments use `//`, running from the marker to the end of the line. Valid on their own line or trailing after content, and valid in any `.axitl` file including included ones:

``` text
// ---- Wars ----
!!group "World War II" 1939-1945 red fill=diagonal {
  !event "Germany invades Poland" 1939   // trailing comment
}
```

- **Quoted strings are exempt.** A `//` inside a label, font name, or file path is literal text, not a comment — `event "Either//Or" 1970` keeps its label intact. The lexer must therefore track string state rather than naively splitting each line on the first `//`
- **No block comments.** Line comments cover the need, and omitting block comments avoids nesting/termination edge cases. Cheap to add later if a use case appears
- **The include resolver must be comment-aware.** Because include resolution is a text-flattening pass that runs *before* the grammar (§5), a commented-out `include` line would otherwise still be followed and its file pulled in. The preprocessor has to strip (or at minimum recognise) comments during flattening, not leave it to the parser — commenting out an include is an obvious thing an author will do, and it silently doing nothing would be a nasty bug

**Interaction with `/` as a range separator.** A single `/` separates the two halves of a date range (§3.3), so `//` is only ever a comment. But this creates a specific typo hazard worth handling explicitly: `span "Something" 1963//1964` parses as the date `1963` followed by a comment, silently discarding the intended end date rather than erroring on the doubled slash. The parser should emit a targeted diagnostic — something like "`//` found where a date range separator was expected; did you mean a single `/`?" — when a comment marker immediately follows a date token in range position, rather than a generic unexpected-end-of-line error.

### 3.10 Multi-line declarations

A declaration with many parameters — `timeline` especially — can be continued across several lines instead of wrapping off the edge of the window:

``` text
timeline
    start=600BC
    end=2026
    length=15m
    width=210
    baseline=low
    lane_height=8mm
    font="HersheySans1"
    font_size=4mm

!!person "Isaac Newton" 1642-1727 red
```

- A **continuation line** is an indented line (leading spaces and/or tabs — either is fine, and they may be mixed, since indentation here carries no depth meaning) whose first token is a `key=value` parameter or an `illustration(…)` (the latter added 2026-11-01, since a title or the credits, §16, often ends with one)
- The declaration **ends** at the first line that is not a continuation: a blank line, or a line beginning at column 0. A blank line before the next keyword is the recommended style — it's what makes the block visually obvious — but the indentation is what actually does the work, so a missing blank line degrades to a style inconsistency rather than a parse failure. (Requiring a blank line would make "blank" load-bearing, which is fragile given editors that strip or add trailing whitespace; a whitespace-only line counts as blank regardless)
- Comment lines (§3.9) inside a block are skipped and do **not** terminate it, so parameters can be annotated or temporarily commented out in place
- The discriminator that keeps this unambiguous against a `group`'s indented body is the `key=value` shape: a group's children always begin with a keyword or a `!`/`-`/`^`/`v` symbol, never with `key=` or `illustration(`, so an indented line starting with either can only ever be a continuation. Inside `{ }` braces, indentation stays purely cosmetic
- The same rule applies to any declaration taking `key=value` parameters, so a long `include` line can be broken up the same way

### 3.11 Time labels (events)

``` text
timeline ... time_label=sec
!event "First explosion" 1986-04-26T01:23:44
event "Germany invades Poland" 1939-09-01 time_label=day
```

- An event's flag can carry a second, smaller line under its label giving the event's date or time: `time_label=none|date|year|month|day|hour|min|sec`. It lets the reader place an event exactly, which matters most when its pole is broken (§8) or it sits far from a labelled tick; whether an event needs one is left to the author (added 2026-10-12)
- Settable on `timeline` (the document default), on a `group` (passed to the events inside it) and on an `event`, with the same inheritance-with-override pattern as `font` (§3.8). `time_label=none` switches off an inherited one. Default: `none`. Giving it on a `person` or `span` is a parse error, since they have no flag
- Formats follow the tick labels (§10.2): `year` → `1939`, `month` → `1939-09`, `day` → `1939-09-01`; `hour`, `min` and `sec` give the time of day: `01:00`, `01:23`, `01:23:44`. `date` gives the date exactly as written, at its own precision, with a space in place of the `T`: `1986-04-26 01:23:44`, `44BC-03-15`
- A time label never claims more precision than the event's date has: `sec` on an event written to the minute gives `01:23`, and `hour` on a date written to the day gives the day, `1986-04-26`. Times are shown as written, without timezone conversion
- Drawn in the event's font at three-quarters of its `font_size`, aligned with the label on the pole's side. Together the label and time label make up the flag (§8.2)

## 4. `timeline` directive (top-level only)

``` text
timeline start=600BC end=2026 length=15m width=210 baseline=low
```

- `width` — the **finished** width of the timeline across the roll, i.e. the dimension the artwork is laid out within, not the width of the paper stock. Per the interpreter spec, stock is always wider than the finished size and the operator trims down afterward, so `width` describes the intended result rather than what's loaded on the machine. Follows the shared length convention (§14): a bare number is millimetres, `cm`/`m` suffixes accepted, decimals fine — `width=210`, `width=21cm`, `width=0.21m`, `width=297.5` are all valid and equivalent where the arithmetic works out
- `width` is **required**: it's the `W` that the golden-ratio baseline split resolves against, and the limit the per-side capacity checks measure against. There's no defensible default for it
- Validating `width` against the plotter's actual travel envelope is the interpreter's job, not the language's — `.axitl` records the intent; `axitime check` is where a width the hardware can't reach should be flagged
- Exactly one of `scale` or `length` (the finished length of the timeline along the roll, following §14's length convention — `15m`, `1500cm`, and `15000` are equivalent) must be given — mutually exclusive, and one is required (no sensible default for either)
- `scale`'s unit is an explicit author choice matched to the document's typical content, independent of what precision any individual entity uses (§3.3): `mm/year`, `mm/day`, `mm/hour`, `mm/minute`, or `mm/second`
- When `length` is given, `scale` is derived once, before layout, by dividing the physical length by the total span, both expressed in the same base unit (the timeline's internal canonical unit is seconds, per §3.3, converted to whatever unit `scale` would otherwise use for display): `scale = length_in_mm / total_span`. The computed scale is surfaced in the build log for sanity-checking before plotting. `length` is often the more natural choice for short, precise timelines, since a defensible mm-per-hour figure is hard to pick blind, whereas "I have 2 metres of paper" is usually already known
- Everything downstream (lane packing, event poles, label-collision resolution, strip-splitting for the physical plot) consumes whatever `scale` ends up being, whether it was typed directly or derived from `length` — no separate density-checking logic needed, since the existing label-collision fallback chain (§8.2) already catches an overly-dense result either way
- `baseline` keyword: `high` / `middle` / `low`, describing where the baseline is physically drawn on the paper (not how much room it leaves). Default: `middle`
  - `low` → baseline near bottom edge → most content area is **above** it
  - `high` → baseline near top edge → most content area is **below** it
  - `middle` → true centre
  - Offsets computed via golden ratio split of the finished width `W` (i.e. the `width` parameter above): `long_side = W/φ`, `short_side = W/φ²`
- Only the top-level file may contain `timeline`; an `include`d file containing one is a parse error
- `lane_height` (row thickness per lane) and `baseline_offset` (gap between baseline and first lane) are optionally specifiable **per side**, falling back to shared defaults of `lane_height=8mm` and `baseline_offset=3mm`:

``` text
timeline start=600BC end=2026 scale=5mm/year width=210 baseline=low lane_height=8mm baseline_offset=3mm
timeline ... above_lane_height=15mm below_lane_height=6mm   // optional per-side override
```

Rationale: the golden-ratio baseline split already gives each side the right *total* capacity, but a single global `lane_height` forces one row-thickness choice for both sides even when content density genuinely differs (e.g. `above` reserved for tall illustrations, `below` packed with thin bars). Per-side override lets the granularity match the capacity split.

- `ticks` and `tick_label_every` control baseline graduations — see §10.3

### 4.1 Edges of the paper

**Along the length (the two ends).** The time axis runs the full finished length — `start` at one end, `end` at the other, with no inset — and **all ink stays inside it**, since anything past either end is trimmed off. Elements that would overhang an end are pulled inward: a flag near an end always points inward (§8.2), illustrations are shifted inward (§3.5), and a bar's label is drawn inward from whichever end of the bar keeps it on the paper (§7). If something still can't be brought inside, a named build warning is emitted.

**Across the width (the two sides).** Lane stacks and poles are bounded by the space each side has under the golden-ratio split. If an entity can't be placed on either side without exceeding that space — a bar or illustration with no free lane band left, or an event whose base pole (§8.1) can't fit on either side — that's a **fatal layout error** naming the entity, since the content genuinely cannot be drawn. Label crowding (§8.2) is different: it degrades to a warning, because something drawable still results.

### 4.2 Entities outside the timeline window

- An entity that **straddles** `start` or `end` is clipped at the window edge, and the clipped end is drawn with the open-end cap (§3.6) — so a person born before `start` gets a sawtooth at the left-hand edge. Lane packing uses the clipped extent
- An entity lying **wholly outside** the window, including an event dated outside it, is omitted with a build warning naming it
- Accepted consequence: at the right-hand edge, a bar that is still ongoing and one that simply continues past `end` look identical. Both mean "continues past here", which is what the reader needs to know

## 5. `include`

``` text
include "common/roman_emperors.axitl" priority=-5
include "common/world_wars.axitl" side=below
```

- Recursive; resolved as a **preprocessing pass before parsing** (text-flattening, not grammar-level recursion)
- Paths resolved relative to the including file's directory
- Cycle detection by checking each include against the chain of files currently being included; clear error naming the cycle
- `priority=` on an `include` is an **additive offset** applied to every contained entity's own priority (composes through nested includes)
- `side=` on an `include`, if present, **overrides** every contained entity's side regardless of what each line says individually (since side is now usually determined automatically per-entity, this is a deliberate wholesale-flip escape hatch, not a default-filling mechanism)
- Included files never contain `timeline`
- An included file may declare graphs (§15); an include's `priority=` and `side=` don't apply to them
- Provenance (source file + line) tracked per entity through the include tree
- Duplicate entities across includes (same `(type, name)`, e.g. two files both defining `person "Julius Caesar"`): the **last one defined wins**, with a build warning naming both provenance locations (which lost, which won). Left to the operator to fix at the source if unintended.
- An **event's identity also includes its date**, at the same precision: `event "General election" 1945` and `event "General election" 1950` are different events, and so are `1950` and `1950-02`. Two events are duplicates only when type, label and date all match
- Including the same file twice by different routes is not a cycle; the second copy's entities are duplicates under the rule above

## 6. Side (above/below) — automatic placement

Layout runs in three phases, each consuming the results of the one before:

1.  **Phase A** — banded entities (`person`, `span`, `group`) get a side and a lane (this section and §7), along with any illustrations attached to them (§3.5)
2.  **Phase B** — events get a side (§6.1) and a base pole length (§8.1); illustrations attached to events are placed; illustrations in a pole's path are nudged
3.  **Phase C** — label collisions involving event flags are resolved (§8.2)

Backgrounds (§15) are placed after all three phases, and nothing in them looks at backgrounds. The title and credits (§16), then notes (§17), are placed before Phase A, and every phase keeps clear of them.

For each banded entity without a forced `^`/`v`, side is resolved during layout (not parsing), jointly with lane assignment:

``` text
lane_above = lowest_free_lane(above_lanes, entity.time_range)
lane_below = lowest_free_lane(below_lanes, entity.time_range)

if lane_above < lane_below: side = above
elif lane_below < lane_above: side = below
else: side = whichever side has more REMAINING PHYSICAL CAPACITY
      (fraction of available width used, not raw lane count —
       accounts for high/low baseline asymmetry)
```

Processed in priority order (highest first), tie-broken by start date then original file order, for deterministic output.

**Groups before their members.** A group's children inherit its resolved side (§9), so a group is always placed before any of its own members, even when a member has higher priority than the group itself. Members are then placed in normal priority order among everything else.

### 6.1 Events

Events don't occupy lanes, so the lane-based rule above can't choose their side. Instead, once Phase A is complete, each event without a forced `^`/`v` (and not inheriting a side from its group) goes on the side where its base pole (§8.1) would be **shorter** — where fewer higher-priority bars stand in its way — considering only sides where that pole fits at all (§4.1). A tie goes to the side with more remaining physical capacity, as for banded entities. Events are processed in priority order, tie-broken by start date then original file order.

## 7. Lane packing (per side, within banded entities)

Standard greedy interval-graph colouring, ordered by priority (higher priority = closer to baseline = lower lane number):

1.  Sort entities on that side by priority descending
2.  Tie-break by start date, then original include order (determinism)
3.  Assign each to the lowest-numbered lane with no time-range overlap on that side

Applies to `person`, `span`, `group` — collectively called **banded entities**. `group` behaves exactly like `span` for this purpose (see §9). Each banded entity occupies exactly 1 lane, and a lane's physical thickness is `lane_height` (see §4).

**Bar labels** (revised 2026-10-12). A bar's label is drawn in a lane, vertically centred, in one of these places, tried in order:

1. **Inside the bar**, if it fits: starting just inside the bar's start (clear of any open-end cap, §3.6).
2. **Beside the bar**, in the same lane: just after the bar's end, or, where that would run off the far end of the paper, just before its start (§4.1). Only if that stretch of the lane is free.
3. **Pulled out**: into the nearest free spot in the next three lanes outward, joined to the middle of the bar's outer edge by a **leader** at 45°. The leader points at the start of the label, level with the middle of its capitals, towards later dates where the label fits and otherwise towards earlier. The angle is always 45°, so a leader can never be mistaken for an event's pole (vertical) or a bar's edge (horizontal); together with the pen colour, that is how the reader matches a pulled-out label to its bar.
4. Failing all three, the label runs past the end of its bar, the bar's outline broken around it, and a build warning is emitted.

A label too long for its bar never pushes the bar outward: the bar takes the lowest lane free for the bar alone. For packing, a bar occupies its own extent plus a label inside or beside it. Pulled-out labels are placed only after every bar and every bar's illustration, so they take leftover space and never displace a bar. A label whose `font_size` won't fit inside `lane_height` (with a small margin) is a build warning.

**Generalized for illustrations:** the same packing routine is used with a `height` parameter (number of lanes, not just 1) and a `start_search_at` parameter (search begins outward from a given lane rather than from 0) to place illustrations — see §3.5. This is the one case where a single entity spans multiple contiguous lanes.

## 8. Events — poles, not bands

`event` entities are **not** placed via lane packing. They are drawn as a straight line ("pole") extending away from the baseline, with the label (and any time label, §3.11) at the far end ("flag").

**Broken poles** (added 2026-10-12). A pole is never drawn through other ink. Wherever it would cross a bar (anywhere inside its outline, whatever its fill), a bar's label, an illustration, a tick label or another event's flag, it is interrupted with a small gap either side and resumes beyond. The stretch beside its own flag is never broken, so the flag stays attached to its pole. A broken pole is normal and not a warning; an author who wants the reader to be sure of an event's date gives it a time label (§3.11). The leader of a pulled-out bar label (§7) is broken by the same rule, except around its own bar and label. Lines may cross lines: a pole and a leader, or two leaders, cross without either being broken.

### 8.1 Pole length (base)

``` text
pole_length = max(outer_edge(B) for B in banded entities on same side,
                   overlapping this event's x, with priority > this event's priority)
              + label_clearance_margin
              (or base_minimum_length if none)
```

- Only *higher-priority* banded entities set this base length. A flag is then lifted clear of every bar beneath it, whatever its priority (§8.2), so the base length is a floor, not the final length
- A pole passes bars of any priority, but is broken where it crosses them rather than drawn through them (§8)
- Poles must **not** cross illustrations (genuine ink collision) — the illustration is nudged sideways instead, minimum distance needed, preferring the direction with more free space, and only to a position where its whole lane band is still free (§3.5)
- If no such position exists, the illustration stays put, the pole is broken where it passes it, and a named build warning is emitted (not fatal)
- A base pole that can't fit on the event's side drives §6.1 to choose the other side; if it fits on neither, that's a fatal layout error (§4.1)

### 8.2 Label-collision resolution (runs after all base pole lengths are known)

By default a flag points toward later dates; near the far end of the paper it points inward instead (§4.1).

Group conflicting event labels (bounding-box overlap) into clusters via x-sweep. Bars (their whole outline, whatever their priority or fill: settled 2026-10-12), bar labels wherever they are placed and the leaders of pulled-out labels (§7), and illustrations are **fixed obstacles** in this check: an event flag overlapping any of them counts as a conflict to resolve, but only the event moves — the obstacle never does. Within each cluster:

1.  **Stagger by priority** — highest-priority event gets the tallest pole in the cluster; each subsequent (descending priority) steps down by at least one flag-height (its label plus any time label). A pole's length is never reduced below its §8.1 base/clearance floor — if a lower-priority event's clearance floor exceeds its staircase step, the floor wins. Poles are also lengthened where needed to lift a flag clear of a fixed obstacle.
2.  **If staggering doesn't fully resolve it** — flip flag orientation (left/right of the pole tip) for cluster members, starting with the **lowest**-priority event first, rechecking after each flip, stopping as soon as the cluster is resolved. A flip that would point a flag off either end of the paper is never made (§4.1).
3.  **If still unresolved** (paper edge or extreme density) — proceed with best achieved separation, emit a named build warning identifying the conflicting events. Not fatal.

Note: "side" for a flag's left/right orientation at the pole tip is a distinct concept from baseline `side` (above/below) — flipping a flag never changes which side of the baseline the event is on.

## 9. Groups

``` text
!group "Industrial Revolution" 1760-1840 orange {
  !!person "James Watt" 1736-1819 illustration(watt.svg)
  !!event "Newcomen engine" 1712 illustration(newcomen.svg)
}
```

- A `group` line is layout-equivalent to a `span` — same priority/side/date-range machinery, participates in the same shared per-side lane pool as any banded entity, and is drawn exactly like a span: a closed, labelled bar (settled 2026-10-12; an earlier reading drew it as a bracket open towards its members, which read as a missing line)
- **Children are placed independently** in the same shared pool (own priority, own lane assignment) — **not** positionally nested inside the group's bracket (deliberate simplification, chosen over reserved-sub-block nesting for lower layout complexity)
- **Side and pen are inherited from the group by default** (which is why a group is always placed before its members, §6). A child with no explicit `^`/`v` uses the group's resolved side; a child with no explicit trailing pen uses the group's pen, and one with no `fill_pen=` the group's (§3.7). Either can be overridden per-line with the child's own `^`/`v` or pen keyword — so a child *can* deliberately end up on the opposite side or in a different pen from its group, but only if it says so explicitly
- Each child gets a `member_of` provenance tag (metadata only — not used by layout, available for future querying/styling)
- Grammar is recursive (`group` can contain `group`), inherited for free from the entity-list structure, though nested groups haven't been exercised in an example yet

## 10. Baseline tick marks

Regular graduations along the baseline, like a ruler or measuring tape. These serve two distinct purposes at once, which constrains the design:

- **For the reader:** a time axis, so positions along the timeline can be read off.
- **For the operator:** the physical measuring reference the interpreter's `plot --start-offset <length>` workflow depends on — an operator resuming after a pen change, jam, or power loss measures against an existing tick with a T-square.

### 10.1 Interval selection

Ticks are placed at round **time** intervals whose physical spacing lands near a target, not at an exact fixed physical spacing. (A literal every-3.5mm rule would place ticks at arbitrary moments — 2.03 years, 2.17 years — so no tick would ever coincide with a round year and labelling would be impossible.)

``` text
ideal_interval = target_spacing_mm / scale
tick_interval  = nearest value on the ladder:

  seconds:  1, 2, 5, 10, 15, 30
  minutes:  1, 2, 5, 10, 15, 30
  hours:    1, 2, 3, 6, 12
  days:     1, 2, 5, 10, 15   (day-of-month — see below)
  months:   1, 3, 6
  years:    1, 2, 5, 10, 20, 25, 50, 100, 200, 500, 1000, …
```

Every rung is a quantity a reader recognises, and every rung divides exactly into *some* larger rung (2 years into 10, 20 years into 100, 15 minutes into 30) — not necessarily the very next one, which is what the labelling rule in §10.2 accounts for.

**Day rungs are day-of-month.** Ticks fall on day 1 of each month and every N days after it, restarting at the next month — e.g. the 1st, 11th, and 21st for N=10. Restarting each month is what lets day ticks line up with month labels at all; a plain weekly rhythm never would, which is why the old 7-day rung was dropped.

**Accepted consequence:** at month and year intervals, physical spacing between ticks varies slightly, since months and years are unequal lengths (28–31 days, leap years), and at day-of-month rungs the last gap in each month is shorter or longer than the rest. This is correct — ticks mark true time positions — but it means the tick strip is not a perfectly regular ruler, which matters for §10.4.

### 10.2 Label interval and format

- Labels go on the **smallest larger rung that is an exact multiple of the tick interval**, i.e. every n-th tick: 2-year ticks → every 5th (decades — the 5-year rung is skipped because 2 doesn't divide into 5); 20-year ticks → every 5th (centuries); 15-minute ticks → every 2nd (half-hours). Produces the intended `1600 , , , , 1610` reading
- n must also clear the label *text* width. After deriving n from the ladder, check whether labels would physically overlap at the resulting spacing; if so, walk further up the ladder (decades → 50s → centuries) until they clear, and emit a build warning noting the label interval was coarsened
- Labelled ticks are drawn **longer** than unlabelled ones — standard major/minor ruler graduation
- Label format follows the precision of the **label** rung, not the tick interval, using the same truncation principle as §3.3: labels on year rungs show `1610`; on month rungs `1986-04`; on day rungs `1986-04-26`; on minute rungs `01:23`. Monthly ticks whose labels have been coarsened to years therefore read `1987`, not `1987-01`

### 10.3 Parameters (on `timeline`)

``` text
timeline ... ticks=3.5mm           // target spacing — default ~3.5mm
timeline ... ticks=off             // omit ticks entirely
timeline ... tick_label_every=10   // override the derived n
```

### 10.4 Interaction with the plotting workflow

- Ticks **must be drawn in the first pen pass**, since they are the alignment reference every subsequent pass and every resumption depends on. This is consistent with the interpreter spec's existing note that ticks are drawn with the first pen (typically black or a hard pencil). Background and fill pens (§§3.7, 15.10) come next, before the rest of the foreground
- Because tick spacing is not perfectly uniform (§10.1), an operator measuring an offset should count ticks to a *labelled* tick and measure from there, rather than assuming a constant mm-per-tick across a long run
- The interpreter's renderer also draws pencil crop marks every 50cm, giving a second, purely physical reference that's independent of tick spacing

## 11. Draw order (for the physical plot)

1.  Baseline + tick marks (auto-generated, first pen pass — see §10.4)
2.  Backgrounds: graphs, with their shading, titles and value scales (§15)
3.  Span / group fills
4.  Event poles + flags (on top of fills)
5.  Illustrations (fine detail, and by this point nothing should be crossing into their footprint)
6.  The title and credits, with their illustrations (§16), and notes (§17)

Crop marks (every 50cm, in pencil) are added by the interpreter's renderer and aren't under the author's control — see the interpreter spec.

## 12. Provenance & determinism (cross-cutting)

- Every entity tagged with originating file + line through the include tree, plus `member_of` group tag where applicable
- All layout algorithms (side placement, lane packing, label staggering, flag flipping) use deterministic tie-breaks so re-running on unchanged input reproduces identical output
- Layout is computed once per run; since the project's plotting is one-shot (timeline isn't altered once drawing starts), there is no requirement to pin/cache lane assignments across separate runs

## 13. Open questions log

No open questions in this spec. The remaining cross-cutting items live in the interpreter/CLI spec: physical motion feasibility checking, where `axitime` gets the plotter's travel envelope for the `width` check (§4), and how a web front-end hosts `libaxitl`.

## 14. Units (added 2026-09-19, from the interpreter/CLI spec discussion)

Every numeric physical-length value anywhere in this language — `width=`, `length=`, `lane_height=`, `baseline_offset=`, `above_lane_height=`/`below_lane_height=`, `font_size=`, `ticks=` (target spacing), and an illustration's `height=` — follows one rule: a bare, unitless number is **millimetres**; `cm` and `m` suffixes are also accepted (`137cm`, `4.126m`), with no space between the number and the suffix. Decimal values are accepted throughout (`297.5`, `21.0cm`, `0.21m`). This matches the same convention `axitime`'s CLI flags use for the same reason — one shared parsing rule instead of the CLI defaulting to centimetres while the language defaulted to millimetres.

This doesn't touch `scale`, which is always an explicit rate (`mm/year`, `mm/day`, etc.) rather than a bare length, and isn't affected by this rule. It also doesn't touch dates, priorities, or any other numeric field — only physical-length parameters.

The same rule covers a graph's `height=`, `fill_depth=`, `shadow=`, and `value_scale=` when it is a length (§15), the title's and credits' `font_size=`, `subtitle_font_size=`, `heading_font_size=`, `max_height=`, `margin=`, `gap=` and illustration `height=` (§16), and a note's `width=`, `font_size=`, `heading_font_size=`, `margin=` and `clearance=` (§17).

## 15. Backgrounds and graphs (added 2026-10-24)

Agreed in discussion on 2026-10-24, tried in a throwaway mock-up, and implemented the same day (`libaxitl/graphs.py` and `graphdata.py`; the examples `crash-1929.axitl` and `reactor-power.axitl`). Open points are in `docs/known-gaps.md`.

A **background** is drawn underneath the timeline, usually in pencil, and everything else (the baseline and ticks, bars, events, their labels and illustrations: together the **foreground**) is drawn over it freely. Backgrounds take no part in laying out the foreground, which is laid out exactly as if they weren't there, so adding, removing or changing a background never moves any foreground ink. The one concession runs the other way: a background is broken where it would run through foreground text or an illustration (§15.8).

The first kind of background is the **graph**: a line plotting a series of values against the timeline's own time axis, with the baseline as its neutral value. Shaded time ranges (recessions, wars, night-time) are a likely second kind and would follow the same rules.

### 15.1 Declaration

``` text
graph "Dow Jones Industrial Average" HB-pencil
    data="dow-1928-1932.csv"
    time_column=Date
    value_column=Close
    origin=first
    y_scale=log
    fill=diagonal
    fill_depth=4mm
```

- `graph` is a declaration of its own, not an entity. It may be written in the main file or in any included file, and a document may have any number of graphs. Inside a group's `{ }` body it is a parse error.
- The quoted string is the graph's **title** (§15.9); `""` means no title.
- A trailing pen keyword (§3.4) sets its pen, as for an entity. The default is `HB-pencil` rather than `black`, since a graph is a background.
- Everything else is `key=value`, so a long declaration continues over indented lines (§3.10). Priority and side symbols (`!`, `-`, `^`, `v`) are a parse error on a graph, and an include's `priority=` and `side=` (§5) don't apply to the graphs it pulls in.
- The points come from either a CSV file (`data=`, §15.2) or a `{ }` body (§15.3). Giving both, or neither, is a parse error.
- Duplicates (§5): a graph's identity is its title. Two graphs with the same title from different files: the last wins, with a warning. Untitled graphs are never duplicates.

| Parameter | Values | Default | |
|---|---|---|---|
| `data=` | a file name | none | §15.2 |
| `first_row=`, `last_row=` | row numbers | `1`, the end of the file | §15.2 |
| `header=` | `yes`, `no` | `yes` | §15.2 |
| `separator=` | `comma`, `semicolon`, `tab` | `comma` | §15.2 |
| `time_column=`, `value_column=` | a column number or header name | `1`, `2` | §15.2 |
| `time_format=` | a pattern, or `decimal_year` | the language's own dates | §15.2 |
| `missing=` | the text that marks a gap | blank cells only | §§15.2, 15.3 |
| `origin=` | a number, or `first` | `0` | §15.5 |
| `y_scale=` | `linear`, `log` | `linear` | §15.5 |
| `height=` | a length | fitted to the paper | §15.5 |
| `range=` | a number | none | §15.5 |
| `line=` | `straight`, `smooth`, `step` | `straight` | §15.6 |
| `fill=` | a §3.7 pattern | `none` | §15.7 |
| `fill_pen=` | a pen | the graph's pen | §15.7 |
| `fill_depth=` | a length | all the way to the baseline | §15.7 |
| `shadow=` | a length | none | §15.7 |
| `value_scale=` | `off`, `start`, or a length | `1m` | §15.9 |
| `value_marks=` | `auto`, or numbers separated by commas | `auto` | §15.9 |
| `unit=` | any text | none | §15.9 |
| `font=`, `font_size=` | as §3.8 | the timeline's | §15.9 |

### 15.2 Data from a CSV file

A CSV file is read as it comes, so a source that would be awkward to reformat can be used directly:

``` text
graph "Global temperature anomaly, °C" H-pencil
    data="global-temps.csv"
    first_row=5          // the header row: this source puts four lines of notes above it
    time_column=Year
    value_column=Anomaly
    missing=-999
```

- `data=` names the file, relative to the file that declares the graph, and it is fetched through the host's `resolve` like an illustration or custom font (interpreter spec, "Library boundary"). It is UTF-8, with any byte-order mark ignored and any line endings.
- Fields are separated by commas, or as `separator=semicolon` or `separator=tab` says, and may be quoted with `"`, a doubled `""` inside quotes standing for one (RFC 4180).
- **Rows** are numbered the way a text editor numbers lines, from 1; a row whose quoted field runs over several lines takes the number of its first. `first_row=` is the first row read and `last_row=` the last, so notes above the data and a footer below it can be skipped. Wholly blank rows are skipped.
- With `header=yes`, the first row read names the columns and the data starts on the row after it. With `header=no`, every row read is data.
- `time_column=` and `value_column=` say where the times and values are. A whole number is a position, counting from 1; anything else is a header name, matched exactly against the header cell with surrounding spaces trimmed. A name with spaces is quoted: `value_column="Adj Close"`. A name with `header=no`, or one the header doesn't have, is an error that lists the header's names. Other columns are ignored.
- **Times** are written in the language's date syntax (§3.3), with one allowance for CSV: a space may stand in for the `T` before a time (`1986-04-26 01:23:44`, as many sources write it).
- **`time_format=`** reads times written some other way. It is a pattern in which `YYYY` is the year, `MM` the month's number, `MMM` an English month abbreviation (`Oct`), `MMMM` a full English month name, `DD` the day, and `hh`, `mm` and `ss` the hour, minute and second. Every other character must appear as written. Numbers may have one digit or two, the year up to four; month names ignore case. BC years and two-digit years can't be read this way. So `time_format="MM/DD/YYYY"` reads `10/29/1929`, and `time_format="DD MMM YYYY"` reads `29 Oct 1929`. A time read with a pattern has the precision of the finest part the pattern names. `time_format=decimal_year` reads a fractional year, such as `1958.2027` in climate records, as that fraction of the way through the year, to the second.
- **Values** are numbers, with an optional sign, decimal point and exponent (`-0.5`, `1.2e4`). Thousands separators and decimal commas are errors. A blank value cell, or one that matches `missing=` (spaces trimmed), is a gap (§15.6). A row with a value but no time is an error.
- Errors and warnings about the data name the file and row (`dow-1928-1932.csv:57`), so `check` and the editor point at the line to fix.

### 15.3 Points written inline

For a handful of points, a `{ }` body saves a separate file:

``` text
graph "Reactor thermal power, MW" origin=3200 y_scale=log {
    1986-04-25T14:00:00   1600
    1986-04-26T00:29:00     30
    1986-04-26T01:23:44  30000
}
```

- Each line of the body is a date (§3.3) and a value, separated by spaces or tabs. A value that matches `missing=` is a gap.
- As with a group (§9), the `{` ends the declaration's last line.

### 15.4 Points in time

- A point sits at the start of its date's period, by §3.3's rule for a single date: a value dated `1929-10` sits at 1 October.
- Points must be in time order, each strictly later than the one before. Anything else is an error naming the row, which catches an export sorted the wrong way and a day/month mix-up.
- The line is clipped at the timeline's start and end, like a bar (§4.2): a stretch from a point before `start` to one after it is drawn from `start` on. A graph whose line lies wholly outside the timeline is omitted with a warning, and so is one with `origin=first` (§15.5) and no point inside the timeline.

### 15.5 Vertical scale

- **`origin=`** is the value drawn on the baseline: `0` by default, or `first` for the first value at or after the timeline's start, which gives "change since the start" for a stock index. Values above the origin are drawn above the baseline and values below it below, at the same rate on both sides.
- **`y_scale=linear`**: the distance from the baseline is proportional to `value − origin`.
- **`y_scale=log`**: the distance is proportional to `log(value ÷ origin)`, so equal ratios are equal distances: with `origin=300`, 600 and 150 are the same distance above and below the baseline. It needs the origin and every value to be above zero; a value of zero or less is an error naming its row, and the default origin of `0` always has to be replaced.
- **The rate:**
  - With neither `height=` nor `range=`, the graph is **fitted to the paper**: drawn as large as it can be while every part of its line inside the timeline stays at least 3mm inside the finished width. The golden-ratio split (§4) gives the two sides different room, so usually one side decides.
  - With `height=` alone, the part of the line furthest from the baseline, on either side, is that far from it.
  - `height=` and `range=` together pin the rate, so that graphs drawn on different timelines from the same data match: a swing of `range` from the origin is `height` from the baseline. For `linear` the swing is a difference; for `log` it is a ratio, so `range=10` puts one power of ten at `height`. `range=` without `height=` is an error.
- A line pushed past the edge of the paper by `height=` is cut 1mm inside the finished edge, with a warning, since all ink stays inside the finished size (§4.1).
- `check` reports each graph's resulting rate, such as `141mm per decade` or `5mm per unit`.

### 15.6 The line

- **`line=straight`** (the default) joins the points with straight lines.
- **`line=smooth`** draws a curve through every point that never overshoots them: between two points it stays between their two values, so every peak and trough of the curve is a real point (monotone cubic interpolation, Steffen's method). The curve is fitted to the points as drawn, after `y_scale`. Smoothing implies a continuity the data may not have, so it suits a measured physical quantity better than prices; choosing it is the author's call.
- **`line=step`** holds each value until the next point, where the line rises or falls straight to the new value. It suits interest rates and anything else set by decision. The line ends at the last point; to carry the last value further, repeat it at a later date (a point past the timeline's end is clipped as usual).
- **Gaps** break the line. With `straight` and `smooth` it resumes at the next point; with `step`, the value before a gap holds until the gap's own time. A point with a gap, or the end of the data, on both sides is drawn as a dot.
- The drawn line may be simplified, but never by more than 0.1mm from the exact line, so spikes survive and dense data (a century of daily closes) costs no more plotting than what can be seen.

### 15.7 Shading

- `fill=` takes the patterns of §3.7 (default `none`), anchored to the page like a bar's fill. Pieces of shading shorter than 0.5mm are left out, as stubs are from bar fills.
- `fill_pen=` draws the shading or shadow in a pen of its own, so the line and labels can be dark and the shading a softer pencil (added 2026-10-24). Default: the graph's pen. Without `fill=` it is an error.
- **Under the line** (the default): the area between the line and the baseline is shaded. `fill_depth=` limits it to the part within that distance of the line, measured from the line in any direction, so the band keeps its thickness where the line is steep; without `fill_depth=` it reaches the baseline. It never crosses the baseline: where the line is below the baseline, the shading lies above the line. A near-vertical spike encloses almost no area, so it gets almost no shading.
- **Drop shadow**: `shadow=<length>` shades a shadow of the line instead. The shadow is the area the line would pass over if slid from `shadow` to `shadow + fill_depth` down the page and towards later dates at once, at 45°, less 0.75mm clear around the line itself. Under a flat stretch it is a band `fill_depth` thick, `shadow` below the line; beside a vertical stretch it is the same, on the later side; where the line runs down and to the right at 45° there is none, as with a real shadow. A shadow is cast on the paper, so it isn't stopped by the baseline and falls the same way on both sides of it. Unlike shading under the line, a shadow shows a spike plainly, which matters where events crowd the spike's moment. `shadow=` needs `fill_depth=`, its thickness.
- `fill_depth=` or `shadow=` without a `fill=` pattern is an error.

### 15.8 Breaking around the foreground

- A graph's line, shading and value scale are broken, leaving 0.75mm either side as for a broken pole (§8), wherever they would run through a bar's label, an event's flag (its label and any time label), a tick label, an illustration, or any graph's own title or value labels.
- They are never broken for lines. They cross bars, poles, leaders, ticks, the baseline and each other freely: the pencil lies underneath, and the reader tells the two apart by weight.
- A steep stretch is broken like any other. Leaving stretches steeper than 45° whole, so that a spike would survive a stack of flags, was tried in the mock-up: it struck through letters without saving the spike (which lay under the pole of the event that caused it). A gap the height of a line of text is easily bridged by the eye, and `shadow=` keeps a crowded spike visible.

### 15.9 Title and value scale

- A graph's own text is drawn in its pen and font (`font=` and `font_size=`, inherited from `timeline` as for entities, §3.8): the title at `font_size`, and value labels at three-quarters of it, like tick labels. It is placed only where it is clear of all foreground ink (bars, their labels and leaders, poles, flags, illustrations, the baseline, and the ticks with their labels), and of other graphs' text. It never moves anything; where there is no room, it moves along or is left out.
- **The title** is drawn once, beside the line near its start, on the side away from the baseline (or else the side towards it), 1.5mm from the line. Where there's no room, it moves later along the line, 1mm at a time, to the first place that has room. If there is none anywhere, it is left out with a warning.
- **A value scale** is a vertical rule from the baseline to the outermost mark, with a short tick and a label at each mark. The origin's label sits just above the baseline, or if there's no room there, just below the tick labels. By default the marks are 3 to 5 round values within the values the graph draws, from the sequence 1, 2, 5, 10, 20, 50… (for `log`: powers of ten, or else 1 and 3, or 1, 2 and 5, in each power of ten). `value_marks=` lists them instead, e.g. `value_marks=-0.5,0,0.5,1`. A mark too close to the baseline to label clear of it, or whose label would overlap another mark's, is left out.
- **`unit=`** names the values' unit, as any text (added 2026-10-24): `unit=MW`, `unit=%`, `unit=$`, `unit="°C"`. Every value scale prints it, at value-label size in the labels' column, just beyond the end of its rule further from the baseline, or the other end if there's no room there; it counts as one of the scale's labels when finding room for the scale. It stands on its own rather than being attached to each number, so a prefix such as `$` and a suffix such as `%` both read naturally.
- **`value_scale=`** sets where scales go: `off` for none, `start` for one near the start of the paper, or a length to repeat them at that interval along the roll, starting at the start (default `1m`), since a reader several metres in won't see one at the start. Each scale goes at the first place from its preferred position where all its labels have room, looking as far as the next scale's position (for `start`, 30cm). Failing that, it goes where the most labels have room, and the rest are left out with a warning. Two graphs' scales never stand in line with each other, so they can't be read as one.

### 15.10 Layout, drawing and plotting

- Graphs are placed in a fourth layout phase, after §6's phases A to C, in document order; nothing in phases A to C looks at them. Their searches step along the roll in fixed increments from fixed starting points, so placement is deterministic like the rest of layout (§12).
- They are drawn after the baseline and ticks and before everything else (§11). Their pens, and their fill pens, come straight after the axis pen in pass order, before any other pen except bars' fill pens, which join them (§3.7). So ink always goes over graphite rather than graphite over ink, and the ticks remain the first pass's measuring reference (§10.4). A graph in `2H-pencil` shares its pass with the crop marks; one in a pen the foreground also uses is drawn first in that pen's pass.

## 16. Title and credits (added 2026-11-01)

Two declarations put fixed pieces in two corners of the paper: a **title** in the top-left corner and the **credits** in the bottom-right. Neither is an entity: they have no date, they're placed before anything else, and everything else keeps clear of them (§16.3).

### 16.1 The title

``` text
title "A Colossal Waste of Time" blue
    subtitle="Five centuries of things people did instead"
    font="avenir-demi.svg" font_size=14mm
    subtitle_font=HersheySerifMed
    illustration(crest.svg at=left)
```

- The quoted string is the title's text, which can't be empty. A trailing pen keyword (§3.4) sets the pen for all of it, subtitle and illustration included. Default: `black`.
- `subtitle=` adds a second, smaller line under the title.
- `illustration(file.svg)` puts a drawing beside the text: `at=left` (the default, in the corner) or `at=right`, `gap=` from the text. By default it is as tall as the text, from the top of the title's capitals to the baseline of the last line (the subtitle's, if there is one). `height=` sets its height instead, and the text is centred against it. Its width follows its aspect ratio. Unlike an entity's illustration (§3.5), it isn't rounded to whole lanes.

| Parameter | Default | |
|---|---|---|
| `font=` | the timeline's | §3.8; an outline font converted with `axitime convert-font` suits a title |
| `font_size=` | `12mm` | the em, as for any text |
| `subtitle=` | none | quoted text |
| `subtitle_font=` | the title's `font` | needs `subtitle=` |
| `subtitle_font_size=` | half the title's `font_size` | needs `subtitle=` |
| `align=` | `left` | which way the lines are aligned: `left` or `right` |
| `margin=` | `5mm` | §16.3 |
| `gap=` | `4mm` | between the illustration and the text |

### 16.2 The credits

``` text
credits max_height=25mm illustration(Logo-Colour.svg fill=solid pens=auto) {    // the logo to the right
    heading "Design, Contraption, and Research"
    "Christopher Wenham, 2026"
    "Creative Commons Attribution-ShareAlike 4.0 License"
    "https://github.com/cwenham/AxiTimeline"
    heading "Sources"
    "Dates checked against Wikipedia"
}
```

- The credits have no label. Their `{ }` body, which they must have, holds their lines from top to bottom, each a quoted string, or `heading` and a quoted string. As with a group (§9), the `{` ends the declaration's last line. A `//` inside the quotes is text, not a comment (§3.9), so web addresses are safe.
- The lines are aligned to the right by default, so they end against the logo, or against the corner when there's no logo; `align=left` aligns them to the left. A heading is drawn in `heading_font` at `heading_font_size`, with extra space above it unless it is the first line.
- `illustration(file.svg)` puts a drawing, typically a logo, beside the lines: `at=right` (the default, in the corner) or `at=left`, `gap=` from them. It is always exactly as tall as the lines, from the top of the first line's capitals to the last line's baseline, so `height=` is an error. Descenders on the last line hang below it, as text beside a picture normally does.
- **`max_height=`** limits that same height, the lines' and so the illustration's. Where the lines would be taller, every line's size and the spacing between them are scaled down by one factor until they fit. They are never scaled up. `check` reports the text size that results, since it may be too small to read.
- A pen keyword sets the pen for all of it, as for the title.

| Parameter | Default | |
|---|---|---|
| `font=`, `font_size=` | the timeline's | the ordinary lines |
| `heading_font=` | the credits' `font` | |
| `heading_font_size=` | 1.25 × the credits' `font_size` | |
| `max_height=` | none | a length |
| `align=` | `right` | which way the lines are aligned: `left` or `right` |
| `margin=` | `5mm` | §16.3 |
| `gap=` | `4mm` | between the illustration and the lines |

### 16.3 Placement

- **Corners.** The title's ink starts `margin` from the start of the paper and from the finished top edge; the credits' ink ends `margin` from the end of the paper and the finished bottom edge. Margins and the `gap` beside an illustration are measured to the ink, not to the fonts' line boxes, so they come out as written. The default `5mm` clears the crop mark in each corner, whose arms reach 2.5mm onto the paper (interpreter spec, "Crop marks").
- **Lines.** By default, each block's illustration goes on its corner's side and its lines are aligned that way: the title's to the left, the credits' to the right. `at=` and `align=` override either. Lines are aligned on their ink, so a large title and its smaller subtitle line up although their fonts' side bearings differ. From one line's descenders (the depth its font allows, not the letters it happens to have) to the next line's capitals is 0.4 of the next line's size, and a heading gets 0.6 of its own size more. These spacings are provisional (`docs/known-gaps.md`).
- **Sides.** The title is above the baseline and the credits below it. Each must keep 1.5mm clear of the inner edge of its side's first lane (below the baseline, that is beyond the ticks and their labels). One that doesn't fit, or that is longer than the paper inside its margins, is a fatal error, like a bar with no room (§4.1).
- **Keeping clear.** The title and credits are placed before Phase A (§6). Every lane that one of them crosses, counting its lines' whole boxes and its illustration, plus 1.5mm across the roll, is reserved along its length, so no bar, bar label or illustration is placed there (§§3.5, 7). Where that leaves a bar no lane, the usual no-room error follows. The reservation doesn't count towards how much of a side is in use when §6 breaks a tie. Event flags treat the title and credits, plus 1.5mm, as fixed obstacles (§8.2); poles and leaders are broken around them (§8); and graphs are broken around their text and illustrations, which graphs' own text also keeps clear of (§15.8).
- **One of each.** A document has at most one title and one credits. Either may come from the main file or an included one, so credits shared by several timelines can live in a common file. A second is an error naming the first. Neither can be inside a group. An include's `priority=` and `side=` (§5) don't apply to them.

### 16.4 Drawing

- The text is drawn as strokes in the pen given, by the same text shaping as everything else (§3.8), so missing characters are replaced with a warning.
- The illustration is drawn as every illustration is (§3.5): by default the outlines of its shapes, all in the block's pen; with `fill=` its filled shapes hatched; and with `pens=` its colours in pens of their own, so a logo in two colours is plotted in two passes.
- They are drawn last, after illustrations (§11).

## 17. Notes (added 2026-11-01)

A **note** is free text, typically a paragraph or two, fixed to the top or bottom edge of the paper: narration that goes with the timeline, such as a summary of a period, or notes about the timeline itself. Like the title and credits (§16) it isn't an entity: it has no lane, it's placed before anything else, and everything else keeps clear of it.

### 17.1 Declaration

``` text
note anchor=start {
    heading "About this timeline"
    "People are drawn above the line and wars below it. Each bar runs from birth to death,"
    "or from the start of a war to its end; a torn end means the story carries on."

    "Dates are Gregorian throughout."
}

note "The century ends with the web, a few years old." anchor=end edge=bottom align=right
```

- A note's text is either one quoted string after `note` (a single paragraph) or a `{ }` body, not both. As with a group (§9), the `{` ends the declaration's last line.
- In the body, each line is a quoted string, or `heading` and a quoted string, as in the credits (§16.2). Quoted lines that follow one another make **one paragraph**, joined with a space, so a long paragraph can be written over several short lines; a blank line ends it, and the next quoted line starts another. A comment line (§3.9) doesn't end a paragraph. A heading is a paragraph of its own. Spaces inside the text are collapsed when it is wrapped.
- A `//` inside the quotes is text, not a comment (§3.9).
- A trailing pen keyword (§3.4) sets its pen. Default: `black`.
- A document may have any number of notes, from the main file or included ones. A note can't be inside a group. An include's `priority=` and `side=` (§5) don't apply to notes, and a note can't have an illustration.

| Parameter | Default | |
|---|---|---|
| `anchor=` | `start` | `start`, `middle`, `end`, or a date (§3.3): §17.2 |
| `edge=` | `top` | `top` or `bottom`: which finished edge it sits against |
| `width=` | 30 × `font_size`, or the paper's length inside the margins if that is shorter | the longest a line may be (a length, along the roll) |
| `align=` | `left` | which way the lines are aligned: `left` or `right` |
| `font=`, `font_size=` | the timeline's | §3.8 |
| `heading_font=` | the note's `font` | |
| `heading_font_size=` | 1.25 × the note's `font_size` | |
| `margin=` | `5mm` | from its edge, and from either end of the paper |
| `clearance=` | `25mm` | along the roll, from the title, the credits and other notes: §17.3 |

### 17.2 Placement

- **Across the roll.** A note on the `top` edge has its ink start `margin` below the finished top edge; one on the `bottom` edge has its ink end `margin` above the finished bottom edge. The default `5mm` clears the crop marks (interpreter spec, "Crop marks"). A top note is above the baseline and a bottom note below it, and each must keep 1.5mm clear of the inner edge of its side's first lane, as the title and credits do (§16.3); one that doesn't fit is a fatal error.
- **Wrapping.** Each paragraph is broken into lines no longer than `width=`, measured by the fonts' advance widths, filling each line in turn. Lines aren't hyphenated, and there is deliberately no justified or centred alignment (settled 2026-11-01): ragged lines read better on the roll. A word too long for a line on its own gets a line anyway and runs past the width, with a warning. A `width=` longer than the paper inside its margins is a fatal error. At the default 30 ems a line holds about 60 characters of the built-in fonts.
- **Lines** are spaced as in the title and credits (§16.3): from one line's descenders to the next line's capitals is 0.4 of the next line's size. A paragraph after another gets 0.5 of its size more, and a heading, unless it is the first line, 0.6 of its own size more. A paragraph straight after its heading gets nothing extra. These spacings are provisional (`docs/known-gaps.md`).
- **Along the roll**, `anchor=` says where it would like to be, and margins and alignment are measured to the ink, as for the title and credits:
  - `start`: its ink starts `margin` from the start of the paper;
  - `end`: its ink ends `margin` from the end of the paper;
  - `middle`: centred on the middle of the paper;
  - a date: centred on where the date falls along the roll (the start of its period, as for an event, §3.3). A note anchored outside the timeline is left out with a warning, like an entity (§4.2). Near either end, it is moved inward just far enough to keep inside its margins.

### 17.3 Keeping clear

- **Of the title, the credits and other notes.** Notes are placed after the title and credits, in document order. Each keeps `clearance` (default `25mm`) along the roll from the title, the credits and every note placed before it, wherever the two would stand side by side across the roll (their line boxes, plus 1.5mm, overlapping across it). So a note at the `start` of the top edge begins 25mm past the end of the title, and one at the `end` of the bottom edge ends 25mm before the credits, while the title never pushes a note on the bottom edge. `clearance=` on the note changes the distance, `0` included.
- A note that has to move away from its anchor for this moves the least distance it can, in either direction (later, if both are equal), staying inside its margins. One anchored to a date that no longer reaches its date is a warning naming what it moved for. If there is nowhere along its edge for it, that's a fatal error.
- **By everything else**, exactly as for the title and credits (§16.3): every lane the note crosses, counting its lines' whole boxes plus 1.5mm across the roll, is reserved along its length, so no bar, bar label or illustration is placed there, and the reservation doesn't count towards how much of a side is in use when §6 breaks a tie. Event flags treat a note, plus 1.5mm, as a fixed obstacle (§8.2); poles and leaders are broken around it (§8); and graphs are broken around its text (§15.8).

### 17.4 Drawing

- The text is drawn as strokes in the note's pen, by the same text shaping as everything else (§3.8), so missing characters are replaced with a warning.
- Notes are drawn last, with the title and credits (§11).
