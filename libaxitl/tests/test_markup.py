"""Inline formatting (§3.12): CommonMark's emphasis and GitHub's strikethrough in labels, the title, the credits and
notes, drawn in the bold and italic cuts a font's family really has."""

import pytest

from libaxitl import AxitlError, draw, layout, parse, shape
from libaxitl.fonts import font_variant, load_builtin_font
from libaxitl.markup import Span, parse_inline, plain_text

T = "timeline start=1900 end=1999 length=1000 width=210 ticks=off\n"


def marked(text):
    """Spans written compactly: [bis:text] for a styled stretch."""
    out = ""
    for s in parse_inline(text):
        tag = "".join(k for k, v in (("b", s.bold), ("i", s.italic), ("s", s.strike)) if v)
        out += f"[{tag}:{s.text}]" if tag else s.text
    return out


def lay(source):
    return layout(parse(source).document)


def warnings(source):
    return [d.code for d in parse(source).diagnostics]


# -- reading the formatting ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, expected",
    [
        # From the CommonMark spec's emphasis examples.
        ("*foo bar*", "[i:foo bar]"),
        ("a * foo bar*", "a * foo bar*"),
        ('a*"foo"*', 'a*"foo"*'),
        ("foo*bar*", "foo[i:bar]"),
        ("5*6*78", "5[i:6]78"),
        ("_foo bar_", "[i:foo bar]"),
        ("foo_bar_", "foo_bar_"),
        ("5_6_78", "5_6_78"),
        ("пристаням_стремятся_", "пристаням_стремятся_"),
        ("foo-_(bar)_", "foo-[i:(bar)]"),
        ("_foo*", "_foo*"),
        ("*foo bar *", "*foo bar *"),
        ("*(*foo*)*", "[i:(foo)]"),
        ("_foo_bar_baz_", "[i:foo_bar_baz]"),
        ("**foo bar**", "[b:foo bar]"),
        ("** foo bar**", "** foo bar**"),
        ("foo**bar**", "foo[b:bar]"),
        ("__foo bar__", "[b:foo bar]"),
        ("foo__bar__", "foo__bar__"),
        ("**foo*bar*baz**", "[b:foo][bi:bar][b:baz]"),
        ("*foo**bar**baz*", "[i:foo][bi:bar][i:baz]"),
        ("***foo** bar*", "[bi:foo][i: bar]"),
        ("*foo **bar***", "[i:foo ][bi:bar]"),
        ("foo***bar***baz", "foo[bi:bar]baz"),
        ("foo******bar*********baz", "foo[b:bar]***baz"),
        ("**foo*", "*[i:foo]"),
        ("*foo**", "[i:foo]*"),
        ("*foo *bar**", "[i:foo bar]"),
        # Escapes, strikethrough, and text an author might write without meaning formatting.
        ("\\*not emphasised*", "*not emphasised*"),
        ("a \\_b\\_ \\\\ c\\d", "a _b_ \\ c\\d"),
        ("~~struck~~ and ~one~", "[s:struck] and ~one~"),
        ("**bold ~~both~~**", "[b:bold ][bs:both]"),
        ("snake_case_name", "snake_case_name"),
        ("2 * 3 * 4", "2 * 3 * 4"),
        ("", ""),
    ],
)
def test_commonmark_emphasis(text, expected):
    assert marked(text) == expected


def test_plain_text():
    assert plain_text("**Ada** *Lovelace* ~~Byron~~ \\*") == "Ada Lovelace Byron *"


# -- the cuts a family has --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "font, bold, italic, expected",
    [
        ("HersheySerifMed", True, False, ("HersheySerifBold", True, False)),
        ("HersheySerifMed", False, True, ("HersheySerifMedItalic", False, True)),
        ("HersheySerifMed", True, True, ("HersheySerifBoldItalic", True, True)),
        ("HersheySerifBold", False, True, ("HersheySerifBoldItalic", True, True)),
        ("HersheySerifBold", True, False, ("HersheySerifBold", True, False)),
        ("HersheySans1", True, False, ("HersheySansMed", True, False)),
        ("HersheySans1", False, True, ("HersheySans1", False, False)),  # no italic: upright
        ("HersheySans1", True, True, ("HersheySansMed", True, False)),
        ("HersheyScript1", True, False, ("HersheyScriptMed", True, False)),
        ("EMSNixish", True, True, ("EMSNixishItalic", False, True)),  # no bold: normal weight
        ("EMSReadability", False, True, ("EMSReadabilityItalic", False, True)),
        ("HersheyGothEnglish", True, True, ("HersheyGothEnglish", False, False)),
    ],
)
def test_font_variants(font, bold, italic, expected):
    cut, b, i = font_variant(load_builtin_font(font), bold, italic)
    assert (cut.name, b, i) == expected


# -- shaping ------------------------------------------------------------------------------------------------------


def test_bold_is_drawn_in_the_bold_cut_and_measured_in_it():
    serif = load_builtin_font("HersheySerifMed")
    plain = shape(serif, "Ada Lovelace", 5.0, markup=True)
    bold = shape(serif, "Ada **Lovelace**", 5.0, markup=True)
    assert plain.text == bold.text == "Ada Lovelace"
    assert [f.name for f in bold.char_fonts()] == ["HersheySerifMed"] * 4 + ["HersheySerifBold"] * 8
    expected = shape(serif, "Ada ", 5.0).width + shape(load_builtin_font("HersheySerifBold"), "Lovelace", 5.0).width
    assert bold.width == pytest.approx(expected)
    # Without markup, the asterisks are just text.
    assert shape(serif, "Ada **Lovelace**", 5.0).text == "Ada **Lovelace**"


