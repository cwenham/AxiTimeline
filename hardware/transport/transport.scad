// AxiTimeline paper transport: every printed part, an assembly view, and print layouts.
// Design notes and the layout are in docs/transport.md; build and print notes in README.md here.
//
// Pick what to show or export with `part` (OpenSCAD's Customizer lists them), e.g.
//   openscad -o front_bracket_left.stl -D 'part="front_bracket_left"' transport.scad
// "assembly" shows everything in place; any other name is that part laid out for printing.

include <params.scad>
use <lib.scad>

show_paper = true;  // in the assembly: the paper and rolls
show_board = true;  // in the assembly: the board and AxiDraw
part = "assembly"; // [assembly, back_bracket_left, back_bracket_right, front_bracket_left, front_bracket_right, drive_housing, dancer_guide_full, dancer_guide_plain, flag_slider, roller_half, dancer_half, drive_cone, tail_cone, tail_knob, motor_gear, spacers, rod_collar, pinch_block, pinch_arm, board_jaw, foot]

// ======================================================================================================
// Brackets. Each is modelled on the +x side (the operator's left); the -x ones are built with side = -1,
// which picks that side's features and mirrors the result. A bracket is a 30mm plate (x 245..275) against
// a leg, with its board seat, the leg's cap and cheeks on the outer side, and its bearings' bolts through it.
// ======================================================================================================

module leg_clamp_add(yc) {
    // A cap over the leg's top end, and cheeks either side of it. The cheeks stop below the roller axles'
    // bolt heads, so any head fits there.
    box([plate_out, yc - leg / 2 - 5, leg_top], [plate_out + leg, yc + leg / 2 + 5, -2]);
    for (s = [-1, 1])
        box([plate_out, yc + s * leg / 2, -80], [plate_out + leg, yc + s * (leg / 2 + 5), -36]);
}

module leg_clamp_cut(yc) {
    // Two M5s through the plate into T-nuts in the leg's inner slot, and one through each cheek.
    for (z = [-30, -65]) counterbored_x(yc, z, plate_in, 6, 10, m5, plate_out + 1);
    for (s = [-1, 1]) ycyl(leg_x, -45, yc + s * (leg / 2 - 1), yc + s * (leg / 2 + 6), m5);
}

module seat_add(y0, y1) {
    box([plate_out, y0, -board_t - seat_t], [seat_x1, y1, -board_t]);
    ym = (y0 + y1) / 2;
    hull() {
        box([plate_out, ym - 2, -board_t - seat_t - 0.1], [seat_x1 - 8, ym + 2, -board_t - seat_t]);
        box([plate_out, ym - 2, -55], [plate_out + 0.1, ym + 2, -board_t - seat_t]);
    }
}

// The clamp bolts sit 7 and 17 in from the board's edge (at y0 when edge > 0, at y1 when edge < 0), which
// keeps the back ones clear of the AxiDraw's bar.
function jaw_bolts_y(y0, y1, edge) = edge > 0 ? [y0 + 7, y0 + 17] : [y1 - 7, y1 - 17];

module seat_cut(y0, y1, edge) {
    // Slots for the two clamp bolts, outside the board's edge, with a channel underneath for their nuts
    // (corners up when printed, so its roof needs no bridge).
    for (yy = jaw_bolts_y(y0, y1, edge)) {
        hull() for (xx = jaw_bolt_x) zcyl(xx, yy, -board_t - seat_t - 1, -board_t + 1, m5);
        hull() for (xx = jaw_bolt_x) zhex(xx, yy, -board_t - seat_t - 1, -board_t - seat_t + nut_m5[1], nut_m5[0], rot = 0);
    }
}

// A bolt through the plate for a 50mm roller's axle: head outside, captured nut on the inner face.
module roller_axle_cut(p, slot = 0) {
    roof = plate_in + nut_m8[1];
    hull() for (dy = [-slot, slot]) xhex(p[0] + dy, p[1], plate_in - 1, roof, nut_m8[0]);
    bridge_layers_x(p[0], p[1], roof, nut_m8[0], m8, slot);
    hull() for (dy = [-slot, slot]) xcyl(p[0] + dy, p[1], roof + 2 * layer, plate_out + 1, m8);
}

