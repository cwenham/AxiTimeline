'use strict';
const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { vscode, registered, settings, information, panels, document } = require('./vscode-stub');
const { Previewer, VIEW_TYPE, svgSize, failureText } = require('../src/preview');

const EXTENSION = path.join(__dirname, '..');
const AXITIME = path.join(EXTENSION, '..', '..', '.venv', 'bin', 'axitime'); // from uv sync

const made = [];
process.on('exit', () => {
  for (const dir of made) (fs.rmSync || fs.rmdirSync)(dir, { recursive: true, force: true });
});

/** A fresh folder holding the given files, and open documents for them. Removed when the tests end. */
function folder(files) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'axitl-preview-test-'));
  made.push(dir);
  const documents = {};
  for (const [name, text] of Object.entries(files)) {
    fs.writeFileSync(path.join(dir, name), text);
    documents[name] = document(text, path.join(dir, name));
  }
  return { dir, documents, uri: (name) => vscode.Uri.file(path.join(dir, name)) };
}

/** Write a file's new text, as a save would, and return its document. */
function save(dir, name, text) {
  fs.writeFileSync(path.join(dir, name), text);
  return document(text, path.join(dir, name));
}

const MAIN = 'timeline start=1900 end=2000 length=40cm width=100\nspan "A" 1910-1920 red\ninclude "bits.axitl"\n';
const BITS = 'event "B" 1950\n';
const previewer = () => new Previewer(vscode.Uri.file(EXTENSION));

test("a preview SVG's size is read from its width and height in mm", () => {
  const svg = '<?xml version="1.0"?>\n<svg xmlns="x" width="400mm" height="125.5mm" viewBox="0 0 400 125.5"><path/></svg>';
  assert.deepStrictEqual(svgSize(svg), { widthMm: 400, heightMm: 125.5 });
  assert.deepStrictEqual(svgSize('<svg width="10" height="20">'), { widthMm: null, heightMm: null });
});

test('a failed render reports what axitime printed, less its closing count', () => {
  const stdout = 'main.axitl:2: error: \'purple\' is not a pen [unknown-pen]\nmain.axitl: render failed with 1 error and 0 warnings\n';
  assert.strictEqual(failureText('axitime', stdout, '', { code: 1 }), "main.axitl:2: error: 'purple' is not a pen [unknown-pen]");
  assert.ok(failureText('/no/axitime', '', '', { code: 'ENOENT' }).startsWith('/no/axitime was not found.'));
});

test('the page allows only its own script and style, and blob images', async () => {
  const { uri } = folder({ 'bits.axitl': BITS });
  const shown = previewer();
  await shown.show(uri('bits.axitl'), vscode.ViewColumn.Beside); // an include: nothing is run
  const html = panels[panels.length - 1].webview.html;
  const nonce = /'nonce-([^']+)'/.exec(html)[1];
  assert.ok(html.includes(`<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src blob:;`));
  assert.ok(html.includes(`<script nonce="${nonce}" src="vscode-webview://stub${path.join(EXTENSION, 'media', 'preview.js')}">`));
  for (const name of ['preview.js', 'preview.css']) assert.ok(fs.existsSync(path.join(EXTENSION, 'media', name)), name);
  shown.dispose();
});

test('an include, or a timeline in an untrusted workspace, is not rendered, and the panel says why', async () => {
  const { uri } = folder({ 'main.axitl': MAIN, 'bits.axitl': BITS });
  const shown = previewer();
  await shown.show(uri('bits.axitl'), vscode.ViewColumn.Beside);
  assert.ok(panels[panels.length - 1].latest.error.includes('it is an include'));
  vscode.workspace.isTrusted = false;
  try {
    await shown.show(uri('main.axitl'), vscode.ViewColumn.Beside);
    assert.ok(panels[panels.length - 1].latest.error.includes('trusted workspace'));
  } finally {
    vscode.workspace.isTrusted = true;
  }
  shown.dispose();
});

test('the preview command needs an .axitl file', async () => {
  vscode.window.activeTextEditor = undefined;
  information.length = 0;
  await registered.commands['axitl.preview.showToSide']();
  assert.deepStrictEqual(information, ['Open an .axitl timeline to preview it.']);
});

// -- rendering --------------------------------------------------------------------------------------------

function withAxitime(name, fn) {
  test(name, async () => {
    if (!fs.existsSync(AXITIME)) return console.log(`     (skipped: no ${AXITIME}; run uv sync)`);
    settings['check.command'] = [AXITIME];
    try {
      await fn();
    } finally {
      delete settings['check.command'];
      vscode.workspace.textDocuments = [];
    }
  });
}

