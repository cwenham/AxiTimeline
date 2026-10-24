'use strict';
const assert = require('assert');
const path = require('path');
const { registered, document } = require('./vscode-stub');
const extension = require('../src/extension');

extension.activate({ subscriptions: [] });

// Documents are placed in the repo's examples folder, so file names complete against real files.
const EXAMPLES = path.join(__dirname, '..', '..', '..', 'examples');

/** Completion items at the | in a document saved as examples/<name>. */
async function complete(source, name = 'industrial.axitl') {
  const lines = source.split('\n');
  const line = lines.findIndex((l) => l.includes('|'));
  const character = lines[line].indexOf('|');
  lines[line] = lines[line].replace('|', '');
  const doc = document(lines.join('\n'), path.join(EXAMPLES, name));
  const items = await registered.completion.provider.provideCompletionItems(doc, { line, character });
  return items.sort((a, b) => (a.sortText || a.label).localeCompare(b.sortText || b.label)); // as listed
}

function hover(source) {
  const line = 0;
  const character = source.indexOf('|');
  const doc = document(source.replace('|', ''), path.join(EXAMPLES, 'industrial.axitl'));
  return registered.hover.provider.provideHover(doc, { line, character });
}

const labels = (items) => items.map((i) => i.label);
const find = (items, label) => items.find((i) => i.label === label);

test('activation registers completion, with its trigger characters, and hover for axitl', () => {
  assert.deepStrictEqual(registered.completion.selector, { language: 'axitl' });
  assert.deepStrictEqual(registered.completion.triggers, ['=', '"', '(', '/']);
  assert.deepStrictEqual(registered.hover.selector, { language: 'axitl' });
});

test('keywords go in as templates, ready to tab through', async () => {
  const items = await complete('|');
  assert.deepStrictEqual(labels(items), ['timeline', 'include', 'person', 'event', 'span', 'group', 'graph']);
  assert.strictEqual(find(items, 'person').insertText.value, 'person "${1:Name}" ${2:1900}-${3:1950}$0');
  assert.strictEqual(find(items, 'group').insertText.value, 'group "${1:Name}" ${2:1900}-${3:1950} {\n\t$0\n}');
  assert.ok(find(items, 'timeline').insertText.value.includes('\twidth=${4:210}'));
  assert.strictEqual(find(items, 'include').command.command, 'editor.action.triggerSuggest');
  assert.strictEqual(find(items, 'graph').insertText.value, 'graph "${1:Title}"\n\tdata="${2}"$0');
});

test('after side and priority marks only entity keywords are offered, replacing just the word', async () => {
  const items = await complete('^!!pe|');
  assert.deepStrictEqual(labels(items), ['person', 'event', 'span', 'group']);
  assert.deepStrictEqual(find(items, 'person').range.inserting.start, { line: 0, character: 3 });
});

test('a keyword typed on a line that already has more on it goes in alone', async () => {
  const items = await complete('pers| "Newton" 1642-1727');
  assert.strictEqual(find(items, 'person').insertText, undefined);
});

test('a timeline continuation line offers the parameters not yet given, required ones marked', async () => {
  const items = await complete('timeline\n    start=1900\n    length=2m\n    |');
  const params = items.filter((i) => i.kind === 'Property');
  assert.ok(!labels(params).includes('start=') && !labels(params).includes('scale='));
  assert.strictEqual(find(items, 'width=').detail, 'required');
  assert.strictEqual(find(items, 'baseline=').command.command, 'editor.action.triggerSuggest');
  assert.ok(params.every((p) => p.sortText < find(items, 'person').sortText), 'parameters first');
});

test('after an entity date: pens with colour swatches, the parameters it takes, and illustration', async () => {
  const span = await complete('span "S" 1900-1950 |');
  const red = find(span, 'red');
  assert.strictEqual(red.kind, 'Color');
  assert.strictEqual(red.documentation, '#c62828');
  assert.strictEqual(find(span, 'HB-pencil').detail, 'HB pencil');
  assert.deepStrictEqual(labels(span.filter((i) => i.kind === 'Property')), ['fill=', 'fill_pen=', 'font=', 'font_size=']);
  assert.strictEqual(find(span, 'illustration(…)').insertText.value, 'illustration($1)$0');

  const event = await complete('event "E" 1900 blue illustration(a.svg) |');
  assert.deepStrictEqual(labels(event), ['font=', 'font_size=', 'time_label=']);
});

test('values for a key, with help for each', async () => {
  const items = await complete('span "S" 1900-1950 fill=|');
  assert.deepStrictEqual(labels(items), ['none', 'solid', 'diagonal', 'crosshatch', 'wave', 'dots']);
  assert.ok(find(items, 'solid').documentation.value.includes('hatching'));
  assert.deepStrictEqual(labels(await complete('timeline end=|')), ['now']);
});

test('font names get quotes when none were typed, and a closing quote only when it is missing', async () => {
  const bare = await complete('timeline font=|');
  assert.strictEqual(find(bare, 'EMSTech').insertText, '"EMSTech"');
  assert.strictEqual(find(bare, 'HersheySans1').detail, 'built-in font (default)');
  assert.strictEqual(find(await complete('timeline font="EMS|"'), 'EMSTech').insertText, 'EMSTech');
  assert.strictEqual(find(await complete('timeline font="EMS|'), 'EMSTech').insertText, 'EMSTech"');
});