// The roll motor's pocket, open on the outer side, leaving a skin on the inner face for its four screws.
module motor_pocket_cut(p) {
    box([motor_face_x, p[0] - nema / 2 - 0.5, p[1] - nema / 2 - 0.5],
        [plate_out + 1, p[0] + nema / 2 + 0.5, p[1] + nema / 2 + 0.5]);
    nema_face_holes(p[0], p[1], plate_in - 1, motor_face_x + 1);
}

// The tailstock's captured nut, on the outer face.
module tail_nut_cut(p) {
    xcyl(p[0], p[1], plate_in - 1, plate_out + 1, m8);
    xhex(p[0], p[1], plate_out - nut_m8[1], plate_out + 1, nut_m8[0]);
}

module back_bracket(side) {
    left = side > 0;
    pts = left
        ? [[-168, -2], [-95, -2], [-95, -board_t], [3, -board_t], [3, -104], [-55, -104], [-100, -95], [-130, -82], [-168, -82]]
        : [[-168, -2], [-95, -2], [-95, -board_t], [-45, -board_t], [-45, -95], [-100, -95], [-130, -82], [-168, -82]];
    mirror([left ? 0 : 1, 0, 0]) difference() {
        union() {
            yz_plate(pts, plate_in, plate_out);
            leg_clamp_add(leg_y_back);
            seat_add(board_y0, board_y0 + seat_depth);
        }
        leg_clamp_cut(leg_y_back);
        seat_cut(board_y0, board_y0 + seat_depth, 1);
        roller_axle_cut(back_roller, slot = left ? 0 : 4);   // the right-hand one is the tracking trim
        if (left) {
            xcyl(supply[0], supply[1], plate_in - 1, plate_out + 1, m8);   // the drive cone's axle bolt
            motor_pocket_cut(supply_motor);
        } else {
            tail_nut_cut(supply);
        }
        xcyl(-100, -50, plate_in - 1, plate_out + 1, 18);   // lightening
    }
}

module drive_housing_bolts_cut(through_pocket) {
    for (dz = [-19, 19]) {
        xcyl(drive[0], drive[1] + dz, plate_in - 1, plate_out + 1, m5);
        if (!through_pocket) xhex(drive[0], drive[1] + dz, plate_out - nut_m5[1], plate_out + 1, nut_m5[0]);
    }
}

module front_bracket(side) {
    left = side > 0;
    pts = left
        ? [[335, -board_t], [398, -board_t], [398, 22], [452, 22], [452, -2], [495, -2], [495, 25], [515, 25],
           [515, -82], [440, -82], [434, -152], [376, -152], [360, -100], [335, -100]]
        : [[335, -board_t], [398, -board_t], [398, 22], [452, 22], [452, -2], [495, -2], [495, 25], [515, 25],
           [515, -82], [430, -95], [335, -95]];
    mirror([left ? 0 : 1, 0, 0]) difference() {
        union() {
            yz_plate(pts, plate_in, plate_out);
            leg_clamp_add(leg_y_front);
            seat_add(board_y1 - seat_depth, board_y1);
            if (!left)   // the drive motor stands 7 off the plate, so its shaft enters the coupler by 10
                box([plate_out, drive[0] - 25, drive[1] - 25], [drive_motor_face_x, drive[0] + 25, 22]);
        }
        leg_clamp_cut(leg_y_front);
        seat_cut(board_y1 - seat_depth, board_y1, -1);
        roller_axle_cut(front_roller);
        drive_housing_bolts_cut(!left);
        // The pinch rail's screw: up through the post into a T-nut in the rail's bottom slot. The window
        // below is tall enough to stand an M5 x 16 up in and turn it with a hex key from beneath.
        zcyl((plate_in + plate_out) / 2, rail[0], 0, 26, m5);
        box([plate_in - 1, rail[0] - 6, -22], [plate_out + 1, rail[0] + 6, 14]);
        if (left) {
            xcyl(takeup[0], takeup[1], plate_in - 1, plate_out + 1, m8);
            motor_pocket_cut(takeup_motor);
        } else {
            tail_nut_cut(takeup);
            // The coupler's pocket, open at the top for a hex key, and the drive motor's face.
            box([plate_in + 3, drive[0] - 21, drive[1] - 24], [drive_motor_face_x - 3, drive[0] + 21, 40]);
            xcyl(drive[0], drive[1], plate_in - 1, plate_in + 4, 14);
            nema_face_holes(drive[0], drive[1], drive_motor_face_x - 4, drive_motor_face_x + 1);
        }
    }
}

