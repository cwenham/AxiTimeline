"""Running a plot: the window, the strips, the hardware, and what happens when something goes wrong.

The roll is much longer than the AxiDraw can reach, so a job is drawn in **strips**: the stretch of roll under
the plotter is drawn, then the paper moves on by one strip's length and the next is drawn. Strokes that cross a
strip boundary are cut there; the two halves meet again on paper if the paper moves exactly a strip's length.

Machine coordinates are millimetres from the AxiDraw's home corner. The roll runs under the AxiDraw's base beam,
along its Y axis, so each strip is turned a quarter-turn onto the machine (never mirrored): along the roll is Y,
across it is X. Every strip sits ``origin_along_mm`` to ``origin_along_mm + strip_mm`` from home along Y, and the
page's nearer edge ``origin_across_mm`` from home along X. Which way time runs depends on which way the paper
moves on (``feed``).
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


class StopRequest:
    """While the plotter moves, Ctrl+C, SIGHUP and SIGTERM ask the run to stop at the next safe point, between
    strokes. Interrupting the plotter software in the middle of a command can leave the AxiDraw stuck with its
    motors holding, unable to lift the pen or go home. A second Ctrl+C stops at once, for when something hangs."""

    def __init__(self, report: Callable[[str], None] = print):
        self.reason: str | None = None
        self.report = report

    def __call__(self) -> str | None:
        """Why a stop was asked for, or None: what the plotter checks between strokes."""
        return self.reason

    def _handle(self, signum: int, frame) -> None:
        if self.reason is not None and signum == signal.SIGINT:
            raise KeyboardInterrupt  # asked twice: stop now, whatever it's doing
        if self.reason is None:
            self.reason = f"stopped by {signal.Signals(signum).name}"
            try:
                self.report("stopping after the current stroke (press Ctrl+C again to stop at once)")
            except OSError:
                pass  # the terminal may already be gone

    @contextlib.contextmanager
    def installed(self) -> Iterator[None]:
        try:
            previous = {s: signal.signal(s, self._handle) for s in _INTERRUPTS}
        except ValueError:  # not the main thread, where handlers can't be changed
            previous = {}
        try:
            yield
        finally:
            for s, handler in previous.items():
                signal.signal(s, handler)


ABORT_SECONDS = 30  # long enough to lift the pen and drive home from anywhere on the plotter


def _abort_timed_out(signum: int, frame) -> None:
    raise TimeoutError(f"the safe stop didn't finish within {ABORT_SECONDS} seconds")


def _shielded(action: Callable[[], bool]) -> bool:
    """Run a safe abort with Ctrl+C, SIGHUP and SIGTERM held off, so a second interrupt can't cut it short and
    leave the pen down, but give up after ``ABORT_SECONDS`` so it can't hang. True if it finished."""
    previous: dict = {}
    try:
        previous = {s: signal.signal(s, signal.SIG_IGN) for s in _INTERRUPTS}
        if hasattr(signal, "SIGALRM"):
            previous[signal.SIGALRM] = signal.signal(signal.SIGALRM, _abort_timed_out)
            signal.alarm(ABORT_SECONDS)
    except ValueError:  # not the main thread, where handlers can't be changed: just run it
        pass
    try:
        return bool(action())
    except Exception:
        return False
    finally:
        if hasattr(signal, "SIGALRM") and signal.SIGALRM in previous:
            signal.alarm(0)
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
    """A strip's strokes in machine coordinates. Its earlier end leads in the feed direction, so moving the paper
    on by ``strip_mm`` carries what was drawn exactly onto where the next strip would draw it."""
    _, top, _, height = plot_file.page
    along, across = config.origin_along_mm, config.origin_across_mm
    if config.feed == "towards-front":  # time runs back towards the base beam; the page's top edge is nearer home
        far = along + config.strip_mm
        return [[(across + y - top, far - (x - strip.x0)) for x, y in stroke] for stroke in strip.strokes]
    # towards the back: time runs towards the front; the page's bottom edge is nearer home
    return [[(across + top + height - y, along + x - strip.x0) for x, y in stroke] for stroke in strip.strokes]


