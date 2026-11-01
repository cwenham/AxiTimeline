# AxiTimeline for VS Code

Editor support for `.axitl` files: syntax highlighting, completion, hover help, errors and warnings from
`axitime check`, and a rendered preview. Plain JavaScript with no dependencies and no build step.

## What it does

- **Highlighting** of keywords, side and priority marks, labels, dates, pens, parameters and their values,
  illustrations and comments, and of `**bold**`, `*italic*` and `~~struck~~` text inside quotes (§3.12; an
  approximation of CommonMark's rules, so the render is the final word). Only words the language knows are coloured, so a typo shows up as plain text:
  `purple`, `7B-pencil`, `fill=stripes` or `colour=red` stay uncoloured. Date ranges show their separator
  in its own colour, which makes two traps from the spec visible: `1910-12` has no separator because it is
  December 1910, not 1910 to 1912, and in `1963//1964` the end date turns into a comment (§§3.3, 3.9).
- **Completion**, fitted to where the cursor is:
  - at the start of a line: `timeline`, `include`, the entity keywords, `graph`, `title`, `credits` and
    `note`, inserted as templates to tab through (`person "Name" 1900-1950`). `graph`, `title`, `credits` and
    `note` aren't offered inside a group. After `^`, `v`, `!` or `-` marks, only entity keywords are offered; a
    second `timeline` is not. Inside the credits' or a note's `{ }` body only `heading` is.
  - after an entity's date: pens (with a swatch of their preview colour), the parameters that entity takes
    and haven't been given yet, and `illustration(…)`. `fill=` is offered only for bars and `time_label=`
    only for events and groups.
  - after a graph's title (§15): pens, `HB-pencil` marked as its default, and a graph's parameters; nothing
    inside its `{ }` body of points.
  - after a title's text, or after `credits` (§16): pens, their parameters (`align=` among them) and
    `illustration(…)`, which takes `at=left` or `at=right` there.
  - after `note` or a note's quoted text (§17): pens, a note's parameters, with the values of `anchor=`
    (`start`, `middle`, `end`; a date works too) and `edge=` (`top`, `bottom`), and `illustration(…)`, which
    takes `at=left` or `at=right` there but no `height=`.
  - on a `timeline` or `include` line, or an indented continuation line under one (§3.10): their parameters.
    The timeline's required ones are marked, and `length=` and `scale=` exclude each other.
  - after `key=`: the values it takes (fills, time labels, `baseline=`, `end=now`, `ticks=off`, units for
    `scale=`), the built-in fonts for `font=`, and pens with their swatches for `fill_pen=`.
  - file names: `.axitl` files for `include "…"`, `.svg` files for `illustration(…)` and custom fonts, `.csv`
    files for a graph's `data=`,
    relative to the document, as libaxitl resolves them.
  - nothing inside labels, dates or comments.
- **Hover help** for keywords, entity heads (spelling out the side and priority the marks give), pens,
  parameters, values and built-in fonts, condensed from the language spec, with its section numbers. A
  parameter shared between declarations, such as `height=` or `fill=`, is explained as it applies on its line.
- **Errors and warnings** from `axitime check`, run when a file is opened and each time it's saved, so they're
  exactly what the real parser and layout report. Problems in an included file are shown in that file too.
  A file without a `timeline` is an include: checked on its own it's spared the missing-timeline error, and
  saving it checks the open timelines again, since they may include it. axitime gives a line but no column,
  so each squiggle covers its line.
- **A rendered preview** beside the source: the preview button in the editor's title bar, *AxiTimeline: Open
  Preview to the Side* (`Cmd+K V`, or `Ctrl+K V`), or *Open Preview* (`Cmd+Shift+V`) to open it in place. It's
  the every-pen preview SVG from `axitime render --preview-only`, drawn on white paper whatever the theme, and
  like the checks it shows the file as saved: it renders when opened and again on each save. Saving an include
  re-renders every open preview, as does saving an `.svg`, `.csv`, `.tsv` or `.txt` file, since illustrations,
  custom fonts and graph data come from those. If a save has errors the last good drawing stays, under a banner
  saying what's wrong. *Fit* shows the whole timeline and *Fit height* fits the roll's width to the panel so you
  scroll along it; `−`, `+` and *1:1* (the size it will be plotted) zoom, as do Ctrl or Cmd and the scroll
  wheel, or a pinch, around the pointer. Drag to pan; with nothing to scroll up and down, the wheel moves along
  the timeline. Keys: `+` and `-`, `0` for fit, `h` for fit height, `1` for 1:1. The zoom and position survive
  the panel being hidden or VS Code reloading, and an open preview comes back after a reload.
- `//` comment toggling, bracket matching, auto-closing quotes and brackets, indentation inside a group's
  `{ }` and after a lone `timeline`, and folding of groups and multi-line declarations.

### Settings

- `axitl.check.enabled` (default on): run `axitime check` on open and save.
- `axitl.check.command`: how to run axitime, for checks and previews, one word per item, e.g.
  `["/Users/me/AxiTimeline/.venv/bin/axitime"]`. Left empty, the extension uses the `axitime` in the nearest
  `.venv` folder at or above the file, else the one in the AxiTimeline checkout the extension is linked from
  (see *Installing*), so timelines kept in a folder of their own work after `uv sync` too, else `axitime` on the
  PATH. Set it only for a different axitime. A `.venv/bin/axitime` is quicker than `uv run`, which checks the
  environment is up to date before every run, and outside the repo needs `--project` to find it.

Checking and previewing run a program found in the workspace, so they only happen in a trusted workspace (VS
Code's *Workspace Trust*). If axitime can't be run, the extension says so once and logs the details to the
*AxiTimeline* output panel.

## Installing

Link this folder into VS Code's extensions folder, from the repo root, then reload VS Code (*Developer:
Reload Window*):

```bash
ln -s "$PWD/editors/vscode" ~/.vscode/extensions/axitimeline.axitl-0.1.0
```

Because it's a link, changes here take effect on the next reload. To remove it, delete the link and reload.

To try it without installing, open a window with it loaded:

```bash
"/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code" --extensionDevelopmentPath="$PWD/editors/vscode" examples
```

## Layout

- `syntaxes/axitl.tmLanguage.json`: the TextMate grammar for highlighting.
- `language-configuration.json`: comments, brackets, word boundaries, indentation and folding.
- `src/analyse.js`: works out what fits at the cursor, from the text alone (no `vscode` API, so it's testable
  under plain node).
- `src/extension.js`: the completion and hover providers, and wiring for the checks.
- `src/check.js`: runs `axitime check --json` and turns its report into diagnostics.
- `src/preview.js`: the preview panels: runs `axitime render --preview-only` into a temporary folder per panel
  and sends the page the SVG it writes (`<name>-preview.svg`).
- `media/preview.js` and `media/preview.css`: the preview panel's page, which shows the SVG and zooms it.
- `src/vocabulary.json`: the language's closed vocabularies: pens and their preview colours, fonts, entity
  keywords, parameters and values.
- `src/docs.js`: the help text.

## Tests and keeping in step with the language

- `node test/run.js` (from this folder, any node from 12 up) runs the completion, hover, checking and preview
  tests, driving the extension through a stand-in for the `vscode` API. The checking and preview tests run the
  repo's `.venv/bin/axitime`, so `uv sync` first; without it they're skipped. The preview page's zooming runs
  only in a webview, so it isn't covered: try it by hand after changing `media/`.
- `uv run pytest` (from the repo root) includes `test/test_vocabulary.py`, which checks `vocabulary.json`
  against libaxitl and that the grammar highlights every pen, font, parameter and value. When the language
  gains a pen, font, parameter or value, that test fails until `vocabulary.json` and the grammar's patterns
  in `syntaxes/` are updated (and `src/docs.js` given its help text).
