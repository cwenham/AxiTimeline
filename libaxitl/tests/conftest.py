import pytest


class Files:
    """An in-memory ``resolve``: a dict of name → content that records every name asked for."""

    def __init__(self, files: dict[str, str | bytes]):
        self.files = files
        self.requested: list[str] = []

    def __call__(self, name: str):
        self.requested.append(name)
        if name not in self.files:
            raise LookupError("no such file")
        return self.files[name]


@pytest.fixture
def make_files():
    """Build an in-memory resolver: ``make_files({"a.axitl": "..."})``."""
    return Files
