#!/bin/sh
# Render the transport's assembly from a few angles for the READMEs, with a timeline part-way through
# plotting on the paper (examples/flight.axitl). Needs OpenSCAD, Inkscape (to outline the pen strokes, since
# OpenSCAD imports SVG shapes as filled) and uv. Writes ../../docs/images/transport-*.png.
set -e
cd "$(dirname "$0")"
OPENSCAD=${OPENSCAD:-/Applications/OpenSCAD.app/Contents/MacOS/OpenSCAD}
INKSCAPE=${INKSCAPE:-/Applications/Inkscape.app/Contents/MacOS/inkscape}
HERE=$(pwd)
INK="$HERE/views/ink"
IMAGES="$HERE/../../docs/images"
rm -rf "$INK" && mkdir -p "$INK"

# The first 60cm of the timeline, one SVG per pen, each with its strokes outlined. The strokes are drawn
# 0.8mm wide rather than the pens' 0.3, so they can be seen at this scale.
uv run axitime render ../../examples/flight.axitl -o "$INK" --length 60cm > /dev/null
list=""
for f in "$INK"/flight-*.svg; do
    case "$f" in *-preview.svg|*-outlined.svg) continue ;; esac
    grep -q 'stroke-length-mm="0"' "$f" && continue
    colour=$(grep -o 'stroke="#[0-9a-fA-F]*"' "$f" | head -1 | cut -d'"' -f2)
    out="${f%.svg}-outlined.svg"
    # One path per stroke: OpenSCAD drops parts of a long path whose outline overlaps itself.
    python3 - "$f" <<'PY'
import re, sys
path = sys.argv[1]
svg = open(path).read()
def split(m):
    attrs, d = re.sub(r'\s*id="[^"]*"', "", m.group(1)), m.group(2)
    return "".join(f'<path{attrs} d="{"M" + part.strip()}"/>' for part in d.split("M") if part.strip())
svg = re.sub(r'<path([^>]*?) d="([^"]*)"\s*/>', split, svg)
svg = re.sub(r'stroke-width="[0-9.]*"', 'stroke-width="0.8"', svg)
open(path, "w").write(svg)
PY
    "$INKSCAPE" "$f" --actions="select-all:all;object-stroke-to-path;export-filename:$out;export-plain-svg;export-do" 2> /dev/null
    list="$list${list:+, }[\"$out\", \"$colour\"]"
done

view() {  # name, projection, camera (translate x,y,z, rotate x,y,z, distance), extra -D settings
    name=$1; projection=$2; camera=$3; shift 3
    echo "rendering transport-$name.png"
    "$OPENSCAD" -o "$IMAGES/transport-$name.png" -D "ink=[$list]" "$@" --camera="$camera" \
        --imgsize=1600,1100 --colorscheme=Tomorrow --projection="$projection" transport.scad 2> /dev/null
}

view front    p "0,170,-110,60,0,215,1650"   # from the operator's side, front right
view assembly p "0,150,-120,58,0,35,1750"    # from behind the AxiDraw, back left
view cutaway  o "0,170,-140,90,0,90,1400" -D cutaway=true   # from the left, the near half cut away
view closeup  p "-10,290,0,52,0,262,720"     # the pen and the timeline, from the operator's right
