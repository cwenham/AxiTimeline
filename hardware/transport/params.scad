// Shared dimensions for the paper transport (docs/transport.md). All millimetres.
//
// Coordinates, as in the doc and the side-view drawing:
//   x  across the paper, from its centreline; +x is the operator's LEFT (the operator stands at +y, facing -y)
//   y  along the paper, from the front face of the AxiDraw's bar; +y is towards the operator
//   z  up, from the board's top surface
// Every part is modelled in these coordinates, so transport.scad's assembly needs no placing. Each part's
// print module then lays it flat on the bed.

$fn = 64;

// ---- The board and the AxiDraw (measured) --------------------------------------------------------------
board_t = 6.5;
board_y0 = -85;            // back edge (the bar's rear face is 25 in front of it)
board_y1 = 365;            // front edge (450 deep)
board_w = 640;
axidraw_leg_y = [-93, 33];  // its legs, 15 wide, 500 apart inside
board_shift = 15;          // how far the board may sit off-centre from the pen's travel; the clamps' slots allow it

// ---- Paper and rollers ---------------------------------------------------------------------------------
paper_w = 430;
core_bore = 26;
roller_d = 50;
roller_face = 230;         // edge rollers run x -230..230, clear of the drive roller's bearing housings
dancer_face = 235;         // dancers are a little shorter, to leave room for the endstop flag
back_roller = [-128, -25];  // [y, z] of the axle
front_roller = [460, -25];
supply = [-73, -75];        // [y, z] of the roll's axis
takeup = [405, -75];
dancer_y_back = -128;
dancer_y_front = 460;
dancer_top = -150;         // axle height at the top and bottom of the dancers' travel
dancer_bottom = -260;

// ---- Drive roller and pinch wheels ---------------------------------------------------------------------
rod_d = 8;                 // the 8mm steel rod, gritted to about 8.5
grit = 0.25;
drive = [425, -(rod_d / 2 + grit)];
drive_bearing_x = 236.5;   // centre of each drive-roller 608 (they sit x 233..240)
wheel_d = 25;              // the hard-plastic pinch wheels, on M5
wheel_w = 8;               // measure yours; the arm's fork is cut to fit
wheel_x = paper_w / 2 - 8; // each wheel runs in the outer 15 of the paper
pinch_axle = [drive[0], wheel_d / 2];
rail = [505, 35];           // centre of the 20x20 pinch rail
rail_size = 20;

// ---- Structure -----------------------------------------------------------------------------------------
plate_in = 245;            // brackets' inner face (|x|)
plate_out = 275;           // brackets' outer face, against the leg
leg = 20;                  // 2020 extrusion legs, 300 long, standing on end
leg_len = 300;
leg_x = plate_out + leg / 2;       // |x| of each leg's centre
leg_y_back = -153;                 // leg centres: behind the back roller, in front of the front roller
leg_y_front = 485;
leg_top = -12;                     // each leg's top end; the bracket's cap sits on it
foot_t = 5;
table_z = leg_top - leg_len - foot_t;   // -317
seat_t = 8;                        // the board rests on seat flanges, 8 thick, under its corners
seat_depth = 30;
seat_x1 = 350;                     // seat flanges reach out to |x| 350, past the board's side edge
jaw_bolt_x = [325, 345];           // the clamp bolts can sit anywhere along this slot, outside the board

// ---- Roll holders, gears and motors --------------------------------------------------------------------
cone_tip_x = 205;          // the cones enter each end of the core by 10
cone_base_x = 215;
flange_x = 226;            // drive cone: flange and hub run 215..226, gear 226..236
gear_x = [226, 236];
gear_m = 1.5;
gear_small = 16;           // on the motor
gear_big = 48;             // on the cone: 3:1
gear_cd = gear_m * (gear_small + gear_big) / 2;   // 48
motor_skin = 3;            // roll motors bolt to a 3mm skin at the bracket's inner face
motor_face_x = plate_in + motor_skin;              // 248
supply_motor = [supply[0] + gear_cd, supply[1]];   // in front of the supply cone, under the board
takeup_motor = [takeup[0], takeup[1] - gear_cd];   // below the take-up cone
drive_motor_face_x = 285;  // the drive motor stands 10 off the bracket, so its shaft enters the coupler by 12
coupler = [19, 25];        // 5-to-8mm flexible beam coupler, bought: diameter, length
drive_rod_end = 261;       // the drive rod runs from x 240 (its +x bearing) to -261, 11 into the coupler: 501 long
tail_travel = 15;          // the tailstock screw's travel

// ---- Bought parts --------------------------------------------------------------------------------------
b608 = [8, 22, 7];
b604 = [4, 12, 4];
nema = 42.3;
nema_holes = 31;
nema_boss = 22;
m3 = 3.3;  m4 = 4.4;  m5 = 5.4;  m8 = 8.5;
nut_m3 = [5.5, 2.5];       // across flats, thickness
nut_m5 = [8, 4.2];
nut_m8 = [13, 6.6];
fit = 0.15;                // extra clearance on press fits
layer = 0.2;               // print layer height, for the bridging layers over bed-side recesses

// ---- Print bed (Prusa Core One) ------------------------------------------------------------------------
bed = [250, 220, 270];
