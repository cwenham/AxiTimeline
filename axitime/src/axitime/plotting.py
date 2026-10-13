"""Running a plot: the window, the strips, the hardware, and what happens when something goes wrong.

The roll is much longer than the AxiDraw can reach, so a job is drawn in **strips**: the stretch of roll under
the plotter is drawn, then the paper moves on by one strip's length and the next is drawn. Strokes that cross a
strip boundary are cut there; the two halves meet again on paper if the paper moves exactly a strip's length.

Machine coordinates are millimetres from the AxiDraw's home corner: x along the roll, y across it. A strip's
start sits ``origin_x_mm`` from home, and the page's top edge ``origin_y_mm`` from home. (This orientation is an
assumption until the hardware spec is in the repo: docs/known-gaps.md.)
"""

from __future__ import annotations

import contextlib
import math
import signal
from dataclasses import dataclass
from typing import Callable, Iterator, Protocol

from libaxitl.geometry import Box, keep_inside

from . import joblog
from .config import PlotterConfig
from .plotfile import PlotFile, Point


class PlotError(Exception):
    """A plot that can't go ahead or can't continue. The message is written for the operator."""


class Cancelled(Exception):
    """The run was stopped another way than Ctrl+C: the AxiDraw's pause button, a closed terminal, a kill."""


# A closed terminal (a dropped SSH connection, say) sends SIGHUP and a plain `kill` sends SIGTERM. Left alone,
# either would end plot on the spot with the pen possibly still down, so both are turned into a cancel.
_STOPPING = tuple(s for s in (getattr(signal, "SIGHUP", None), signal.SIGTERM) if s is not None)
_INTERRUPTS = (signal.SIGINT, *_STOPPING)


@contextlib.contextmanager
def stop_signals_cancel() -> Iterator[None]:
    """While plotting, SIGHUP and SIGTERM stop the run the way Ctrl+C does: through the safe abort."""

    def cancel(signum: int, frame) -> None:
        raise Cancelled(f"stopped by {signal.Signals(signum).name}")

    previous = {s: signal.signal(s, cancel) for s in _STOPPING}
    try:
        yield
    finally:
        for s, handler in previous.items():
            signal.signal(s, handler)


def _shielded(action: Callable[[], None]) -> None:
    """Run ``action`` with Ctrl+C, SIGHUP and SIGTERM held off, so a second interrupt can't cut a safe abort
    short and leave the pen down."""
    try:
        previous = {s: signal.signal(s, signal.SIG_IGN) for s in _INTERRUPTS}
    except ValueError:  # not the main thread, where handlers can't be changed: just run it
        previous = {}
    try:
        action()
    finally:
        for s, handler in previous.items():
            signal.signal(s, handler)


@dataclass(frozen=True)
class Window:
    start: float  # where the operator's window starts, mm along the roll
    end: float
    bleed_start: float
    bleed_end: float

    @property
    def cut_from(self) -> float:
        return self.start - self.bleed_start

    @property
    def cut_to(self) -> float:
        return self.end + self.bleed_end


def window_for(plot_file: PlotFile, start_offset: float | None, length: float | None, bleed: float) -> Window:
    """The stretch of roll to plot: physical bounds only, never dates (interpreter spec, ``plot``).

    Bleed extends strokes past an edge only where that edge is a cut in the middle of the job.
    """
    have_from, have_to = plot_file.window
    start = have_from if start_offset is None else start_offset
    if not have_from <= start < have_to:
        raise PlotError(
            f"--start-offset {start / 10:.1f}cm is outside this file, which covers "
            f"{have_from / 10:.1f}–{have_to / 10:.1f}cm"
        )
    if length is not None and length <= 0:
        raise PlotError("--length must be more than zero")
    end = have_to if length is None else min(start + length, have_to)
    return Window(
        start,
        end,
        bleed if start > 0 else 0.0,
        bleed if end < plot_file.job_length_mm else 0.0,
    )


@dataclass(frozen=True)
class Strip:
    index: int
    x0: float  # the stretch of roll it covers, mm
    x1: float
    strokes: tuple[tuple[Point, ...], ...]  # in roll coordinates

    @property
    def length(self) -> float:
        return sum(math.dist(p, q) for s in self.strokes for p, q in zip(s, s[1:], strict=False))


