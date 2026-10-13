'use strict';
// Help text for hovers and completions, condensed from docs/language-spec.md (section numbers refer to it).

const keywords = {
  timeline:
    "The document's settings: its dates, size and defaults. Exactly one, in the top-level file only (§4). " +
    'Needs `start=`, `end=` and `width=`, and one of `length=` or `scale=`.',
  include:
    'Pulls in another `.axitl` file, relative to this one. `priority=` is added to every included ' +
    "entity's priority; `side=` forces them all `above` or `below` (§5).",
  person:
    'A life, drawn as a bar. Needs a range, `1642-1727`, or an open start, `1953-` (§§3.3, 3.6). ' +
    'Bars stack in lanes; higher priority sits nearer the baseline (§7).',
  event:
    'A moment, drawn as a pole from the baseline with its label as a flag at the far end. ' +
    'Takes one date, never a range (§8).',
  span:
    'A period, drawn as a bar. Needs a range, `1939-1945` or `1962-10-16/1962-10-28`, or an open start (§3.3).',
  group:
    'A labelled bar like a span, with a `{ }` body. Its members are placed independently but inherit ' +
    'its side, pen, font and time label unless they give their own (§9).',
  illustration:
    'Attaches an SVG drawing: `illustration(file.svg)`, or `illustration(file.svg height=40mm)`. ' +
    'The default height is 2 lanes, rounded up to whole lanes; the width keeps its aspect ratio (§3.5).',
};

const parameters = {
  start: 'The first date the timeline shows (required), at any precision: `600BC`, `1986-04-25T14:00:00` (§3.3).',
  end:
    'The last date the timeline shows (required), or `now`: the moment it is built, truncated to the ' +
    'precision of `start` (§3.6).',
  length:
    'The finished length along the roll (§4). Give this or `scale=`, not both. A bare number is ' +
    'millimetres; `cm` and `m` work too: `length=15m` (§14).',
  scale:
    'An explicit rate: `5mm/year`, or per `day`, `hour`, `minute` or `second` (§4). ' +
    'Give this or `length=`, not both.',
  width:
    'The finished width across the roll (required): `width=210`. A bare number is millimetres (§§4, 14).',
  baseline:
    'Where the baseline is drawn: `high`, `middle` (the default) or `low`, splitting the width by the ' +
    'golden ratio (§4).',
  lane_height: 'The thickness of each lane, on both sides. Default `8mm` (§4).',
  above_lane_height: 'The thickness of each lane above the baseline, overriding `lane_height` (§4).',
  below_lane_height: 'The thickness of each lane below the baseline, overriding `lane_height` (§4).',
  baseline_offset: 'The gap between the baseline and the first lane, on both sides. Default `3mm` (§4).',
  above_baseline_offset: 'The gap between the baseline and the first lane above it, overriding `baseline_offset` (§4).',
  below_baseline_offset: 'The gap between the baseline and the first lane below it, overriding `baseline_offset` (§4).',
  ticks: 'The target spacing of the baseline ticks, default `3.5mm`, or `off` (§10.3).',
  tick_label_every: 'Label every n-th tick, overriding the interval worked out from the tick ladder (§10.3).',
  open_end_style:
    'The torn cap drawn on open-ended bars and bars clipped by the window: `sawtooth` (the default) or ' +
    '`sine` (§3.6).',
  font:
    'A built-in stroke font (default `HersheySans1`), or a custom SVG font file ending `.svg`, relative ' +
    'to this file. On `timeline` it sets the default (§3.8).',
  font_size:
    "The font's em size; capitals are about two-thirds of it. Default `4mm`. On `timeline` it sets the " +
    'default (§3.8).',
  time_label:
    "A second, smaller line under an event's flag giving its date or time. On `timeline` or a `group` " +
    'it sets the default for the events inside (§3.11).',
  fill:
    'How a bar is filled: outline only by default. Hatching stops short of the label. Bars only, not ' +
    'events (§3.7).',
  priority: "On `include`: a whole number added to every included entity's priority, e.g. `-5` (§5).",
  side: 'On `include`: forces every included entity `above` or `below` the baseline (§5).',
  height: 'The illustration\'s height, rounded up to whole lanes. Default 2 lanes (§3.5).',
};

