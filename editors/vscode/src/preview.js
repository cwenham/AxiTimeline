'use strict';
// A rendered preview of a timeline, beside its source: `axitime render --preview-only` writes the every-pen
// preview SVG to a folder of the panel's own, and the panel shows it on white paper (media/preview.js does the
// zooming). Like the checks, it renders the file as saved, on opening and on each save.

const vscode = require('vscode');
const childProcess = require('child_process');
const crypto = require('crypto');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { axitimeCommand, hasTimeline } = require('./check');

const VIEW_TYPE = 'axitl.preview';
const TIMEOUT_MS = 120000;
// Saving one of these may change a drawing: an illustration or custom font, or a graph's data.
const RESOURCE = /\.(svg|csv|tsv|txt)$/i;

/** A preview SVG's size in mm, from its width and height attributes ("400mm"). */
function svgSize(svg) {
  const head = svg.slice(0, svg.indexOf('>', svg.indexOf('<svg')) + 1);
  const mm = (name) => {
    const match = new RegExp(`\\s${name}="([\\d.]+)mm"`).exec(head);
    return match ? Number(match[1]) : null;
  };
  return { widthMm: mm('width'), heightMm: mm('height') };
}

/** Remove a file or folder, if it's there (fs.rmSync is newer than the node the tests allow). */
function remove(target) {
  try {
    (fs.rmSync || fs.rmdirSync)(target, { recursive: true, force: true });
  } catch (err) {
    // already gone
  }
}

/** What a failed render printed, less the count it ends with. File names are relative to the timeline's folder. */
function failureText(command, stdout, stderr, err) {
  if (err && err.code === 'ENOENT') {
    return `${command} was not found. Set axitl.check.command, or run uv sync in the AxiTimeline repo.`;
  }
  const lines = `${stdout}\n${stderr}`.split(/\r?\n/).filter((line) => line.trim() && !/: render failed with /.test(line));
  if (lines.length) return lines.join('\n');
  return err && err.killed ? 'axitime took too long and was stopped' : String(err || 'unknown error');
}

class Preview {
  constructor(previewer, file, panel) {
    this.previewer = previewer;
    this.file = file;
    this.panel = panel;
    this.dir = fs.mkdtempSync(path.join(os.tmpdir(), 'axitl-preview-'));
    this.child = null;
    this.latest = { type: 'status', rendering: true }; // what the webview is told when it (re)loads
    this.dirty = false;
    panel.title = `Preview ${path.basename(file)}`;
    panel.webview.options = { enableScripts: true, localResourceRoots: [vscode.Uri.joinPath(previewer.extensionUri, 'media')] };
    panel.webview.html = this.html();
    panel.webview.onDidReceiveMessage((message) => {
      if (message && message.type === 'ready') this.post();
    });
    panel.onDidDispose(() => this.dispose());
  }

