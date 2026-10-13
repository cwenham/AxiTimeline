"""The ``axitime`` command line: ``check``, ``list-pens``, ``render`` and ``plot``.

The first three run the same pipeline (parse, layout, draw) in memory; ``render`` then writes SVG files, a
preview of every pen and one file per pen. ``plot`` never reads ``.axitl`` source: it draws one per-pen SVG.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import libaxitl
from libaxitl import (
    AxitlError,
    DateValue,
    Diagnostic,
    Drawing,
    Kind,
    ParseResult,
    RenderError,
    RenderOptions,
    ResolvedLayout,
    Severity,
    draw,
    layout,
    parse,
    page_for,
    render,
    stroke_lengths,
)
from libaxitl.dates import DateError, parse_date
from libaxitl.pens import PENS
from libaxitl.units import UnitError, format_number, parse_length

from . import __version__
from . import joblog
from .config import ConfigError, PlotterConfig, load_config
from .jobhash import job_hash, resource_hashes
from .plotfile import PlotFileError, load_plot_file
from .plotting import Cancelled, ManualTransport, PlotError, plan_strips, run, stop_signals_cancel, window_for
from .resolver import filesystem_resolver

EXIT_OK = 0
EXIT_ERRORS = 1
EXIT_USAGE = 2

_PLURALS = {Kind.PERSON: "people", Kind.EVENT: "events", Kind.SPAN: "spans", Kind.GROUP: "groups"}


class UsageError(Exception):
    """A problem with the command line rather than the timeline; exits with status 2."""


def clock_now() -> DateValue:
    """The host's clock as a date: local wall-clock time, since dates without a timezone are taken literally."""
    return DateValue.from_datetime(dt.datetime.now())


@dataclass
class Job:
    """Everything the pipeline produced for one source file, as far as it got."""

    source_path: str
    result: ParseResult | None = None
    resolved: ResolvedLayout | None = None
    drawing: Drawing | None = None
    diagnostics: tuple[Diagnostic, ...] = ()
    hash: str | None = None  # the job hash, once layout has resolved now
    notes: list[str] = field(default_factory=list)
    stages: list[str] = field(default_factory=list)

    @property
    def errors(self) -> int:
        return sum(d.severity is Severity.ERROR for d in self.diagnostics)

    @property
    def warnings(self) -> int:
        return len(self.diagnostics) - self.errors


def run_pipeline(source_path: str, now_text: str | None) -> Job:
    try:
        source = Path(source_path).read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        raise UsageError(f"can't read {source_path}: {exc}") from None
    pinned = None
    if now_text is not None:
        try:
            pinned = parse_date(now_text)
        except DateError as exc:
            raise UsageError(f"--now: {exc}") from None
    job = Job(source_path)
    try:
        job.stages.append("parse")
        job.result = parse(source, filesystem_resolver, source_name=source_path)
        job.diagnostics = job.result.diagnostics
        uses_now = job.result.document.timeline.end_is_now
        if pinned is not None and not uses_now:
            job.notes.append("--now has no effect: the timeline doesn't end at now")
        job.stages.append("layout")
        job.resolved = layout(job.result.document, (pinned or clock_now()) if uses_now else None)
        job.diagnostics += job.resolved.diagnostics
        job.hash = job_hash(job.result, job.resolved, source_path)
        job.stages.append("draw")
        job.drawing = draw(job.resolved)
        job.diagnostics += job.drawing.diagnostics
    except AxitlError as exc:
        # A parse failure carries everything; a later failure needs the earlier warnings put in front.
        job.diagnostics = (job.diagnostics if job.result else ()) + exc.diagnostics
    return job


def _diagnostic_json(d: Diagnostic) -> dict:
    return {
        "severity": d.severity.value,
        "code": d.code,
        "message": d.message,
        "source": d.location.source if d.location else None,
        "line": d.location.line if d.location else None,
    }


def _summary(result: ParseResult) -> dict:
    entities = list(result.document.walk())
    kinds = Counter(e.kind for e in entities)
    pens = Counter(e.pen for e in entities)
    return {
        "entities": {k.value: kinds.get(k, 0) for k in Kind},
        "pens": {pen: pens[pen] for pen in PENS if pen in pens},
        "fonts": list(result.document.fonts),
        "resources": [{"kind": r.kind, "name": r.name} for r in result.resources],
    }


