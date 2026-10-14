"""axitime plot: reading per-pen SVGs, the job log, windows, strips, confirmation and safe abort.

The AxiDraw is replaced by a simulated plotter and the operator by scripted answers.
"""

import sys
import time
import types

import pytest

from axitime import cli, plotting
from axitime.config import ConfigError, PlotterConfig, load_config
from axitime.joblog import Match, find_job, read_header, runs
from axitime.plotfile import PlotFileError, load_plot_file
from axitime.plotting import PlotError, SimulatedPlotter, Strip, Window, plan_strips, to_machine, window_for

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


PAGE = types.SimpleNamespace(page=(0.0, -10.0, 1000.0, 160.0))  # x, y, width, height of a per-pen SVG's page


def turn(a, b, c):
    """Which way a, b, c turn: the sign flips if a drawing is mirrored, and not if it's rotated."""
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


@pytest.mark.parametrize("feed", ["towards-front", "towards-back"])
def test_strips_are_turned_onto_the_y_axis_never_mirrored(feed):
    config = PlotterConfig(feed=feed)
    letter = ((0.0, -10.0), (10.0, -10.0), (0.0, 0.0))  # along the roll, then across it
    (placed,) = to_machine(Strip(0, 0.0, 250.0, (letter,)), PAGE, config)
    assert placed[1][0] == placed[0][0]  # a line along the roll runs along the machine's Y axis
    assert turn(*placed) > 0 and turn(*letter) > 0
    assert all(10 <= y <= 260 and 5 <= x <= 165 for x, y in placed)


def test_towards_the_front_the_page_top_edge_is_nearer_home_and_time_runs_back():
    (placed,) = to_machine(Strip(0, 0.0, 250.0, (((0.0, -10.0), (250.0, -10.0)),)), PAGE, PlotterConfig())
    assert placed == [(5.0, 260.0), (5.0, 10.0)]


def test_towards_the_back_the_page_bottom_edge_is_nearer_home_and_time_runs_forward():
    config = PlotterConfig(feed="towards-back")
    (placed,) = to_machine(Strip(0, 0.0, 250.0, (((0.0, 150.0), (250.0, 150.0)),)), PAGE, config)
    assert placed == [(5.0, 10.0), (5.0, 260.0)]


@pytest.mark.parametrize("feed, moves", [("towards-front", +250.0), ("towards-back", -250.0)])
def test_moving_the_paper_on_carries_ink_onto_the_next_strip(feed, moves):
    # strokes cut at a strip edge only meet again if the next strip draws exactly where the paper has carried them
    config = PlotterConfig(feed=feed)
    point = (((240.0, 50.0), (260.0, 50.0)),)
    (here,) = to_machine(Strip(0, 0.0, 250.0, point), PAGE, config)
    (there,) = to_machine(Strip(1, 250.0, 500.0, point), PAGE, config)
    assert [(x, y + moves) for x, y in here] == there


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
    assert operator.plotter.events == ["begin", "draw", "draw", "draw", "finish"]  # the third is empty for red


def test_the_paper_moves_on_past_empty_strips_in_one_go(job, operator):
    operator.answers = ["red", "", ""]
    plot(job)
    moves = [p for p in operator.prompts if p.startswith("Move the paper")]
    assert len(moves) == 2 and "by exactly 250mm, towards the front," in moves[0]
    assert "by exactly 500mm" in moves[1]  # strips 3 and 4 at once: red has nothing in 50–75cm


def test_later_runs_append_to_the_same_log(job, operator):
    operator.answers = ["red", "", "", "red", "", ""]
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
    assert "strip 1: 0.0–25.0cm" in capsys.readouterr().out


# -- safe abort -----------------------------------------------------------------------------------------


class FailingPlotter(SimulatedPlotter):
    def __init__(self, error):
        super().__init__()
        self.error = error

    def draw(self, strokes, should_stop=lambda: None):
        if len(self.strips) == 1:  # fail on the second strip drawn
            raise self.error
        super().draw(strokes, should_stop)


@pytest.mark.parametrize("error, status", [(KeyboardInterrupt(), "cancelled"), (RuntimeError("serial port gone"), "errored")])
def test_a_failure_makes_the_hardware_safe_and_is_logged(job, operator, error, status):
    operator.plotter = FailingPlotter(error)
    operator.answers = ["red", ""]
    assert plot(job) == 1
    assert operator.plotter.events == ["begin", "draw", "abort"]
    (log,) = job.glob("t-*.log")
    end = runs(log)[-1]
    assert f" end {status} strip=2 x=250-500mm" in end
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
    path.write_text(
        '[plotter]\nstrip_mm = 280\norigin_across_mm = 8\nfeed = "towards-back"\n[transport]\nkind = "manual"\n'
    )
    config = load_config(path)
    assert (config.strip_mm, config.origin_across_mm, config.feed, config.travel_along_mm) == (
        280.0, 8.0, "towards-back", 297.0,
    )


