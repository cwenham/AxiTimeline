"""The plotter's settings: built-in AxiDraw SE/A3 defaults, overridden by a small TOML file.

The file is ``~/.config/axitime/plotter.toml`` unless ``--config`` names another. Every key is optional::

    [plotter]
    travel_along_mm = 297      # the AxiDraw's Y travel: the roll runs under its base beam, along Y
    travel_across_mm = 430     # its X travel, across the roll
    strip_mm = 250             # how much of the roll is drawn before the paper moves on
    origin_along_mm = 10       # where each strip starts, measured from the AxiDraw's home along Y
    origin_across_mm = 5       # where the page's nearer edge sits, measured from home along X
    feed = "towards-front"     # which way the paper moves on: "towards-front" (out from under the base beam,
                               # towards the operator) or "towards-back"
    pen_pos_up = 60            # pyaxidraw pen heights and speeds, as percentages
    pen_pos_down = 40
    speed_pendown = 25
    speed_penup = 75

    [transport]
    kind = "manual"            # the operator moves the paper on between strips
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, fields
from pathlib import Path

DEFAULT_PATH = Path.home() / ".config" / "axitime" / "plotter.toml"


FEEDS = ("towards-front", "towards-back")


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class PlotterConfig:
    travel_along_mm: float = 297.0  # AxiDraw SE/A3, with the roll along its Y axis
    travel_across_mm: float = 430.0
    strip_mm: float = 250.0
    origin_along_mm: float = 10.0
    origin_across_mm: float = 5.0
    feed: str = "towards-front"
    pen_pos_up: int = 60
    pen_pos_down: int = 40
    speed_pendown: int = 25
    speed_penup: int = 75
    transport: str = "manual"
    source: str = "built-in AxiDraw SE/A3 defaults"

    def check(self) -> None:
        if self.strip_mm <= 0:
            raise ConfigError("strip_mm must be more than zero")
        if self.origin_along_mm < 0 or self.origin_across_mm < 0:
            raise ConfigError("origin_along_mm and origin_across_mm can't be negative")
        if self.origin_along_mm + self.strip_mm > self.travel_along_mm:
            raise ConfigError(
                f"a {self.strip_mm:g}mm strip starting {self.origin_along_mm:g}mm from home doesn't fit the "
                f"plotter's {self.travel_along_mm:g}mm of travel along the roll"
            )
        if self.feed not in FEEDS:
            raise ConfigError(f"feed must be {FEEDS[0]} or {FEEDS[1]}, not '{self.feed}'")
        if self.transport != "manual":
            raise ConfigError(
                f"transport kind '{self.transport}' isn't supported yet; only 'manual' is, until the paper "
                "transport's controller protocol is specified (docs/known-gaps.md)"
            )

    def fits_across(self, page_height_mm: float) -> bool:
        """Whether a page this tall (the finished width plus crop-mark margins) is within reach across the roll."""
        return self.origin_across_mm + page_height_mm <= self.travel_across_mm


def load_config(path: Path | None = None) -> PlotterConfig:
    """The settings from ``path`` (or the default file, if it exists) over the built-in defaults."""
    chosen = path or DEFAULT_PATH
    if path is None and not chosen.exists():
        config = PlotterConfig()
        config.check()
        return config
    try:
        data = tomllib.loads(chosen.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"can't read {chosen}: {exc}") from None
    known = {f.name: f.type for f in fields(PlotterConfig) if f.name not in ("transport", "source")}
    values: dict = {}
    for key, value in (data.get("plotter") or {}).items():
        if key not in known:
            raise ConfigError(f"{chosen}: [plotter] has no setting '{key}'")
        if known[key] == "str":
            if not isinstance(value, str):
                raise ConfigError(f"{chosen}: {key} must be a word in quotes")
            values[key] = value
            continue
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ConfigError(f"{chosen}: {key} must be a number")
        values[key] = int(value) if known[key] == "int" else float(value)
    transport = data.get("transport") or {}
    unknown = set(data) - {"plotter", "transport"}
    if unknown:
        raise ConfigError(f"{chosen}: unknown section [{sorted(unknown)[0]}]")
    config = PlotterConfig(**values, transport=str(transport.get("kind", "manual")), source=str(chosen))
    config.check()
    return config
