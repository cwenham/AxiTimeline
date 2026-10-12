# Vendored: axidrawinternal 3.9.6

`axidrawinternal-3.9.6-py2.py3-none-any.whl` is copied unmodified from Evil Mad Scientist's AxiDraw Python API
3.9.6 (`https://cdn.evilmadscientist.com/dl/ad/public/AxiDraw_API.zip`, `prebuilt_dependencies/`). It is
licensed under the GNU GPL v2, like the rest of the AxiDraw software; the wheel contains its Python source.

Why it's here: the AxiDraw API (`axicli`, which provides `pyaxidraw`) isn't on PyPI, and its `setup.py` points
at this wheel by a temporary file path inside the unpacked zip. A uv lockfile would record that path from one
machine's cache, which doesn't exist on any other. So the workspace overrides that requirement with this copy
(`[tool.uv] override-dependencies` and `[tool.uv.sources]` in the root `pyproject.toml`).

Install the AxiDraw support with `uv sync --extra axidraw`. When EMS releases a new API version, update the URL
in `axitime/pyproject.toml` and replace this wheel with the one from the new zip.
