# AxiTimeline for VS Code

Editor support for `.axitl` files: syntax highlighting, completion and hover help. Plain JavaScript with no
dependencies and no build step.

## What it does

- **Highlighting** of keywords, side and priority marks, labels, dates, pens, parameters and their values,
  illustrations and comments. Only words the language knows are coloured, so a typo shows up as plain text:
  `purple`, `7B-pencil`, `fill=stripes` or `colour=red` stay uncoloured. Date ranges show their separator
  in its own colour, which makes two traps from the spec visible: `1910-12` has no separator because it is
  December 1910, not 1910 to 1912, and in `1963//1964` the end date turns into a comment (§§3.3, 3.9).
- **Completion**, fitted to where the cursor is:
  - at the start of a line: `timeline`, `include` and the entity keywords, inserted as templates to tab
    through (`person "Name" 1900-1950`). After `^`, `v`, `!` or `-` marks, only entity keywords are offered;
    a second `timeline` is not.
  - after an entity's date: pens (with a swatch of their preview colour), the parameters that entity takes
    and haven't been given yet, and `illustration(…)`. `fill=` is offered only for bars and `time_label=`
    only for events and groups.
  - on a `timeline` or `include` line, or an indented continuation line under one (§3.10): their parameters.
    The timeline's required ones are marked, and `length=` and `scale=` exclude each other.
  - after `key=`: the values it takes (fills, time labels, `baseline=`, `end=now`, `ticks=off`, units for
    `scale=`), and the built-in fonts for `font=`.
  - file names: `.axitl` files for `include "…"`, `.svg` files for `illustration(…)` and custom fonts,
    relative to the document, as libaxitl resolves them.
  - nothing inside labels, dates or comments.
- **Hover help** for keywords, entity heads (spelling out the side and priority the marks give), pens,
  parameters, values and built-in fonts, condensed from the language spec, with its section numbers.
- `//` comment toggling, bracket matching, auto-closing quotes and brackets, indentation inside a group's
  `{ }` and after a lone `timeline`, and folding of groups and multi-line declarations.

It doesn't check documents for errors; `uv run axitime check file.axitl` does that with the real parser.

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
- `src/extension.js`: the completion and hover providers.
- `src/vocabulary.json`: the language's closed vocabularies: pens and their preview colours, fonts, entity
  keywords, parameters and values.
- `src/docs.js`: the help text.

## Tests and keeping in step with the language

- `node test/run.js` (from this folder, any node from 12 up) runs the completion and hover tests, including
  the providers driven through a stand-in for the `vscode` API.
- `uv run pytest` (from the repo root) includes `test/test_vocabulary.py`, which checks `vocabulary.json`
  against libaxitl and that the grammar highlights every pen, font, parameter and value. When the language
  gains a pen, font, parameter or value, that test fails until `vocabulary.json` and the grammar's patterns
  in `syntaxes/` are updated (and `src/docs.js` given its help text).