def _layout_summary(resolved: ResolvedLayout) -> dict:
    return {
        "length_mm": resolved.length_mm,
        "width_mm": resolved.width_mm,
        "scale": str(resolved.scale),
        "scale_derived": resolved.scale_derived,
        "now": str(resolved.now) if resolved.now is not None else None,
        "lanes": {
            s.side.value: {"used": s.lanes_used, "capacity": s.lane_capacity} for s in (resolved.above, resolved.below)
        },
        "ticks": {"every": resolved.tick_interval, "labels_every": resolved.tick_label_interval},
        "pens": list(resolved.pens),
        "omitted": [e.label for e in resolved.omitted],
    }


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _length(mm: float) -> str:
    """A length in whichever metric unit reads most naturally for its size (a display choice, not a rule)."""
    if mm >= 1000:
        return f"{format_number(mm / 1000, 2)}m"
    if mm >= 100:
        return f"{format_number(mm / 10, 1)}cm"
    return f"{format_number(mm, 1)}mm"


def _print_diagnostics(job: Job, verb: str) -> None:
    for d in job.diagnostics:
        print(d)
    status = "failed" if job.errors else "passed"
    print(f"{job.source_path}: {verb} {status} with {_plural(job.errors, 'error')} and {_plural(job.warnings, 'warning')}")


# -- check ----------------------------------------------------------------------------------------------------


def _config(args: argparse.Namespace) -> PlotterConfig:
    try:
        return load_config(Path(args.config) if getattr(args, "config", None) else None)
    except ConfigError as exc:
        raise UsageError(str(exc)) from None


def _reach_check(job: Job, config: PlotterConfig) -> None:
    """A page wider than the plotter can reach across the roll is a fatal check error (language spec §4)."""
    if job.drawing is None:
        return
    page = job.drawing.width_mm + 2 * job.drawing.page_margin_mm
    if not config.fits_across(page):
        timeline = job.result.document.timeline
        job.diagnostics += (
            Diagnostic(
                Severity.ERROR,
                "too-wide",
                f"the page is {page:g}mm across the roll (width {job.drawing.width_mm:g}mm plus crop marks), but the "
                f"plotter reaches {config.travel_across_mm - config.origin_y_mm:g}mm from where the page starts "
                f"({config.source})",
                timeline.location,
            ),
        )


def cmd_check(args: argparse.Namespace) -> int:
    job = run_pipeline(args.file, args.now)
    _reach_check(job, _config(args))
    if args.json:
        report = {
            "source": job.source_path,
            "ok": job.errors == 0,
            "errors": job.errors,
            "warnings": job.warnings,
            "diagnostics": [_diagnostic_json(d) for d in job.diagnostics],
            "summary": _summary(job.result) if job.result else None,
            "layout": _layout_summary(job.resolved) if job.resolved else None,
            "job_hash": job.hash,
            "notes": job.notes,
            "stages": job.stages,
            "versions": {"axitime": __version__, "libaxitl": libaxitl.__version__},
        }
        json.dump(report, sys.stdout, indent=2, ensure_ascii=False)
        print()
        return EXIT_OK if job.errors == 0 else EXIT_ERRORS

    _print_diagnostics(job, "check")
    if job.result:
        summary = _summary(job.result)
        counts = ", ".join(f"{n} {_PLURALS[Kind(k)] if n != 1 else k}" for k, n in summary["entities"].items() if n)
        print(f"  entities: {counts or 'none'}")
        print("  fonts:    " + ", ".join(summary["fonts"]))
    resolved = job.resolved
    if resolved:
        scale = f"{resolved.scale}{' (from length=)' if resolved.scale_derived else ''}"
        print(f"  paper:    {_length(resolved.length_mm)} by {_length(resolved.width_mm)}, scale {scale}")
        if resolved.now is not None:
            print(f"  now:      {resolved.now}  (pass --now {resolved.now} to reproduce this layout later)")
        lanes = ", ".join(
            f"{s.lanes_used} of {s.lane_capacity} {s.side.value}" for s in (resolved.above, resolved.below)
        )
        print(f"  lanes:    {lanes}")
        if resolved.tick_interval:
            print(f"  ticks:    every {resolved.tick_interval}, labelled every {resolved.tick_label_interval or 'none'}")
    if job.drawing:
        print("  pens:     " + ", ".join(job.drawing.pens) + f"  ({resolved.axis_pen} draws the baseline and ticks first)")
    if job.hash:
        print(f"  job hash: {job.hash}")
    for note in job.notes:
        print(f"  note: {note}")
    return EXIT_OK if job.errors == 0 else EXIT_ERRORS