@pytest.mark.parametrize(
    "text, message",
    [
        ("[plotter]\nstrip = 3\n", "no setting 'strip'"),
        ("[plotter]\nstrip_mm = 290\n", "doesn't fit"),
        ("[plotter]\norigin_y_mm = 5\n", "no setting 'origin_y_mm'"),
        ('[plotter]\nfeed = "sideways"\n', "feed must be towards-front or towards-back"),
        ("[plotter]\nfeed = 1\n", "must be a word in quotes"),
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
    monkeypatch.setitem(sys.modules, "pyaxidraw", None)  # as if it weren't installed
    monkeypatch.setattr(cli, "ask", lambda prompt: "red")
    assert plot(job) == 2
    assert "uv sync --extra axidraw" in capsys.readouterr().err


# -- signals: a closed terminal or a kill stops the run the safe way ---------------------------------------

import os  # noqa: E402
import signal  # noqa: E402


class SignalledPlotter(SimulatedPlotter):
    """Gets a signal while drawing its first strip, as if the SSH session dropped or someone ran kill."""

    def __init__(self, signum):
        super().__init__()
        self.signum = signum

    def draw(self, strokes, should_stop=lambda: None):
        os.kill(os.getpid(), self.signum)  # the stroke in progress finishes; the stop comes before the next
        super().draw(strokes, should_stop)


@pytest.mark.parametrize("signum", [signal.SIGHUP, signal.SIGTERM], ids=["SIGHUP", "SIGTERM"])
def test_a_hang_up_or_kill_mid_plot_is_a_safe_cancel(job, operator, signum):
    before = signal.getsignal(signum)
    operator.plotter = SignalledPlotter(signum)
    operator.answers = ["red"]
    assert plot(job) == 1
    assert operator.plotter.events == ["begin", "abort"]
    (log,) = job.glob("t-*.log")
    assert f'end cancelled strip=1 x=0-250mm message="stopped by {signal.Signals(signum).name}"' in runs(log)[-1]
    assert signal.getsignal(signum) is before  # plot puts the old handler back


class InterruptedAbortPlotter(SimulatedPlotter):
    """Is interrupted while drawing, and again (Ctrl+C) in the middle of its own safe abort."""

    def draw(self, strokes, should_stop=lambda: None):
        raise KeyboardInterrupt

    def abort(self):
        self.events.append("abort")
        os.kill(os.getpid(), signal.SIGINT)  # a second Ctrl+C, impatient
        self.events.append("abort finished")
        return True


def test_a_second_interrupt_cant_cut_the_safe_abort_short(job, operator):
    operator.plotter = InterruptedAbortPlotter()
    operator.answers = ["red"]
    assert plot(job) == 1
    assert operator.plotter.events[-2:] == ["abort", "abort finished"]
    assert signal.getsignal(signal.SIGINT) is signal.default_int_handler


def test_a_hang_up_at_the_pen_prompt_plots_nothing(job, operator, monkeypatch):
    def ask(prompt):
        os.kill(os.getpid(), signal.SIGHUP)
        return "red"

    monkeypatch.setattr(cli, "ask", ask)
    assert plot(job) == 1
    assert operator.plotter.events == [] and not list(job.glob("*.log"))


class StrokeCountingPlotter(SimulatedPlotter):
    """Draws stroke by stroke, the way the AxiDraw backend does, getting a Ctrl+C during its first stroke."""

    def __init__(self, presses=1):
        super().__init__()
        self.drawn = 0
        self.presses = presses

    def draw(self, strokes, should_stop=lambda: None):
        for _ in strokes:
            if should_stop():
                raise plotting.Cancelled(should_stop())
            if self.drawn == 0:
                for _ in range(self.presses):
                    os.kill(os.getpid(), signal.SIGINT)
            self.drawn += 1


def test_ctrl_c_stops_between_strokes_not_in_the_middle_of_one(job, operator):
    operator.plotter = StrokeCountingPlotter()
    operator.answers = ["red"]
    assert plot(job) == 1
    assert operator.plotter.drawn == 1  # the stroke under way was finished; nothing after it was started
    (log,) = job.glob("t-*.log")
    assert 'message="stopped by SIGINT"' in runs(log)[-1] and "safe-stop" not in runs(log)[-1]


def test_a_second_ctrl_c_stops_at_once(job, operator):
    operator.plotter = StrokeCountingPlotter(presses=2)
    operator.answers = ["red"]
    assert plot(job) == 1
    (log,) = job.glob("t-*.log")
    assert 'message="stopped at once by a second Ctrl+C"' in runs(log)[-1]
    assert operator.plotter.events[-1] == "abort"


class StuckAbortPlotter(SimulatedPlotter):
    def draw(self, strokes, should_stop=lambda: None):
        raise RuntimeError("serial port gone")

    def abort(self):
        self.events.append("abort")
        time.sleep(5)  # hangs, as the real one did
        return True


def test_an_abort_that_hangs_is_given_up_and_reported_honestly(job, operator, monkeypatch, capsys):
    monkeypatch.setattr(plotting, "ABORT_SECONDS", 1)
    operator.plotter = StuckAbortPlotter()
    operator.answers = ["red"]
    started = time.monotonic()
    assert plot(job) == 1
    assert time.monotonic() - started < 4
    (log,) = job.glob("t-*.log")
    assert runs(log)[-1].endswith(" safe-stop=incomplete")
    assert "switch the AxiDraw off before touching it" in capsys.readouterr().out
