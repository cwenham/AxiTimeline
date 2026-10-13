'use strict';
// Completion and hover help for .axitl files. Highlighting is the TextMate grammar in syntaxes/; comments,
// brackets and indentation are in language-configuration.json. What fits where is worked out in analyse.js.

const vscode = require('vscode');
const { completionContext, hoverTarget, splitComment, PENS } = require('./analyse');
const docs = require('./docs');
const vocabulary = require('./vocabulary.json');

const SUGGEST = { title: 'Suggest', command: 'editor.action.triggerSuggest' };
const REQUIRED = ['start', 'end', 'width'];
const ONE_OF = { length: 'scale', scale: 'length' };
const SUGGESTS_VALUES = new Set(Object.keys(vocabulary.values).concat(['font', 'scale']));

const TEMPLATES = {
  timeline: ['timeline\n\tstart=${1:1900}\n\tend=${2:now}\n\tlength=${3:2m}\n\twidth=${4:210}\n$0', 'start, end, length, width'],
  include: ['include "$1"$0', 'include "file.axitl"'],
  person: ['person "${1:Name}" ${2:1900}-${3:1950}$0', 'person "Name" 1900-1950'],
  event: ['event "${1:Name}" ${2:1900}$0', 'event "Name" 1900'],
  span: ['span "${1:Name}" ${2:1900}-${3:1950}$0', 'span "Name" 1900-1950'],
  group: ['group "${1:Name}" ${2:1900}-${3:1950} {\n\t$0\n}', 'group "Name" 1900-1950 { … }'],
};

function activate(context) {
  const selector = { language: 'axitl' };
  context.subscriptions.push(
    vscode.languages.registerCompletionItemProvider(selector, { provideCompletionItems }, '=', '"', '(', '/'),
    vscode.languages.registerHoverProvider(selector, { provideHover })
  );
}

function deactivate() {}

function linesOf(document) {
  const lines = [];
  for (let i = 0; i < document.lineCount; i++) lines.push(document.lineAt(i).text);
  return lines;
}

function markdown(text) {
  const md = new vscode.MarkdownString(text);
  md.supportHtml = true;
  return md;
}

/** Insert over what has been typed, or replace up to the end of the word (the user's insert mode decides). */
function rangeFor(position, start, after, rest) {
  const end = position.character + rest.exec(after)[0].length;
  return {
    inserting: new vscode.Range(position.line, start, position.line, position.character),
    replacing: new vscode.Range(position.line, start, position.line, end),
  };
}

