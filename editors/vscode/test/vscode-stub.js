'use strict';
// Just enough of the vscode API for extension.js to run under plain node, with real file listing.

const fs = require('fs');
const path = require('path');
const Module = require('module');

class Range {
  constructor(startLine, startCharacter, endLine, endCharacter) {
    this.start = { line: startLine, character: startCharacter };
    this.end = { line: endLine, character: endCharacter };
  }
}

class CompletionItem {
  constructor(label, kind) {
    this.label = label;
    this.kind = kind;
  }
}

class SnippetString {
  constructor(value) {
    this.value = value;
  }
}

class MarkdownString {
  constructor(value) {
    this.value = value;
  }
}

class Hover {
  constructor(contents, range) {
    this.contents = contents;
    this.range = range;
  }
}

class Uri {
  constructor(fsPath) {
    this.scheme = 'file';
    this.fsPath = fsPath;
  }
  static file(fsPath) {
    return new Uri(path.resolve(fsPath));
  }
  static joinPath(uri, ...segments) {
    return new Uri(path.join(uri.fsPath, ...segments));
  }
  toString() {
    return `file://${this.fsPath}`;
  }
}

class Diagnostic {
  constructor(range, message, severity) {
    this.range = range;
    this.message = message;
    this.severity = severity;
  }
}

class DiagnosticCollection {
  constructor(name) {
    this.name = name;
    this.entries = new Map(); // fsPath → diagnostics
  }
  set(uri, diagnostics) {
    this.entries.set(uri.fsPath, diagnostics);
  }
  get(uri) {
    return this.entries.get(uri.fsPath);
  }
  clear() {
    this.entries.clear();
  }
  dispose() {}
}

const FileType = { File: 1, Directory: 2, SymbolicLink: 64 };
const DiagnosticSeverity = { Error: 0, Warning: 1 };
const disposable = () => ({ dispose() {} });
const CompletionItemKind = {};
['Keyword', 'Property', 'Color', 'Function', 'EnumMember', 'Constant', 'Unit', 'Folder', 'File'].forEach(
  (name) => (CompletionItemKind[name] = name)
);

const registered = {};
const settings = {}; // axitl.* settings, by key without the prefix
const warnings = []; // messages shown with window.showWarningMessage
const vscode = {
  Range,
  Diagnostic,
  DiagnosticSeverity,
  CompletionItem,
  CompletionItemKind,
  SnippetString,
  MarkdownString,
  Hover,
  Uri,
  FileType,
  languages: {
    registerCompletionItemProvider(selector, provider, ...triggers) {
      registered.completion = { selector, provider, triggers };
      return { dispose() {} };
    },
    registerHoverProvider(selector, provider) {
      registered.hover = { selector, provider };
      return { dispose() {} };
    },
    createDiagnosticCollection: (name) => new DiagnosticCollection(name),
  },
  window: {
    createOutputChannel: () => ({ lines: [], appendLine(line) { this.lines.push(line); }, show() {}, dispose() {} }),
    showWarningMessage(message) {
      warnings.push(message);
      return Promise.resolve(undefined);
    },
  },
  commands: { executeCommand: () => Promise.resolve() },
  workspace: {
    isTrusted: true,
    textDocuments: [],
    getConfiguration: () => ({ get: (key, fallback) => (key in settings ? settings[key] : fallback) }),
    onDidOpenTextDocument: disposable,
    onDidSaveTextDocument: disposable,
    onDidCloseTextDocument: disposable,
    onDidGrantWorkspaceTrust: disposable,
    onDidChangeConfiguration: disposable,
    fs: {
      async readDirectory(uri) {
        return fs.readdirSync(uri.fsPath, { withFileTypes: true }).map((d) => [
          d.name,
          d.isDirectory() ? FileType.Directory : FileType.File,
        ]);
      },
    },
  },
};

const load = Module._load;
Module._load = function (request, ...rest) {
  return request === 'vscode' ? vscode : load.call(this, request, ...rest);
};

/** An .axitl text document holding `text`, as if saved at `fsPath`. */
function document(text, fsPath) {
  const lines = text.split('\n');
  return {
    uri: Uri.file(fsPath),
    languageId: 'axitl',
    lineCount: lines.length,
    lineAt: (i) => ({ text: lines[i] }),
    getText: () => text,
  };
}

module.exports = { vscode, registered, settings, warnings, document };
