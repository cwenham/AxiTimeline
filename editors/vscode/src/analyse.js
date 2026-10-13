'use strict';
/**
 * What can be typed, or what is written, at a position in an .axitl document, worked out from the text alone.
 *
 * Kept free of the vscode API so the tests can run it under plain node. It reads lines the way libaxitl's
 * preprocessor and grammar do (language spec §§3, 3.9, 3.10): `//` comments outside quotes, a declaration
 * continued on indented `key=value` lines, and each declaration shaped as a head, a quoted label, a date,
 * then items (pens, `key=value` parameters and `illustration(...)`).
 */

const vocabulary = require('./vocabulary.json');

const PENS = Object.keys(vocabulary.pens);
const PEN_SET = new Set(PENS);
const HEAD = /^([\^v]?)([!-]*)(person|event|span|group)$/;
const KEY_START = /^[A-Za-z_][A-Za-z0-9_]*=/;
const TOKEN = /\s+|"((?:[^"\\]|\\.?)*)("?)|[{}()=]|[^\s"{}()=]+/g;

/** The code on a line and the column its `//` comment starts at (-1 for none), skipping `//` inside quotes. */
function splitComment(line) {
  let inString = false;
  for (let i = 0; i < line.length; i++) {
    const c = line[i];
    if (inString) {
      if (c === '\\') i++;
      else if (c === '"') inString = false;
    } else if (c === '"') {
      inString = true;
    } else if (c === '/' && line[i + 1] === '/') {
      return { code: line.slice(0, i), comment: i };
    }
  }
  return { code: line, comment: -1 };
}

/**
 * Split code (no comment) into tokens: words, quoted strings (possibly still open) and the punctuation
 * `{ } ( ) =`. Positions are columns in the text given.
 */
function tokenize(text) {
  const tokens = [];
  TOKEN.lastIndex = 0;
  let m;
  while ((m = TOKEN.exec(text))) {
    const t = m[0];
    if (/^\s/.test(t)) continue;
    const token = { type: 'word', text: t, start: m.index, end: m.index + t.length };
    if (t[0] === '"') {
      token.type = 'string';
      token.content = m[1];
      token.closed = m[2] === '"';
    } else if ('{}()='.includes(t)) {
      token.type = t;
    }
    tokens.push(token);
  }
  return tokens;
}

function isContinuation(line) {
  return /^[ \t]/.test(line) && KEY_START.test(splitComment(line).code.trim());
}

/** The kind of declaration a head word starts: timeline, include, an entity keyword, or null. */
function declarationKind(word) {
  if (word === 'timeline' || word === 'include') return word;
  const m = HEAD.exec(word);
  return m ? m[3] : null;
}

/**
 * The declaration an indented line could continue (§3.10): the nearest line above that isn't a continuation,
 * reached through only continuation and comment lines. A blank line ends a declaration, and a line opening a
 * group's `{ }` body can't be continued. Returns its tokens, or null.
 */
function declarationAbove(lines, line) {
  const parts = [];
  for (let i = line - 1; i >= 0; i--) {
    const { code, comment } = splitComment(lines[i]);
    if (!code.trim()) {
      if (comment >= 0) continue;
      return null;
    }
    parts.unshift(code);
    if (isContinuation(lines[i])) continue;
    const trimmed = code.trim();
    if (trimmed.endsWith('{') || trimmed.endsWith('}')) return null;
    return { line: i, tokens: tokenize(parts.join(' ')) };
  }
  return null;
}

/** Tokens on the continuation lines below a line, up to the end of its declaration. */
function continuationBelow(lines, line) {
  const parts = [];
  for (let i = line + 1; i < lines.length; i++) {
    const { code, comment } = splitComment(lines[i]);
    if (!code.trim()) {
      if (comment >= 0) continue;
      break;
    }
    if (!isContinuation(lines[i])) break;
    parts.push(code);
  }
  return tokenize(parts.join(' '));
}

/** The parameters, pens and illustrations among a declaration's items (outside any `illustration(...)`). */
function summarise(tokens) {
  const keys = new Set();
  let pen = false;
  let illustration = false;
  let depth = 0;
  tokens.forEach((t, i) => {
    if (t.type === '(') depth++;
    else if (t.type === ')') depth = Math.max(0, depth - 1);
    else if (t.type === 'word' && depth === 0) {
      const next = tokens[i + 1];
      const prev = tokens[i - 1];
      if (next && next.type === '=') keys.add(t.text);
      else if (t.text === 'illustration') illustration = true;
      else if (PEN_SET.has(t.text) && !(prev && prev.type === '=')) pen = true;
    }
  });
  return { keys, pen, illustration };
}

