"""The AxiDraw backend against a stand-in for pyaxidraw's documented interactive API.

This checks the calls axitime makes, in order, not the real hardware: that needs an AxiDraw.
"""

import sys
import types

import pytest

from axitime.config import PlotterConfig
from axitime.plotting import Cancelled, PlotError


class FakeAxiDraw:
    def __init__(self, connects=True, fail_on=None, code=0):
        self.calls = []
        self.options = types.SimpleNamespace()
        self.errors = types.SimpleNamespace(code=0)
        self.plot_status = types.SimpleNamespace(stopped=0)
        self.connects, self.fail_on, self.fail_code = connects, fail_on, code

    def __getattr__(self, name):
        def call(*args):
            self.calls.append((name, *args))
            if name == self.fail_on:
                self.errors.code = self.fail_code
                raise RuntimeError(name)
            return self.connects if name == "connect" else None

        return call


@pytest.fixture
def fake(monkeypatch):
    holder = {}

    def make(**kwargs):
        ad = FakeAxiDraw(**kwargs)
        holder["ad"] = ad
        module = types.ModuleType("pyaxidraw.axidraw")
        module.AxiDraw = lambda: ad
        package = types.ModuleType("pyaxidraw")
        package.axidraw = module
        monkeypatch.setitem(sys.modules, "pyaxidraw", package)
        monkeypatch.setitem(sys.modules, "pyaxidraw.axidraw", module)
        from axitime.axidraw import AxiDrawPlotter

        return AxiDrawPlotter

    return make


def test_a_session_sets_mm_and_the_se_a3_then_connects(fake):
    plotter = fake()(PlotterConfig(pen_pos_down=35))
    plotter.begin()
    ad = plotter.ad
    assert (ad.options.units, ad.options.model, ad.options.pen_pos_down) == (2, 2, 35)
    assert ad.errors.connect and ad.errors.disconnect
    assert not ad.errors.button and not ad.errors.keyboard  # pyaxidraw would disconnect before raising
    assert [c[0] for c in ad.calls] == ["interactive", "connect"]


def test_strokes_are_drawn_as_paths_and_each_strip_ends_home(fake):
    plotter = fake()(PlotterConfig())
    plotter.draw([[(10, 5), (20, 5), (20, 15)]])
    assert plotter.ad.calls == [
        ("moveto", 10, 5), ("draw_path", [[10, 5], [20, 5], [20, 15]]), ("penup",), ("moveto", 0, 0), ("block",),
    ]


def test_a_dry_run_moves_with_the_pen_up(fake):
    plotter = fake()(PlotterConfig(), dry_run=True)
    plotter.draw([[(10, 5), (20, 5)]])
    assert [c[0] for c in plotter.ad.calls] == ["moveto", "moveto", "penup", "moveto", "block"]


def test_finishing_lifts_the_pen_goes_home_and_switches_the_motors_off(fake):
    plotter = fake()(PlotterConfig())
    plotter.finish()
    assert plotter.ad.calls == [("penup",), ("moveto", 0, 0), ("block",), ("usb_command", "EM,0,0\r"), ("disconnect",)]


def test_abort_never_raises_even_when_the_connection_is_gone(fake):
    plotter = fake(fail_on="penup", code=104)(PlotterConfig())
    plotter.abort()
    assert plotter.ad.calls[-1] == ("disconnect",)


def test_the_pause_button_is_a_cancel_and_lost_usb_an_error(fake):
    with pytest.raises(Cancelled, match="pause button"):
        fake(fail_on="draw_path", code=102)(PlotterConfig()).draw([[(1, 1), (2, 2)]])
    with pytest.raises(PlotError, match="lost the USB connection"):
        fake(fail_on="draw_path", code=104)(PlotterConfig()).draw([[(1, 1), (2, 2)]])


def test_no_connection_is_a_clear_error(fake):
    with pytest.raises(PlotError, match="couldn't connect"):
        fake(connects=False)(PlotterConfig()).begin()


def test_a_stop_request_is_honoured_between_strokes(fake):
    plotter = fake()(PlotterConfig())
    asked = iter([None, "stopped by SIGINT"])
    with pytest.raises(Cancelled, match="SIGINT"):
        plotter.draw([[(1, 1), (2, 2)], [(3, 3), (4, 4)]], lambda: next(asked))
    assert [c[0] for c in plotter.ad.calls] == ["moveto", "draw_path"]  # the first stroke, complete; no second


def test_the_pause_button_cancels_and_the_abort_still_goes_home(fake):
    plotter = fake()(PlotterConfig())
    ad = plotter.ad
    original = ad.__getattr__

    def pausing(name):  # the button is pressed during the first stroke
        if name == "draw_path":
            ad.plot_status.stopped = 102
        return original(name)

    ad.__class__ = type("Pausing", (FakeAxiDraw,), {"__getattr__": lambda self, name: pausing(name)})
    with pytest.raises(Cancelled, match="pause button"):
        plotter.draw([[(1, 1), (2, 2)], [(3, 3), (4, 4)]])
    ad.calls.clear()
    assert plotter.abort() is True
    assert ad.plot_status.stopped == 0  # cleared, so the moves home aren't skipped
    assert [c[0] for c in ad.calls] == ["clear_pause_request", "penup", "moveto", "block", "usb_command", "disconnect"]


def test_abort_reports_when_it_couldnt_finish(fake):
    assert fake(fail_on="penup", code=104)(PlotterConfig()).abort() is False
