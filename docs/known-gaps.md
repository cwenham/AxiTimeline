# Known gaps before and during coding

Issues found in review that are **not yet written into either spec**. Each needs a decision (or a deliberate
"author's responsibility" note) before or while the relevant stage is implemented. Ordered roughly by how soon
they bite. Delete an item once it is settled in the spec it belongs to.

Already resolved, so not listed:
- paper width (now the required `width=` on `timeline`, language spec §4) and where bar labels go and how they
  pack (language spec §7);
- font metrics and missing/unknown font names (settled 2026-10-12: language spec §3.8, interpreter spec
  "Library boundary" and "Job log");
- multi-line `include` declarations versus text-flattening (settled 2026-10-12: the flattening pass recognises
  continuation lines, interpreter spec "Public shape");
- the `baseline=` default (`middle`, language spec §4) and an event's identity for duplicates (includes its
  date, language spec §5), both settled 2026-10-12;
- poles running through bars and their labels (settled 2026-10-12: poles are broken around other ink, and the
  new `time_label` lets an author date an event exactly; language spec §§3.11, 8);
- per-pen ink length (settled 2026-10-12: measured by render, interpreter spec "Layout engine");
- the SVG coordinate and unit convention (settled 2026-10-12: 1 user unit = 1mm, interpreter spec "SVG
  conventions"), and crop marks centred on the finished edges (settled 2026-10-12, interpreter spec "Crop
  marks");
- event flags drawn over lower-priority bars (settled 2026-10-12: bars are fixed obstacles for flags,
  language spec §8.2);
- the job hash's exact serialisation (settled 2026-10-12, interpreter spec "Job log");
- safe abort during `plot`, the plotter's travel envelope (a config file over AxiDraw SE/A3 defaults), confirming
  the pen by typing its name, and how a job's first pass starts its log (all settled 2026-10-12, interpreter
  spec "axitime plot" and "Job log");
- bar labels too long for their bars: beside the bar, else pulled out up to three lanes with a 45° leader ending
  level with the middle of the label's capitals, else running past the bar with a warning (settled 2026-10-12,
  language spec §7). A label squeezed out entirely is the author's cue to shorten it or rearrange, not a case
  for more layout logic.

## Found while building layout and render

### 1. Layout and drawing spacing values are provisional
The spec asks for "a small margin" in several places without numbers. They are all in one place,
`LayoutStyle` in `libaxitl/layout.py`: bar inset 1mm, label inset 1.5mm, gap between lane neighbours 1.5mm,
flag gap 1mm, flag clearance 1mm, stagger gap 0.5mm, collision padding 0.4mm, illustration gap 1.5mm, ticks
1mm/2mm, tick labels at 0.75 × `font_size`, time label gap 0.4mm, 0.75mm left either side where a pole is broken,
pieces of broken pole or leader shorter than 1mm left out, and 0.5mm between a leader's end and its label. The drawing values are in `DrawStyle` in
`libaxitl/draw.py` (cap depth 1.5mm, hatching 2mm, solid 0.4mm, fills 0.75mm clear of labels, crop arms 2.5mm).
All of them need checking on paper.

## Needed before plot

### 2. Illustration content constraints (implemented, to confirm)
Illustrations are inlined author SVGs that a pen will physically draw. As implemented: every shape is drawn as its
outline; text, embedded images, `<use>` references and foreign objects are left out; filled shapes are drawn as
outlines; and `check` reports each of these as a warning (interpreter spec, "How the renderer draws"). Confirm
this, or say that illustrations should be the author's responsibility with no warnings.

## Operational / hardware-adjacent

### 3. The paper transport and strips (hardware drafted, not built)
The paper transport's hardware is drafted in `docs/transport.md` (2026-10-15): a raised board with the rolls and
weighted dancer loops hanging below both edges, a gritted drive roller at the front edge, and three steppers
driven from a Pico. It isn't built yet, so `plot` currently:
- runs the roll under the AxiDraw's base beam, along its Y axis (settled 2026-10-14, interpreter spec "The
  roll's orientation"), and draws the job in strips that fit its Y travel (`strip_mm` in the plotter config, 250mm
  by default), cutting strokes at strip edges. Which way the paper moves (`feed`) is a setting until the
  transport is designed;
