"""Inline formatting in labels and text (language spec §3.11): Markdown's emphasis, by CommonMark's rules.

``*italic*`` or ``_italic_``, ``**bold**`` or ``__bold__``, ``***both***``, and GitHub's ``~~strikethrough~~``.
A backslash before an ASCII punctuation character makes it literal (``\\*``). Delimiters open and close by
CommonMark's flanking rules, so ``snake_case`` and ``2 * 3 * 4`` stay as written, and an unmatched delimiter
is drawn as itself. Only those inline forms are recognised: nothing else in CommonMark (links, code, HTML) is.
"""

from __future__ import annotations

import string
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class Span:
    """A stretch of text in one style."""

    text: str
    bold: bool = False
    italic: bool = False
    strike: bool = False

    @property
    def style(self) -> tuple[bool, bool, bool]:
        return self.bold, self.italic, self.strike


Spans = tuple[Span, ...]

_ESCAPABLE = frozenset(string.punctuation)


def _is_space(c: str) -> bool:
    return c == "" or c.isspace()  # the ends of the text count as whitespace


def _is_punct(c: str) -> bool:
    return c != "" and unicodedata.category(c)[0] in "PS"


@dataclass
class _Run:
    """A run of delimiter characters (or one literal character, when ``char`` is empty)."""

    text: str  # a literal's character; a delimiter run's character, repeated
    char: str = ""  # *, _ or ~ for a delimiter run
    count: int = 0  # delimiters not yet used
    can_open: bool = False
    can_close: bool = False
    original: int = 0  # the run's length as written (CommonMark's "rule of 3" looks at it)
    active: bool = True  # still on the delimiter stack


def parse_inline(text: str) -> Spans:
    """The text's spans, in order, with the delimiters that formed emphasis removed. Adjacent spans differ in
    style; text without any formatting comes back as one plain span (none at all for an empty string)."""
    atoms: list[_Run] = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == "\\" and i + 1 < n and text[i + 1] in _ESCAPABLE:
            atoms.append(_Run(text[i + 1]))
            i += 2
            continue
        if c in "*_~":
            j = i
            while j < n and text[j] == c:
                j += 1
            before = text[i - 1] if i > 0 else ""
            after = text[j] if j < n else ""
            left = not _is_space(after) and (not _is_punct(after) or _is_space(before) or _is_punct(before))
            right = not _is_space(before) and (not _is_punct(before) or _is_space(after) or _is_punct(after))
            if c == "_":
                can_open = left and (not right or _is_punct(before))
                can_close = right and (not left or _is_punct(after))
            else:
                can_open, can_close = left, right
            length = j - i
            if c == "~" and length != 2:  # strikethrough is exactly two tildes; anything else is literal
                atoms.extend(_Run(c) for _ in range(length))
            else:
                atoms.append(_Run(c * length, c, length, can_open, can_close, length))
            i = j
            continue
        atoms.append(_Run(c))
        i += 1

    # Style counts per atom, for nesting: (bold, italic, strike).
    depth = [[0, 0, 0] for _ in atoms]
    # Each delimiter run's used delimiters, as (count, opened): on an opener they come off its inner (right) end, on
    # a closer off its inner (left) end, so what is left of a run is drawn on its outer side.
    for k, closer in enumerate(atoms):
        if not closer.char:
            continue
        while closer.active and closer.can_close and closer.count > 0:
            opener_index = None
            for m in range(k - 1, -1, -1):
                o = atoms[m]
                if not (o.char == closer.char and o.active and o.can_open and o.count > 0):
                    continue
                if closer.char == "~":
                    if o.count != closer.count:
                        continue
                elif (o.can_close or closer.can_open) and (o.original + closer.original) % 3 == 0 and not (
                    o.original % 3 == 0 and closer.original % 3 == 0
                ):
                    continue  # CommonMark's rule of 3
                opener_index = m
                break
            if opener_index is None:
                if not closer.can_open:
                    closer.active = False
                break
            opener = atoms[opener_index]
            used = 2 if opener.count >= 2 and closer.count >= 2 else 1
            slot = 2 if closer.char == "~" else (0 if used == 2 else 1)
            for m in range(opener_index + 1, k):
                depth[m][slot] += 1
                if atoms[m].char:
                    atoms[m].active = False  # delimiters between them can no longer match
            opener.count -= used
            closer.count -= used
            if opener.count == 0:
                opener.active = False
            if closer.count == 0:
                closer.active = False

    spans: list[Span] = []
    for atom, d in zip(atoms, depth, strict=True):
        chars = atom.text if not atom.char else atom.char * atom.count
        if not chars:
            continue
        style = (d[0] > 0, d[1] > 0, d[2] > 0)
        if spans and spans[-1].style == style:
            spans[-1] = Span(spans[-1].text + chars, *style)
        else:
            spans.append(Span(chars, *style))
    return tuple(spans)


def plain_text(text: str) -> str:
    """The text with its formatting removed: what is actually drawn, before any font's substitutions."""
    return "".join(s.text for s in parse_inline(text))


def characters(spans: Spans) -> list[tuple[str, tuple[bool, bool, bool]]]:
    """Each character with its style."""
    return [(c, s.style) for s in spans for c in s.text]


def from_characters(chars: list[tuple[str, tuple[bool, bool, bool]]]) -> Spans:
    """Spans from styled characters, joining neighbours in the same style."""
    spans: list[Span] = []
    for c, style in chars:
        if spans and spans[-1].style == style:
            spans[-1] = Span(spans[-1].text + c, *style)
        else:
            spans.append(Span(c, *style))
    return tuple(spans)
