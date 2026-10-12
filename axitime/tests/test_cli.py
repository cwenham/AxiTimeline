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
    assert report["ok"] is True and report["stages"] == ["parse", "layout", "draw"]
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


# -- list-pens and render ---------------------------------------------------------------------------------

import xml.etree.ElementTree as ET  # noqa: E402

JOB = "{urn:axitimeline:job:1}job"


def test_list_pens(capsys):
    assert main(["list-pens", "--now", "2026", str(EXAMPLES / "industrial.axitl")]) == EXIT_OK
    lines = capsys.readouterr().out.splitlines()
    assert [line.split()[0] for line in lines] == [
        "black", "red", "orange", "green", "violet", "grey", "HB-pencil", "2H-pencil", "total",
    ]
    assert lines[0].split()[1].endswith("m") and "strokes" in lines[0]


def test_list_pens_json(capsys):
    assert main(["list-pens", "--json", str(EXAMPLES / "chernobyl.axitl")]) == EXIT_OK
    report = json.loads(capsys.readouterr().out)
    assert [p["pen"] for p in report["pens"]] == ["black", "2H-pencil"]
    assert all(p["length_mm"] > 0 and p["strokes"] > 0 for p in report["pens"])


def test_render_writes_a_preview_and_one_file_per_pen(tmp_path, capsys):
    assert main(["render", "--now", "2026", "-o", str(tmp_path), str(EXAMPLES / "industrial.axitl")]) == EXIT_OK
    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == sorted(
        f"industrial-{n}.svg"
        for n in ("preview", "black", "red", "orange", "green", "violet", "grey", "HB-pencil", "2H-pencil")
    )
    red = ET.parse(tmp_path / "industrial-red.svg").getroot()
    job = red.find("{http://www.w3.org/2000/svg}metadata/" + JOB)
    assert (job.get("pen"), job.get("source"), job.get("now")) == ("red", "industrial.axitl", "2026")
    assert red.get("viewBox") == ET.parse(tmp_path / "industrial-preview.svg").getroot().get("viewBox")
    assert "rendered the whole job, 4m" in capsys.readouterr().out


def test_render_a_physical_window(tmp_path, capsys):
    args = ["render", "--preview-only", "-o", str(tmp_path), "--start-offset", "137cm", "--length", "20cm"]
    assert main(args + [str(EXAMPLES / "chernobyl.axitl")]) == EXIT_OK
    root = ET.parse(tmp_path / "chernobyl-preview.svg").getroot()
    assert root.get("viewBox") == "1368 -2.5 204 215"  # 2mm bleed at both cuts
    assert "rendered 1.37m to 1.57m of 2m" in capsys.readouterr().out


def test_render_a_calendar_window(tmp_path, capsys):
    args = ["render", "--preview-only", "-o", str(tmp_path), "--from", "1986-04-26T01", "--to", "1986-04-26T01"]
    assert main(args + ["--bleed", "0", str(EXAMPLES / "chernobyl.axitl")]) == EXIT_OK
    job = ET.parse(tmp_path / "chernobyl-preview.svg").getroot().find("{http://www.w3.org/2000/svg}metadata/" + JOB)
    start, end = float(job.get("window-start-mm")), float(job.get("window-end-mm"))
    assert end - start == pytest.approx(125.0, abs=0.01)  # one hour at 125mm an hour


@pytest.mark.parametrize(
    "extra, message",
    [
        (["--start-offset", "10cm", "--from", "1986-04-26"], "not both"),
        (["--from", "1990", "--to", "1991"], "don't overlap"),
        (["--bleed", "two"], "--bleed"),
        (["--start-offset", "3m"], "outside the job"),
    ],
)
def test_render_usage_errors(tmp_path, capsys, extra, message):
    assert main(["render", "-o", str(tmp_path), *extra, str(EXAMPLES / "chernobyl.axitl")]) == EXIT_USAGE
    assert message in capsys.readouterr().err
