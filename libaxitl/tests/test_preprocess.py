"""The text pass before the grammar: comments, continuation lines, include flattening (§3.9, §3.10, §5)."""

import pytest

from libaxitl import AxitlError, parse

T = "timeline start=1900 end=2000 length=2m width=210\n"


def flat(source, files=None, make_files=None):
    resolve = make_files(files or {}) if make_files else None
    return parse(source, resolve).flattened_text


def errors(source, resolve=None):
    with pytest.raises(AxitlError) as info:
        parse(source, resolve)
    return [(d.code, d.message) for d in info.value.errors]


# -- comments ---------------------------------------------------------------------------------------------


def test_comments_are_removed_but_not_inside_strings():
    text = flat(T + '// a heading\nevent "Either//Or" 1970   // trailing\n')
    assert text == T + 'event "Either//Or" 1970\n'


def test_escaped_quotes_dont_end_a_string_early():
    text = flat(T + r'event "The \"Glorious\" // Revolution" 1688' + "\n")
    assert r'"The \"Glorious\" // Revolution"' in text


def test_commented_out_include_is_not_followed(make_files):
    resolve = make_files({})
    parse(T + '// include "missing.axitl"\n', resolve)
    assert resolve.requested == []


def test_unterminated_string():
    assert errors(T + 'event "oops 1970\n')[0][0] == "unterminated-string"


# -- multi-line declarations ------------------------------------------------------------------------------


def test_continuation_lines_are_joined_and_comment_lines_skipped():
    source = (
        "timeline\n"
        "    start=1900\n"
        "    // end=1950  (commented out in place)\n"
        "\tend=2000\n"
        "  \t  length=2m width=210   // mixed tabs and spaces\n"
        "\n"
        'event "e" 1950\n'
    )
    assert flat(source) == 'timeline start=1900 end=2000 length=2m width=210\nevent "e" 1950\n'


def test_blank_line_ends_a_declaration():
    source = "timeline start=1900 end=2000 length=2m\n\n    width=210\n"
    assert errors(source)[0][0] == "orphan-parameter"


def test_unindented_parameter_line():
    assert errors("timeline start=1900 end=2000 length=2m\nwidth=210\n")[0][0] == "unindented-parameter"


def test_a_group_childs_indentation_is_not_a_continuation():
    source = T + 'group "G" 1900-1950 {\n    event "e" 1920\n        font_size=6mm\n}\n'
    assert flat(source) == T + 'group "G" 1900-1950 {\nevent "e" 1920 font_size=6mm\n}\n'


def test_crlf_and_bom_are_normalised():
    assert flat("﻿" + T.replace("\n", "\r\n") + 'event "e" 1950\r\n') == T + 'event "e" 1950\n'


def test_cosmetic_edits_do_not_change_the_flattened_text():
    a = flat(T + 'event "e" 1950 red\n')
    b = flat("// header\n" + T + '\n\n   event\t"e"  1950    red   // note\n')
    assert a == b


def test_whitespace_inside_labels_is_kept():
    assert 'event "two  spaces\tand tab" 1950' in flat(T + 'event   "two  spaces\tand tab"   1950\n')


# -- includes ---------------------------------------------------------------------------------------------


def test_include_is_replaced_by_its_content(make_files):
    text = flat(T + 'include "a.axitl"\nevent "after" 1950\n', {"a.axitl": 'event "inside" 1920\n'}, make_files)
    assert text == T + 'event "inside" 1920\nevent "after" 1950\n'


def test_include_paths_are_relative_to_the_including_file(make_files):
    files = {
        "lib/a.axitl": 'include "sub/b.axitl"\n',
        "lib/sub/b.axitl": 'include "../c.axitl"\n',
        "lib/c.axitl": 'event "deep" 1920\n',
    }
    resolve = make_files(files)
    result = parse(T + 'include "lib/a.axitl"\n', resolve)
    assert resolve.requested == ["lib/a.axitl", "lib/sub/b.axitl", "lib/c.axitl"]
    assert [e.location.source for e in result.document.walk()] == ["lib/c.axitl"]


def test_include_modifiers_are_written_into_entity_prefixes(make_files):
    files = {"a.axitl": '!!person "p" 1900-1950\nevent "e" 1920\n-span "s" 1910-1915\n^event "up" 1930\n'}
    text = flat(T + 'include "a.axitl" priority=-1 side=below\n', files, make_files)
    assert text == T + 'v!person "p" 1900-1950\nv-event "e" 1920\nv--span "s" 1910-1915\nv-event "up" 1930\n'


def test_include_modifiers_on_continuation_lines(make_files):
    files = {"a.axitl": 'event "e" 1920\n'}
    text = flat(T + 'include "a.axitl"\n    priority=2\n    side=above\n', files, make_files)
    assert text.splitlines()[1] == '^!!event "e" 1920'


def test_nested_include_offsets_add_and_the_outermost_side_wins(make_files):
    files = {
        "outer.axitl": 'include "inner.axitl" priority=3 side=above\n',
        "inner.axitl": 'event "e" 1920\n',
    }
    text = flat(T + 'include "outer.axitl" priority=-1 side=below\n', files, make_files)
    assert text.splitlines()[1] == 'v!!event "e" 1920'


def test_include_cycle_is_named(make_files):
    files = {"a.axitl": 'include "b.axitl"\n', "b.axitl": 'include "a.axitl"\n'}
    (code, message), = errors(T + 'include "a.axitl"\n', make_files(files))
    assert code == "include-cycle"
    assert "a.axitl → b.axitl → a.axitl" in message


def test_including_a_file_twice_is_not_a_cycle(make_files):
    files = {"a.axitl": 'include "c.axitl"\n', "b.axitl": 'include "c.axitl"\n', "c.axitl": 'event "e" 1920\n'}
    result = parse(T + 'include "a.axitl"\ninclude "b.axitl"\n', make_files(files))
    assert [d.code for d in result.diagnostics] == ["duplicate-entity"]
    assert len(list(result.document.walk())) == 1


def test_include_inside_a_group_body_adds_members(make_files):
    files = {"a.axitl": 'event "e" 1920\n'}
    result = parse(T + 'group "G" 1900-1950 {\n  include "a.axitl"\n}\n', make_files(files))
    (group,) = result.document.entities
    assert [c.label for c in group.children] == ["e"]


@pytest.mark.parametrize(
    "line, code",
    [
        ("include a.axitl", "include-syntax"),
        ('include "a.axitl" priority=high', "bad-value"),
        ('include "a.axitl" side=left', "bad-value"),
        ('include "a.axitl" colour=red', "unknown-parameter"),
        ('include "a.axitl" side=above side=below', "duplicate-parameter"),
        ('include "a.axitl" extra', "include-syntax"),
        ('include "missing.axitl"', "missing-include"),
    ],
)
def test_bad_includes(line, code, make_files):
    assert errors(T + line + "\n", make_files({"a.axitl": ""}))[0][0] == code


def test_an_included_file_cannot_contain_a_timeline(make_files):
    assert errors(T + 'include "a.axitl"\n', make_files({"a.axitl": T}))[0][0] == "timeline-in-include"


def test_include_must_be_utf8(make_files):
    assert errors(T + 'include "a.axitl"\n', make_files({"a.axitl": b"\xff\xfe"}))[0][0] == "include-encoding"


def test_include_without_a_resolver():
    (code, message), = errors(T + 'include "a.axitl"\n')
    assert code == "missing-include" and "no resolver" in message
