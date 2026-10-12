"""Diagnostics shared by every libaxitl stage.

Each diagnostic has a stable kebab-case ``code`` so hosts can filter or script on it (``axitime check --json``)
without parsing the human-readable message.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Severity(Enum):
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True)
class SourceLocation:
    """Where something came from: the resource name as passed to ``resolve`` (or the top-level source name)."""

    source: str
    line: int
    column: int | None = None

    def __str__(self) -> str:
        if self.column is None:
            return f"{self.source}:{self.line}"
        return f"{self.source}:{self.line}:{self.column}"


@dataclass(frozen=True)
class Diagnostic:
    severity: Severity
    code: str
    message: str
    location: SourceLocation | None = None

    def __str__(self) -> str:
        where = f"{self.location}: " if self.location else ""
        return f"{where}{self.severity.value}: {self.message} [{self.code}]"


class AxitlError(Exception):
    """Raised when a stage cannot produce a result.

    Carries every diagnostic collected up to that point, warnings included, so a host can report them all.
    """

    def __init__(self, diagnostics: list[Diagnostic] | tuple[Diagnostic, ...]):
        self.diagnostics = tuple(diagnostics)
        errors = [d for d in self.diagnostics if d.severity is Severity.ERROR]
        summary = str(errors[0]) if errors else "failed"
        if len(errors) > 1:
            summary += f" (and {len(errors) - 1} more error{'s' if len(errors) > 2 else ''})"
        super().__init__(summary)

    @property
    def errors(self) -> tuple[Diagnostic, ...]:
        return tuple(d for d in self.diagnostics if d.severity is Severity.ERROR)


class Diagnostics:
    """Collects diagnostics during a stage, in the order they were found."""

    def __init__(self) -> None:
        self.items: list[Diagnostic] = []

    def error(self, code: str, message: str, location: SourceLocation | None = None) -> None:
        self.items.append(Diagnostic(Severity.ERROR, code, message, location))

    def warning(self, code: str, message: str, location: SourceLocation | None = None) -> None:
        self.items.append(Diagnostic(Severity.WARNING, code, message, location))

    @property
    def has_errors(self) -> bool:
        return any(d.severity is Severity.ERROR for d in self.items)

    def raise_if_errors(self) -> None:
        if self.has_errors:
            raise AxitlError(self.items)
