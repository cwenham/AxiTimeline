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

const FileType = { File: 1, Directory: 2, SymbolicLink: 64 };
const CompletionItemKind = {};
['Keyword', 'Property', 'Color', 'Function', 'EnumMember', 'Constant', 'Unit', 'Folder', 'File'].forEach(
  (name) => (CompletionItemKind[name] = name)
);

const registered = {};
const vscode = {
  Range,
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
  },
  workspace: {
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

/** A text document holding `text`, as if saved at `fsPath`. */
function document(text, fsPath) {
  const lines = text.split('\n');
  return { uri: Uri.file(fsPath), lineCount: lines.length, lineAt: (i) => ({ text: lines[i] }) };
}

module.exports = { vscode, registered, document };