def plan_strips(strokes, window: Window, strip_mm: float) -> list[Strip]:
    """Cut the window into strips the plotter can reach, each stroke cut at the strip edges."""
    count = max(1, math.ceil((window.cut_to - window.cut_from) / strip_mm - 1e-9))
    strips = []
    for k in range(count):
        x0 = window.cut_from + k * strip_mm
        x1 = min(x0 + strip_mm, window.cut_to)
        area = Box(x0, -1e9, x1, 1e9)
        pieces = tuple(tuple(piece) for stroke in strokes for piece in keep_inside(stroke, area))
        strips.append(Strip(k, x0, x1, pieces))
    return strips


def to_machine(strip: Strip, plot_file: PlotFile, config: PlotterConfig) -> list[list[Point]]:
    page_y = plot_file.page[1]
    return [
        [(x - strip.x0 + config.origin_x_mm, y - page_y + config.origin_y_mm) for x, y in stroke]
        for stroke in strip.strokes
    ]


class Plotter(Protocol):
    def begin(self) -> None: ...

    def draw(self, strokes: list[list[Point]]) -> None:
        """Draw one strip's strokes (machine coordinates), finishing with the pen up and the carriage home."""

    def finish(self) -> None:
        """After the last strip: pen up, home, motors off, disconnect."""

    def abort(self) -> None:
        """After a failure or Ctrl+C: pen up, home, motors off, disconnect. Must never raise."""


class Transport(Protocol):
    def advance(self, mm: float, next_start: float) -> None:
        """Move the paper on by ``mm`` so the roll from ``next_start`` is under the plotter."""


class ManualTransport:
    """Until the paper transport's controller protocol is specified, the operator moves the paper on."""

    def __init__(self, ask: Callable[[str], str] = input):
        self.ask = ask

    def advance(self, mm: float, next_start: float) -> None:
        self.ask(
            f"Move the paper on by exactly {mm:g}mm, so the roll at {next_start / 10:.1f}cm sits where this "
            "strip started, then press Enter: "
        )


@dataclass(frozen=True)
class Outcome:
    status: str  # completed, cancelled or errored
    strip: Strip | None  # the strip in progress when it stopped
    message: str = ""


def run(
    plot_file: PlotFile,
    strips: list[Strip],
    window: Window,
    config: PlotterConfig,
    plotter: Plotter,
    transport: Transport,
    log_path,
    forced: str | None = None,
    dry_run: bool = False,
    report: Callable[[str], None] = print,
) -> Outcome:
    """Plot the strips, logging the run's start and end. On any failure the hardware is made safe first."""
    start = (
        f"start pen={plot_file.pen} file={plot_file.path.name} "
        f"window={window.start:g}-{window.end:g}mm bleed={window.bleed_start:g}/{window.bleed_end:g}mm "
        f"strips={len(strips)}" + (" dry-run" if dry_run else "") + (f' forced="{forced}"' if forced else "")
    )
    joblog.append(log_path, start)
    current: Strip | None = None
    try:
        plotter.begin()
        to_move = 0.0
        for strip in strips:
            if strip.index > 0:
                to_move += config.strip_mm
            if not strip.strokes:
                continue  # nothing for this pen here: the paper moves on past it with the next strip
            if to_move:
                transport.advance(to_move, strip.x0)
                to_move = 0.0
            current = strip
            report(f"strip {strip.index + 1} of {len(strips)}: {strip.x0 / 10:.1f}–{strip.x1 / 10:.1f}cm")
            plotter.draw(to_machine(strip, plot_file, config))
        plotter.finish()
    except (KeyboardInterrupt, Cancelled) as exc:
        _shielded(plotter.abort)
        outcome = Outcome("cancelled", current, str(exc) if isinstance(exc, Cancelled) else "")
    except Exception as exc:  # serial errors, lost USB, anything: make the hardware safe, then record it
        _shielded(plotter.abort)
        outcome = Outcome("errored", current, str(exc) or type(exc).__name__)
    else:
        joblog.append(log_path, "end completed")
        return Outcome("completed", None)
    where = f" strip={current.index + 1} x={current.x0:g}-{current.x1:g}mm" if current else " before the first strip"
    detail = f' message="{outcome.message}"' if outcome.message else ""
    joblog.append(log_path, f"end {outcome.status}{where}{detail}")
    return outcome


class SimulatedPlotter:
    """Records what it is asked to draw: for ``--simulate`` and for tests."""

    def __init__(self) -> None:
        self.strips: list[list[list[Point]]] = []
        self.events: list[str] = []

    def begin(self) -> None:
        self.events.append("begin")

    def draw(self, strokes: list[list[Point]]) -> None:
        self.strips.append(strokes)
        self.events.append("draw")

    def finish(self) -> None:
        self.events.append("finish")

    def abort(self) -> None:
        self.events.append("abort")
