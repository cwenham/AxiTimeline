#!/bin/sh
# Export every printed part of the paper transport to stl/, laid out for printing, and check each one fits
# the print bed. Usage: ./build.sh [part ...]   (no arguments builds them all)
set -e
cd "$(dirname "$0")"
OPENSCAD=${OPENSCAD:-/Applications/OpenSCAD.app/Contents/MacOS/OpenSCAD}
PARTS="back_bracket_left back_bracket_right front_bracket_left front_bracket_right drive_motor_mount drive_housing
dancer_guide_full dancer_guide_plain flag_slider roller_half dancer_half drive_cone
tail_cone tail_knob motor_gear spacers rod_collar pinch_block pinch_arm board_jaw foot"
[ $# -gt 0 ] && PARTS="$*"
mkdir -p stl
for p in $PARTS; do
    echo "exporting $p"
    "$OPENSCAD" -o "stl/$p.stl" -D "part=\"$p\"" transport.scad 2> "stl/$p.log" || { cat "stl/$p.log"; exit 1; }
    if grep -q -i "warning" "stl/$p.log"; then grep -i "warning" "stl/$p.log"; fi
done
python3 check_fit.py stl/*.stl
