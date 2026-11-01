'use strict';
const assert = require('assert');
const { completionContext, hoverTarget } = require('../src/analyse');

/** Split a document with one | marking the cursor into lines, a line number and a column. */
function cursor(source) {
  const lines = source.split('\n');
  const line = lines.findIndex((l) => l.includes('|'));
  const character = lines[line].indexOf('|');
  lines[line] = lines[line].replace('|', '');
  return [lines, line, character];
}

const at = (source) => completionContext(...cursor(source));
const hover = (source) => hoverTarget(...cursor(source));

function expect(source, expected) {
  const actual = at(source);
  for (const [key, value] of Object.entries(expected)) {
    const got = actual[key] instanceof Set ? [...actual[key]].sort() : actual[key];
    assert.deepStrictEqual(got, value, `${key} for ${JSON.stringify(source)}: got ${JSON.stringify(actual)}`);
  }
  return actual;
}

const TIMELINE = 'timeline start=1900 end=2000 length=1m width=210\n';

// -- the start of a declaration ----------------------------------------------------------------------------

test('an empty document starts a declaration, and a timeline is still possible', () => {
  expect('|', { kind: 'statement', marks: '', prefix: '', start: 0, timeline: true, continues: null });
});

test('a partly typed keyword is the prefix', () => {
  expect('pe|', { kind: 'statement', prefix: 'pe', start: 0 });
});

test('side and priority marks come before the keyword and are kept', () => {
  expect('^!!pe|', { kind: 'statement', marks: '^!!', prefix: 'pe', start: 3 });
  expect('v|', { kind: 'statement', marks: 'v', prefix: '' });
  expect('--|', { kind: 'statement', marks: '--', prefix: '' });
});

test('a second timeline is not offered', () => {
  expect(TIMELINE + '\n|', { kind: 'statement', timeline: false });
});

test('inside a group body: no timeline, and the { line cannot be continued', () => {
  expect('group "G" 1900-1950 {\n  |\n}', { kind: 'statement', inBody: true, timeline: false, continues: null });
});

test('an indented line can continue the declaration above, and knows its parameters on both sides', () => {
  const c = expect('timeline\n    start=1900\n    |\n    width=210', { kind: 'statement', timeline: false });
  assert.strictEqual(c.continues.decl, 'timeline');
  assert.deepStrictEqual([...c.continues.used].sort(), ['start', 'width']);
});

test('a comment line inside a declaration does not end it; a blank line does', () => {
  assert.strictEqual(at('timeline\n    start=1900\n    // note\n    |').continues.decl, 'timeline');
  assert.strictEqual(at('timeline\n    start=1900\n\n    |').continues, null);
});

test('a group member can be continued too', () => {
  assert.strictEqual(at('group "G" 1900-1950 {\n  person "P" 1900-1950\n  |').continues.decl, 'person');
});

test('marks on an indented line start an entity, not a continuation', () => {
  expect('timeline\n    ^|', { kind: 'statement', marks: '^', continues: null });
});

// -- items after the date ----------------------------------------------------------------------------------

test('after an entity date: an item, nothing given yet', () => {
  expect('person "Newton" 1642-1727 |', { kind: 'item', decl: 'person', prefix: '', start: 26, pen: false, used: [] });
});

test('a partly typed item is the prefix', () => {
  expect('person "Newton" 1642-1727 fo|', { kind: 'item', prefix: 'fo', start: 26 });
});

test('pens, parameters and illustrations already given are known, before and after the cursor', () => {
  expect('person "Newton" 1642-1727 red fill=solid |', { pen: true, used: ['fill'], illustration: false });
  expect('person "Newton" 1642-1727 | red', { pen: true });
  expect('event "E" 1900 illustration(a.svg height=2cm) |', { illustration: true, used: [] });
});

test('a value that happens to be a pen word is not a pen', () => {
  expect('event "E" 1900 font=red |', { pen: false, used: ['font'] });
});

test('timeline and include lines take parameters', () => {
  expect('timeline start=1900 |', { kind: 'item', decl: 'timeline', used: ['start'] });
  expect('include "a.axitl" |', { kind: 'item', decl: 'include' });
});

// -- nowhere to complete -----------------------------------------------------------------------------------

test('nothing inside a label, or where the date goes', () => {
  expect('person "New|', { kind: 'none' });
  expect('person "Newton"|', { kind: 'none' });
  expect('person "Newton" |', { kind: 'none' });
  expect('person "Newton" 16|', { kind: 'none' });
});

test('nothing in a comment, but // inside a label is not a comment', () => {
  expect('person "Newton" 1642-1727 // r|', { kind: 'none' });
  expect('event "Either//Or" 1970 |', { kind: 'item', decl: 'event' });
});

test('nothing after a group body opens, or for a key=value line with nothing to continue', () => {
  expect('group "G" 1900-1950 { |', { kind: 'none' });
  expect('width=|', { kind: 'none' });
});

// -- values ------------------------------------------------------------------------------------------------