// The drive roller's bearing housing: bolts to a bracket's inner face through oversize holes, so the roller
// can be set flush with the board and square to the AxiDraw. Modelled for the +x side.
module drive_housing() {
    difference() {
        box([drive_bearing_x - b608[2] / 2, drive[0] - 20, drive[1] - 25], [plate_in, drive[0] + 20, drive[1] + 25]);
        xcyl(drive[0], drive[1], drive_bearing_x - b608[2] / 2 - 1, drive_bearing_x + b608[2] / 2, b608[1] + 2 * fit);
        xcyl(drive[0], drive[1], drive_bearing_x, plate_in + 1, 11);
        for (dz = [-19, 19]) xcyl(drive[0], drive[1] + dz, drive_bearing_x - 5, plate_in + 1, 9);
    }
}

// ======================================================================================================
// Dancer guides: bolted to each leg's inner face, with a slot open at the top for the dancer's axle bolt.
// On one guide per dancer, a flag slider rides the bolt in a recess on the outer face, and two Omron
// EE-SX672 slot sensors screw flat to that face at the top and bottom of the travel.
// ======================================================================================================

guide_x = [257, plate_out];

// dir = +1 at the back (the flag is in front of the axle), -1 at the front. Modelled on the +x side.
// The "full" guide has the slider's recess and the sensors' screw holes; the other guide is "plain" and
// narrower, which keeps it clear of the take-up motor. The back +x and front -x guides are full; each
// full (or plain) guide is the other turned end for end.
module dancer_guide(yd, yleg, dir, full = true) {
    reach = full ? sensor_top_y + sensor[2] - 3 : 14;
    y0 = min(yleg - dir * (leg / 2 + 2), yd + dir * reach);
    y1 = max(yleg - dir * (leg / 2 + 2), yd + dir * reach);
    difference() {
        box([guide_x[0], y0, dancer_bottom - 32], [guide_x[1], y1, full ? dancer_top + 32 : dancer_top + 20]);
        // the axle's slot, open at the top; its bottom is 5 below the bottom of the travel, so the bottom
        // sensor sees the flag before the bolt reaches the end of the slot
        hull() {
            xcyl(yd, dancer_bottom - 5, guide_x[0] - 1, guide_x[1] + 1, m8 + 0.2);
            xcyl(yd, dancer_top + 45, guide_x[0] - 1, guide_x[1] + 1, m8 + 0.2);
        }
        if (full) {
            // the flag slider's recess, open at the top so an overshoot can't jam it
            box([guide_x[1] - 2.5, yd - 8.3, dancer_bottom - 5 - flag_h / 2 - 3], [guide_x[1] + 1, yd + 8.3, dancer_top + 50]);
            // each sensor's two M3s, through the guide into nuts in its inner face
            for (zb = sensor_beams_z, dz = [-1, 1]) {
                ys = yd + dir * sensor_tab_y;
                xhex(ys, zb + dz * sensor_holes / 2, guide_x[0] - 1, guide_x[0] + nut_m3[1], nut_m3[0]);
                bridge_layers_x(ys, zb + dz * sensor_holes / 2, guide_x[0] + nut_m3[1], nut_m3[0], m3);
                xcyl(ys, zb + dz * sensor_holes / 2, guide_x[0] + nut_m3[1] + 2 * layer, guide_x[1] + 1, m3);
            }
        }
        // three M5s into T-nuts in the leg's inner slot
        for (z = [dancer_top, (dancer_top + dancer_bottom) / 2, dancer_bottom])
            counterbored_x(yleg, z, guide_x[0], 5, 10, m5, guide_x[1] + 1);
    }
}

