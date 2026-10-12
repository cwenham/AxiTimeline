"""Reading what layout needs from an illustration's SVG: its intrinsic size, for the aspect ratio (§3.5)."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

# CSS absolute units, in px (96 px to the inch), so width and height compare even if written differently.
_PX_PER = {"": 1.0, "px": 1.0, "in": 96.0, "cm": 96 / 2.54, "mm": 96 / 25.4, "pt": 96 / 72, "pc": 16.0}
_LENGTH = re.compile(r"^\s*([0-9]*\.?[0-9]+(?:[eE][-+]?\d+)?)\s*(px|in|cm|mm|pt|pc)?\s*$")


class IllustrationError(ValueError):
    pass


def _length(value: str | None) -> float | None:
    if value is None:
        return None
    m = _LENGTH.match(value)
    if not m:
        return None  # percentages and the like don't give an intrinsic size
    return float(m.group(1)) * _PX_PER[m.group(2) or ""]


def intrinsic_size(content: str | bytes, name: str) -> tuple[float, float]:
    """The illustration's intrinsic (width, height): from its width/height attributes, else its viewBox."""
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise IllustrationError(f"illustration '{name}' is not readable SVG ({exc})") from None
    if root.tag.rsplit("}", 1)[-1] != "svg":
        raise IllustrationError(f"illustration '{name}' is not an SVG document")
    width, height = _length(root.get("width")), _length(root.get("height"))
    if not (width and height):
        box = (root.get("viewBox") or "").replace(",", " ").split()
        try:
            width, height = float(box[2]), float(box[3])
        except (IndexError, ValueError):
            raise IllustrationError(
                f"illustration '{name}' has no usable size: give its <svg> a width and height, or a viewBox"
            ) from None
    if width <= 0 or height <= 0:
        raise IllustrationError(f"illustration '{name}' has a zero or negative size")
    return width, height
