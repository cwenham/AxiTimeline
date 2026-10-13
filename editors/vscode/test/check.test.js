'use strict';
const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { vscode, settings, warnings, document } = require('./vscode-stub');
const { Checker, axitimeCommand, hasTimeline, readReport } = require('../src/check');

const REPO = path.join(__dirname, '..', '..', '..');
const AXITIME = path.join(REPO, '.venv', 'bin', 'axitime'); // from uv sync; the checks that run it need it

const made = [];
process.on('exit', () => {
  for (const dir of made) (fs.rmSync || fs.rmdirSync)(dir, { recursive: true, force: true });
});

/** A fresh folder holding the given files, and open documents for them. Removed when the tests end. */
function folder(files) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'axitl-check-'));
  made.push(dir);
  const documents = {};
  for (const [name, text] of Object.entries(files)) {
    const file = path.join(dir, name);
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(file, text);
    documents[name] = document(text, file);
  }
  return { dir, documents, file: (name) => path.join(dir, name) };
}

/** Each file's diagnostics as [line, start, end, severity, code]. */
function found(checker) {
  const out = {};
  for (const [file, list] of checker.collection.entries) {
    out[path.basename(file)] = list.map((d) => [d.range.start.line, d.range.start.character, d.range.end.character, d.severity, d.code]);
  }
  return out;
}

const MAIN = [
  'timeline start=1900 end=2000 length=1m width=210',
  '',
  'include "common/bits.axitl"',
  '  span "Typo" 1910-12 purple   // two errors on this line',
  'event "Glyph’s" 1950',
].join('\n');
const BITS = ['person "Bad date" 1900-13-40 red', 'span "Fine" 1920-1930 fill=stripes'].join('\n');
const E = vscode.DiagnosticSeverity.Error;
const W = vscode.DiagnosticSeverity.Warning;

// -- finding axitime and reading its report ----------------------------------------------------------------

test('axitime is the setting, else the nearest .venv above the file, else on the PATH', () => {
  const { dir } = folder({ 'a/.venv/bin/axitime': '', 'a/b/c/x.axitl': '' });
  assert.deepStrictEqual(axitimeCommand(path.join(dir, 'a/b/c'), ['my', 'axitime']), ['my', 'axitime']);
  assert.deepStrictEqual(axitimeCommand(path.join(dir, 'a/b/c'), []), [path.join(dir, 'a/.venv/bin/axitime')]);
  assert.deepStrictEqual(axitimeCommand(dir, undefined), ['axitime']);
});

test('a document without a timeline declaration is an include', () => {
  assert.strictEqual(hasTimeline(MAIN), true);
  assert.strictEqual(hasTimeline('  timeline\n    start=1900'), true);
  assert.strictEqual(hasTimeline(BITS), false);
  assert.strictEqual(hasTimeline('// timeline start=1900\nevent "timeline" 1900'), false);
});

test('a report becomes absolute files and 0-based lines; an include is not told it lacks a timeline', () => {
  const report = {
    diagnostics: [
      { severity: 'error', code: 'missing-timeline', message: 'm', source: 'bits.axitl', line: 1 },
      { severity: 'error', code: 'bad-date', message: 'd', source: 'sub/x.axitl', line: 3 },
      { severity: 'warning', code: 'w', message: 'no location', source: null, line: null },
    ],
  };
  const read = readReport(report, '/t', '/t/bits.axitl', true);
  assert.deepStrictEqual(read, [
    { file: '/t/sub/x.axitl', line: 2, severity: 'error', code: 'bad-date', message: 'd' },
    { file: '/t/bits.axitl', line: 0, severity: 'warning', code: 'w', message: 'no location' },
  ]);
  assert.strictEqual(readReport(report, '/t', '/t/bits.axitl', false).length, 3);
});

// -- running it --------------------------------------------------------------------------------------------

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

withAxitime("checking a timeline reports its own and its includes' problems, each across its line's code", async () => {
  const { documents } = folder({ 'main.axitl': MAIN, 'common/bits.axitl': BITS });
  const checker = new Checker();
  await checker.check(documents['main.axitl']);
  assert.deepStrictEqual(found(checker), {
    'main.axitl': [[3, 2, 28, E, 'needs-range'], [3, 2, 28, E, 'unknown-pen'], [4, 0, 20, W, 'missing-glyph']],
    'bits.axitl': [[0, 0, 32, E, 'bad-date'], [1, 0, 34, E, 'bad-value']],
  });
  const diagnostic = checker.collection.entries.get(documents['main.axitl'].uri.fsPath)[1];
  assert.strictEqual(diagnostic.source, 'axitime');
  assert.ok(diagnostic.message.includes("'purple' is not a pen"));
});

withAxitime('an include checked on its own and through its timeline shows each problem once', async () => {
  const { documents } = folder({ 'main.axitl': MAIN, 'common/bits.axitl': BITS });
  const checker = new Checker();
  await checker.check(documents['main.axitl']);
  await checker.check(documents['common/bits.axitl']);
  assert.deepStrictEqual(found(checker)['bits.axitl'].map((d) => d[4]), ['bad-date', 'bad-value']);
  checker.forget(documents['main.axitl'].uri.fsPath); // closed: the include keeps its own check's findings
  assert.deepStrictEqual(Object.keys(found(checker)), ['bits.axitl']);
  checker.forget(documents['common/bits.axitl'].uri.fsPath);
  assert.deepStrictEqual(found(checker), {});
});

withAxitime('saving an include checks the open timelines again too', async () => {
  const { documents } = folder({ 'main.axitl': MAIN, 'common/bits.axitl': BITS });
  vscode.workspace.textDocuments = [documents['main.axitl'], documents['common/bits.axitl']];
  const checker = new Checker();
  await checker.saved(documents['common/bits.axitl']);
  assert.ok(found(checker)['main.axitl'], 'main.axitl was checked');
});

withAxitime('a clean file has no diagnostics', async () => {
  const checker = new Checker();
  await checker.check(document(fs.readFileSync(path.join(REPO, 'examples/chernobyl.axitl'), 'utf8'),
    path.join(REPO, 'examples/chernobyl.axitl')));
  assert.deepStrictEqual(found(checker), {});
});

withAxitime('nothing is run in an untrusted workspace, or with checking switched off', async () => {
  const { documents } = folder({ 'main.axitl': MAIN, 'common/bits.axitl': BITS });
  const checker = new Checker();
  await checker.check(documents['main.axitl']);
  vscode.workspace.isTrusted = false;
  try {
    await checker.check(documents['main.axitl']);
    assert.deepStrictEqual(found(checker), {});
  } finally {
    vscode.workspace.isTrusted = true;
  }
  settings['check.enabled'] = false;
  try {
    await checker.check(documents['main.axitl']);
    assert.deepStrictEqual(found(checker), {});
  } finally {
    delete settings['check.enabled'];
  }
});

test('when axitime cannot be run, say so once and show nothing', async () => {
  const { documents } = folder({ 'main.axitl': MAIN });
  settings['check.command'] = [path.join(os.tmpdir(), 'no-such-axitime')];
  warnings.length = 0;
  try {
    const checker = new Checker();
    await checker.check(documents['main.axitl']);
    await checker.check(documents['main.axitl']);
    assert.deepStrictEqual(found(checker), {});
    assert.strictEqual(warnings.length, 1);
    assert.ok(warnings[0].includes('no-such-axitime was not found'), warnings[0]);
    assert.ok(checker.output.lines.length === 2);
  } finally {
    delete settings['check.command'];
  }
});
