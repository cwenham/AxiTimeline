"""The job hash: one SHA-256 that identifies a job exactly (interpreter spec, "Job log").

The hash covers everything that decides what goes on the paper: the flattened source, both versions, the
resolved ``now`` when the timeline uses it, and the content of every illustration and custom font. It is
computed over a text preimage with a fixed format, so two machines (or two implementations) always agree:

    axitimeline-job 1
    libaxitl 0.1.0
    axitime 0.1.0
    now 2026                                   (only when the timeline ends at now)
    resource <kind> <sha256> <path>            (one per illustration and custom font, sorted)
    source <length of the flattened text in bytes>
    <the flattened text>

Resource content is hashed with line endings normalised to LF and any UTF-8 byte-order mark dropped, so a
Windows checkout of the same files hashes the same. Resource paths are relative to the main ``.axitl`` file's
folder, so the hash doesn't depend on where axitime was run from. Includes need no line: their text is
already in the flattened source.
"""

from __future__ import annotations

import hashlib
import posixpath
from dataclasses import dataclass

import libaxitl
from libaxitl import ParseResult, ResolvedLayout

from . import __version__

SCHEME = "axitimeline-job 1"


@dataclass(frozen=True)
class ResourceHash:
    kind: str  # include, illustration or font
    path: str  # relative to the main file's folder
    sha256: str


def normalised(content: bytes) -> bytes:
    """Resource content as hashed: LF line endings, no UTF-8 byte-order mark."""
    return content.removeprefix(b"\xef\xbb\xbf").replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def resource_hashes(result: ParseResult, source_path: str) -> list[ResourceHash]:
    """A hash of every file the job read through ``resolve``, includes too (for the job log's header)."""
    folder = posixpath.dirname(source_path) or "."
    found = {
        (r.kind, posixpath.relpath(r.name, folder)): hashlib.sha256(normalised(r.content)).hexdigest()
        for r in result.resources
    }
    return [ResourceHash(kind, path, digest) for (kind, path), digest in sorted(found.items())]


def preimage(result: ParseResult, resolved: ResolvedLayout, source_path: str) -> bytes:
    lines = [SCHEME, f"libaxitl {libaxitl.__version__}", f"axitime {__version__}"]
    if resolved.now is not None:
        lines.append(f"now {resolved.now}")
    for r in resource_hashes(result, source_path):
        if r.kind != "include":
            lines.append(f"resource {r.kind} {r.sha256} {r.path}")
    source = result.flattened_text.encode("utf-8")
    lines.append(f"source {len(source)}")
    return ("\n".join(lines) + "\n").encode("utf-8") + source


def job_hash(result: ParseResult, resolved: ResolvedLayout, source_path: str) -> str:
    return hashlib.sha256(preimage(result, resolved, source_path)).hexdigest()