def test_a_strikethrough_is_one_stroke_across_its_text_at_half_the_x_height():
    sans = load_builtin_font("HersheySans1")
    shaped = shape(sans, "a ~~struck **through**~~ b", 4.0, markup=True)
    assert len(shaped.strikes) == 1
    x0, x1, y = shaped.strikes[0]
    s = shaped.scale
    assert x0 * s == pytest.approx(shape(sans, "a ", 4.0).width)
    assert x1 * s == pytest.approx(shaped.width - shape(sans, " b", 4.0).width)
    assert y == pytest.approx(sans.x_height / 2)
    segments = shaped.segments(10.0, 20.0)
    assert segments[-2:] == (("M", 10.0 + x0 * s, 20.0 - y * s), ("L", 10.0 + x1 * s, 20.0 - y * s))
    assert len(shaped.segments(10.0, 20.0, strikes=False)) == len(segments) - 2


# -- where it applies ------------------------------------------------------------------------------------------


def test_labels_title_credits_and_notes_are_formatted():
    source = (
        "timeline start=1900 end=1999 length=1000 width=210 ticks=off font=HersheySerifMed\n"
        'title "A **Century**" subtitle="*Lives* and ~~wars~~"\n'
        'credits {\n  heading "**Design**"\n  "By *me*"\n}\n'
        'note "Some **bold** words"\n'
        'person "**Ada** Lovelace" 1915-1952\n'
        'event "*Sputnik*" 1957\n'
    )
    L = lay(source)
    cuts = lambda t: {f.name for f in t.shaped.char_fonts()}  # noqa: E731
    assert cuts(L.title.texts[0]) == {"HersheySerifMed", "HersheySerifBold"}
    assert (L.title.texts[0].text, L.title.texts[0].shaped.text) == ("A **Century**", "A Century")
    assert L.title.texts[1].shaped.strikes
    assert "HersheySerifBold" in cuts(L.credits.texts[0])
    assert "HersheySerifMedItalic" in cuts(L.credits.texts[1])
    assert "HersheySerifBold" in cuts(L.notes[0].texts[0])
    assert "HersheySerifBold" in cuts(L.bars[0].label)
    assert cuts(L.events[0].flag) == {"HersheySerifMedItalic"}
    assert L.bars[0].label.shaped.text == "Ada Lovelace"


def test_time_labels_and_graphs_are_not_formatted():
    L = lay(T + 'event "E" 1957-10-04 time_label=day\ngraph "a_b_c *d*" {\n  1900 1\n  1950 2\n}\n')
    assert L.events[0].time_label.shaped.fonts == ()
    assert "a_b_c *d*" in [t.shaped.text for t in L.graphs[0].texts]


def test_formatting_across_a_notes_lines_carries_on():
    words = " ".join(["word"] * 40)
    L = lay(T + f'note width=60 {{\n  "plain **{words}** ~~{words}~~"\n}}\n')
    lines = L.notes[0].texts
    assert len(lines) > 3
    bold_lines = [t for t in lines if t.shaped.fonts]
    assert len(bold_lines) >= 2  # the bold runs over more than one line, each line drawn bold
    struck = [t for t in lines if t.shaped.strikes]
    assert len(struck) >= 2
    for t in lines:
        assert "*" not in t.text and "~" not in t.text
        assert t.shaped.width <= 60 + 1e-9


def test_a_style_the_font_lacks_is_a_warning_and_drawn_plain():
    assert warnings(T + 'event "*Sputnik*" 1957\n') == ["missing-style"]
    message = parse(T + 'event "*Sputnik*" 1957\n').diagnostics[0].message
    assert "HersheySans1 has no italic" in message and "upright" in message
    assert warnings(T + 'event "**Sputnik**" 1957\n') == []
    assert warnings(T + 'event "**Sputnik**" 1957 font=EMSNixish\n') == ["missing-style"]
    assert lay(T + 'event "*Sputnik*" 1957\n').events[0].flag.shaped.fonts == ()


def test_formatting_doesnt_make_another_entity():
    files = {"people.axitl": 'person "Ada" 1915-1952\n'}
    result = parse(T + 'include "people.axitl"\nperson "**Ada**" 1915-1952 blue\n', files.__getitem__)
    assert [e.label for e in result.document.entities] == ["**Ada**"]
    assert "duplicate-entity" in [d.code for d in result.diagnostics]


def test_an_escaped_delimiter_in_the_source_is_drawn():
    L = lay(T + 'event "\\*six\\*" 1957\n')
    assert L.events[0].flag.shaped.text == "*six*"


def test_a_strikethrough_is_drawn_in_the_labels_pen():
    L = lay(T + 'event "~~Cancelled~~" 1957 blue\n')
    flag = L.events[0].flag
    x0, x1, y = flag.shaped.strikes[0]
    s = flag.shaped.scale
    line = [(flag.x + x0 * s, flag.y - y * s), (flag.x + x1 * s, flag.y - y * s)]
    strokes = [st for st in draw(L).strokes if st.pen == "blue"]
    assert any(list(st.points) == line for st in strokes)