const WORD_REST = /^[^\s"{}()=]*/;

async function provideCompletionItems(document, position) {
  const lines = linesOf(document);
  const at = completionContext(lines, position.line, position.character);
  const after = lines[position.line].slice(position.character);
  switch (at.kind) {
    case 'statement':
      return statementItems(at, rangeFor(position, at.start, after, WORD_REST), after);
    case 'item':
      return itemItems(at, rangeFor(position, at.start, after, WORD_REST));
    case 'value':
      return valueItems(at, position, after, document);
    case 'path':
      return pathItems(at, position, after, document, at.purpose);
    default:
      return [];
  }
}

function statementItems(at, range, after) {
  // On a line that already has more after the cursor, a keyword goes in alone rather than as a template.
  const bare = splitComment(after).code.trim() !== '';
  const continuingSettings = at.continues && (at.continues.decl === 'timeline' || at.continues.decl === 'include');
  const words = at.marks ? vocabulary.entities : (at.timeline ? ['timeline'] : []).concat('include', vocabulary.entities);
  const items = words.map((word, i) => {
    const item = new vscode.CompletionItem(word, vscode.CompletionItemKind.Keyword);
    item.range = range;
    item.documentation = markdown(docs.keywords[word]);
    item.sortText = (continuingSettings ? '1' : '0') + String(i).padStart(2, '0');
    if (!bare) {
      item.insertText = new vscode.SnippetString(TEMPLATES[word][0]);
      item.detail = TEMPLATES[word][1];
      if (word === 'include') item.command = SUGGEST;
    }
    return item;
  });
  if (at.continues) {
    items.push(...parameterItems(at.continues.decl, at.continues.used, range, continuingSettings ? '0' : '1'));
  }
  return items;
}

function parameterItems(decl, used, range, group) {
  let keys;
  if (decl === 'timeline') keys = vocabulary.timelineParameters;
  else if (decl === 'include') keys = vocabulary.includeParameters;
  else if (decl === 'illustration') keys = vocabulary.illustrationParameters;
  else {
    keys = vocabulary.entityParameters.filter(
      (key) =>
        (key !== 'fill' || vocabulary.bandedEntities.includes(decl)) &&
        (key !== 'time_label' || decl === 'event' || decl === 'group')
    );
  }
  return keys
    .filter((key) => !used.has(key) && !(decl === 'timeline' && used.has(ONE_OF[key])))
    .map((key, i) => {
      const item = new vscode.CompletionItem(`${key}=`, vscode.CompletionItemKind.Property);
      item.range = range;
      item.documentation = markdown(docs.parameters[key]);
      let rank = '1';
      if (decl === 'timeline' && (REQUIRED.includes(key) || ONE_OF[key])) {
        item.detail = ONE_OF[key] ? `required: this or ${ONE_OF[key]}=` : 'required';
        rank = '0';
      }
      item.sortText = group + rank + String(i).padStart(2, '0');
      if (SUGGESTS_VALUES.has(key)) item.command = SUGGEST;
      return item;
    });
}

function itemItems(at, range) {
  const items = [];
  const entity = vocabulary.entities.includes(at.decl);
  if (entity && !at.pen) {
    PENS.forEach((pen, i) => {
      // A colour item whose documentation is a colour string gets a swatch in the list.
      const item = new vscode.CompletionItem(pen, vscode.CompletionItemKind.Color);
      item.range = range;
      item.detail = docs.penDetail(pen);
      item.documentation = vocabulary.pens[pen];
      item.sortText = '0' + String(i).padStart(2, '0');
      items.push(item);
    });
  }
  items.push(...parameterItems(at.decl, at.used, range, '1'));
  if (entity && !at.illustration) {
    const item = new vscode.CompletionItem('illustration(…)', vscode.CompletionItemKind.Function);
    item.range = range;
    item.filterText = 'illustration';
    item.insertText = new vscode.SnippetString('illustration($1)$0');
    item.documentation = markdown(docs.keywords.illustration);
    item.sortText = '2';
    item.command = SUGGEST;
    items.push(item);
  }
  return items;
}

async function valueItems(at, position, after, document) {
  const range = rangeFor(position, at.start, after, at.quoted ? /^[^"]*/ : WORD_REST);
  if (at.key === 'font') return fontItems(at, position, after, document, range);
  if (at.key === 'scale') return scaleItems(at, range);
  const options = vocabulary.values[at.key] || [];
  const help = docs.values[at.key] || {};
  return options.map((value, i) => {
    const item = new vscode.CompletionItem(value, vscode.CompletionItemKind.EnumMember);
    item.range = range;
    item.documentation = help[value] && markdown(help[value]);
    item.sortText = String(i).padStart(2, '0');
    return item;
  });
}

async function fontItems(at, position, after, document, range) {
  const items = [];
  if (!at.prefix.includes('/')) {
    vocabulary.fonts.forEach((name, i) => {
      const item = new vscode.CompletionItem(name, vscode.CompletionItemKind.Constant);
      item.range = range;
      item.insertText = at.quoted ? name + (after.startsWith('"') ? '' : '"') : `"${name}"`;
      item.detail = name === vocabulary.defaultFont ? 'built-in font (default)' : 'built-in font';
      item.sortText = '0' + String(i).padStart(2, '0');
      items.push(item);
    });
  }
  // A custom font is an .svg file; a bare value gets quotes, so that a path can follow.
  const files = await pathItems(at, position, after, document, 'font');
  if (!at.quoted) {
    for (const item of files) item.insertText = `"${item.insertText}${item.kind === vscode.CompletionItemKind.File ? '"' : ''}`;
  }
  return items.concat(files);
}

function scaleItems(at, range) {
  const number = (/^(\d+(?:\.\d*)?|\.\d+)/.exec(at.prefix) || [])[1];
  return vocabulary.scaleUnits.map((unit, i) => {
    const item = new vscode.CompletionItem(`${number || '5'}mm/${unit}`, vscode.CompletionItemKind.Unit);
    item.range = range;
    item.insertText = number ? item.label : new vscode.SnippetString(`\${1:5}mm/${unit}`);
    item.documentation = markdown(docs.parameters.scale);
    item.sortText = String(i);
    return item;
  });
}

/** Files and folders beside the document, for an include, an illustration or a custom font. */
async function pathItems(at, position, after, document, purpose) {
  if (document.uri.scheme !== 'file') return [];
  const slash = at.prefix.lastIndexOf('/');
  const folder = vscode.Uri.joinPath(document.uri, '..', at.prefix.slice(0, slash + 1));
  const base = at.prefix.slice(slash + 1);
  const start = position.character - base.length;
  const range = rangeFor(position, start, after, at.quoted ? /^[^"/]*/ : /^[^\s"{}()=/]*/);
  let entries;
  try {
    entries = await vscode.workspace.fs.readDirectory(folder);
  } catch (err) {
    return [];
  }
  const extension = purpose === 'include' ? '.axitl' : '.svg';
  const close = at.quoted && !after.replace(/^[^"]*/, '').startsWith('"') ? '"' : '';
  const items = [];
  for (const [name, type] of entries.sort((a, b) => (a[0] < b[0] ? -1 : 1))) {
    if (name.startsWith('.')) continue;
    let item;
    if (type & vscode.FileType.Directory) {
      item = new vscode.CompletionItem(`${name}/`, vscode.CompletionItemKind.Folder);
      item.insertText = `${name}/`;
      item.command = SUGGEST;
      item.sortText = `1${name}`;
    } else if (name.toLowerCase().endsWith(extension)) {
      if (vscode.Uri.joinPath(folder, name).toString() === document.uri.toString()) continue;
      item = new vscode.CompletionItem(name, vscode.CompletionItemKind.File);
      item.insertText = name + close;
      item.sortText = `0${name}`;
    } else {
      continue;
    }
    item.range = range;
    items.push(item);
  }
  return items;
}

function provideHover(document, position) {
  const target = hoverTarget(linesOf(document), position.line, position.character);
  const text = target && describe(target);
  if (!text) return null;
  return new vscode.Hover(markdown(text), new vscode.Range(position.line, target.start, position.line, target.end));
}

function describe(target) {
  switch (target.type) {
    case 'keyword':
      return `**${target.name}**\n\n${docs.keywords[target.name]}`;
    case 'head':
      return `**${target.name}**\n\n${docs.head(target)}`;
    case 'parameter':
      return docs.parameters[target.name] && `**${target.name}=**\n\n${docs.parameters[target.name]}`;
    case 'value': {
      const help = (docs.values[target.key] || {})[target.name];
      return help && `**${target.key}=${target.name}**\n\n${help}`;
    }
    case 'pen':
      return `<span style="color:${vocabulary.pens[target.name]};">■</span> **${target.name}**\n\n${docs.pen(target.name)}`;
    case 'font':
      return docs.font(target.name);
    default:
      return null;
  }
}

module.exports = { activate, deactivate };
