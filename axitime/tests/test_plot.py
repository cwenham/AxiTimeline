"""axitime plot: reading per-pen SVGs, the job log, windows, strips, confirmation and safe abort.

The AxiDraw is replaced by a simulated plotter and the operator by scripted answers.
"""

import pytest

from axitime import cli
from axitime.config import ConfigError, PlotterConfig, load_config
from axitime.joblog import Match, find_job, read_header, runs
from axitime.plotfile import PlotFileError, load_plot_file
from axitime.plotting import PlotError, SimulatedPlotter, Window, plan_strips, window_for

SOURCE = """timeline start=1900 end=1999 length=1m width=150 ticks=off
^span "Early" 1900-1930 red
^span "Late" 1985-1999 red
vevent "Middle" 1950 black
"""


@pytest.fixture
def job(tmp_path):
    (tmp_path / "t.axitl").write_text(SOURCE)
    assert cli.main(["render", "-o", str(tmp_path), str(tmp_path / "t.axitl")]) == 0
    return tmp_path


@pytest.fixture
def operator(monkeypatch):
    """Scripted answers to prompts, and a simulated plotter."""

    class Operator:
        def __init__(self):
            self.answers = []
            self.prompts = []
            self.plotter = SimulatedPlotter()

        def ask(self, prompt):
            self.prompts.append(prompt)
            return self.answers.pop(0) if self.answers else ""

    op = Operator()
    monkeypatch.setattr(cli, "ask", op.ask)
    monkeypatch.setattr(cli, "make_plotter", lambda config, dry_run: op.plotter)
    return op


def plot(job, *extra):
    return cli.main(["plot", str(job / "t-red.svg"), *extra])


# -- reading the file -----------------------------------------------------------------------------------


def test_a_per_pen_file_reads_back(job):
    f = load_plot_file(job / "t-red.svg")
    assert (f.pen, f.source, f.stem, f.job_length_mm, f.window) == ("red", "t.axitl", "t", 1000.0, (0.0, 1000.0))
    assert len(f.job_hash) == 64 and f.strokes
    assert f.page == (0.0, -2.5, 1000.0, 155.0)


def test_only_per_pen_files_can_be_plotted(job, tmp_path):
    with pytest.raises(PlotFileError, match="preview of every pen"):
        load_plot_file(job / "t-preview.svg")
    other = tmp_path / "other.svg"
    other.write_text('<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0 L1 1"/></svg>')
    with pytest.raises(PlotFileError, match="wasn't written by axitime render"):
        load_plot_file(other)


# -- windows and strips ---------------------------------------------------------------------------------


def test_the_window_bleeds_only_at_cuts_in_the_middle_of_the_job(job):
    f = load_plot_file(job / "t-red.svg")
    assert window_for(f, None, None, 2) == Window(0, 1000, 0, 0)
    assert window_for(f, 300, 200, 2) == Window(300, 500, 2, 2)
    assert window_for(f, 900, 500, 2) == Window(900, 1000, 2, 0)  # runs to the job's end: no bleed there
    with pytest.raises(PlotError, match="outside this file"):
        window_for(f, 1000, None, 2)


def test_strips_cut_strokes_at_their_edges():
    stroke = ((100.0, 5.0), (700.0, 5.0))
    strips = plan_strips([stroke], Window(0, 1000, 0, 0), 400)
    assert [(s.x0, s.x1) for s in strips] == [(0, 400), (400, 800), (800, 1000)]
    assert [s.strokes for s in strips] == [(((100.0, 5.0), (400.0, 5.0)),), (((400.0, 5.0), (700.0, 5.0)),), ()]


# -- the job log ----------------------------------------------------------------------------------------


def test_a_first_pass_starts_a_new_job_log(job, operator):
    operator.answers = ["red", ""]  # confirm the pen, then press Enter to move the paper on
    assert plot(job) == 0
    lookup = find_job(load_plot_file(job / "t-red.svg"), job)
    assert lookup.match is Match.EXISTING
    header = read_header(lookup.path)
    assert header["source"] == "t.axitl" and header["job-hash"] == load_plot_file(job / "t-red.svg").job_hash
    lines = runs(lookup.path)
    assert len(lines) == 2 and " start pen=red file=t-red.svg window=0-1000mm" in lines[0]
    assert lines[1].endswith(" end completed")
    assert operator.plotter.events == ["begin", "draw", "draw", "finish"]  # the middle strip is empty for red


def test_the_paper_moves_on_past_empty_strips_in_one_go(job, operator):
    operator.answers = ["red", ""]
    plot(job)
    (move,) = [p for p in operator.prompts if p.startswith("Move the paper")]
    assert "by exactly 800mm" in move  # strips 2 and 3 at once: red has nothing in 40–80cm


def test_later_runs_append_to_the_same_log(job, operator):
    operator.answers = ["red", "", "red", ""]
    plot(job)
    plot(job, "--start-offset", "50cm")
    (log,) = job.glob("t-*.log")
    lines = runs(log)
    assert len(lines) == 4 and "window=500-1000mm bleed=2/0mm" in lines[2]


