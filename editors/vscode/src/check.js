'use strict';
// Diagnostics from `axitime check --json`, run when an .axitl file is opened or saved. The real parser and layout
// do the checking, so the editor reports exactly what render would. Diagnostics carry a file and line, not a
// column, so each covers its line's code.

const vscode = require('vscode');
const childProcess = require('child_process');
const fs = require('fs');
const path = require('path');
const { splitComment } = require('./analyse');

const TIMEOUT_MS = 60000;
const VENV_AXITIME = process.platform === 'win32' ? ['Scripts', 'axitime.exe'] : ['bin', 'axitime'];

/**
 * The command that runs axitime for a file in `dir`: the setting if given, else the axitime in the nearest
 * `.venv` at or above `dir`, else `axitime` on the PATH. Not `uv run`, which checks the environment is up to date
 * before every run: slower, on every save.
 */
function axitimeCommand(dir, configured) {
  if (configured && configured.length) return configured;
  for (let d = dir; ; d = path.dirname(d)) {
    const candidate = path.join(d, '.venv', ...VENV_AXITIME);
    if (fs.existsSync(candidate)) return [candidate];
    if (path.dirname(d) === d) return ['axitime'];
  }
}

/** Whether a document declares a timeline. One that doesn't is an include (language spec §5). */
function hasTimeline(text) {
  return text.split(/\r?\n/).some((line) => /^\s*timeline(?![\w])/.test(splitComment(line).code));
}

/**
 * A check report's diagnostics as `{file, line, severity, code, message}`, with absolute file names and
 * 0-based lines. Names in the report are relative to `dir`, where axitime ran. An include checked on its own
 * has no timeline by design, so that error is left out for it.
 */
function readReport(report, dir, file, isInclude) {
  return report.diagnostics
    .filter((d) => !(isInclude && d.code === 'missing-timeline'))
    .map((d) => ({
      file: d.source ? path.resolve(dir, d.source) : file,
      line: d.line ? d.line - 1 : 0,
      severity: d.severity,
      code: d.code,
      message: d.message,
    }));
}

class Checker {
  constructor() {
    this.collection = vscode.languages.createDiagnosticCollection('axitl');
    this.output = vscode.window.createOutputChannel('AxiTimeline');
    this.results = new Map(); // checked file → the diagnostics its check found, in any file it includes
    this.running = new Map(); // checked file → its axitime process
    this.warned = false;
  }

  /** Check an .axitl document saved on disk. Resolves once its diagnostics are published. */
  check(document) {
    if (document.languageId !== 'axitl' || document.uri.scheme !== 'file') return Promise.resolve();
    const file = document.uri.fsPath;
    const settings = vscode.workspace.getConfiguration('axitl', document.uri);
    if (!vscode.workspace.isTrusted || !settings.get('check.enabled', true)) {
      this.forget(file);
      return Promise.resolve();
    }
    const dir = path.dirname(file);
    const [command, ...args] = axitimeCommand(dir, settings.get('check.command'));
    const isInclude = !hasTimeline(document.getText());
    const previous = this.running.get(file);
    if (previous) previous.kill();
    return new Promise((resolve) => {
      const child = childProcess.execFile(
        command,
        args.concat('check', '--json', path.basename(file)),
        { cwd: dir, timeout: TIMEOUT_MS, maxBuffer: 16 * 1024 * 1024 },
        (err, stdout, stderr) => {
          if (this.running.get(file) !== child) return resolve(); // superseded by a later check
          this.running.delete(file);
          let report = null;
          try {
            report = JSON.parse(stdout);
          } catch (parseError) {
            this.failed(file, command, err, stderr);
          }
          if (report) {
            this.results.set(file, readReport(report, dir, file, isInclude));
            this.output.appendLine(`${file}: ${report.errors} error(s), ${report.warnings} warning(s)`);
          } else {
            this.results.delete(file);
          }
          this.publish();
          resolve();
        }
      );
      this.running.set(file, child);
    });
  }

  /** After a save: an include may be part of any open timeline, so those are checked again too. */
  saved(document) {
    const checks = [this.check(document)];
    if (document.languageId === 'axitl' && !hasTimeline(document.getText())) {
      for (const other of vscode.workspace.textDocuments) {
        if (other !== document && other.languageId === 'axitl' && hasTimeline(other.getText())) {
          checks.push(this.check(other));
        }
      }
    }
    return Promise.all(checks);
  }

  checkAll() {
    return Promise.all(vscode.workspace.textDocuments.map((d) => this.check(d)));
  }

  forget(file) {
    const child = this.running.get(file);
    if (child) child.kill();
    this.running.delete(file);
    if (this.results.delete(file)) this.publish();
  }

  failed(file, command, err, stderr) {
    const reason = err && err.code === 'ENOENT' ? `${command} was not found` : (stderr || String(err)).trim();
    this.output.appendLine(`${file}: couldn't check with ${command}: ${reason}`);
    if (this.warned) return;
    this.warned = true;
    vscode.window
      .showWarningMessage(
        `AxiTimeline couldn't run axitime check: ${reason}. Set axitl.check.command, or run uv sync in the ` +
          'AxiTimeline repo.',
        'Open Settings',
        'Show Output'
      )
      .then((choice) => {
        if (choice === 'Open Settings') vscode.commands.executeCommand('workbench.action.openSettings', 'axitl.check');
        if (choice === 'Show Output') this.output.show();
      });
  }

  /** Every check's diagnostics, merged per file. A file checked itself and through an include appears once. */
  publish() {
    const byFile = new Map();
    const seen = new Set();
    const lines = new Map();
    for (const found of this.results.values()) {
      for (const d of found) {
        const key = [d.file, d.line, d.code, d.message].join('\0');
        if (seen.has(key)) continue;
        seen.add(key);
        if (!lines.has(d.file)) lines.set(d.file, linesOf(d.file));
        const diagnostic = new vscode.Diagnostic(
          lineRange(lines.get(d.file), d.line),
          d.message,
          d.severity === 'error' ? vscode.DiagnosticSeverity.Error : vscode.DiagnosticSeverity.Warning
        );
        diagnostic.source = 'axitime';
        diagnostic.code = d.code;
        if (!byFile.has(d.file)) byFile.set(d.file, []);
        byFile.get(d.file).push(diagnostic);
      }
    }
    this.collection.clear();
    for (const [file, diagnostics] of byFile) this.collection.set(vscode.Uri.file(file), diagnostics);
  }

  dispose() {
    for (const child of this.running.values()) child.kill();
    this.running.clear();
    this.collection.dispose();
    this.output.dispose();
  }
}

/** A file's lines: from its open document if there is one, else from disk. */
function linesOf(file) {
  const open = vscode.workspace.textDocuments.find((d) => d.uri.fsPath === file);
  if (open) {
    const lines = [];
    for (let i = 0; i < open.lineCount; i++) lines.push(open.lineAt(i).text);
    return lines;
  }
  try {
    return fs.readFileSync(file, 'utf8').split(/\r?\n/);
  } catch (err) {
    return [];
  }
}

/** A line's code, without its indentation or comment. */
function lineRange(lines, line) {
  const index = Math.max(0, Math.min(line, lines.length - 1));
  const code = splitComment(lines[index] || '').code;
  const start = code.length - code.trimStart().length;
  return new vscode.Range(index, start, index, Math.max(start, code.trimEnd().length));
}

module.exports = { Checker, axitimeCommand, hasTimeline, readReport };