- uses a "manual" transport: between strips it asks the operator to move the paper on by an exact distance
  (skipping strips with nothing to draw for that pen, so the paper moves on in one go).

The transport plugs into one call, `advance(mm, next_start)` in `axitime/plotting.py`, so whatever protocol the
controller ends up with only has to implement that. An optical flow sensor could make it closed-loop (measure
the paper's actual movement rather than trusting the motor), which would matter because strokes cut at a strip
edge only meet again if the paper moves exactly a strip's length (`docs/transport.md` suggests it only catch
slipping, since mouse-type sensors drift). To decide with the hardware: the controller's serial protocol and its
accuracy. The drafted layout feeds towards the front, which is the current default.

## Background graphs (language spec §15, added 2026-10-24)

Implemented 2026-10-24, after a throwaway mock-up; see the examples `crash-1929.axitl` and `reactor-power.axitl`.
Still open:

- **Averaged data.** A point sits at the start of its period (§15.4), but a monthly or yearly average belongs to
  the middle of it: on a 5 mm/year timeline, a yearly average drawn at 1 January is 2.5mm early against the
  events. An `at=start|middle` option was discussed; undecided, since no averaged data is planned yet.
- **Flat background lines beside foreground lines.** In `crash-1929.axitl`, a stepped line running along a bar's
  edge reads as a doubled edge, and a flat line broken where it meets a flag looks like a leader pointing at it.
  Pencil against ink may tell them apart on paper; if not, options are a dashed line style for backgrounds
  (slower to plot) or a wider gap where a flat line meets text.
- **Value labels on a crowded roll.** Labels keep clear of bars entirely, so where long bars fill the lanes a
  mark's label may find no room anywhere: in `crash-1929.axitl`, the discount rate's marks at 2 and 4 fall on lane
  edges under bars that run to the end of the roll, so it uses `value_scale=start`. Labels with no room are left
  out with a warning, and the author can change `height=`, `value_marks=` or `value_scale=`.
- **Several graphs.** Each has its own value scale, told apart only by position and pen, which is weak with two
  pencil grades. Linking each scale to its title (the title beside the first scale, say) may be needed.
- **On paper:** ink over pencil (graphite picked up by felt and fountain nibs, especially over dense `solid`
  shading, and which grade to default to: HB may be too soft); the plotting time of `solid` shading, whose
  horizontal hatching every 0.4mm becomes many short strokes in a narrow band; and whether the 2mm spacing of the
  other patterns suits a band only a few millimetres deep.
- **Spacing values** are provisional (in `LayoutStyle` and `DrawStyle`): a fitted graph 3mm inside the finished edges; lines
  cut 1mm inside them; 0.75mm gaps around text and around a shadow's own line; simplification within 0.1mm;
  shading pieces under 0.5mm left out; the title 1.5mm from the line; value-scale ticks 1.2mm long with labels
  0.6mm beyond them at 0.75 × `font_size`; label searches in 1mm steps.
- **Fill pens beside the axis pen.** Fill pens are plotted straight after the axis pass, but a bar whose own pen is
  the axis pen (black) has its outline drawn in that first pass, so its pencil fill goes on after it, touching
  the outline's inside edge. Check on paper whether that matters.
- **Left out for now:** decimal commas (`decimal=comma`), more than one `missing=` marker, timezones in
  `time_format=`, and other kinds of background (shaded time ranges).

## Smaller points

- **Closed pen vocabulary** (language spec §3.4): no brown, pink, white, cyan or magenta. Adding one later is a
  grammar change. Confirm the list is final before the grammar is frozen.
- **`--now` coarser than the timeline `start`**: the interpreter spec rejects it with an error. That was a
  drafting decision rather than something the language spec dictates; confirm.
- **`--now` supplied when the source does not use `now`**: spec says it has no effect and axitime says so.
  Also a drafting decision.
- **Deliberately deferred, not gaps**: physical motion feasibility checking (until after hardware testing) and
  how a web front-end hosts libaxitl (Pyodide in-browser vs a small Python service).

## Interpretations made in code, to confirm

Places where the specs were silent or ambiguous and the code had to pick something. Each is a reasonable
reading, not a settled decision: confirm it (and move it into the spec) or correct it.