test('a scale keeps the number typed and offers each unit', async () => {
  const items = await complete('timeline scale=12|');
  assert.deepStrictEqual(labels(items), ['12mm/year', '12mm/day', '12mm/hour', '12mm/minute', '12mm/second']);
  const blank = await complete('timeline scale=|');
  assert.strictEqual(find(blank, '5mm/day').insertText.value, '${1:5}mm/day');
});

test('include names .axitl files and folders beside the document, but not the document itself', async () => {
  const items = await complete('include "|"');
  assert.deepStrictEqual(labels(items), [
    'century.axitl', 'chernobyl.axitl', 'crash-1929.axitl', 'labels.axitl', 'reactor-power.axitl',
    'common/', 'data/', 'illustrations/',
  ]);
  assert.strictEqual(find(items, 'common/').command.command, 'editor.action.triggerSuggest');
  const nested = await complete('include "common/w|"');
  assert.deepStrictEqual(labels(nested), ['dow-1929.axitl', 'wars.axitl']);
  assert.deepStrictEqual(nested[0].range.inserting.start, { line: 0, character: 16 });
});

test('illustration names .svg files', async () => {
  const items = await complete('event "E" 1900 illustration(illustrations/|)');
  assert.deepStrictEqual(labels(items), ['apple.svg']);
  assert.strictEqual(items[0].insertText, 'apple.svg');
});

test('nothing is offered inside a label or a comment', async () => {
  assert.deepStrictEqual(await complete('person "Isa|'), []);
  assert.deepStrictEqual(await complete('person "Isaac" 1642-1727 // r|'), []);
});

test('hover help for heads, pens and parameters, covering the whole word', () => {
  const head = hover('^!!pe|rson "Newton" 1642-1727 red');
  assert.ok(head.contents.value.includes('Forced above the baseline'));
  assert.ok(head.contents.value.includes('Priority +2'));
  assert.deepStrictEqual([head.range.start.character, head.range.end.character], [0, 9]);

  const pen = hover('person "Newton" 1642-1727 HB-pe|ncil');
  assert.ok(pen.contents.value.includes('color:#797981'));
  assert.ok(pen.contents.value.includes('HB pencil (medium)'));

  assert.ok(hover('timeline sca|le=5mm/year').contents.value.includes('explicit rate'));
  assert.ok(hover('timeline end=n|ow').contents.value.includes('truncated to the precision'));
  assert.strictEqual(hover('timeline colour=r|ed'), null);
  assert.strictEqual(hover('person "Ne|wton" 1642-1727'), null);
});

// -- graphs (language spec §15) -------------------------------------------------------------------------------

test('a graph offers pens, HB-pencil marked as its default, and only its own parameters', async () => {
  const items = await complete('graph "Dow" |');
  assert.ok(find(items, 'HB-pencil').detail.includes('the default for a graph'));
  assert.strictEqual(find(items, 'illustration(…)'), undefined);
  const vocabulary = require('../src/vocabulary.json');
  assert.deepStrictEqual(
    labels(items.filter((i) => i.kind === 'Property')),
    vocabulary.graphParameters.map((key) => `${key}=`)
  );
  assert.strictEqual(find(items, 'data=').command.command, 'editor.action.triggerSuggest');
});

test("a graph's values, with help", async () => {
  assert.deepStrictEqual(labels(await complete('graph "Dow" y_scale=|')), ['linear', 'log']);
  assert.deepStrictEqual(labels(await complete('graph "Dow" line=|')), ['straight', 'smooth', 'step']);
  assert.ok(find(await complete('graph "Dow" origin=|'), 'first').documentation.value.includes('change since'));
});

test('data= names CSV files and folders, quoting a bare name', async () => {
  const quoted = await complete('graph "Dow" data="data/|"');
  assert.deepStrictEqual(labels(quoted), ['dow-1928-1932.csv']);
  assert.strictEqual(quoted[0].insertText, 'dow-1928-1932.csv');
  assert.ok(labels(await complete('graph "Dow" data=|')).includes('data/'));
});

test('hover help for a graph says what a shared parameter means on it', () => {
  assert.ok(hover('gra|ph "Dow" data="d.csv"').contents.value.includes('background graph'));
  assert.ok(hover('graph "Dow" hei|ght=40mm').contents.value.includes('furthest'));
  assert.ok(hover('event "E" 1900 illustration(a.svg hei|ght=40mm)').contents.value.includes('whole lanes'));
  assert.ok(hover('graph "Dow" fi|ll=solid').contents.value.includes('Shading under the line'));
  assert.ok(hover('span "S" 1900-1950 fi|ll=solid').contents.value.includes('Bars only'));
});

test('fill_pen= offers every pen with its swatch, and hovering one says which pen it is', async () => {
  const items = await complete('span "S" 1900-1950 black fill=diagonal fill_pen=|');
  assert.strictEqual(items.length, Object.keys(require('../src/vocabulary.json').pens).length);
  assert.strictEqual(find(items, '2H-pencil').documentation, '#8b8b93');
  assert.ok(labels(await complete('graph "G" fill=solid fill_pen=|')).includes('HB-pencil'));
  assert.ok(hover('span "S" 1900-1950 fill_pen=2H-pen|cil').contents.value.includes('2H pencil (hard and light)'));
  assert.ok(hover('span "S" 1900-1950 fill_p|en=2H-pencil').contents.value.includes('soft'));
  assert.ok(hover('graph "G" un|it=MW').contents.value.includes('every value scale'));
});