test('the value after key=', () => {
  expect('span "S" 1900-1950 fill=|', { kind: 'value', decl: 'span', key: 'fill', prefix: '', start: 24 });
  expect('span "S" 1900-1950 fill=dia|', { kind: 'value', key: 'fill', prefix: 'dia', start: 24 });
});

test('a value on a continuation line belongs to the declaration above', () => {
  expect('timeline\n    baseline=|', { kind: 'value', decl: 'timeline', key: 'baseline' });
  expect('include "a.axitl"\n    side=|', { kind: 'value', decl: 'include', key: 'side' });
});

test('a quoted value starts after its quote; nothing once it is closed', () => {
  expect('timeline font="Her|"', { kind: 'value', key: 'font', prefix: 'Her', quoted: true, start: 15 });
  expect('timeline font="Her"|', { kind: 'none' });
});

// -- file names --------------------------------------------------------------------------------------------

test("an illustration's file name, bare or quoted", () => {
  expect('event "E" 1900 illustration(|)', { kind: 'path', purpose: 'illustration', prefix: '', start: 28 });
  expect('event "E" 1900 illustration(pics/ap|)', { kind: 'path', prefix: 'pics/ap', start: 28, quoted: false });
  expect('event "E" 1900 illustration("my ap|")', { kind: 'path', prefix: 'my ap', start: 29, quoted: true });
});

test("then the illustration's own parameters", () => {
  expect('event "E" 1900 illustration(a.svg |)', { kind: 'item', decl: 'illustration', used: [] });
  expect('event "E" 1900 illustration(a.svg height=|)', { kind: 'value', decl: 'illustration', key: 'height' });
});

test("an include's file name", () => {
  expect('include "common/w|"', { kind: 'path', purpose: 'include', prefix: 'common/w', start: 9, quoted: true });
  expect('include |', { kind: 'none' });
});

// -- hover -------------------------------------------------------------------------------------------------

test("hovering an entity's head gives its keyword, side and priority", () => {
  assert.deepStrictEqual(hover('^!!pe|rson "N" 1642-1727'), {
    type: 'head', name: 'person', side: '^', priority: 2, mixed: false, start: 0, end: 9,
  });
  assert.strictEqual(hover('--ev|ent "E" 1900').priority, -2);
  assert.strictEqual(hover('!-!s|pan "S" 1900-1950').mixed, true);
  assert.strictEqual(hover('  !!pe|rson "P" 1900-1950').name, 'person');
});

test('hovering keywords, pens, parameters and values', () => {
  assert.deepStrictEqual(hover('ti|meline start=1900'), { type: 'keyword', name: 'timeline', start: 0, end: 8 });
  assert.strictEqual(hover('event "E" 1900 il|lustration(a.svg)').name, 'illustration');
  assert.deepStrictEqual(hover('span "S" 1900-1950 r|ed'), { type: 'pen', name: 'red', start: 19, end: 22 });
  assert.deepStrictEqual(hover('span "S" 1900-1950 fi|ll=solid'), {
    type: 'parameter', name: 'fill', decl: 'span', start: 19, end: 23,
  });
  assert.deepStrictEqual(hover('span "S" 1900-1950 fill=so|lid'), {
    type: 'value', key: 'fill', name: 'solid', start: 24, end: 29,
  });
  assert.strictEqual(hover('timeline\n    st|art=1900').type, 'parameter');
});

test('hovering a built-in font, quoted or bare', () => {
  assert.strictEqual(hover('timeline font="Hershey|Sans1"').type, 'font');
  assert.strictEqual(hover('timeline font=EMS|Tech').type, 'font');
  assert.strictEqual(hover('timeline font="my|font.svg"'), null);
});

test('nothing to say for labels, dates and comments', () => {
  assert.strictEqual(hover('event "r|ed" 1900'), null);
  assert.strictEqual(hover('event "E" 19|00'), null);
  assert.strictEqual(hover('event "E" 1900 // r|ed'), null);
});

// -- graphs (language spec §15) -------------------------------------------------------------------------------

test('a graph is offered at the top level, but not inside a group', () => {
  expect('|', { kind: 'statement', inBody: false });
  expect('group "G" 1900-1950 {\n  |\n}', { kind: 'statement', inBody: true });
});

test("a graph's items follow its title, with no date", () => {
  expect('graph "Dow" |', { kind: 'item', decl: 'graph', prefix: '' });
  expect('graph "Dow" HB-pencil y_sc|', { kind: 'item', decl: 'graph', prefix: 'y_sc', pen: true });
  expect('graph "Dow" y_scale=|', { kind: 'value', decl: 'graph', key: 'y_scale' });
  expect('graph "Do|', { kind: 'none' });
});

test('a graph continued on indented lines, and its parameters known', () => {
  const c = expect('graph "Dow"\n    data="dow.csv"\n    |', { kind: 'statement' });
  assert.strictEqual(c.continues.decl, 'graph');
  assert.deepStrictEqual([...c.continues.used], ['data']);
  expect('graph "Dow"\n    data="dow.csv"\n    origin=|', { kind: 'value', decl: 'graph', key: 'origin' });
});

