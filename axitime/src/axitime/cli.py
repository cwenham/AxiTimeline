"""The ``axitime`` command line.

Only ``check`` exists so far, and it runs the parse stage only: layout checks (lane space, pole fit, label
collisions) arrive with ``libaxitl.layout``.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import libaxitl
from libaxitl import AxitlError, Diagnostic, Kind, ParseResult, Severity, parse
from libaxitl.pens import PENS

from . import __version__
from .resolver import filesystem_resolver

EXIT_OK = 0
EXIT_ERRORS = 1
EXIT_USAGE = 2

_PLURALS = {Kind.PERSON: "people", Kind.EVENT: "events", Kind.SPAN: "spans", Kind.GROUP: "groups"}


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


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def cmd_check(args: argparse.Namespace) -> int:
    source_path: str = args.file
    try:
        source = Path(source_path).read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        print(f"axitime: can't read {source_path}: {exc}", file=sys.stderr)
        return EXIT_USAGE

    result: ParseResult | None = None
    try:
        result = parse(source, filesystem_resolver, source_name=source_path)
        diagnostics = result.diagnostics
    except AxitlError as exc:
        diagnostics = exc.diagnostics
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
            "stages": ["parse"],
            "versions": {"axitime": __version__, "libaxitl": libaxitl.__version__},
        }
        json.dump(report, sys.stdout, indent=2, ensure_ascii=False)
        print()
        return EXIT_OK if errors == 0 else EXIT_ERRORS

    for d in diagnostics:
        print(d)
    status = "failed" if errors else "passed"
    print(f"{source_path}: parse {status} with {_plural(errors, 'error')} and {_plural(warnings, 'warning')}")
    if result:
        summary = _summary(result)
        counts = ", ".join(f"{n} {_PLURALS[Kind(k)] if n != 1 else k}" for k, n in summary["entities"].items() if n)
        print(f"  entities: {counts or 'none'}")
        print("  pens:     " + ", ".join(f"{pen} ({n})" for pen, n in summary["pens"].items()))
        print("  fonts:    " + ", ".join(summary["fonts"]))
    print("  note: layout checks (lane space, pole fit, label collisions) are not implemented yet")
    return EXIT_OK if errors == 0 else EXIT_ERRORS


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="axitime", description="Pen-plotter timelines from .axitl files.")
    parser.add_argument("--version", action="version", version=f"axitime {__version__} (libaxitl {libaxitl.__version__})")
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check", help="validate a .axitl file without drawing anything")
    check.add_argument("file", help="the .axitl source file")
    check.add_argument("--json", action="store_true", help="print a machine-readable report")
    check.set_defaults(handler=cmd_check)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main())
