"""The one seam where libaxitl touches host I/O: fetching includes, illustrations and custom fonts by name.

The host supplies ``resolve(name) -> str | bytes``. Every resource fetched is recorded, with its content, so
the host can hash exactly what the parse used (interpreter spec, "Job log") without re-reading anything.
"""

from __future__ import annotations

import posixpath
from dataclasses import dataclass
from typing import Callable

from .diagnostics import Diagnostics, SourceLocation

Resolver = Callable[[str], "str | bytes"]


@dataclass(frozen=True)
class Resource:
    kind: str  # "include", "illustration" or "font"
    name: str
    content: bytes


def relative_name(including: str, name: str) -> str:
    """``name`` as written in the file ``including``, made relative to the same root as ``including``."""
    return posixpath.normpath(posixpath.join(posixpath.dirname(including), name))


def no_resolver(name: str) -> bytes:
    raise LookupError("no resolver was supplied, so includes, illustrations and custom fonts can't be read")


class Fetcher:
    def __init__(self, resolve: Resolver, sink: Diagnostics):
        self._resolve = resolve
        self._sink = sink
        self._cache: dict[tuple[str, str], bytes | None] = {}
        self.resources: list[Resource] = []

    def fetch(self, kind: str, name: str, location: SourceLocation | None) -> bytes | None:
        """The resource's content, or None (with an error recorded) if it can't be fetched."""
        key = (kind, name)
        if key in self._cache:
            return self._cache[key]
        try:
            content = self._resolve(name)
        except Exception as exc:  # the host's loader can fail in any way it likes
            reason = str(exc) or type(exc).__name__
            self._sink.error(f"missing-{kind}", f"can't read {kind} '{name}': {reason}", location)
            self._cache[key] = None
            return None
        if isinstance(content, str):
            content = content.encode("utf-8")
        elif isinstance(content, (bytes, bytearray)):
            content = bytes(content)
        else:
            self._sink.error(
                f"missing-{kind}",
                f"can't read {kind} '{name}': the resolver returned {type(content).__name__}, not text or bytes",
                location,
            )
            self._cache[key] = None
            return None
        self._cache[key] = content
        self.resources.append(Resource(kind, name, content))
        return content
