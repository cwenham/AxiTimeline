"""Keep the tests from reading this machine's own plotter settings (~/.config/axitime/plotter.toml)."""

import pytest

from axitime import config


@pytest.fixture(autouse=True)
def built_in_plotter_settings(monkeypatch, tmp_path_factory):
    monkeypatch.setattr(config, "DEFAULT_PATH", tmp_path_factory.getbasetemp() / "no-plotter.toml")