test("nothing is offered inside a graph's body of points, even when its { ends a continuation line", () => {
  expect('graph "Rate" line=step {\n    |\n}', { kind: 'none' });
  expect('graph "Rate"\n    line=step {\n    1929-08-09 6\n    |\n}', { kind: 'none' });
  expect('graph "Rate" {\n    1929-08-09 6\n}\n|', { kind: 'statement', inBody: false });
});

test('hovering a graph: its keyword, and parameters known to belong to it', () => {
  assert.deepStrictEqual(hover('gra|ph "Dow" data="d.csv"'), { type: 'keyword', name: 'graph', start: 0, end: 5 });
  assert.strictEqual(hover('graph "Dow" hei|ght=40mm').decl, 'graph');
  assert.strictEqual(hover('graph "Dow"\n    fill_de|pth=4mm').decl, 'graph');
  assert.strictEqual(hover('event "E" 1900 illustration(a.svg hei|ght=40mm)').decl, 'illustration');
  assert.deepStrictEqual(hover('graph "Dow" y_scale=l|og'), { type: 'value', key: 'y_scale', name: 'log', start: 20, end: 23 });
});

// -- the title and credits (§16) -------------------------------------------------------------------------------

test('a title is like a graph: its items follow its quoted text', () => {
  expect('title "A Century" |', { kind: 'item', decl: 'title', used: [] });
  expect('title "A Cen|', { kind: 'none' });
  expect('title "A Century" subtitle="x" |', { kind: 'item', decl: 'title', used: ['subtitle'] });
});

test('the credits have no label: their items start straight after the keyword', () => {
  expect('credits |', { kind: 'item', decl: 'credits', used: [] });
  expect('credits max_height=20mm |', { kind: 'item', decl: 'credits', used: ['max_height'] });
  expect('credits max_height=20mm {|', { kind: 'none' });
});

test("the credits' body holds lines of text: only heading can start one, and nothing continues them", () => {
  expect('credits {\n  "x"\n  |\n}', { kind: 'statement', body: 'credits', inBody: true, continues: null, timeline: false });
  expect('credits {\n  hea|', { kind: 'statement', body: 'credits', prefix: 'hea' });
  expect('credits {\n  ^|', { kind: 'none' });
  expect('group "G" 1900-1950 {\n  |\n}', { kind: 'statement', body: 'group' });
});

test('an indented illustration( line continues the declaration above, and knows whose it is', () => {
  const c = expect('title "T"\n    illustration(a.svg |)', { kind: 'item', decl: 'illustration', owner: 'title' });
  assert.deepStrictEqual([...c.used], []);
  expect('credits\n    max_height=20mm illustration(logo.svg |) {', { decl: 'illustration', owner: 'credits' });
  expect('event "E" 1900 illustration(a.svg |)', { decl: 'illustration', owner: 'event' });
});

test('hover: title and credits are keywords, and heading is one inside the credits', () => {
  assert.deepStrictEqual(hover('tit|le "T"'), { type: 'keyword', name: 'title', start: 0, end: 5 });
  assert.strictEqual(hover('credits {\n  head|ing "Sources"\n}').name, 'heading');
  assert.strictEqual(hover('head|ing "Sources"'), null);
  assert.deepStrictEqual(hover('title "T" subtitle_font=Hershey|Sans1'), { type: 'font', name: 'HersheySans1', start: 24, end: 36 });
  assert.strictEqual(hover('title "T"\n    illustration(a.svg a|t=left)').decl, 'illustration');
  assert.strictEqual(hover('title "T"\n    ga|p=3').decl, 'title');
});

// -- notes (§17) ----------------------------------------------------------------------------------------------

test('a note takes its items after its quoted text, or straight after the keyword', () => {
  expect('note |', { kind: 'item', decl: 'note', used: [] });
  expect('note anchor=end |', { kind: 'item', decl: 'note', used: ['anchor'] });
  expect('note "Dates are Greg|', { kind: 'none' });
  expect('note "Dates are Gregorian." edge=bottom |', { kind: 'item', decl: 'note', used: ['edge'] });
  expect('note anchor=|', { kind: 'value', decl: 'note', key: 'anchor' });
});

test("a note's body holds paragraphs: only heading can start a line, and nothing continues them", () => {
  expect('note {\n  "x"\n  |\n}', { kind: 'statement', body: 'note', inBody: true, continues: null, timeline: false });
  expect('note anchor=end {\n  hea|', { kind: 'statement', body: 'note', prefix: 'hea' });
  expect('note {\n  ^|', { kind: 'none' });
});

test('hover: note is a keyword, and heading is one inside a note', () => {
  assert.deepStrictEqual(hover('no|te "x"'), { type: 'keyword', name: 'note', start: 0, end: 4 });
  assert.strictEqual(hover('note {\n  head|ing "About"\n}').name, 'heading');
  assert.strictEqual(hover('note "x"\n    clear|ance=3').decl, 'note');
});
