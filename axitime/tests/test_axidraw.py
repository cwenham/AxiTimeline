"""The AxiDraw backend against a stand-in for pyaxidraw's documented interactive API.

This checks the calls axitime makes, in order, not the real hardware: that needs an AxiDraw.
"""

import logging
import sys
import types

import pytest

from axitime.config import PlotterConfig
from axitime.plotting import Cancelled, PlotError


class FakeAxiDraw:
    def __init__(self, connects=True, fail_on=None, code=0, held=0, busy=0):
        self.calls = []
        self.options = types.SimpleNamespace()
        self.errors = types.SimpleNamespace(code=0)
        self.plot_status = types.SimpleNamespace(stopped=0)
        self.connects, self.fail_on, self.fail_code = connects, fail_on, code
        self.held = held  # how many more "QB" queries report the pause button pressed
        self.busy = busy  # how many more "QG" queries report motion still queued
        self.position = (0.0, 0.0)
        self.hooks = {}  # name -> called with the arguments before the call is answered

    def __getattr__(self, name):
        def call(*args):
            self.calls.append((name, *args))
            if name in self.hooks:
                self.hooks[name](*args)
            if name == self.fail_on:
                self.errors.code = self.fail_code
                raise RuntimeError(name)
            return self._answer(name, args)

        return call

    def _answer(self, name, args):
        if name == "connect":
            return self.connects
        if name == "moveto" and not self.plot_status.stopped:  # pyaxidraw skips moves once it has stopped
            self.position = args
        if name == "current_pos":
            return self.position
        if args == ("QB\r",):
            self.held, pressed = max(self.held - 1, 0), self.held > 0
            return "1" if pressed else "0"
        if args == ("QG\r",):
            self.busy, moving = max(self.busy - 1, 0), self.busy > 0
            return "03" if moving else "00"
        return None


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
        from axitime import axidraw

        monkeypatch.setattr(axidraw, "_POLL_SECONDS", 0)
        return axidraw.AxiDrawPlotter

    return make


def test_a_session_sets_mm_and_the_se_a3_then_connects(fake):
    plotter = fake()(PlotterConfig(pen_pos_down=35))
    plotter.begin()
    ad = plotter.ad
    assert (ad.options.units, ad.options.model, ad.options.pen_pos_down) == (2, 2, 35)
    assert ad.errors.connect and ad.errors.disconnect
    assert not ad.errors.button and not ad.errors.keyboard  # pyaxidraw would disconnect before raising
    assert [c[0] for c in ad.calls] == ["interactive", "connect"]


def test_pyaxidraws_advice_to_home_by_hand_is_dropped(fake):
    fake()(PlotterConfig()).begin()
    pyaxidraw_log = logging.getLogger("axidrawinternal.axidraw")
    advice = pyaxidraw_log.makeRecord(pyaxidraw_log.name, logging.WARNING, __file__, 0,
                                      "Manually home this AxiDraw before plotting next item.\n", (), None)
    other = pyaxidraw_log.makeRecord(pyaxidraw_log.name, logging.WARNING, __file__, 0, "Low voltage", (), None)
    assert not pyaxidraw_log.filter(advice) and pyaxidraw_log.filter(other)


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
    assert plotter.ad.calls == [
        ("penup",), ("moveto", 0, 0), ("block",), ("usb_query", "QG\r"), ("current_pos",),
        ("usb_command", "EM,0,0\r"), ("disconnect",),
    ]


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


def paused(fake, **kwargs):
    """A plotter whose pause button was pressed during the first of two strokes."""
    plotter = fake(**kwargs)(PlotterConfig())
    ad = plotter.ad
    ad.hooks["draw_path"] = lambda *args: setattr(ad.plot_status, "stopped", 102)
    with pytest.raises(Cancelled, match="pause button"):
        plotter.draw([[(1, 1), (2, 2)], [(3, 3), (4, 4)]])
    ad.calls.clear()
    return plotter


def test_the_pause_button_cancels_and_the_abort_still_goes_home(fake):
    plotter = paused(fake)
    ad = plotter.ad
    assert plotter.abort() is True
    assert ad.plot_status.stopped == 0  # cleared, so the moves home aren't skipped
    assert ad.calls == [
        ("usb_query", "QB\r"), ("usb_query", "QB\r"), ("clear_pause_request",),
        ("penup",), ("moveto", 0, 0), ("block",), ("usb_query", "QG\r"), ("current_pos",),
        ("usb_command", "EM,0,0\r"), ("disconnect",),
    ]


def test_the_abort_waits_for_the_pause_button_to_be_let_go(fake):
    plotter = paused(fake, held=3)  # the board goes on reporting the press while the button is held
    calls = plotter.ad.calls
    assert plotter.abort() is True
    assert calls[: calls.index(("moveto", 0, 0))].count(("usb_query", "QB\r")) == 5  # 3 pressed, then 2 clear


def test_a_move_home_that_was_stopped_again_isnt_reported_as_home(fake):
    plotter = paused(fake, held=1000)  # held down throughout: pyaxidraw halts the move home as well
    ad = plotter.ad
    ad.hooks["moveto"] = lambda *args: setattr(ad.plot_status, "stopped", 102)
    assert plotter.abort() is False
    assert ad.position == (1, 1)  # where it paused
    assert ad.calls[-2:] == [("usb_command", "EM,0,0\r"), ("disconnect",)]  # the motors still go off


def test_the_motors_stay_on_until_the_moves_home_have_finished(fake):
    plotter = fake(busy=4)(PlotterConfig())
    calls = plotter.ad.calls
    assert plotter.abort() is True
    assert calls.count(("usb_query", "QG\r")) == 5
    assert calls.index(("usb_command", "EM,0,0\r")) > max(i for i, c in enumerate(calls) if c[1:] == ("QG\r",))


def test_a_board_that_never_settles_isnt_reported_as_home(fake):
    plotter = fake(busy=10**6)(PlotterConfig())
    assert plotter.abort() is False
    assert plotter.ad.calls[-2:] == [("usb_command", "EM,0,0\r"), ("disconnect",)]


def test_abort_reports_when_it_couldnt_finish(fake):
    assert fake(fail_on="penup", code=104)(PlotterConfig()).abort() is False