/** Whether the line sits inside a group's `{ }` body. */
function insideBody(lines, line) {
  let depth = 0;
  for (let i = 0; i < line; i++) {
    for (const t of tokenize(splitComment(lines[i]).code)) {
      if (t.type === '{') depth++;
      else if (t.type === '}') depth = Math.max(0, depth - 1);
    }
  }
  return depth > 0;
}

const NONE = Object.freeze({ kind: 'none' });

/**
 * What fits at the cursor, for completion. One of:
 *
 * - `{kind: 'none'}`: a label, a date, a comment, or somewhere nothing can be suggested
 * - `{kind: 'statement', marks, prefix, start, timeline, inBody, continues}`: the start of a declaration.
 *   `marks` are side and priority marks already typed (only an entity can follow them); `timeline` says
 *   whether a timeline declaration is still possible here; `continues`, on an indented line, describes the
 *   declaration the line could continue instead (`{decl, used, pen, illustration}`), or is null
 * - `{kind: 'item', decl, prefix, start, used, pen, illustration}`: an item on a declaration's line: a
 *   parameter (`used` lists those already given), a pen (`pen` says one is already given) or an illustration
 * - `{kind: 'value', decl, key, prefix, start, quoted}`: the value after `key=`
 * - `{kind: 'path', purpose, prefix, start, quoted}`: a file name: `purpose` is include or illustration
 *
 * `decl` is timeline, include, illustration (inside its parentheses) or an entity keyword. `prefix` is what
 * has been typed of the thing being completed, and `start` the column it starts at, so a suggestion replaces
 * the columns from `start` to the cursor.
 */
