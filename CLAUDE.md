# AxiTimeline

Pen-plotter timelines on rolls of paper: an AxiDraw SE/A3 plus a custom paper transport, driven by a plain-text
language (`.axitl`) that describes people, events, spans and groups on a timeline. This repo is the software
side: **libaxitl** (reusable engine library) and **axitime** (the CLI that hosts it and drives the plotter).

## Read these first, in this order
1. `docs/language-spec.md`: the `.axitl` grammar and layout rules (dates, pens, lanes, event poles, ticks, units).
2. `docs/interpreter-cli-spec.md`: the architecture, library boundary and CLI commands.
3. `docs/known-gaps.md`: issues not yet written into the specs. Check it before implementing any stage.

If a spec and the code disagree, the spec is the intent. Fix the spec deliberately, do not let them drift.
The specs in `docs/` are the canonical copies (since 2026-10-12); the claude.ai artifact and project doc they
began as are superseded. Change the specs here, in the same commit as the code they describe.

## Settled decisions (do not reopen without asking)
- **Python** for both libaxitl and axitime; `pyaxidraw`/`pyserial` for the AxiDraw EBB board. Parser uses **Lark**.
- **Pure three-stage pipeline in libaxitl:** `parse(source, resolve) -> AST`, `layout(ast, now) -> ResolvedLayout`,
  `render(layout, options) -> svg`. The library does no **host** I/O (file, network, database, clipboard,
  clock); the host supplies `resolve(name)` for includes, illustrations and custom fonts, and supplies `now`.
  Reading the library's own bundled package data (the built-in fonts) is allowed: it is identical on every
  host and pinned by the library version.
- **Text is drawn by libaxitl as strokes** from SVG stroke fonts (never SVG `<text>`). The 18 Hershey Text
  fonts are bundled; a `font="x.svg"` is a custom font fetched through `resolve`. `font_size` is the em size.
  Layout and render share one text-shaping function. Unknown font = parse error; a missing character is
  substituted with a warning (language spec §3.8).
- **Includes are a text-flattening pre-pass** before the grammar runs, comment-aware (`//` comments).
- **`plot` only ever consumes a frozen, pen-specific SVG**, never `.axitl`. Per-pen metadata lives in the SVG
  `<metadata>` element.
- **Units:** bare number = millimetres, `cm` and `m` suffixes accepted, in both CLI flags and `.axitl`. Internal
  canonical unit is mm. `scale` is always an explicit rate (`mm/year` etc.).
- **Job hash** = SHA-256 over flattened source + axitime/libaxitl version + resolved `now` (when used) + the
  SHA-256 of each illustration and custom font fetched through `resolve`.
  Job log filename = source basename + last 6 hex chars of the hash; `plot` verifies the full hash.
- **Crop marks:** crosshairs every 50 cm, drawn in `2H-pencil` by the renderer; not part of the language. They are
  centred on both finished edges (arms 2.5mm), so the trim cuts through them.
- Paper stock is always larger than the finished size; all ink stays inside the finished length and width, except
  crop marks, which cross the finished edges by 2.5mm (so stock needs at least that much spare each side).

## Repo layout and commands
- uv workspace, Python 3.12: `libaxitl/` (the library, no hardware dependencies) and `axitime/` (the CLI host).
- `uv sync` to set up; `uv run pytest` to run all tests.
- `uv run axitime check|list-pens|render <file.axitl> [--now DATE]`; `render -o DIR` writes a preview and one SVG
  per pen (window with `--start-offset`/`--length` or `--from`/`--to`).
- `uv run axitime plot <file-pen.svg> [--simulate|--dry-run]` plots one per-pen SVG; the job log goes beside it.
  Plotter settings: `~/.config/axitime/plotter.toml` (see `axitime/config.py`). pyaxidraw is optional and only
  imported for a real plot; tests use a simulated plotter and a fake pyaxidraw.
- On the machine that drives the AxiDraw, install with `uv sync --extra axidraw` (a plain `uv sync` removes it).
  The AxiDraw API isn't on PyPI; one of its wheels is vendored (`vendor/README.md` explains why). On a new
  machine uv may rewrite one `axidrawinternal` metadata line in `uv.lock`; that's expected and harmless.
- To look at output, render it and export a PNG with Inkscape:
  `/Applications/Inkscape.app/Contents/MacOS/inkscape x.svg --export-type=png --export-dpi=100`.
- Spacing constants live in `LayoutStyle` (`libaxitl/layout.py`) and `DrawStyle` (`libaxitl/draw.py`).
- Built-in fonts live in `libaxitl/src/libaxitl/fonts/data/` (copied from Inkscape's Hershey Text
  `svg_fonts`, with their licence notices). Keep `HERSHEY-NOTICE.txt` and `OFL.txt` beside them.
- `editors/vscode/` is the VS Code extension (highlighting, completion, hover; plain JS, no build step; see its
  README). Its tests: `node test/run.js` from that folder. It repeats the language's vocabularies (pens, fonts,
  parameters, values) in `src/vocabulary.json` and the grammar; `uv run pytest` checks them against libaxitl, so
  a language change that adds to them has to update the extension in the same commit.

## Working notes
- The author is UK-based; metric throughout. British spelling in user-facing text.
- Layout must be deterministic: identical input (and `now`) gives byte-identical output. Use explicit
  tie-breaks as the spec lists them; never rely on dict/set ordering.
- Ask before changing a settled decision above. Record new decisions in the relevant spec, not only in code.