// The flag slider: a block that rides in the guide's recess on the dancer's bolt (washers and nut on its
// outer face), and a carrier holding the flag: a fin parallel to the guide, sensor_slot_x out from its face,
// reaching into each sensor's slot past the beam when the dancer is at that end of its travel. Every face
// starts at z = -flag_h / 2, so it prints on its side. Print it in black: the sensors' infrared passes
// through light-coloured plastic.
module flag_slider(yd, dir) {
    zs = [-flag_h / 2, flag_h / 2];
    fx = guide_x[1] + sensor_slot_x;
    difference() {
        union() {
            box([guide_x[1] - 2.2, yd - 8, zs[0]], [guide_x[1] + 2, yd + 8, zs[1]]);                  // block
            box([guide_x[1], yd + dir * 8, zs[0]], [guide_x[1] + 2, yd + dir * 18, zs[1]]);          // carrier
            box([guide_x[1], yd + dir * 9, zs[0]], [fx + flag_t / 2, yd + dir * 18, zs[1]]);
            box([fx - flag_t / 2, yd + dir * 18, zs[0]], [fx + flag_t / 2, yd + dir * (sensor_top_y + 6), zs[1]]);   // fin
        }
        xcyl(yd, 0, guide_x[1] - 3, guide_x[1] + 3, m8);
    }
}

// An EE-SX672 sensor, for the assembly: its tab flat on the guide's outer face, its slot facing the
// flag, the beam at height zb.
module ee_sx672(yd, dir, zb) {
    ytop = yd + dir * sensor_top_y;
    color("dimgray") {
        difference() {
            box([guide_x[1] + sensor_slot_x - sensor[0] / 2, ytop, zb - sensor[1] / 2],
                [guide_x[1] + sensor_slot_x + sensor[0] / 2, ytop + dir * sensor[2], zb + sensor[1] / 2]);
            box([guide_x[1] + sensor_slot_x - 2.5, ytop - dir, zb - sensor[1]], [guide_x[1] + sensor_slot_x + 2.5, ytop + dir * 9, zb + sensor[1]]);
        }
        box([guide_x[1], yd + dir * (sensor_tab_y - 3.1), zb - 13], [guide_x[1] + 3, yd + dir * (sensor_tab_y + 3.1), zb + 13]);
    }
}

// ======================================================================================================
// Rollers, dancers, roll holders, gears.
// ======================================================================================================

// Half of a 50mm roller, from its middle (x = 0) out to its end face at x = face. The other half is the
// same part turned round. A carbon tube spine runs through both halves; a 608 sits in each end.
// captive_head: the dancers carry their axle bolts captive, head inside, so they need a cavity for it.
module roller_half(face, spine_d, captive_head) {
    pocket = b608[2] + 0.3;
    cavity_d = captive_head ? 18 : 12;   // room for an M8 hex, button or pan head; the edge rollers' bolt tip
    cavity = captive_head ? 7 : 12;
    shoulder = face - pocket - cavity;   // where the spine stops
    bore = spine_d + 2 * fit;
    difference() {
        xcyl(0, 0, 0, face, roller_d);
        xcyl(0, 0, face - pocket, face + 1, b608[1] + 2 * fit);
        xcyl(0, 0, shoulder, face - pocket + 0.01, cavity_d);
        xcyl(0, 0, -1, shoulder + 0.01, bore);
        // Where the spine's bore narrows to a smaller cavity, step in at 45 degrees: the halves print
        // upright, middle end down, so a flat step there would need support.
        if (bore > cavity_d) hull() {
            xcyl(0, 0, shoulder - 0.01, shoulder, bore);
            xcyl(0, 0, shoulder + (bore - cavity_d) / 2, shoulder + (bore - cavity_d) / 2 + 0.01, cavity_d);
        }
        // a small chamfer at the end face
        translate([face, 0, 0]) rotate([0, 90, 0])
            difference() { cylinder(d = roller_d + 2, h = 2, center = true); cylinder(d1 = roller_d - 2, d2 = roller_d + 2, h = 2, center = true); }
    }
}

function spine_len(face, captive_head) = 2 * (face - b608[2] - 0.3 - (captive_head ? 7 : 12)) - 1;

