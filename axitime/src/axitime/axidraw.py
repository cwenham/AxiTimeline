"""The AxiDraw, driven through pyaxidraw's interactive API (https://axidraw.com/doc/py_api/).

pyaxidraw is imported only when a real plot starts, so everything else in axitime works without it installed.
Coordinates are millimetres from the home corner, where the carriage must be when a session starts.
"""

from __future__ import annotations

from .config import PlotterConfig
from .plotting import Cancelled, PlotError, Point

INSTALL = "uv sync --extra axidraw (in the AxiTimeline folder)"
_UNITS_MM = 2
_MODEL_SE_A3 = 2  # "AxiDraw V3/A3 or SE/A3"
_PAUSE_BUTTON, _LOST_USB = 102, 104


class AxiDrawPlotter:
    def __init__(self, config: PlotterConfig, dry_run: bool = False):
        try:
            from pyaxidraw import axidraw
        except ImportError:
            raise PlotError(f"pyaxidraw (the AxiDraw Python API) isn't installed. Install it with: {INSTALL}") from None
        self.ad = axidraw.AxiDraw()
        self.config = config
        self.dry_run = dry_run

    def begin(self) -> None:
        ad, c = self.ad, self.config
        ad.interactive()
        ad.options.units = _UNITS_MM
        ad.options.model = _MODEL_SE_A3
        ad.options.pen_pos_up = c.pen_pos_up
        ad.options.pen_pos_down = c.pen_pos_down
        ad.options.speed_pendown = c.speed_pendown
        ad.options.speed_penup = c.speed_penup
        # A failed connection or lost USB raises. The pause button doesn't: pyaxidraw would disconnect before
        # raising, leaving no way to lift the pen and go home, so draw() checks for it instead. Ctrl+C is left
        # to axitime (plotting.StopRequest), which stops between strokes rather than mid-command.
        ad.errors.connect = ad.errors.disconnect = True
        ad.errors.button = ad.errors.keyboard = False
        try:
            connected = ad.connect()
        except RuntimeError:
            connected = False
        if not connected:
            raise PlotError("couldn't connect to the AxiDraw: is it plugged in, switched on, and at its home corner?")

    def _check(self) -> None:
        """Raise if pyaxidraw has stopped: the pause button, or lost USB."""
        stopped = getattr(getattr(self.ad, "plot_status", None), "stopped", 0) or getattr(self.ad.errors, "code", 0)
        if stopped == _PAUSE_BUTTON:
            raise Cancelled("the AxiDraw's pause button was pressed")
        if stopped == _LOST_USB:
            raise PlotError("lost the USB connection to the AxiDraw")

    def draw(self, strokes: list[list[Point]], should_stop=lambda: None) -> None:
        ad = self.ad
        try:
            for stroke in strokes:
                reason = should_stop()  # between strokes: the one safe place to stop
                if reason:
                    raise Cancelled(reason)
                if self.dry_run:  # the full motion with the pen held up
                    for x, y in stroke:
                        ad.moveto(x, y)
                else:
                    ad.moveto(*stroke[0])
                    ad.draw_path([[x, y] for x, y in stroke])
                self._check()
            ad.penup()
            ad.moveto(0, 0)
            ad.block()
            self._check()
        except RuntimeError as exc:
            code = getattr(ad.errors, "code", 0)
            if code == _PAUSE_BUTTON:
                raise Cancelled("the AxiDraw's pause button was pressed") from exc
            if code == _LOST_USB:
                raise PlotError("lost the USB connection to the AxiDraw") from exc
            raise

    def _shut_down(self) -> None:
        ad = self.ad
        ad.penup()
        ad.moveto(0, 0)
        ad.block()
        ad.usb_command("EM,0,0\r")  # the EBB's "enable motors" command with both off
        ad.disconnect()

    def finish(self) -> None:
        self._shut_down()

    def abort(self) -> bool:
        """Pen up, home, motors off, as far as the connection still allows. Never raises; True if it all happened."""
        status = getattr(self.ad, "plot_status", None)
        if getattr(status, "stopped", 0) == _PAUSE_BUTTON:
            # After the pause button pyaxidraw skips further moves; clear that, so the pen lifts and goes home.
            status.stopped = 0
            if hasattr(self.ad, "clear_pause_request"):
                self.ad.clear_pause_request()
        try:
            self._shut_down()
            return True
        except Exception:
            try:
                self.ad.disconnect()
            except Exception:
                pass
            return False