**Dates (`libaxitl/dates.py`)**
- A timestamp with `Z` or an offset is converted to UTC; one without is taken literally, i.e. as UTC. So
  `14:00+03:00` and `11:00` are the same moment.
- Times may be written to the hour (`T12`) or minute (`T12:30`) as well as the second, per ISO 8601.
- Two digits after a year and a hyphen always read as a month: `1910-12` is December 1910 (as §3.3 intends),
  and `14-37` is an error suggesting `14/37`. A `/` between two bare years is accepted.

**Inheritance and includes**
- `font` and `font_size` cascade timeline → group → member, like a group's pen (§3.8 says "same pattern").
- Nested includes: `priority=` offsets add up; for `side=`, the outermost include's override wins.
- An include's `side=` makes every entity it pulls in explicitly sided, as if written with `^`/`v`, so layout
  will treat them as forced (§3.2: placed first).
- `include` is allowed inside a group's `{ }` body; the included entities become members of that group.

**Duplicates (§5)**
- The last-wins rule applies to definitions from *different files* (or the same line arriving twice, from a
  file included by two routes). The same identity repeated *within one file* is kept, e.g. two different
  people both called "John Smith", since §5 only speaks of duplicates across includes.

**Syntax details**
- Quoted strings accept `\"` and `\\` escapes; any other backslash is literal.
- The pen keyword may appear anywhere after the date, not only immediately after it.
- An illustration's file name may be quoted or bare. Its aspect ratio comes from the `<svg>` `width`/`height`,
  else from its `viewBox`. Illustration and custom-font paths are relative to the declaring file, like includes.

**Layout (`libaxitl/layout.py`, `libaxitl/ticks.py`)**
- The time axis runs from the first moment of `start` to the *end* of `end`'s period, so `end=2026` includes
  all of 2026. `mm/year` uses the mean Gregorian year (365.2425 days). A derived scale is reported in the
  largest unit the timeline spans at least twice.
- `baseline=low` puts the baseline W/φ from the top edge, leaving the larger share above it (and the reverse for
  `high`).
- Ticks and their labels hang below the baseline, so lanes below start beyond them (tick band + the below
  `baseline_offset`). Tick labels use the timeline's font at 0.75 × its `font_size`, centred on their tick. The
  baseline and ticks are drawn in `black`.
- The nearest ladder rung is judged by ratio. Day-of-month ticks drop a final tick closer than half a step to the
  next month's 1st (so 10-day ticks are the 1st, 11th and 21st). Year ticks follow written years (100BC, 100,
  200), so the step across BC/AD is a year short. Ticks at both ends of the paper are included.
- `tick_label_every` counts from the rung's own alignment (day counts restart each month).
- The ladder's label spacing is judged with labels centred on their ticks. The labels at the two ends are then
  shifted inward onto the paper; if one runs into its neighbour, the neighbour keeps its long tick but drops its
  text.
- The remaining-capacity tie-break (§6) compares the fraction of each side's width in use (lane 0's inner edge
  plus the lanes used); then the side with more space; then above.
- Forced entities go first among events as well as bars (§3.2).
- `label_clearance_margin` (§8.1) is the flag's own height plus 1mm. With no higher-priority bars, a pole
  reaches just past lane 0's inner edge. A flag hangs beside the outer end of its pole.
- §8.2 conflicts also count another event's pole running through a flag, since that is ink through text too.
- An event's illustration goes on whichever side of the pole its band sits lower; a tie goes left, away from
  the flag's default direction. Illustrations are drawn at their exact height from the inner edge of their band.
- Illustrations are nudged again after staggering, since a lengthened pole can grow into one; anything still
  colliding then is reported as a warning.
- A group member whose group lies wholly outside the timeline gets an automatic side.
- `axitime` reads `now` from the local wall clock, since dates without a timezone are taken literally.
- Side choice for events (§6.1) still compares base poles, which only count higher-priority bars. Since flags
  are now lifted clear of every bar (§8.2), an event can land on the side where its flag then has to climb
  higher. Comparing the lifted lengths instead would be a small change if it turns out to matter on paper.

**Render (`libaxitl/draw.py`, `libaxitl/render.py`)**
- Preview colours approximate each pen on screen (pencils in greys, softer grades darker); on paper the pen decides.
