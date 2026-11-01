"""The VS Code extension's vocabulary and grammar against libaxitl, so the editor can't drift from the language.

The extension lists the language's closed vocabularies in ``src/vocabulary.json`` and repeats some of them in
the highlighting grammar's patterns. These tests fail when libaxitl gains a pen, font, parameter or value the
editor doesn't know about (or loses one it still offers).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from libaxitl import graphdata, grammar, parser
from libaxitl.fonts import BUILTIN_FONTS, DEFAULT_FONT
from libaxitl.model import (
    Baseline, Edge, Fill, Horizontal, Kind, LineMode, NoteAnchor, OpenEndStyle, Side, TimeLabel, ValueScaleMode, YScale,
)
from libaxitl.pens import DEFAULT_PEN, PENS
from libaxitl.render import pen_colour
from libaxitl.units import SCALE_UNITS

EXTENSION = Path(__file__).resolve().parent.parent
VOCABULARY = json.loads((EXTENSION / "src" / "vocabulary.json").read_text())
GRAMMAR = json.loads((EXTENSION / "syntaxes" / "axitl.tmLanguage.json").read_text())
PARAMETER_RULES = GRAMMAR["repository"]["parameter"]["patterns"]  # the last is the catch-all for unknown keys


def rule(name: str) -> str:
    return GRAMMAR["repository"][name]["match"]


def test_pens_and_their_preview_colours():
    assert list(VOCABULARY["pens"]) == list(PENS)
    assert VOCABULARY["pens"] == {pen: pen_colour(pen) for pen in PENS}
    assert VOCABULARY["defaultPen"] == DEFAULT_PEN


def test_fonts():
    assert VOCABULARY["fonts"] == list(BUILTIN_FONTS)
    assert VOCABULARY["defaultFont"] == DEFAULT_FONT


def test_entities():
    assert VOCABULARY["entities"] == [k.value for k in Kind]
    assert VOCABULARY["bandedEntities"] == [k.value for k in Kind if k.is_banded]


def test_backgrounds():
    assert VOCABULARY["backgrounds"] == ["graph"]
    assert "graph(?![\\w])/" in grammar.GRAMMAR
    assert VOCABULARY["defaultGraphPen"] == parser.DEFAULT_GRAPH_PEN


def test_corners():
    assert VOCABULARY["corners"] == ["title", "credits"]
    assert "title(?![\\w])/" in grammar.GRAMMAR and "credits(?![\\w])/" in grammar.GRAMMAR
    assert "heading(?![\\w])/" in grammar.GRAMMAR


def test_notes():
    assert VOCABULARY["notes"] == ["note"]
    assert "note(?![\\w])/" in grammar.GRAMMAR


def test_parameters():
    assert VOCABULARY["timelineParameters"] == list(parser._TIMELINE_KEYS)
    assert VOCABULARY["entityParameters"] == list(parser._ENTITY_KEYS)
    assert VOCABULARY["graphParameters"] == list(parser._GRAPH_KEYS)
    assert VOCABULARY["titleParameters"] == list(parser._TITLE_KEYS)
    assert VOCABULARY["creditsParameters"] == list(parser._CREDITS_KEYS)
    assert VOCABULARY["noteParameters"] == list(parser._NOTE_KEYS)
    assert VOCABULARY["illustrationParameters"] == list(parser._ILLUSTRATION_KEYS)
    assert VOCABULARY["titleIllustrationParameters"] == list(parser._TITLE_ILLUSTRATION_KEYS)
    assert VOCABULARY["creditsIllustrationParameters"] == list(parser._CREDITS_ILLUSTRATION_KEYS)
    assert VOCABULARY["noteIllustrationParameters"] == list(parser._NOTE_ILLUSTRATION_KEYS)


def test_values():
    values = VOCABULARY["values"]
    for key, enum in (("fill", Fill), ("time_label", TimeLabel), ("baseline", Baseline),
                      ("open_end_style", OpenEndStyle), ("side", Side)):
        assert values[key] == [m.value for m in enum], key
    assert VOCABULARY["scaleUnits"] == list(SCALE_UNITS)
    for key, enum in (("y_scale", YScale), ("line", LineMode)):
        assert values[key] == [m.value for m in enum], key
    assert values["value_scale"] == [m.value for m in ValueScaleMode if m is not ValueScaleMode.EVERY]
    assert values["separator"] == list(graphdata.SEPARATORS)
    assert values["header"] == ["yes", "no"]
    assert values["at"] == values["align"] == [m.value for m in Horizontal]
    assert values["pens"] == ["auto"]
    assert values["anchor"] == [m.value for m in NoteAnchor]
    assert values["edge"] == [m.value for m in Edge]


def _all_keys() -> list[str]:
    v = VOCABULARY
    return sorted(set(v["timelineParameters"] + v["entityParameters"] + v["includeParameters"]
                      + v["illustrationParameters"] + v["graphParameters"] + v["titleParameters"]
                      + v["creditsParameters"] + v["titleIllustrationParameters"] + v["noteParameters"]))


@pytest.mark.parametrize("key", _all_keys())
def test_grammar_highlights_every_parameter(key):
    known = [r["match"] for r in PARAMETER_RULES[:-1] if re.match(r["match"], f"{key}=")]
    assert known, f"no highlighting rule for {key}="


@pytest.mark.parametrize("key", sorted(VOCABULARY["values"]))
def test_grammar_highlights_every_value(key):
    for value in VOCABULARY["values"][key]:
        matches = [m for r in PARAMETER_RULES[:-1] if (m := re.fullmatch(r["match"], f"{key}={value}"))]
        assert matches and matches[0].group(3) == value, f"{key}={value}"


@pytest.mark.parametrize("key", ["font", "subtitle_font", "heading_font"])
def test_grammar_highlights_every_font_written_bare(key):
    for font in BUILTIN_FONTS:
        assert any(re.fullmatch(r["match"], f"{key}={font}") for r in PARAMETER_RULES[:-1]), font


def test_grammar_highlights_the_title_credits_and_headings():
    assert re.match(rule("corner"), "title \"T\"").group(1) == "title"
    assert re.match(rule("corner"), "  credits {").group(1) == "credits"
    assert re.match(rule("corner"), "note anchor=start {").group(1) == "note"
    assert not re.match(rule("corner"), "notes")
    assert not re.match(rule("corner"), "titles")
    assert re.match(rule("heading"), '  heading "Sources"').group(1) == "heading"


def test_grammar_highlights_exactly_the_pens():
    pen = rule("pen")
    for name in PENS:
        assert re.fullmatch(pen, name), name
    for wrong in ("purple", "7B-pencil", "1H-pencil", "fountain-pink", "pencil", "BB-pencil", "reddish"):
        assert not re.fullmatch(pen, wrong), wrong


@pytest.mark.parametrize("text, is_year_range", [
    ("1642-1727", True),
    ("509BC-27BC", True),
    ("1953-", True),
    ("1910-12", False),  # December 1910, not 1910 to 1912 (language spec §3.3)
    ("1963-11-22", False),
    ("1953-04-01/", False),
])
def test_grammar_shows_a_year_range_separator_only_for_a_range(text, is_year_range):
    assert bool(re.fullmatch(rule("year-range"), text)) is is_year_range
    if not is_year_range:
        assert re.fullmatch(rule("date"), text)
