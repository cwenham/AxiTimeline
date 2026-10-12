"""Reading a per-pen SVG written by ``axitime render``: its metadata, its page and its strokes.

``plot`` only ever works from these files (interpreter spec, "Pipeline"), so this is where it checks that a file
really is one: a single pen, a job hash, and nothing but straight-line paths.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from libaxitl.render import METADATA_NAMESPACE
from libaxitl.svgpath import PathError, flatten, parse_path

_SVG = "{http://www.w3.org/2000/svg}"
_JOB = f"{{{METADATA_NAMESPACE}}}job"
_FILE = f"{{{METADATA_NAMESPACE}}}file"
_HASH = re.compile(r"^[0-9a-f]{64}$")

Point = tuple[float, float]


class PlotFileError(ValueError):
    """A file plot can't use. The message is written for the operator."""


@dataclass(frozen=True)
class FileHash:
    kind: str
    path: str
    sha256: str


@dataclass(frozen=True)
class PlotFile:
    path: Path
    pen: str
    job_hash: str
    source: str  # the .axitl file's name
    now: str | None
    axitime_version: str
    libaxitl_version: str
    job_length_mm: float
    window: tuple[float, float]  # the stretch of the roll this file was rendered for, in mm
    stroke_length_mm: float
    files: tuple[FileHash, ...]
    page: tuple[float, float, float, float]  # viewBox: x, y, width, height in mm
    strokes: tuple[tuple[Point, ...], ...]

    @property
    def stem(self) -> str:
        return Path(self.source).stem


def _number(job: ET.Element, name: str, path: Path) -> float:
    try:
        return float(job.get(name, ""))
    except ValueError:
        raise PlotFileError(f"{path.name} has no usable {name} in its metadata") from None


def load_plot_file(path: Path) -> PlotFile:
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise PlotFileError(f"can't read {path}: {exc}") from None
    job = root.find(f"{_SVG}metadata/{_JOB}")
    if root.tag != f"{_SVG}svg" or job is None:
        raise PlotFileError(f"{path.name} wasn't written by axitime render: it has no axitime job metadata")
    pen = job.get("pen", "")
    if pen == "all":
        raise PlotFileError(f"{path.name} is a preview of every pen; plot one of the per-pen files instead")
    job_hash = job.get("job-hash", "")
    if not _HASH.match(job_hash):
        raise PlotFileError(f"{path.name} has no job hash; render it again with this version of axitime")
    layers = [g for g in root.iter(f"{_SVG}g")]
    if len(layers) != 1 or layers[0].get("id") != f"pen-{pen}":
        raise PlotFileError(f"{path.name} should hold exactly one layer, for the pen {pen}")
    strokes: list[tuple[Point, ...]] = []
    for element in layers[0]:
        if element.tag != f"{_SVG}path":
            raise PlotFileError(f"{path.name} contains a <{element.tag.rsplit('}', 1)[-1]}>, which plot doesn't draw")
        try:
            segments = parse_path(element.get("d", ""))
        except PathError as exc:
            raise PlotFileError(f"{path.name}: {exc}") from None
        if any(seg[0] not in ("M", "L") for seg in segments):
            raise PlotFileError(f"{path.name} has curves in it; files from axitime render contain only straight lines")
        strokes.extend(tuple(line) for line in flatten(segments) if len(line) > 1)
    try:
        page = tuple(float(v) for v in (root.get("viewBox") or "").split())
        assert len(page) == 4
    except (ValueError, AssertionError):
        raise PlotFileError(f"{path.name} has no usable viewBox") from None
    files = tuple(
        FileHash(f.get("kind", ""), f.get("path", ""), f.get("sha256", "")) for f in job.findall(_FILE)
    )
    return PlotFile(
        path=path,
        pen=pen,
        job_hash=job_hash,
        source=job.get("source", path.stem),
        now=job.get("now"),
        axitime_version=job.get("axitime-version", "?"),
        libaxitl_version=job.get("libaxitl-version", "?"),
        job_length_mm=_number(job, "job-length-mm", path),
        window=(_number(job, "window-start-mm", path), _number(job, "window-end-mm", path)),
        stroke_length_mm=_number(job, "stroke-length-mm", path),
        files=files,
        page=page,  # type: ignore[arg-type]
        strokes=tuple(strokes),
    )