// The drive cone: enters the core's end, with the 48-tooth gear the roll motor turns. It runs on a 608 on
// an M8 bolt through the bracket; the bolt's nut is reached through the cone's open tip. +x side.
module drive_cone() {
    difference() {
        union() {
            hull() { xcyl(0, 0, cone_tip_x, cone_tip_x + 0.01, 20); xcyl(0, 0, cone_base_x, cone_base_x + 0.01, 32); }
            for (a = [0 : 90 : 270]) rotate([a, 0, 0])   // ribs to grip the core
                hull() { box([cone_tip_x + 1, -0.8, 9.5], [cone_tip_x + 1.5, 0.8, 10.5]); box([cone_base_x, -0.8, 15], [cone_base_x + 0.01, 0.8, 17]); }
            xcyl(0, 0, cone_base_x, gear_x[0], 40);
            translate([gear_x[0], 0, 0]) rotate([0, 90, 0]) linear_extrude(gear_x[1] - gear_x[0]) gear2d(gear_m, gear_big);
        }
        xcyl(0, 0, gear_x[1] - b608[2] - 0.3, gear_x[1] + 1, b608[1] + 2 * fit);
        cone_bore(gear_x[1] - b608[2] - 0.3, -1);
    }
}

// The bore through a cone, from its bearing's seat at x = seat towards its tip (dir = -1 along x): a 1.5mm
// flat ring for the bearing's outer race to sit on, then 45 degrees in to 16mm, so it prints without support.
module cone_bore(seat, dir) {
    xcyl(0, 0, cone_tip_x - 1, seat + dir * 1.65, 16);
    hull() { xcyl(0, 0, seat + dir * 1.65, seat + dir * 1.64, 16); xcyl(0, 0, seat - 0.01, seat + 0.01, 19.3); }
}

// The tailstock cone: runs on a 608 clamped between two nuts on an M8x100 bolt, which screws through the
// bracket's captured nut, with the knob on its head. Modelled on the +x side; the -x copy is mirrored.
module tail_cone() {
    hub = [cone_base_x + 5, cone_base_x + 5 + b608[2] + 2];
    difference() {
        union() {
            hull() { xcyl(0, 0, cone_tip_x, cone_tip_x + 0.01, 20); xcyl(0, 0, cone_base_x, cone_base_x + 0.01, 32); }
            for (a = [0 : 90 : 270]) rotate([a, 0, 0])
                hull() { box([cone_tip_x + 1, -0.8, 9.5], [cone_tip_x + 1.5, 0.8, 10.5]); box([cone_base_x, -0.8, 15], [cone_base_x + 0.01, 0.8, 17]); }
            xcyl(0, 0, cone_base_x, hub[0], 40);
            hull() { xcyl(0, 0, hub[0] - 0.01, hub[0], 40); xcyl(0, 0, hub[0] + 5, hub[0] + 5.01, 30); }   // 45 degrees under the flange
            xcyl(0, 0, hub[0] + 5, hub[1], 30);
        }
        xcyl(0, 0, hub[1] - b608[2] - 0.3, hub[1] + 1, b608[1] + 2 * fit);
        cone_bore(hub[1] - b608[2] - 0.3, -1);
    }
}

module tail_knob() {
    difference() {
        union() {
            cylinder(d = 32, h = 12);
            for (a = [0 : 30 : 330]) rotate(a) translate([16, 0, 0]) cylinder(d = 4, h = 12, $fn = 16);
        }
        translate([0, 0, 12 - 5.6]) rotate(30) cylinder(d = nut_m8[0] / cos(30) + 2 * fit, h = 6, $fn = 6);
        translate([0, 0, -1]) cylinder(d = m8, h = 20);
    }
}

// The roll motors' 16-tooth gear, on the 5mm D shaft with an M3 grub screw.
module motor_gear() {
    difference() {
        union() {
            linear_extrude(gear_x[1] - gear_x[0]) gear2d(gear_m, gear_small);
            cylinder(d = 16, h = gear_x[1] - gear_x[0] + 8);
        }
        translate([0, 0, -1]) d_bore(30);
        translate([0, 0, gear_x[1] - gear_x[0] + 4]) rotate([0, 90, 0]) cylinder(d = m3, h = 10);
        translate([4.5, -nut_m3[0] / 2 - fit, gear_x[1] - gear_x[0] + 4 - 2.75 - 2]) cube([nut_m3[1] + 0.3, nut_m3[0] + 2 * fit, 12]);
    }
}