class Plotter(Protocol):
    def begin(self) -> None: ...

    def draw(self, strokes: list[list[Point]], should_stop: Callable[[], str | None]) -> None:
        """Draw one strip's strokes (machine coordinates), finishing with the pen up and the carriage home.

        Before each stroke, call ``should_stop``; if it gives a reason, raise ``Cancelled(reason)``."""

    def finish(self) -> None:
        """After the last strip: pen up, home, motors off, disconnect."""

    def abort(self) -> bool:
        """After a failure or a stop: pen up, home, motors off, disconnect. Must never raise. True if all of
        that is known to have happened."""


class Transport(Protocol):
    def advance(self, mm: float, next_start: float) -> None:
        """Move the paper on by ``mm`` so the roll from ``next_start`` is under the plotter."""


class ManualTransport:
    """Until the paper transport's controller protocol is specified, the operator moves the paper on."""

    def __init__(self, ask: Callable[[str], str] = input, feed: str = "towards-front"):
        self.ask = ask
        self.towards = "the front" if feed == "towards-front" else "the back"

    def advance(self, mm: float, next_start: float) -> None:
        self.ask(
            f"Move the paper on by exactly {mm:g}mm, towards {self.towards}, so the roll at {next_start / 10:.1f}cm "
            "sits where this strip started, then press Enter: "
        )


@dataclass(frozen=True)
class Outcome:
    status: str  # completed, cancelled or errored
    strip: Strip | None  # the strip in progress when it stopped
    message: str = ""
    safe: bool = True  # the pen is known to be up, the carriage home and the motors off


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
    stop = StopRequest(report)
    with stop.installed():
        try:
            plotter.begin()
            to_move = 0.0
            for strip in strips:
                if strip.index > 0:
                    to_move += config.strip_mm
                if not strip.strokes:
                    continue  # nothing for this pen here: the paper moves on past it with the next strip
                if stop():
                    raise Cancelled(stop())
                if to_move:
                    transport.advance(to_move, strip.x0)
                    to_move = 0.0
                current = strip
                report(f"strip {strip.index + 1} of {len(strips)}: {strip.x0 / 10:.1f}–{strip.x1 / 10:.1f}cm")
                plotter.draw(to_machine(strip, plot_file, config), stop)
            plotter.finish()
        except (KeyboardInterrupt, Cancelled) as exc:
            safe = _shielded(plotter.abort)
            reason = str(exc) if isinstance(exc, Cancelled) else "stopped at once by a second Ctrl+C"
            outcome = Outcome("cancelled", current, reason, safe)
        except Exception as exc:  # serial errors, lost USB, anything: make the hardware safe, then record it
            safe = _shielded(plotter.abort)
            outcome = Outcome("errored", current, str(exc) or type(exc).__name__, safe)
        else:
            joblog.append(log_path, "end completed")
            return Outcome("completed", None)
    where = f" strip={current.index + 1} x={current.x0:g}-{current.x1:g}mm" if current else " before the first strip"
    detail = f' message="{outcome.message}"' if outcome.message else ""
    joblog.append(log_path, f"end {outcome.status}{where}{detail}" + ("" if outcome.safe else " safe-stop=incomplete"))
    return outcome


class SimulatedPlotter:
    """Records what it is asked to draw: for ``--simulate`` and for tests."""

    def __init__(self) -> None:
        self.strips: list[list[list[Point]]] = []
        self.events: list[str] = []

    def begin(self) -> None:
        self.events.append("begin")

    def draw(self, strokes: list[list[Point]], should_stop: Callable[[], str | None] = lambda: None) -> None:
        for _ in strokes:
            if should_stop():
                raise Cancelled(should_stop())
        self.strips.append(strokes)
        self.events.append("draw")

    def finish(self) -> None:
        self.events.append("finish")

    def abort(self) -> bool:
        self.events.append("abort")
        return True