  html() {
    const webview = this.panel.webview;
    const media = (name) => webview.asWebviewUri(vscode.Uri.joinPath(this.previewer.extensionUri, 'media', name));
    const nonce = crypto.randomBytes(16).toString('base64');
    const csp = [
      "default-src 'none'",
      'img-src blob:',
      `style-src ${webview.cspSource}`,
      `script-src 'nonce-${nonce}'`,
    ].join('; ');
    const file = JSON.stringify(this.file).replace(/</g, '\\u003c');
    return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta http-equiv="Content-Security-Policy" content="${csp}">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<link rel="stylesheet" href="${media('preview.css')}">
<title>Preview</title>
</head>
<body>
<div id="bar">
  <button data-zoom="fit" title="Show the whole timeline">Fit</button>
  <button data-zoom="height" title="Fit the roll's width to the panel's height, and scroll along the timeline">Fit height</button>
  <button data-zoom="out" title="Zoom out (or Ctrl and scroll, or pinch)">−</button>
  <span id="zoom" title="Size against the paper's own"></span>
  <button data-zoom="in" title="Zoom in (or Ctrl and scroll, or pinch)">+</button>
  <button data-zoom="actual" title="Actual size, as plotted">1:1</button>
  <span id="status"></span>
</div>
<div id="banner" hidden></div>
<div id="view"><div id="stage"><div id="paper"><img id="drawing" alt=""></div></div></div>
<script nonce="${nonce}">window.AXITL_FILE = ${file};</script>
<script nonce="${nonce}" src="${media('preview.js')}"></script>
</body>
</html>`;
  }

  /** Send the webview the latest render (or failure), and whether the editor has unsaved changes. */
  post() {
    this.panel.webview.postMessage(Object.assign({}, this.latest, { dirty: this.dirty }));
  }

  update(message) {
    // A failure keeps the last drawing on screen, so a typo doesn't blank the panel.
    const { svg, widthMm, heightMm } = this.latest;
    this.latest = Object.assign(svg ? { svg, widthMm, heightMm } : {}, message);
    this.post();
  }

  /** Render the file as saved. Resolves once the webview has been sent the result. */
  render() {
    if (this.child) this.child.kill();
    this.child = null;
    const document = vscode.workspace.textDocuments.find((d) => d.uri.fsPath === this.file);
    let text = document ? document.getText() : null;
    if (text === null) {
      try {
        text = fs.readFileSync(this.file, 'utf8');
      } catch (err) {
        this.update({ type: 'status', error: `Can't read ${path.basename(this.file)}: ${err.message}` });
        return Promise.resolve();
      }
    }
    if (!vscode.workspace.isTrusted) {
      this.update({ type: 'status', error: 'Previews run axitime, a program in the workspace, so they only render in a trusted workspace.' });
      return Promise.resolve();
    }
    if (!hasTimeline(text)) {
      this.update({ type: 'status', error: 'This file has no timeline, so it is an include: preview a timeline that includes it.' });
      return Promise.resolve();
    }
    const dir = path.dirname(this.file);
    const settings = vscode.workspace.getConfiguration('axitl', vscode.Uri.file(this.file));
    const [command, ...args] = axitimeCommand(dir, settings.get('check.command'));
    const out = path.join(this.dir, 'out');
    remove(out);
    this.update({ type: 'status', rendering: true, error: null });
    return new Promise((resolve) => {
      const child = childProcess.execFile(
        command,
        args.concat('render', '--preview-only', '-o', out, path.basename(this.file)),
        { cwd: dir, timeout: TIMEOUT_MS, maxBuffer: 16 * 1024 * 1024 },
        (err, stdout, stderr) => {
          if (this.child !== child) return resolve(); // superseded by a later render, or closed
          this.child = null;
          const svgFile = path.join(out, `${path.parse(this.file).name}-preview.svg`);
          if (!err && fs.existsSync(svgFile)) {
            const svg = fs.readFileSync(svgFile, 'utf8');
            const warnings = (stdout.match(/: warning: /g) || []).length;
            this.update(Object.assign({ type: 'status', svg, rendering: false, error: null, warnings, at: Date.now() }, svgSize(svg)));
          } else {
            this.update({ type: 'status', rendering: false, error: failureText(command, stdout, stderr, err) });
          }
          resolve();
        }
      );
      this.child = child;
    });
  }

  setDirty(dirty) {
    if (dirty === this.dirty) return;
    this.dirty = dirty;
    this.post();
  }

  dispose() {
    if (this.child) this.child.kill();
    this.child = null;
    remove(this.dir);
    this.previewer.panels.delete(this.file);
  }
}

class Previewer {
  constructor(extensionUri) {
    this.extensionUri = extensionUri;
    this.panels = new Map(); // file → its Preview
  }

  /** Show (or bring forward) the preview of an .axitl file. Resolves once it has rendered. */
  show(uri, column) {
    if (!uri || uri.scheme !== 'file') {
      vscode.window.showInformationMessage('Save the timeline to a file to preview it.');
      return Promise.resolve();
    }
    const file = uri.fsPath;
    const open = this.panels.get(file);
    if (open) {
      open.panel.reveal(column);
      return Promise.resolve();
    }
    const panel = vscode.window.createWebviewPanel(VIEW_TYPE, `Preview ${path.basename(file)}`, column, {
      enableScripts: true,
      localResourceRoots: [vscode.Uri.joinPath(this.extensionUri, 'media')],
    });
    return this.attach(file, panel);
  }

  /** Take over a panel, new or restored after a reload, and render into it. */
  attach(file, panel) {
    const preview = new Preview(this, file, panel);
    this.panels.set(file, preview);
    const document = vscode.workspace.textDocuments.find((d) => d.uri.fsPath === file);
    preview.dirty = Boolean(document && document.isDirty);
    return preview.render();
  }

  /** After a save: re-render the file's own preview, or all of them for an include or a resource they may use. */
  saved(document) {
    const file = document.uri.fsPath;
    let previews = [];
    if (document.languageId === 'axitl') {
      previews = hasTimeline(document.getText()) ? [this.panels.get(file)].filter(Boolean) : [...this.panels.values()];
    } else if (RESOURCE.test(file)) {
      previews = [...this.panels.values()];
    }
    const own = this.panels.get(file);
    if (own) own.setDirty(false);
    return Promise.all(previews.map((p) => p.render()));
  }

  changed(document) {
    const preview = this.panels.get(document.uri.fsPath);
    if (preview) preview.setDirty(document.isDirty);
  }

  renderAll() {
    return Promise.all([...this.panels.values()].map((p) => p.render()));
  }

  dispose() {
    for (const preview of [...this.panels.values()]) preview.panel.dispose();
  }
}

module.exports = { Previewer, VIEW_TYPE, svgSize, failureText };