// Spacers that set each bearing's inner race off its bracket or guide:
//   4 x 15mm for the 50mm rollers, 2 x 9mm for the drive cones, 4 x 22mm for the dancers.
module spacers() {
    lens = [plate_in - roller_face, plate_in - roller_face, plate_in - roller_face, plate_in - roller_face, 9, 9, 22, 22, 22, 22];
    for (i = [0 : len(lens) - 1]) translate([(i % 5) * 16, floor(i / 5) * 16, 0])
        difference() { cylinder(d = 11.5, h = lens[i]); translate([0, 0, -1]) cylinder(d = m8, h = lens[i] + 2); }
}

module rod_collar() {
    difference() {
        cylinder(d = 18, h = 8);
        translate([0, 0, -1]) cylinder(d = rod_d + 0.3, h = 10);
        translate([0, 0, 4]) rotate([0, 90, 0]) cylinder(d = m3, h = 10);
        translate([5.5, -nut_m3[0] / 2 - fit, -1]) cube([nut_m3[1] + 0.3, nut_m3[0] + 2 * fit, 6.75]);
    }
}

// ======================================================================================================
// Pinch wheels. Both parts are flat plates in the y-z plane, so they print without supports. The block
// sits under the rail with a lip behind it, held by one M5 through the lip into a T-nut in the rail's rear
// slot; it can sit anywhere along the rail. The arm pivots on the block, with the wheel on an M5 at its front end, beside it.
// An extension spring between M3 pins on the block's lip and the arm's tail (both on the arm's wheel side)
// pulls the tail up and the wheel down; press the tail down to lift the wheel for threading. Modelled for the wheel at x = wheel_x.
// ======================================================================================================

arm_x = [wheel_x + wheel_w / 2 + 0.5, wheel_x + wheel_w / 2 + 6.5];   // the arm, beside the wheel
block_x = [arm_x[1] + 0.5, arm_x[1] + 12.5];                          // the block, beside the arm
pivot = [487, 16];
arm_spring = [501, 18];     // spring pins (M3): on the arm's tail, and on the block's lip
block_spring = [490, 44];

module pinch_block() {
    r0 = rail[0] - rail_size / 2;   // the rail's rear face
    rz = rail[1] - rail_size / 2;   // its bottom face
    pts = [[r0 - 10, rz + rail_size + 4], [r0, rz + rail_size + 4], [r0, rz], [rail[0] + 8, rz],
           [rail[0] + 8, rz - 9], [pivot[0] + 9, pivot[1] - 7], [pivot[0] - 8, pivot[1] - 7], [pivot[0] - 8, pivot[1] + 6], [r0 - 10, rz - 2]];
    difference() {
        yz_plate(pts, block_x[0], block_x[1]);
        ycyl((block_x[0] + block_x[1]) / 2, rail[1], r0 - 11, r0 + 1, m5);         // through the lip into a T-nut
        xcyl(pivot[0], pivot[1], block_x[0] - 1, block_x[1] + 1, m5);
        xcyl(block_spring[0], block_spring[1], block_x[0] - 1, block_x[1] + 1, m3);
    }
}

module pinch_arm() {
    difference() {
        hull() {
            xcyl(pivot[0], pivot[1], arm_x[0], arm_x[1], 14);
            xcyl(pinch_axle[0], pinch_axle[1], arm_x[0], arm_x[1], 14);
            xcyl(arm_spring[0], arm_spring[1], arm_x[0], arm_x[1], 8);
        }
        xcyl(pivot[0], pivot[1], arm_x[0] - 1, arm_x[1] + 1, m5);
        xcyl(pinch_axle[0], pinch_axle[1], arm_x[0] - 1, arm_x[1] + 1, m5);
        xcyl(arm_spring[0], arm_spring[1], arm_x[0] - 1, arm_x[1] + 1, m3);
    }
}

// ======================================================================================================
// Board clamp jaws and feet.
// ======================================================================================================