def test_the_wrong_pen_name_stops_before_anything_moves(job, operator):
    operator.answers = ["black"]
    assert plot(job) == 1
    assert operator.plotter.events == [] and not list(job.glob("*.log"))


def test_force_goes_ahead_with_a_different_pen_and_says_so(job, operator):
    operator.answers = ["blue", ""]
    assert plot(job, "--force") == 0
    (log,) = job.glob("t-*.log")
    assert "forced=\"the operator typed 'blue' for the red pen\"" in runs(log)[0]


def test_an_empty_answer_always_stops_even_with_force(job, operator):
    operator.answers = [""]
    assert plot(job, "--force") == 1


def test_a_different_version_of_the_same_source_is_refused(job, operator, capsys):
    operator.answers = ["red", ""]
    plot(job)
    (job / "t.axitl").write_text(SOURCE.replace("1985-1999", "1986-1999"))
    cli.main(["render", "-o", str(job), str(job / "t.axitl")])
    assert plot(job) == 2
    assert "no existing job matches this file" in capsys.readouterr().err
    operator.answers = ["red", ""]
    assert plot(job, "--force") == 0
    logs = sorted(job.glob("t-*.log"))
    assert len(logs) == 2  # the forced run starts its own job log, recording the override
    assert any("no existing job matched" in line for log in logs for line in runs(log))


def test_simulate_plots_nothing_and_logs_nothing(job, operator, capsys):
    assert plot(job, "--simulate") == 0
    assert operator.plotter.events == [] and not list(job.glob("*.log"))
    assert "strip 1: 0.0–40.0cm" in capsys.readouterr().out


# -- safe abort -----------------------------------------------------------------------------------------


class FailingPlotter(SimulatedPlotter):
    def __init__(self, error):
        super().__init__()
        self.error = error

    def draw(self, strokes):
        if len(self.strips) == 1:  # fail on the second strip drawn
            raise self.error
        super().draw(strokes)


@pytest.mark.parametrize("error, status", [(KeyboardInterrupt(), "cancelled"), (RuntimeError("serial port gone"), "errored")])
def test_a_failure_makes_the_hardware_safe_and_is_logged(job, operator, error, status):
    operator.plotter = FailingPlotter(error)
    operator.answers = ["red", ""]
    assert plot(job) == 1
    assert operator.plotter.events == ["begin", "draw", "abort"]
    (log,) = job.glob("t-*.log")
    end = runs(log)[-1]
    assert f" end {status} strip=3 x=800-1000mm" in end
    if status == "errored":
        assert 'message="serial port gone"' in end


def test_ctrl_c_while_moving_the_paper_is_a_cancel_too(job, operator, monkeypatch):
    operator.answers = ["red"]

    def ask(prompt):
        if prompt.startswith("Move the paper"):
            raise KeyboardInterrupt
        return operator.answers.pop(0)

    monkeypatch.setattr(cli, "ask", ask)
    assert plot(job) == 1
    assert operator.plotter.events[-1] == "abort"


# -- the plotter's settings -----------------------------------------------------------------------------


def test_config_overrides_defaults(tmp_path):
    path = tmp_path / "plotter.toml"
    path.write_text("[plotter]\nstrip_mm = 300\norigin_y_mm = 8\n[transport]\nkind = \"manual\"\n")
    config = load_config(path)
    assert (config.strip_mm, config.origin_y_mm, config.travel_along_mm) == (300.0, 8.0, 430.0)


@pytest.mark.parametrize(
    "text, message",
    [
        ("[plotter]\nstrip = 3\n", "no setting 'strip'"),
        ("[plotter]\nstrip_mm = 425\n", "doesn't fit"),
        ('[transport]\nkind = "serial"\n', "isn't supported yet"),
        ("[plotter\n", "can't read"),
    ],
)
def test_bad_config(tmp_path, text, message):
    path = tmp_path / "plotter.toml"
    path.write_text(text)
    with pytest.raises(ConfigError, match=message):
        load_config(path)


def test_a_page_wider_than_the_plotter_reaches(job, tmp_path, capsys):
    narrow = tmp_path / "narrow.toml"
    narrow.write_text("[plotter]\ntravel_across_mm = 150\n")
    assert cli.main(["check", "--config", str(narrow), str(job / "t.axitl")]) == 1
    assert "[too-wide]" in capsys.readouterr().out
    assert cli.main(["plot", "--config", str(narrow), str(job / "t-red.svg")]) == 2
    assert PlotterConfig().fits_across(155.0)


def test_without_pyaxidraw_plot_says_how_to_install_it(job, monkeypatch, capsys):
    monkeypatch.setattr(cli, "ask", lambda prompt: "red")
    assert plot(job) == 2
    assert "pip install https://cdn.evilmadscientist.com" in capsys.readouterr().err
