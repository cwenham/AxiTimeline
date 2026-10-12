import json
from pathlib import Path

import pytest

from axitime.cli import EXIT_ERRORS, EXIT_OK, EXIT_USAGE, main

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


def test_check_passes_on_the_examples(capsys):
    assert main(["check", str(EXAMPLES / "industrial.axitl")]) == EXIT_OK
    out = capsys.readouterr().out
    assert "check passed with 0 errors and 0 warnings" in out
    assert "3 people, 2 events, 3 spans, 2 groups" in out
    assert "lanes:    3 of 15 above, 2 of 8 below" in out
    assert "now:      " in out  # the example ends at now, so check says which value it used


def test_check_json_report(capsys):
    assert main(["check", "--json", str(EXAMPLES / "industrial.axitl")]) == EXIT_OK
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is True and report["stages"] == ["parse", "layout"]
    assert report["summary"]["entities"] == {"person": 3, "event": 2, "span": 3, "group": 2}
    assert report["summary"]["pens"]["HB-pencil"] == 1
    kinds = {(r["kind"], Path(r["name"]).name) for r in report["summary"]["resources"]}
    assert kinds == {("include", "wars.axitl"), ("illustration", "apple.svg")}


def test_includes_resolve_relative_to_the_source_file(tmp_path, monkeypatch, capsys):
    (tmp_path / "lib").mkdir()
    (tmp_path / "lib" / "a.axitl").write_text('event "from lib" 1950\n')
    (tmp_path / "main.axitl").write_text('timeline start=1900 end=2000 length=2m width=210\ninclude "lib/a.axitl"\n')
    monkeypatch.chdir(tmp_path.parent)
    assert main(["check", f"{tmp_path.name}/main.axitl"]) == EXIT_OK


def test_check_reports_errors_with_locations(tmp_path, capsys):
    source = tmp_path / "bad.axitl"
    source.write_text('timeline start=1900 end=2000 length=2m width=210\nspan "X" 1910-12\nevent "e" 1920 gray\n')
    assert main(["check", str(source)]) == EXIT_ERRORS
    out = capsys.readouterr().out
    assert f"{source}:2: error:" in out and "[needs-range]" in out
    assert f"{source}:3: error:" in out and "did you mean grey?" in out
    assert "check failed with 2 errors" in out


def test_check_json_on_errors(tmp_path, capsys):
    source = tmp_path / "bad.axitl"
    source.write_text('timeline start=1900 end=2000 length=2m\n')
    assert main(["check", "--json", str(source)]) == EXIT_ERRORS
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is False and report["summary"] is None
    assert report["diagnostics"][0] == {
        "severity": "error",
        "code": "missing-parameter",
        "message": "timeline needs width= (the finished width across the roll, e.g. width=210)",
        "source": str(source),
        "line": 1,
    }


def test_missing_source_file(tmp_path, capsys):
    assert main(["check", str(tmp_path / "nope.axitl")]) == EXIT_USAGE
    assert "can't read" in capsys.readouterr().err


def test_missing_include_is_a_check_error(tmp_path, capsys):
    source = tmp_path / "main.axitl"
    source.write_text('timeline start=1900 end=2000 length=2m width=210\ninclude "gone.axitl"\n')
    assert main(["check", str(source)]) == EXIT_ERRORS
    out = capsys.readouterr().out
    assert f"can't read include '{tmp_path}/gone.axitl': no such file" in out


def test_version(capsys):
    with pytest.raises(SystemExit):
        main(["--version"])
    assert "libaxitl" in capsys.readouterr().out


def test_now_can_be_pinned(capsys):
    assert main(["check", "--json", "--now", "2026-10-12", str(EXAMPLES / "industrial.axitl")]) == EXIT_OK
    report = json.loads(capsys.readouterr().out)
    assert report["layout"]["now"] == "2026" and report["notes"] == []


def test_now_without_a_now_timeline_says_it_has_no_effect(capsys):
    assert main(["check", "--now", "2026", str(EXAMPLES / "chernobyl.axitl")]) == EXIT_OK
    assert "--now has no effect" in capsys.readouterr().out


def test_bad_now(tmp_path, capsys):
    assert main(["check", "--now", "next tuesday", str(EXAMPLES / "industrial.axitl")]) == EXIT_USAGE
    assert "--now" in capsys.readouterr().err
    source = tmp_path / "day.axitl"
    source.write_text("timeline start=1900-01-01 end=now length=2m width=210\n")
    assert main(["check", "--now", "2026", str(source)]) == EXIT_ERRORS
    assert "[now-too-coarse]" in capsys.readouterr().out


def test_layout_errors_come_with_the_parse_warnings(tmp_path, capsys):
    (tmp_path / "a.axitl").write_text('span "s" 1900-1950\n')
    source = tmp_path / "main.axitl"
    source.write_text(
        'timeline start=1900 end=1999 length=1m width=20 ticks=off\ninclude "a.axitl"\nspan "s" 1900-1950\n'
    )
    assert main(["check", "--json", str(source)]) == EXIT_ERRORS
    report = json.loads(capsys.readouterr().out)
    assert [d["code"] for d in report["diagnostics"]] == ["duplicate-entity", "no-room"]
    assert report["layout"] is None
