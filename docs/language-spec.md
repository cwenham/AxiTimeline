# AxiTimeline Language Spec

Specification for the `.axitl` language and its layout engine — the description language and how it resolves to physical positions on paper. Companion to the separate hardware spec (plotter/transport electronics) and interpreter CLI spec (`axitime`/`libaxitl`).

Status: working draft, reflecting all decisions taken in design discussion so far.

This file (`docs/language-spec.md` in the AxiTimeline repo) is the **canonical copy** of this spec, and changes are made here alongside the code. The claude.ai artifact it began as is superseded.

History: reconciled 2026-09-19, merging the units section (§14) that originated in the interpreter/CLI spec discussion. Revised 2026-10-12 after a full review pass: text-collision rules, paper-edge handling, clipping at the timeline window, event side selection, `now` reproducibility, removal of standalone illustrations, date-grammar tightening, day-scale ticks, and concrete defaults. Moved into the repo 2026-10-12, then amended the same day: fonts (§3.8), the `baseline` default (§4), event identity for duplicates (§5), broken poles with time labels (§§3.11, 8), flags kept clear of bars (§8.2), groups drawn like spans (§9), and bar labels placed beside their bars or pulled out (§7).

## 1. System overview

Hardware (from the earlier design phase): AxiDraw SE/A3 for pen plotting, a custom paper feed/rewind controller (ESP32/Pico), and multi-pass-per-pen plotting onto a paper roll, orchestrated by a Raspberry Pi — computationally ample, since all real-time motion is offloaded to the EBB and the feed microcontroller.

The software architecture — `libaxitl` (parse → layout → render) and the `axitime` CLI (`check`, `list-pens`, `render`, `plot`), with plotting driven only from frozen per-pen SVGs — is defined in the **interpreter CLI & architecture spec**, not here. This spec defines what that pipeline's parse and layout stages must do: the `.axitl` language (§§2–5, §14) and the layout rules it resolves through (§§6–12).

## 2. Entity types

`person`, `event`, `span`, `group`, `include`, plus the top-level `timeline` directive. Keywords are lowercase. Illustrations are attachments to entities, not entities in their own right (§3.5).

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

- A **continuation line** is an indented line (leading spaces and/or tabs — either is fine, and they may be mixed, since indentation here carries no depth meaning) whose first token is a `key=value` parameter
- The declaration **ends** at the first line that is not a continuation: a blank line, or a line beginning at column 0. A blank line before the next keyword is the recommended style — it's what makes the block visually obvious — but the indentation is what actually does the work, so a missing blank line degrades to a style inconsistency rather than a parse failure. (Requiring a blank line would make "blank" load-bearing, which is fragile given editors that strip or add trailing whitespace; a whitespace-only line counts as blank regardless)
- Comment lines (§3.9) inside a block are skipped and do **not** terminate it, so parameters can be annotated or temporarily commented out in place
- The discriminator that keeps this unambiguous against a `group`'s indented body is the `key=value` shape: a group's children always begin with a keyword or a `!`/`-`/`^`/`v` symbol, never with `key=`, so an indented line starting `key=` can only ever be a continuation. Inside `{ }` braces, indentation stays purely cosmetic
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
- Provenance (source file + line) tracked per entity through the include tree
- Duplicate entities across includes (same `(type, name)`, e.g. two files both defining `person "Julius Caesar"`): the **last one defined wins**, with a build warning naming both provenance locations (which lost, which won). Left to the operator to fix at the source if unintended.
- An **event's identity also includes its date**, at the same precision: `event "General election" 1945` and `event "General election" 1950` are different events, and so are `1950` and `1950-02`. Two events are duplicates only when type, label and date all match
- Including the same file twice by different routes is not a cycle; the second copy's entities are duplicates under the rule above

## 6. Side (above/below) — automatic placement

Layout runs in three phases, each consuming the results of the one before:

1.  **Phase A** — banded entities (`person`, `span`, `group`) get a side and a lane (this section and §7), along with any illustrations attached to them (§3.5)
2.  **Phase B** — events get a side (§6.1) and a base pole length (§8.1); illustrations attached to events are placed; illustrations in a pole's path are nudged
3.  **Phase C** — label collisions involving event flags are resolved (§8.2)

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
- **Side and pen are inherited from the group by default** (which is why a group is always placed before its members, §6). A child with no explicit `^`/`v` uses the group's resolved side; a child with no explicit trailing pen uses the group's pen. Either can be overridden per-line with the child's own `^`/`v` or pen keyword — so a child *can* deliberately end up on the opposite side or in a different pen from its group, but only if it says so explicitly
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

- Ticks **must be drawn in the first pen pass**, since they are the alignment reference every subsequent pass and every resumption depends on. This is consistent with the interpreter spec's existing note that ticks are drawn with the first pen (typically black or a hard pencil)
- Because tick spacing is not perfectly uniform (§10.1), an operator measuring an offset should count ticks to a *labelled* tick and measure from there, rather than assuming a constant mm-per-tick across a long run
- The interpreter's renderer also draws pencil crop marks every 50cm, giving a second, purely physical reference that's independent of tick spacing

## 11. Draw order (for the physical plot)

1.  Baseline + tick marks (auto-generated, first pen pass — see §10.4)
2.  Span / group fills
3.  Event poles + flags (on top of fills)
4.  Illustrations (last — fine detail, and by this point nothing should be crossing into their footprint)

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