const values = {
  fill: {
    none: 'Outline only (the default).',
    solid:
      'Dense hatching, since a plotter has no flat fill. Costs real plot time and pen wear (§3.7).',
    diagonal: 'Diagonal hatching.',
    crosshatch: 'Crossed hatching.',
    wave: 'Wavy lines.',
    dots: 'Dots.',
  },
  time_label: {
    none: 'No time label (the default). Switches off one inherited from the timeline or a group.',
    date: 'The date exactly as written, at its own precision: `1986-04-26 01:23:44`, `44BC-03-15`.',
    year: 'The year: `1939`.',
    month: 'The year and month: `1939-09`.',
    day: 'The full date: `1939-09-01`.',
    hour: 'The hour: `01:00`. Never more precise than the date itself.',
    min: 'Hours and minutes: `01:23`. Never more precise than the date itself.',
    sec: 'Hours, minutes and seconds: `01:23:44`. Never more precise than the date itself.',
  },
  baseline: {
    high: 'The baseline near the top edge, leaving most of the room below it.',
    middle: 'The baseline in the centre (the default).',
    low: 'The baseline near the bottom edge, leaving most of the room above it.',
  },
  open_end_style: {
    sawtooth: 'A zig-zag torn edge (the default).',
    sine: 'A wavy torn edge.',
  },
  side: {
    above: 'Every included entity above the baseline.',
    below: 'Every included entity below the baseline.',
  },
  ticks: {
    off: 'No ticks. Ticks are also the operator\'s measuring reference when resuming a plot (§10.4).',
  },
  end: {
    now:
      'The moment the timeline is built, truncated to the precision of `start`. Pin it with ' +
      '`axitime render --now` to re-render the same layout later (§3.6).',
  },
};

const PEN_NOTE = 'Each pen is plotted in its own pass; the default is `black` (§3.4).';

function pen(name) {
  if (name.endsWith('-pencil')) {
    const grade = name.slice(0, -'-pencil'.length);
    const feel = grade === 'HB' || grade === 'F' ? 'medium' : grade.endsWith('B') ? 'soft and dark' : 'hard and light';
    return `${grade} pencil (${feel}). ${PEN_NOTE}`;
  }
  if (name.startsWith('fountain-')) return `Fountain pen, ${name.slice('fountain-'.length)} ink. ${PEN_NOTE}`;
  return `${name[0].toUpperCase()}${name.slice(1)} pen. ${PEN_NOTE}`;
}

/** A short name for a pen, for the completion list. */
function penDetail(name) {
  if (name.endsWith('-pencil')) return `${name.slice(0, -'-pencil'.length)} pencil`;
  if (name.startsWith('fountain-')) return `fountain pen, ${name.slice('fountain-'.length)}`;
  return `${name} pen`;
}

function font(name) {
  return `Built-in stroke font \`${name}\`, from the Hershey Text set (§3.8).`;
}

/** What an entity's head says: its keyword, then its side and priority marks (§§3.1, 3.2). */
function head(target) {
  const side = {
    '^': 'Forced above the baseline (§3.2).',
    v: 'Forced below the baseline (§3.2).',
    '': 'Side chosen automatically, or inherited from its group (§§6, 9).',
  }[target.side];
  let priority;
  if (target.mixed) priority = 'Mixing `!` and `-` in one run is an error (§3.1).';
  else if (target.priority > 0) priority = `Priority +${target.priority}: nearer the baseline (§3.1).`;
  else if (target.priority < 0) priority = `Priority ${target.priority}: further from the baseline (§3.1).`;
  else priority = 'Priority 0, the default (§3.1).';
  return `${keywords[target.name]}\n\n${side} ${priority}`;
}

module.exports = { keywords, parameters, values, pen, penDetail, font, head };