# -- list-pens ------------------------------------------------------------------------------------------------


def cmd_list_pens(args: argparse.Namespace) -> int:
    job = run_pipeline(args.file, args.now)
    if job.drawing is None:
        _print_diagnostics(job, "list-pens")
        return EXIT_ERRORS
    lengths = job.drawing.length_by_pen()
    strokes = Counter(s.pen for s in job.drawing.strokes)
    if args.json:
        pens = [{"pen": p, "length_mm": round(lengths[p], 1), "strokes": strokes[p]} for p in job.drawing.pens]
        json.dump({"source": job.source_path, "pens": pens}, sys.stdout, indent=2)
        print()
        return EXIT_OK
    width = max(len(p) for p in job.drawing.pens)
    for pen in job.drawing.pens:
        print(f"{pen:<{width}}  {_length(lengths[pen]):>8}  {_plural(strokes[pen], 'stroke')}")
    print(f"{'total':<{width}}  {_length(sum(lengths.values())):>8}")
    for note in job.notes:
        print(f"note: {note}")
    return EXIT_OK


# -- render ---------------------------------------------------------------------------------------------------


def _window(args: argparse.Namespace, resolved: ResolvedLayout, notes: list[str]) -> tuple[float, float] | None:
    """The window to render, from physical bounds or calendar bounds, in mm along the roll."""
    physical = args.start_offset is not None or args.length is not None
    calendar = args.date_from is not None or args.date_to is not None
    if physical and calendar:
        raise UsageError("give either --start-offset/--length or --from/--to, not both")
    total = resolved.length_mm
    try:
        if physical:
            start = parse_length(args.start_offset) if args.start_offset is not None else 0.0
            length = parse_length(args.length) if args.length is not None else total - start
            return start, length
        if calendar:
            start = resolved.time_to_position(parse_date(args.date_from)) if args.date_from else 0.0
            end = resolved.time_to_position(parse_date(args.date_to), end=True) if args.date_to else total
    except (UnitError, DateError) as exc:
        raise UsageError(str(exc)) from None
    if not calendar:
        return None
    if end <= 0 or start >= total or end <= start:
        raise UsageError("the dates given don't overlap the timeline")
    if start < 0 or end > total:
        notes.append("the dates given run past the timeline's ends; rendering only the part on the paper")
    start, end = max(start, 0.0), min(end, total)
    return start, end - start


def cmd_render(args: argparse.Namespace) -> int:
    job = run_pipeline(args.file, args.now)
    if job.drawing is None:
        _print_diagnostics(job, "render")
        return EXIT_ERRORS
    for d in job.diagnostics:
        print(d)
    resolved, drawing = job.resolved, job.drawing
    try:
        bleed = parse_length(args.bleed)
    except UnitError as exc:
        raise UsageError(f"--bleed: {exc}") from None
    window = _window(args, resolved, job.notes)
    metadata = {"source": Path(job.source_path).name, "axitime-version": __version__, "job-hash": job.hash}
    files = tuple(
        ("file", {"kind": f.kind, "path": f.path, "sha256": f.sha256})
        for f in resource_hashes(job.result, job.source_path)
    )
    if resolved.now is not None:
        metadata["now"] = str(resolved.now)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    stem = Path(job.source_path).stem
    written = []
    try:
        for pen in [None] if args.preview_only else [None, *drawing.pens]:
            options = RenderOptions(pen=pen, window=window, bleed_mm=bleed, metadata=metadata, metadata_entries=files)
            svg = render(resolved, options, drawing=drawing)
            path = out / f"{stem}-{pen or 'preview'}.svg"
            path.write_text(svg, encoding="utf-8")
            written.append((pen, path, svg))
    except RenderError as exc:
        raise UsageError(str(exc)) from None
    total = resolved.length_mm
    if window is None:
        print(f"rendered the whole job, {_length(total)}")
    else:
        start, end = window[0], min(window[0] + window[1], total)
        print(f"rendered {_length(start)} to {_length(end)} of {_length(total)}, bleed {_length(bleed)} at cut edges")
    lengths = stroke_lengths(drawing, page_for(drawing, window, bleed))
    for pen, path, _ in written:
        what = "preview, every pen" if pen is None else f"{pen}, {_length(lengths[pen])} of ink"
        print(f"  {path}  ({what})")
    print(f"  job hash: {job.hash}")
    if resolved.now is not None:
        print(f"  now: {resolved.now}  (pass --now {resolved.now} to reproduce these files later)")
    for note in job.notes:
        print(f"  note: {note}")
    return EXIT_OK


