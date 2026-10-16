> **Draft, 2026-10-15.** The paper transport's hardware, worked out with the author before anything is
> built. Nothing here is settled until it has been built and tested; change it as the hardware changes.
> The software side is in `docs/interpreter-cli-spec.md` ("The roll's orientation") and item 3 of
> `docs/known-gaps.md`.

# Paper transport

The transport moves the roll under the AxiDraw SE/A3, along its Y axis and under its bar, so that `plot` can
draw a long timeline in strips. Parts are designed in Fusion and 3D-printed where possible.

## What it has to do

- **Move the paper both ways.** Every pen is its own pass along the whole roll, so after each pass the roll
  winds back to the start. Both rolls need motors, and the paper on the board must be held the same way in
  either direction.
- **Advance exactly `strip_mm`.** Strokes cut at a strip edge only meet again if the paper moves exactly a
  strip's length, and pens only line up if every pass puts the paper in the same place. Aim for 0.1mm per
  advance. The AxiDraw itself repeats very well (first hardware runs, 2026-10-14), so this is where the
  accuracy has to come from.
- **Keep the paper flat at one height under the pen.** Only paper fits under the AxiDraw's bar: it is 7.5mm
  above the board.
- **Handle art paper over 150gsm.** Never bend the paper tighter than a roll core, about 25mm radius. The roll
  on hand (430mm wide, 26mm core bore) is already bent tighter than that at its core, so 50mm rollers suit
  it too.

## Paper path

![Side view at 1:1](images/transport-side.svg)

The board is raised on a stand, with the supply roll below its back edge and the take-up roll below its front
edge. Between each roll and the board the paper hangs in a loop, with a weighted roller (a **dancer**) resting
in it:

1. The supply roll pays out into the back loop, around the back dancer, and up over the back roller.
2. The paper crosses the board, under the bar, past the pen.
3. It passes flat over the **drive roller**, set flush with the board just beyond the pen's reach, with a
   sprung **pinch wheel** pressing it down onto each margin, as on a vinyl cutter.
4. It turns down over the front roller, around the front dancer, and up onto the take-up roll.

- **The dancers set the tension.** Each holds its loop at half its own weight, whichever way the paper moves
  and however full the rolls are. About 400g gives 2N.
- **The rolls only keep their dancers in range.** Each roll motor runs to keep its dancer between two sensors,
  so it needs no precision.
- **The drive roller does the measuring.** It is the only part whose movement has to be exact.
- **Nothing rises above the board except the pinch wheels and their rail.** Both sit beyond the pen
  carriage's reach. Everything else is at or below the board's surface.
- **It feeds towards the front.** That matches the default `feed = "towards-front"`: supply at the back,
  finished roll at the front where the operator can see it.

## Layout

Coordinates: **Y** is measured from the front face of the AxiDraw's bar, positive towards the operator. **Z** is
measured from the board's top surface, positive up. **X** is measured from the paper's centreline. All in mm.
The drawing above is at 1:1, so it can be inserted into a Fusion sketch (Insert > Insert SVG); check its 100mm
scale bar after importing, and delete the white background rectangle if it comes in too.

### The AxiDraw (measured 2026-10-14/15)

| Part | Where |
|---|---|
| Bar | Y −60 to 0, 7.5 clear above the board |
| Legs | Y −93 to 33; 15 wide, 500 apart inside (X ±250 if centred) |
| Pen tip | Y 60 at home, 300 of travel, Y 360 at full reach |
| Pen carriage | Ends about 30 in front of the pen tip (to the thumbscrew), so about Y 395 at full reach |
| A 250mm strip | Y 70 to 320 at the default `origin_along_mm` of 10 |

### Along the paper (Y) and up (Z)

| Part | Y | Z |
|---|---|---|
| Back roller, Ø50 | −128 | −25 (top flush with the board) |
| Back dancer, Ø50 | −128 | travels −150 to −260 |
| Supply spindle | −73 | −75 |
| Board, 18mm | −100 to 415 | 0 to −18 |
| Take-up spindle | 405 | −75 |
| Drive roller, 8mm | 425 | −4.25 (top flush) |
| Pinch wheel axle, Ø25 wheel | 425 | 12.5 |
| Front roller, Ø50 | 460 | −25 (top flush) |
| Front dancer, Ø50 | 460 | travels −150 to −260 |
| Pinch rail, 20×20 | 505 | 35 (25 to 45) |
| Side plates | −170 to 515 | −18 to −318 |
| Tabletop | | −318 |

