"""The ``axitime`` command line.

Only ``check`` exists so far. It runs the parse and layout stages and reports everything they found; drawing
(``render``) and plotting (``plot``) come later.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from collections import Counter
from pathlib import Path

import libaxitl
from libaxitl import AxitlError, DateValue, Diagnostic, Kind, ParseResult, ResolvedLayout, Severity, layout, parse
from libaxitl.dates import DateError, parse_date
from libaxitl.pens import PENS
from libaxitl.units import format_number

from . import __version__
from .resolver import filesystem_resolver

EXIT_OK = 0
EXIT_ERRORS = 1
EXIT_USAGE = 2

_PLURALS = {Kind.PERSON: "people", Kind.EVENT: "events", Kind.SPAN: "spans", Kind.GROUP: "groups"}


def clock_now() -> DateValue:
    """The host's clock as a date: local wall-clock time, since dates without a timezone are taken literally."""
    return DateValue.from_datetime(dt.datetime.now())


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


def cmd_check(args: argparse.Namespace) -> int:
    source_path: str = args.file
    try:
        source = Path(source_path).read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        print(f"axitime: can't read {source_path}: {exc}", file=sys.stderr)
        return EXIT_USAGE
    pinned = None
    if args.now is not None:
        try:
            pinned = parse_date(args.now)
        except DateError as exc:
            print(f"axitime: --now: {exc}", file=sys.stderr)
            return EXIT_USAGE

    result: ParseResult | None = None
    resolved: ResolvedLayout | None = None
    notes: list[str] = []
    stages = ["parse"]
    try:
        result = parse(source, filesystem_resolver, source_name=source_path)
        diagnostics = result.diagnostics
        stages.append("layout")
        uses_now = result.document.timeline.end_is_now
        if pinned is not None and not uses_now:
            notes.append("--now has no effect: the timeline doesn't end at now")
        resolved = layout(result.document, (pinned or clock_now()) if uses_now else None)
        diagnostics = diagnostics + resolved.diagnostics
    except AxitlError as exc:
        # A parse failure carries everything; a layout failure needs the parse's warnings put in front.
        diagnostics = (result.diagnostics if result else ()) + exc.diagnostics
    errors = sum(d.severity is Severity.ERROR for d in diagnostics)
    warnings = len(diagnostics) - errors

    if args.json:
        report = {
            "source": source_path,
            "ok": errors == 0,
            "errors": errors,
            "warnings": warnings,
            "diagnostics": [_diagnostic_json(d) for d in diagnostics],
            "summary": _summary(result) if result else None,
            "layout": _layout_summary(resolved) if resolved else None,
            "notes": notes,
            "stages": stages,
            "versions": {"axitime": __version__, "libaxitl": libaxitl.__version__},
        }
        json.dump(report, sys.stdout, indent=2, ensure_ascii=False)
        print()
        return EXIT_OK if errors == 0 else EXIT_ERRORS

    for d in diagnostics:
        print(d)
    status = "failed" if errors else "passed"
    print(f"{source_path}: check {status} with {_plural(errors, 'error')} and {_plural(warnings, 'warning')}")
    if result:
        summary = _summary(result)
        counts = ", ".join(f"{n} {_PLURALS[Kind(k)] if n != 1 else k}" for k, n in summary["entities"].items() if n)
        print(f"  entities: {counts or 'none'}")
        print("  fonts:    " + ", ".join(summary["fonts"]))
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
        print("  pens:     " + ", ".join(resolved.pens) + f"  ({resolved.axis_pen} draws the baseline and ticks first)")
    for note in notes:
        print(f"  note: {note}")
    return EXIT_OK if errors == 0 else EXIT_ERRORS


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="axitime", description="Pen-plotter timelines from .axitl files.")
    parser.add_argument("--version", action="version", version=f"axitime {__version__} (libaxitl {libaxitl.__version__})")
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check", help="validate a .axitl file and its layout without drawing anything")
    check.add_argument("file", help="the .axitl source file")
    check.add_argument("--json", action="store_true", help="print a machine-readable report")
    check.add_argument(
        "--now", metavar="DATE", help="the value of now for a timeline that ends at now (default: the clock)"
    )
    check.set_defaults(handler=cmd_check)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main())
