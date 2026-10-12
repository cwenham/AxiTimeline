"""The job log: an append-only text file recording every plot run of one job (interpreter spec, "Job log").

It lives beside the per-pen SVGs, named after the source file and the last six characters of the job hash. The
header identifies the job; each run then adds a ``start`` line when it begins and an ``end`` line when it
finishes, so a run that died mid-plot is visible as a ``start`` with no ``end``.
"""

from __future__ import annotations

import datetime as dt
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .plotfile import PlotFile

TITLE = "# axitime job log: append-only; each plot run adds a start line and an end line"


class Match(Enum):
    EXISTING = "existing"  # a log for exactly this job: its runs continue
    NEW = "new"  # the source has never been plotted: this is a new job's first pass
    MISMATCH = "mismatch"  # the source has been plotted before, from a different version


@dataclass(frozen=True)
class Lookup:
    match: Match
    path: Path  # the log for this job (which may not exist yet)
    others: tuple[Path, ...]  # logs for the same source file but other jobs


def log_name(stem: str, job_hash: str) -> str:
    return f"{stem}-{job_hash[-6:]}.log"


def read_header(path: Path) -> dict[str, str]:
    header: dict[str, str] = {}
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if line == "---":
                break
            key, sep, value = line.partition(": ")
            if sep and not line.startswith("#") and key != "file":
                header[key] = value
    return header


def find_job(plot_file: PlotFile, folder: Path) -> Lookup:
    """Which log a file's runs go in, and whether that's allowed (interpreter spec, "Job log")."""
    path = folder / log_name(plot_file.stem, plot_file.job_hash)
    if path.exists() and read_header(path).get("job-hash") == plot_file.job_hash:
        return Lookup(Match.EXISTING, path, ())
    # Same source file, other jobs. A log whose name matches but whose full hash doesn't is another job too.
    others = tuple(
        p
        for p in sorted(folder.glob(f"{plot_file.stem}-??????.log"))
        if read_header(p).get("job-hash") != plot_file.job_hash
    )
    if path.exists():  # a six-character collision with a different job: never share its log
        raise FileExistsError(f"{path.name} belongs to a different job with the same last six hash characters")
    return Lookup(Match.MISMATCH if others else Match.NEW, path, others)


def create(path: Path, plot_file: PlotFile) -> None:
    lines = [
        TITLE,
        f"source: {plot_file.source}",
        f"job-hash: {plot_file.job_hash}",
        f"axitime-version: {plot_file.axitime_version}",
        f"libaxitl-version: {plot_file.libaxitl_version}",
    ]
    if plot_file.now is not None:
        lines.append(f"now: {plot_file.now}")
    lines.append(f"length-mm: {plot_file.job_length_mm:g}")
    lines += [f"file: {f.kind} {f.sha256} {f.path}" for f in plot_file.files]
    lines.append("---")
    with path.open("x", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
        f.flush()
        os.fsync(f.fileno())


def append(path: Path, entry: str, now: dt.datetime | None = None) -> None:
    """Add one timestamped line, flushed to disk at once so a crash loses at most the line being written."""
    stamp = (now or dt.datetime.now()).isoformat(timespec="seconds")
    with path.open("a", encoding="utf-8") as f:
        f.write(f"{stamp} {entry}\n")
        f.flush()
        os.fsync(f.fileno())


def runs(path: Path) -> list[str]:
    """The log's run lines, oldest first."""
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return lines[lines.index("---") + 1 :] if "---" in lines else []