# -- plot -----------------------------------------------------------------------------------------------------


def ask(prompt: str) -> str:
    """The operator's answer to a prompt. Tests replace this."""
    return input(prompt)


def make_plotter(config: PlotterConfig, dry_run: bool):
    """The AxiDraw. Tests replace this with a simulated plotter."""
    from .axidraw import AxiDrawPlotter

    return AxiDrawPlotter(config, dry_run)


def cmd_plot(args: argparse.Namespace) -> int:
    config = _config(args)
    try:
        plot_file = load_plot_file(Path(args.file))
        start = parse_length(args.start_offset) if args.start_offset is not None else None
        length = parse_length(args.length) if args.length is not None else None
        bleed = parse_length(args.bleed)
        window = window_for(plot_file, start, length, bleed)
    except (PlotFileError, PlotError, UnitError) as exc:
        raise UsageError(str(exc)) from None
    page_height = plot_file.page[3]
    if not config.fits_across(page_height):
        raise UsageError(
            f"this page is {page_height:g}mm across the roll, more than the plotter reaches "
            f"({config.travel_across_mm - config.origin_y_mm:g}mm, from {config.source})"
        )
    strips = plan_strips(plot_file.strokes, window, config.strip_mm)
    ink = sum(strip.length for strip in strips)
    folder = plot_file.path.parent
    try:
        lookup = joblog.find_job(plot_file, folder)
    except FileExistsError as exc:
        raise UsageError(str(exc)) from None

    forced = []
    if lookup.match is joblog.Match.MISMATCH:
        names = ", ".join(p.name for p in lookup.others)
        message = (
            f"no existing job matches this file: {plot_file.source} has been plotted before from a different "
            f"version ({names})"
        )
        if not args.force:
            raise UsageError(message + ". Render the same version again, or pass --force to start a new job.")
        forced.append(f"no existing job matched; other jobs for this source: {names}")

    total = plot_file.job_length_mm
    print(f"job:     {plot_file.source}, hash ...{plot_file.job_hash[-6:]} ({lookup.path.name})")
    previous = [line for line in joblog.runs(lookup.path) if " start " in line]
    if lookup.match is joblog.Match.EXISTING:
        print(f"         {_plural(len(previous), 'earlier run')}" + (f", last: {previous[-1]}" if previous else ""))
    else:
        print("         a new job: this is its first run")
    print(f"pen:     {plot_file.pen}")
    print(f"window:  {window.start / 10:.1f}–{window.end / 10:.1f}cm of {total / 10:.1f}cm"
          + (f", bleed {window.bleed_start:g}/{window.bleed_end:g}mm" if window.bleed_start or window.bleed_end else ""))
    print(f"ink:     {_length(ink)}")
    drawn = sum(1 for strip in strips if strip.strokes)
    print(f"strips:  {drawn} to draw, of up to {config.strip_mm / 10:g}cm each; you move the paper on between them")
    if args.dry_run:
        print("dry run: the plotter goes through every motion with the pen held up")
    if args.simulate:
        for strip in strips:
            print(f"  strip {strip.index + 1}: {strip.x0 / 10:.1f}–{strip.x1 / 10:.1f}cm, "
                  f"{_plural(len(strip.strokes), 'stroke')}, {_length(strip.length)}")
        print("simulated: nothing was plotted and the job log is unchanged")
        return EXIT_OK

    try:
        plotter = make_plotter(config, args.dry_run)
    except PlotError as exc:
        raise UsageError(str(exc)) from None
    with stop_signals_cancel():
        return _confirm_and_run(args, plot_file, strips, window, config, plotter, lookup, forced)