withAxitime('a timeline renders into a panel beside it, which the page is sent again when it loads', async () => {
  const { uri } = folder({ 'main.axitl': MAIN, 'bits.axitl': BITS });
  const shown = previewer();
  await shown.show(uri('main.axitl'), vscode.ViewColumn.Beside);
  const panel = panels[panels.length - 1];
  assert.strictEqual(panel.viewType, VIEW_TYPE);
  assert.strictEqual(panel.title, 'Preview main.axitl');
  assert.strictEqual(panel.column, vscode.ViewColumn.Beside);
  const { svg, widthMm, heightMm, error, rendering } = panel.latest;
  assert.ok(svg.includes('pen="all"') && svg.includes('<path'), 'the every-pen preview');
  assert.deepStrictEqual([widthMm, heightMm, error, rendering], [400, 100 + 5, null, false]);
  const sent = panel.posted.length;
  panel.receive({ type: 'ready' });
  assert.strictEqual(panel.posted.length, sent + 1);
  assert.strictEqual(panel.latest.svg, svg);

  await shown.show(uri('main.axitl'), vscode.ViewColumn.Active); // already open: brought forward
  assert.strictEqual(panels[panels.length - 1], panel);
  assert.strictEqual(panel.revealed, 1);
  shown.dispose();
});

withAxitime('a broken save keeps the last drawing and shows the errors; a fixed one clears them', async () => {
  const { dir, uri } = folder({ 'main.axitl': MAIN, 'bits.axitl': BITS });
  const shown = previewer();
  await shown.show(uri('main.axitl'), vscode.ViewColumn.Beside);
  const panel = panels[panels.length - 1];
  const good = panel.latest.svg;
  await shown.saved(save(dir, 'main.axitl', MAIN.replace('red', 'purple')));
  assert.strictEqual(panel.latest.svg, good);
  assert.strictEqual(panel.latest.error, "main.axitl:2: error: 'purple' is not a pen [unknown-pen]");
  await shown.saved(save(dir, 'main.axitl', MAIN));
  assert.strictEqual(panel.latest.error, null);
  shown.dispose();
});

withAxitime("saving an include re-renders the timelines; saving another timeline leaves this one be", async () => {
  const { dir, uri } = folder({ 'main.axitl': MAIN, 'bits.axitl': BITS, 'other.axitl': MAIN });
  const shown = previewer();
  await shown.show(uri('main.axitl'), vscode.ViewColumn.Beside);
  const panel = panels[panels.length - 1];
  const before = panel.latest.svg;
  const sent = panel.posted.length;
  await shown.saved(save(dir, 'other.axitl', MAIN));
  assert.strictEqual(panel.posted.length, sent);
  await shown.saved(save(dir, 'bits.axitl', 'event "Moved" 1960\n'));
  assert.notStrictEqual(panel.latest.svg, before);
  shown.dispose();
});

withAxitime('unsaved changes are flagged, and closing a panel removes its folder', async () => {
  const { uri, documents } = folder({ 'main.axitl': MAIN, 'bits.axitl': BITS });
  const shown = previewer();
  await shown.show(uri('main.axitl'), vscode.ViewColumn.Beside);
  const panel = panels[panels.length - 1];
  const preview = shown.panels.get(uri('main.axitl').fsPath);
  shown.changed(Object.assign({}, documents['main.axitl'], { isDirty: true }));
  assert.strictEqual(panel.latest.dirty, true);
  panel.dispose();
  assert.strictEqual(fs.existsSync(preview.dir), false);
  assert.strictEqual(shown.panels.size, 0);
});

withAxitime('a panel restored after a reload renders its timeline again', async () => {
  const { uri } = folder({ 'main.axitl': MAIN, 'bits.axitl': BITS });
  const panel = vscode.window.createWebviewPanel(VIEW_TYPE, 'old', vscode.ViewColumn.Beside, {});
  await registered.serializer.serializer.deserializeWebviewPanel(panel, { file: uri('main.axitl').fsPath });
  assert.ok(panel.latest.svg);
  panel.dispose();
  const gone = vscode.window.createWebviewPanel(VIEW_TYPE, 'old', vscode.ViewColumn.Beside, {});
  await registered.serializer.serializer.deserializeWebviewPanel(gone, { file: path.join(os.tmpdir(), 'no-such.axitl') });
  assert.strictEqual(gone.disposed, true);
});
