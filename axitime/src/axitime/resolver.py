"""axitime's ``resolve(name)``: includes, illustrations and custom fonts come from the local filesystem.

libaxitl hands over names already joined onto the including file's directory, relative to the same root as
the top-level source path axitime passed in, so a plain read relative to the working directory is right.
"""

from __future__ import annotations

from pathlib import Path


def filesystem_resolver(name: str) -> bytes:
    try:
        return Path(name).read_bytes()
    except FileNotFoundError:
        raise LookupError("no such file") from None
    except IsADirectoryError:
        raise LookupError("it is a directory, not a file") from None
    except PermissionError:
        raise LookupError("permission denied") from None
