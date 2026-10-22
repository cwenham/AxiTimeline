// Helpers for transport.scad: holes along x, nut traps, a NEMA 17 face, and an involute spur gear.

include <params.scad>

// A cylinder along x from x0 to x1, centred at [y, z].
module xcyl(y, z, x0, x1, d) {
    translate([min(x0, x1), y, z]) rotate([0, 90, 0]) cylinder(d = d, h = abs(x1 - x0));
}

// A cylinder along y from y0 to y1, centred at [x, z].
module ycyl(x, z, y0, y1, d) {
    translate([x, min(y0, y1), z]) rotate([-90, 0, 0]) cylinder(d = d, h = abs(y1 - y0));
}

// A cylinder along z from z0 to z1, centred at [x, y].
module zcyl(x, y, z0, z1, d) {
    translate([x, y, min(z0, z1)]) cylinder(d = d, h = abs(z1 - z0));
}

// A hexagonal nut trap along z from z0 to z1, centred at [x, y].
module zhex(x, y, z0, z1, af) {
    translate([x, y, min(z0, z1)]) rotate([0, 0, 30]) cylinder(d = af / cos(30) + 2 * fit, h = abs(z1 - z0), $fn = 6);
}

// A hexagonal nut trap along x from x0 to x1, centred at [y, z]; af is the size across flats.
module xhex(y, z, x0, x1, af) {
    translate([min(x0, x1), y, z]) rotate([0, 90, 0]) rotate([0, 0, 30])
        cylinder(d = af / cos(30) + 2 * fit, h = abs(x1 - x0), $fn = 6);
}

// A slot along x, from [y0, z0] to [y1, z1] in the y-z plane, width d.
module xslot(p0, p1, x0, x1, d) {
    hull() { xcyl(p0[0], p0[1], x0, x1, d); xcyl(p1[0], p1[1], x0, x1, d); }
}

// A polygon in the y-z plane, extruded along x from x0 to x1.
module yz_plate(points, x0, x1) {
    translate([min(x0, x1), 0, 0]) rotate([90, 0, 90]) linear_extrude(abs(x1 - x0)) polygon(points);
}

// A box from [x0, y0, z0] to [x1, y1, z1].
module box(p0, p1) {
    translate([min(p0[0], p1[0]), min(p0[1], p1[1]), min(p0[2], p1[2])])
        cube([abs(p1[0] - p0[0]), abs(p1[1] - p0[1]), abs(p1[2] - p0[2])]);
}

// Holes for a NEMA 17's face (boss and four M3s) through x0..x1, the motor's axis at [y, z].
module nema_face_holes(y, z, x0, x1) {
    xcyl(y, z, x0, x1, nema_boss + 1);
    for (dy = [-1, 1], dz = [-1, 1]) xcyl(y + dy * nema_holes / 2, z + dz * nema_holes / 2, x0, x1, m3);
}

// A NEMA 17 body, for the assembly: face at x = face_x, body running away from the paper.
module nema_body(y, z, face_x, len = 38) {
    s = sign(face_x);
    color("dimgray") box([face_x, y - nema / 2, z - nema / 2], [face_x + s * len, y + nema / 2, z + nema / 2]);
    color("silver") xcyl(y, z, face_x, face_x - s * 22, 5);
}

// ---- Involute spur gear ----------------------------------------------------------------------------------

function _inv(rb, t) = rb * [cos(t * 180 / PI) + t * sin(t * 180 / PI), sin(t * 180 / PI) - t * cos(t * 180 / PI)];
function _rot(p, a) = [p[0] * cos(a) - p[1] * sin(a), p[0] * sin(a) + p[1] * cos(a)];

// A 2D spur gear: module m, n teeth, 20 degree pressure angle. backlash is the arc taken off each tooth at
// the pitch circle, so two printed gears mesh without binding.
module gear2d(m, n, backlash = 0.2, steps = 10) {
    rp = m * n / 2;
    rb = rp * cos(20);
    ro = rp + m;
    rr = rp - 1.25 * m;
    tp = sqrt(pow(rp / rb, 2) - 1);
    phip = tp * 180 / PI - atan(tp);                    // polar angle of the involute at the pitch circle
    half = 90 / n - (backlash / 2) / rp * 180 / PI;    // half the tooth's angular thickness at the pitch circle
    t0 = rr > rb ? sqrt(pow(rr / rb, 2) - 1) : 0;
    t1 = sqrt(pow(ro / rb, 2) - 1);
    a = -half - phip;
    flank = [for (i = [0 : steps]) _rot(_inv(rb, t0 + (t1 - t0) * i / steps), a)];
    root_a = atan2(flank[0][1], flank[0][0]);
    tooth = concat(
        [[rr * 0.98 * cos(root_a), rr * 0.98 * sin(root_a)]],
        flank,
        [for (i = [steps : -1 : 0]) [flank[i][0], -flank[i][1]]],
        [[rr * 0.98 * cos(root_a), -rr * 0.98 * sin(root_a)]]);
    union() {
        circle(r = rr);
        for (k = [0 : n - 1]) rotate(k * 360 / n) polygon(tooth);
    }
}

function gear_od(m, n) = m * (n + 2);

// A D-shaped bore for a NEMA 17's 5mm shaft (flat 0.5 deep).
module d_bore(h) {
    intersection() {
        cylinder(d = 5 + 2 * fit, h = h);
        translate([-3, -3, 0]) cube([6, 3 + 2.0 + fit, h]);
    }
}