module board_jaw(y0, y1, edge) {
    difference() {
        box([board_w / 2 - 35, y0, 0], [seat_x1, y1, 5]);
        for (yy = jaw_bolts_y(y0, y1, edge)) hull() for (xx = jaw_bolt_x) zcyl(xx, yy, -1, 6, m5);
    }
}

module foot() {
    difference() {
        union() {
            hull() { translate([-35, -35, 0]) cube([70, 70, 1]); translate([-16, -16, foot_t + 6]) cube([32, 32, 1]); }
            translate([-14, -14, 0]) cube([28, 28, foot_t + 20]);
        }
        translate([-leg / 2 - 0.3, -leg / 2 - 0.3, foot_t]) cube([leg + 0.6, leg + 0.6, 30]);
        for (dx = [-1, 1], dy = [-1, 1]) translate([dx * 26, dy * 26, -1]) cylinder(d = m4, h = 10);
    }
}

// ======================================================================================================
// Assembly.
// ======================================================================================================

module both_sides() { children(); mirror([1, 0, 0]) children(); }

module assembly() {
    // the board and the AxiDraw's bar and legs (simplified)
    if (show_board) {
        color("burlywood", 0.9) box([-board_w / 2, board_y0, -board_t], [board_w / 2, board_y1, 0]);
        color("lightgray") box([-330, -60, 7.5], [330, 0, 45]);
        color("lightgray") both_sides() box([250, axidraw_leg_y[0], 0], [265, axidraw_leg_y[1], 7.5]);
    }
    // legs and feet
    color("silver") both_sides() for (yc = [leg_y_back, leg_y_front])
        box([leg_x - leg / 2, yc - leg / 2, leg_top - leg_len], [leg_x + leg / 2, yc + leg / 2, leg_top]);
    color("tan") both_sides() for (yc = [leg_y_back, leg_y_front]) translate([leg_x, yc, table_z]) foot();
    color("whitesmoke", 0.3) box([-500, -220, table_z - 2], [500, 560, table_z]);
    // brackets
    color("steelblue") { back_bracket(1); back_bracket(-1); front_bracket(1); front_bracket(-1); }
    color("cornflowerblue") both_sides() drive_housing();
    color("cornflowerblue") { both_sides() board_jaw(board_y0, board_y0 + seat_depth, 1);
                              both_sides() board_jaw(board_y1 - seat_depth, board_y1, -1); }
    // dancer guides, flag sliders and sensors (on the back +x and front -x guides)
    color("teal") {
        dancer_guide(dancer_y_back, leg_y_back, 1, true);
        mirror([1, 0, 0]) dancer_guide(dancer_y_back, leg_y_back, 1, false);
        dancer_guide(dancer_y_front, leg_y_front, -1, false);
        mirror([1, 0, 0]) dancer_guide(dancer_y_front, leg_y_front, -1, true);
    }
    color("orange") {
        translate([0, 0, (dancer_top + dancer_bottom) / 2]) {
            flag_slider(dancer_y_back, 1);
            mirror([1, 0, 0]) flag_slider(dancer_y_front, -1);
        }
    }
    for (zb = sensor_beams_z) { ee_sx672(dancer_y_back, 1, zb); mirror([1, 0, 0]) ee_sx672(dancer_y_front, -1, zb); }
    // rollers and dancers
    color("white") both_sides() {
        translate([0, back_roller[0], back_roller[1]]) roller_half(roller_face, 18, false);
        translate([0, front_roller[0], front_roller[1]]) roller_half(roller_face, 18, false);
        translate([0, dancer_y_back, (dancer_top + dancer_bottom) / 2]) roller_half(dancer_face, 14, true);
        translate([0, dancer_y_front, (dancer_top + dancer_bottom) / 2]) roller_half(dancer_face, 14, true);
    }
    // the drive roller, its collars and the coupler
    color("dimgray") xcyl(drive[0], drive[1], drive_bearing_x + 3.5, -drive_rod_end, rod_d);
    color("gold") { xcyl(drive[0], drive[1], -plate_in - 5, -plate_in - 5 - coupler[1], coupler[0]); }
    color("orange") both_sides() translate([drive_bearing_x - 3.5 - 8, drive[0], drive[1]]) rotate([0, 90, 0]) rod_collar();
    // the tailstocks' M8x100 bolts and knobs
    color("silver") for (p = [supply, takeup]) xcyl(p[0], p[1], -cone_tip_x, -(plate_out + 22), 8);
    color("orange") for (p = [supply, takeup]) translate([-(plate_out + 10), p[0], p[1]]) rotate([0, -90, 0]) tail_knob();
    // rolls between their cones (drawn 60 across), cones, gears and motors
    if (show_paper) color("palegreen", 0.8) for (p = [supply, takeup]) xcyl(p[0], p[1], -paper_w / 2, paper_w / 2, 60);
    color("orange") for (p = [supply, takeup]) {
        translate([0, p[0], p[1]]) drive_cone();
        translate([0, p[0], p[1]]) mirror([1, 0, 0]) tail_cone();
    }
    color("orange") for (p = [supply_motor, takeup_motor])
        translate([gear_x[0], p[0], p[1]]) rotate([0, 90, 0]) motor_gear();
    nema_body(supply_motor[0], supply_motor[1], motor_face_x);
    nema_body(takeup_motor[0], takeup_motor[1], motor_face_x);
    nema_body(drive[0], drive[1], -drive_motor_face_x);
    // pinch rail, blocks, arms and wheels
    color("silver") box([-500, rail[0] - rail_size / 2, rail[1] - rail_size / 2], [500, rail[0] + rail_size / 2, rail[1] + rail_size / 2]);
    color("orange") both_sides() { pinch_block(); pinch_arm(); }
    color("black") both_sides() xcyl(pinch_axle[0], pinch_axle[1], wheel_x - wheel_w / 2, wheel_x + wheel_w / 2, wheel_d);
    // the paper (a thin sheet along its path, flat part only)
    if (show_paper) color("seagreen", 0.6) box([-paper_w / 2, back_roller[0], 0], [paper_w / 2, front_roller[0], 0.3]);
}