def _confirm_and_run(args, plot_file, strips, window, config, plotter, lookup, forced) -> int:
    try:
        answer = ask(f"Load the {plot_file.pen} pen. Type its name to start (anything else stops): ").strip()
    except (KeyboardInterrupt, EOFError, Cancelled):
        answer = ""
    if answer != plot_file.pen:
        if not (args.force and answer):
            print("stopped: nothing was plotted")
            return EXIT_ERRORS
        forced.append(f"the operator typed {answer!r} for the {plot_file.pen} pen")
    if lookup.match is not joblog.Match.EXISTING:
        joblog.create(lookup.path, plot_file)
    outcome = run(
        plot_file, strips, window, config, plotter, ManualTransport(ask), lookup.path,
        forced="; ".join(forced) or None, dry_run=args.dry_run,
    )
    if outcome.status == "completed":
        print(f"completed; logged in {lookup.path.name}")
        return EXIT_OK
    where = f" during strip {outcome.strip.index + 1} ({outcome.strip.x0 / 10:.1f}–{outcome.strip.x1 / 10:.1f}cm)" if outcome.strip else ""
    print(f"{outcome.status}{where}" + (f": {outcome.message}" if outcome.message else "")
          + f". The pen is up and the motors are off; logged in {lookup.path.name}")
    return EXIT_ERRORS


# -- the command line -----------------------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="axitime", description="Pen-plotter timelines from .axitl files.")
    parser.add_argument("--version", action="version", version=f"axitime {__version__} (libaxitl {libaxitl.__version__})")
    commands = parser.add_subparsers(dest="command", required=True)
    now_help = "the value of now for a timeline that ends at now (default: the clock)"

    check = commands.add_parser("check", help="validate a .axitl file and its layout without drawing anything")
    check.add_argument("file", help="the .axitl source file")
    check.add_argument("--json", action="store_true", help="print a machine-readable report")
    check.add_argument("--now", metavar="DATE", help=now_help)
    check.add_argument("--config", metavar="FILE", help="plotter settings (default: ~/.config/axitime/plotter.toml)")
    check.set_defaults(handler=cmd_check)

    pens = commands.add_parser("list-pens", help="the pens a job needs and how much each one draws")
    pens.add_argument("file", help="the .axitl source file")
    pens.add_argument("--json", action="store_true", help="print a machine-readable report")
    pens.add_argument("--now", metavar="DATE", help=now_help)
    pens.set_defaults(handler=cmd_list_pens)

    rend = commands.add_parser("render", help="write a preview SVG and one SVG per pen")
    rend.add_argument("file", help="the .axitl source file")
    rend.add_argument("-o", "--out", default=".", metavar="DIR", help="where to write the files (default: here)")
    rend.add_argument("--now", metavar="DATE", help=now_help)
    rend.add_argument("--start-offset", metavar="LENGTH", help="start this far along the roll (e.g. 137cm)")
    rend.add_argument("--length", metavar="LENGTH", help="render only this much of the roll")
    rend.add_argument("--from", dest="date_from", metavar="DATE", help="start at this date instead")
    rend.add_argument("--to", dest="date_to", metavar="DATE", help="end at the end of this date instead")
    rend.add_argument("--bleed", default="2", metavar="LENGTH", help="ink past a cut edge (default 2mm; 0 for none)")
    rend.add_argument("--preview-only", action="store_true", help="write only the preview, not the per-pen files")
    rend.set_defaults(handler=cmd_render)

    plot = commands.add_parser("plot", help="plot one per-pen SVG written by render")
    plot.add_argument("file", help="a per-pen SVG, e.g. timeline-red.svg")
    plot.add_argument("--start-offset", metavar="LENGTH", help="start this far along the roll, to resume (e.g. 137cm)")
    plot.add_argument("--length", metavar="LENGTH", help="stop after this much of the roll")
    plot.add_argument("--bleed", default="2", metavar="LENGTH", help="ink past a cut edge (default 2mm; 0 for none)")
    plot.add_argument("--dry-run", action="store_true", help="go through every motion with the pen held up")
    plot.add_argument("--force", action="store_true", help="go ahead despite a job or pen mismatch (recorded in the log)")
    plot.add_argument("--simulate", action="store_true", help="show the strips that would be plotted, then stop")
    plot.add_argument("--config", metavar="FILE", help="plotter settings (default: ~/.config/axitime/plotter.toml)")
    plot.set_defaults(handler=cmd_plot)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.handler(args)
    except UsageError as exc:
        print(f"axitime: {exc}", file=sys.stderr)
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