function completionContext(lines, line, character) {
  const text = lines[line];
  const { comment } = splitComment(text);
  if (comment >= 0 && character > comment) return NONE;
  const own = tokenize(text.slice(0, character));
  const last = own[own.length - 1];
  const touching = last !== undefined && last.end === character;
  const indented = /^[ \t]/.test(text);
  const above = indented ? declarationAbove(lines, line) : null;

  if (own.length === 0 || (own.length === 1 && touching && own[0].type === 'word')) {
    const m = /^([\^v]?)([!-]*)([A-Za-z_]*)$/.exec(own.length ? own[0].text : '');
    if (!m) return NONE;
    const inBody = insideBody(lines, line);
    const hasTimeline = lines.some(
      (l, i) => i !== line && /^\s*timeline(?![\w])/.test(splitComment(l).code)
    );
    let continues = null;
    if (above && !m[1] && !m[2]) {
      const decl = declarationKind(above.tokens[0] ? above.tokens[0].text : '');
      if (decl) {
        const s = summarise(above.tokens.concat(continuationBelow(lines, line)));
        continues = { decl, used: s.keys, pen: s.pen, illustration: s.illustration };
      }
    }
    return {
      kind: 'statement',
      marks: m[1] + m[2],
      prefix: m[3],
      start: character - m[3].length,
      timeline: !hasTimeline && !indented && !inBody,
      inBody,
      continues,
    };
  }

  let tokens = own;
  if (own[0].type === 'word' && own[1] && own[1].type === '=') {
    if (!above) return NONE; // a key=value line with nothing above to continue
    tokens = above.tokens.concat(own);
  }
  const decl = tokens[0].type === 'word' ? declarationKind(tokens[0].text) : null;
  if (!decl) return NONE;

  let items;
  if (decl === 'timeline') {
    items = tokens.slice(1);
  } else if (decl === 'include') {
    const path = tokens[1];
    if (!path || path.type !== 'string') return NONE;
    if (!path.closed) return pathContext('include', path, character);
    if (path === last && touching) return NONE;
    items = tokens.slice(2);
  } else {
    const label = tokens[1];
    const date = tokens[2];
    if (!label || label.type !== 'string' || !label.closed) return NONE; // typing the label
    if (label === last && touching) return NONE;
    if (!date || date.type !== 'word' || (date === last && touching)) return NONE; // typing the date
    items = tokens.slice(3);
  }

  const after = text.slice(character).replace(/^[^\s"{}()=]*/, ''); // the rest of the line, less the word at the cursor
  const following = tokenize(splitComment(after).code).concat(continuationBelow(lines, line));
  const before = touching ? items.slice(0, -1) : items;
  return itemContext(decl, items, before.concat(following), touching, character);
}

function pathContext(purpose, token, character) {
  if (token && token.type === 'string') {
    return { kind: 'path', purpose, prefix: token.content, start: token.start + 1, quoted: true };
  }
  const prefix = token ? token.text : '';
  return { kind: 'path', purpose, prefix, start: character - prefix.length, quoted: false };
}

function itemContext(decl, items, others, touching, character) {
  // Inside an illustration's parentheses: its file name, then its own parameters.
  let open = -1;
  for (let i = items.length - 1; i >= 0; i--) {
    if (items[i].type === ')') break;
    if (items[i].type === '(') {
      open = i;
      break;
    }
  }
  if (open >= 0) {
    if (!(items[open - 1] && items[open - 1].text === 'illustration')) return NONE;
    const inner = items.slice(open + 1);
    if (inner.length === 0) return pathContext('illustration', null, character);
    if (inner.length === 1 && inner[0].type === 'string' && !inner[0].closed) {
      return pathContext('illustration', inner[0], character);
    }
    if (inner.length === 1 && touching && inner[0].type === 'word') {
      return pathContext('illustration', inner[0], character);
    }
    const used = summarise(inner.slice(1, touching ? -1 : undefined)).keys;
    return trailing('illustration', inner.slice(1), { keys: used, pen: false, illustration: false }, touching, character);
  }
  return trailing(decl, items, summarise(others), touching, character);
}

function trailing(decl, items, summary, touching, character) {
  const n = items.length;
  const last = items[n - 1];
  const value = (key, token) => {
    if (!key || key.type !== 'word') return NONE;
    if (!token) return { kind: 'value', decl, key: key.text, prefix: '', start: character, quoted: false };
    if (token.type === 'string') {
      if (token.closed) return NONE;
      return { kind: 'value', decl, key: key.text, prefix: token.content, start: token.start + 1, quoted: true };
    }
    return { kind: 'value', decl, key: key.text, prefix: token.text, start: token.start, quoted: false };
  };
  if (last && last.type === '=') return value(items[n - 2], null);
  if (last && touching && items[n - 2] && items[n - 2].type === '=') return value(items[n - 3], last);
  if (last && last.type === 'string' && !last.closed) return NONE;
  if (last && touching && last.type !== 'word') return NONE; // straight after a ) or a closing quote
  if (last && last.type === '{') return NONE; // a group's body has begun
  const prefix = touching ? last.text : '';
  return {
    kind: 'item',
    decl,
    prefix,
    start: character - prefix.length,
    used: summary.keys,
    pen: summary.pen,
    illustration: summary.illustration,
  };
}

/**
 * What is written at a position, for hover help. Returns null, or `{type, name, start, end}` where type is
 * keyword, head (with `side`, `priority` and `mixed`), parameter, value (with `key`), pen or font, and
 * start/end are the columns it covers.
 */
function hoverTarget(lines, line, character) {
  const text = lines[line];
  const { code, comment } = splitComment(text);
  if (comment >= 0 && character >= comment) return null;
  const tokens = tokenize(code);
  const i = tokens.findIndex((t) => t.start <= character && character < t.end);
  if (i < 0) return null;
  const t = tokens[i];
  const prev = tokens[i - 1];
  const next = tokens[i + 1];
  const span = { start: t.start, end: t.end };
  if (t.type === 'string') {
    const key = tokens[i - 2];
    if (prev && prev.type === '=' && key && key.text === 'font' && vocabulary.fonts.includes(t.content)) {
      return Object.assign({ type: 'font', name: t.content }, span);
    }
    return null;
  }
  if (t.type !== 'word') return null;
  if (i === 0 && !isContinuation(text)) {
    if (t.text === 'timeline' || t.text === 'include') return Object.assign({ type: 'keyword', name: t.text }, span);
    const m = HEAD.exec(t.text);
    if (m) {
      const run = m[2];
      const mixed = run.includes('!') && run.includes('-');
      const priority = mixed ? 0 : run.startsWith('!') ? run.length : -run.length;
      return Object.assign({ type: 'head', name: m[3], side: m[1], priority, mixed }, span);
    }
  }
  if (t.text === 'illustration' && next && next.type === '(') {
    return Object.assign({ type: 'keyword', name: 'illustration' }, span);
  }
  if (next && next.type === '=') return Object.assign({ type: 'parameter', name: t.text }, span);
  if (prev && prev.type === '=') {
    const key = tokens[i - 2];
    if (key && key.type === 'word') {
      if (key.text === 'font' && vocabulary.fonts.includes(t.text)) return Object.assign({ type: 'font', name: t.text }, span);
      return Object.assign({ type: 'value', key: key.text, name: t.text }, span);
    }
    return null;
  }
  if (PEN_SET.has(t.text)) return Object.assign({ type: 'pen', name: t.text }, span);
  return null;
}

module.exports = {
  PENS,
  completionContext,
  hoverTarget,
  splitComment,
  tokenize,
};