// ======================================================================================================
// Print layouts: each part laid flat, its largest face down.
// ======================================================================================================

module flat_x(side = 1) {   // lay a part modelled in the y-z plane on its inner face
    translate([0, 0, -plate_in]) rotate([0, side > 0 ? -90 : 90, 0]) children();
}

if (part == "assembly") assembly();
else if (part == "back_bracket_left") flat_x(1) back_bracket(1);
else if (part == "back_bracket_right") flat_x(-1) back_bracket(-1);
else if (part == "front_bracket_left") flat_x(1) front_bracket(1);
else if (part == "front_bracket_right") flat_x(-1) front_bracket(-1);
else if (part == "drive_housing") translate([0, 0, plate_in]) rotate([0, 90, 0]) drive_housing();
else if (part == "dancer_guide_full") translate([0, 0, -guide_x[0]]) rotate([0, -90, 0]) dancer_guide(dancer_y_back, leg_y_back, 1, true);
else if (part == "dancer_guide_plain") translate([0, 0, -guide_x[0]]) rotate([0, -90, 0]) dancer_guide(dancer_y_front, leg_y_front, -1, false);
else if (part == "flag_slider") translate([0, 0, flag_h / 2]) flag_slider(dancer_y_back, 1);
else if (part == "roller_half") rotate([0, -90, 0]) roller_half(roller_face, 18, false);
else if (part == "dancer_half") rotate([0, -90, 0]) dancer_half_print();
else if (part == "drive_cone") translate([0, 0, gear_x[1]]) rotate([0, 90, 0]) drive_cone();
else if (part == "tail_cone") translate([0, 0, cone_base_x + 5 + b608[2] + 2]) rotate([0, 90, 0]) tail_cone();
else if (part == "tail_knob") tail_knob();
else if (part == "motor_gear") motor_gear();
else if (part == "spacers") spacers();
else if (part == "rod_collar") rod_collar();
else if (part == "pinch_block") translate([0, 0, -block_x[0]]) rotate([0, -90, 0]) pinch_block();
else if (part == "pinch_arm") translate([0, 0, -arm_x[0]]) rotate([0, -90, 0]) pinch_arm();
else if (part == "board_jaw") board_jaw(0, seat_depth, 1);
else if (part == "foot") foot();

module dancer_half_print() { roller_half(dancer_face, 14, true); }
