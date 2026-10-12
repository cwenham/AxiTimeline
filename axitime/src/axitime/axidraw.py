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
        # Raise instead of quietly carrying on, so a lost connection or the pause button stops the run.
        ad.errors.connect = ad.errors.disconnect = ad.errors.button = True
        try:
            connected = ad.connect()
        except RuntimeError:
            connected = False
        if not connected:
            raise PlotError("couldn't connect to the AxiDraw: is it plugged in, switched on, and at its home corner?")

    def draw(self, strokes: list[list[Point]]) -> None:
        ad = self.ad
        try:
            for stroke in strokes:
                if self.dry_run:  # the full motion with the pen held up
                    for x, y in stroke:
                        ad.moveto(x, y)
                else:
                    ad.moveto(*stroke[0])
                    ad.draw_path([[x, y] for x, y in stroke])
            ad.penup()
            ad.moveto(0, 0)
            ad.block()
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

    def abort(self) -> None:
        """Pen up, home, motors off, as far as the connection still allows. Never raises."""
        try:
            self._shut_down()
        except Exception:
            try:
                self.ad.disconnect()
            except Exception:
                pass