- **Clearances:**
  - The pinch wheel's rearmost point is at Y 412.5, about 17 clear of the carriage at full reach.
  - The back roller is 3.9 clear of the board's back corner.
  - A full 90mm roll clears the board's underside by 12, an edge roller by 4, and a dancer at the top of its
    travel by 5. A roll larger than 90mm needs the spindles lower.
- **Stand height:** 300mm side plates plus an 18mm board puts the board's top 318mm above the table.

### Across the paper (X)

| Part | Where |
|---|---|
| Paper roll on hand | 430 wide, X ±215 |
| Inked page | Up to 400 wide, X ±200, leaving each pinch wheel the outer 15mm of the paper |
| Roller faces | 490 long, X ±245, so a roll up to 480 fits later (the widest that passes the AxiDraw's legs) |
| Bearing centres | X ±255 |
| Side plates' inner faces | X ±265 (18mm ply, so outer faces at X ±283) |
| Board | 600 wide, X ±300 |

Centre the paper on the pen's X travel, not on the AxiDraw's legs: the AxiDraw's cleats should put its home
215mm from the paper's centreline. A 400mm page then runs from 15 to 415 across, so `origin_across_mm` becomes
about 15, and the finished `width=` can be up to about 395 (crop marks reach 2.5 beyond each finished edge).

## Parts

### Drive roller and pinch wheels

- **Roller:** the 8mm solid steel rod, about 570 long.
  - 608ZZ bearings go straight onto it at X ±255, so it turns true. Clean the patina off where they sit, and
    roll the rod on something flat to check it's straight.
  - The rod passes through one side plate to a 60T GT2 pulley (8mm bore, grub screw on a filed flat) outside.
- **Drive motor:** a NEMA 17 with a 20T pulley on the outside of the same plate, on a slotted mount to tension a
  closed GT2 belt. 20T to 60T is 3:1, about 0.04mm per full step.
- **Bearing blocks:** printed, bolted to the plates through slotted holes so the roller can be set flush with
  the board and square to the AxiDraw's Y axis.
- **Grit:** bands of epoxy and 120–180 grit aluminium oxide under the wheel tracks (X ±200 to ±215 for the 430
  roll).
  - Apply it while the motor turns the rod slowly, so the coat comes out even. A roller even a hair thicker
    under one wheel feeds that side faster and steers the paper sideways.
  - Finish with a thin sealing coat so no grains shed onto the board, where one under the paper would make the
    pen skip.
- **Pinch wheels:** the 25mm hard-plastic wheels, on M5 bolts.
  - They sit in printed arms that clamp anywhere along the 20×20 rail, so they can follow the margins of any
    roll width.
  - Spring each to about 15–20N, with a cam to lift it for threading.

### Edge rollers and dancers

- **Construction:** 50mm printed sleeves, printed in sections and glued onto a carbon tube spine about 460 long.
  - Use the 18mm tube (15.5 bore) for the edge rollers; the 14mm (11.5 bore) will do for the dancers if
    there's not enough 18mm.
  - Each sleeve's end sections hold a 608ZZ, running on an M8 bolt fixed in a printed block on the side plate.
  - Neither tube's bore takes the 604s or 608s directly, which is why the bearings sit in the printed ends.
- **Back roller adjustment:** one end of the back roller's block is slotted front to back, as a tracking trim.
- **Dancers:**
  - Their M8 axle bolts ride in vertical slots in printed guides on the plates.
  - Opto endstops sit at the top and bottom of one slot each.
  - Washers on the axle ends adjust the weight. A dancer comes out at about 300g bare; aim for 300–500g and
    add more if the paper's curl needs more tension.

### Rolls

- **Spindles:** the 10mm carbon tubes (7.5 bore), about 540 long.
  - They rest in open cradles made from pairs of 608ZZ.
  - The board covers the cradles from above, so they open outwards: towards the back for the supply roll,
    towards the front for the take-up roll.
- **Chucks:** printed, with a 26mm spigot for the core and a flange to locate the roll. They clamp onto the
  spindle anywhere along it.
- **Drive:** a printed gear on one end of each spindle meshes with the roll motor's gear (about 3:1) when the
  spindle is seated. A latch stops a nearly empty roll lifting out of mesh.
- **Take-up core:** the take-up roll needs an empty core with a 26mm bore, either cardboard or printed, to tape
  the paper's leading end to.

### Stand

- **Side plates:** two 18mm plywood plates, about 685 × 300, standing on the table. Every bearing block, slot
  guide, cradle and motor bolts to them at its place in the layout.
- **Bracing:** the board screws to their top edges, and a batten or two across the middle (under the board,
  clear of the loops) keeps them square.
- **AxiDraw cleats:** printed blocks fit around its feet and screw to the board through slotted holes, so it can
  be turned until its Y axis lines up with the feed, then locked. It mustn't move between passes.
- **Extrusion:** the 1m 20×20 becomes the pinch rail, on brackets at the plates' front ends.
- **Board surface:** flat and smooth. A thin smooth sheet laid under the paper's path, but not under the feet,
  would also bring the paper closer to the pen while leaving at least 4.5mm under the bar.

## Electronics

- **Controller:** a Raspberry Pi Pico, on USB to the Pi, which also powers it. The serial protocol for
  `advance(mm, next_start)` is still to be written.
- **Drivers:** three Pololu TB67S581FNG carriers, wired for step and direction (plus a shared enable) and
  driven straight from the Pico's 3.3V pins.
  - Hard-wire the microstep mode pins to 1/16 or 1/32.
  - Set the current with the trimpot before soldering the headers. Start at about 0.8A for the drive roller
    and 0.6A for the rolls; the motors (Rtelligent 42A02C, 1.5A, about 0.42 N·m) need little torque here.
  - Fit a 100µF electrolytic across each board's motor supply; Pololu warns that voltage spikes can destroy
    these boards at 24V.
  - Never unplug a motor while it's powered.
- **They don't cut the current when holding still,** unlike a TMC2209, and they're audible. All three motors
  must stay powered through a plot, because if the roll motors switch off, the dancers' weight unwinds both
  rolls. So keep the currents low.
- **Power:** the 24V 10A supply for the drivers, with its ground joined to the Pico's. The drivers make their
  own logic supply and the sensors run from the Pico's 3.3V, so the 5V converter isn't needed.
- **Sensors:**
  - Four opto endstops for the dancers, run at 3.3V: the Pico's inputs are not 5V tolerant.
  - Optionally, a paper-out sensor.
  - The optical flow sensor, over SPI, to catch slipping rather than to measure moves (mouse-type sensors
    drift by around a percent).
  - Optionally, a "transport fault, pause the plot" line to the EBB's B0 input. Keep it away from the motor
    wiring, which could set off phantom pauses.
- **Pins:** about 20 of the Pico's 26 GPIO: 6 for step and direction, 1 enable, 4 dancer sensors, 1 paper-out,
  1 pause line, and about 5 for SPI.

## Accuracy and setting up

- **Squareness comes first.** A drive roller 0.1° off square steers the paper about 26mm sideways over 15m, and
  it does that forwards and back for every pen.
  - Square the AxiDraw to the feed with its cleats, then the drive roller with its slotted blocks.
  - Trim what's left with the back roller.
  - The test: draw a long line in a margin, advance a strip, and draw it again.
- **Calibrate the drive roller's scale once.** Its exact diameter (with grit) is the one error that grows with
  distance. Measure it against the 50cm crop marks over a few metres and set it as a factor.
- **Finish every advance moving forwards.** Ending each move in the same direction takes up the belt's play.
- **Repeatable errors don't misregister pens.** Every pass makes the same moves, so they land where earlier
  passes did. Only the joins between strips see a single advance's error.
- **If more accuracy is needed later,** a small reflective sensor at the front edge could stop the paper on a
  mark drawn in the trim margin. Leave room for a bracket there.

## Still open

- **The full roll's outside diameter.** The spindles at Z −75 clear a roll up to 90mm across.
- **Where the AxiDraw's home sits across, relative to its legs.** With the paper centred on the travel it must
  still clear both legs: 35mm each side if the travel is centred between them.
- **The pinch wheels' tread width.**
- **The pen carriage's heights,** which only matter if the drive roller moves closer than Y 425.
- **The controller's serial protocol** and the `transport` setting in `plotter.toml` that will select it.
- **Which paper.** The roll on hand is of unknown weight and length; art paper over 150gsm is the aim.
