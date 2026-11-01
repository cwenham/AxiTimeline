"""The Lark grammar for flattened ``.axitl`` text.

By the time the grammar runs, the preprocessor has removed comments and includes and joined continuation
lines, so every declaration is one line. The grammar only fixes the shape of a line (a head, a quoted label,
then items, then an optional ``{ … }`` body); what the items mean (dates, pens, parameters) is checked by the
AST builder, which can give the author far more specific messages than a grammar error would.
"""

from __future__ import annotations

import functools

from lark import Lark

GRAMMAR = r"""
start: _NL? _statement*

_statement: timeline | entity | graph | title | credits | note

timeline: TIMELINE _item* _NL
entity: HEAD STRING _item* (body | _NL)
body: "{" _NL? _statement* "}" _NL
graph: GRAPH STRING _item* (points | _NL)
points: "{" _NL? point* "}" _NL
point: WORD+ _NL
title: TITLE STRING _item* _NL
credits: CREDITS _item* (credit_lines | _NL)
credit_lines: "{" _NL? credit_line* "}" _NL
credit_line: HEADING? STRING _NL
note: NOTE STRING? _item* (credit_lines | _NL)

_item: bare | param | illustration
bare: WORD
param: WORD "=" _value
illustration: ILLUSTRATION "(" _value param* ")"
_value: WORD | STRING

TIMELINE: "timeline"
ILLUSTRATION: "illustration"
HEAD: /[\^v]?[!\-]*(person|event|span|group)(?![\w])/
GRAPH: /[\^v]?[!\-]*graph(?![\w])/
TITLE: /title(?![\w])/
CREDITS: /credits(?![\w])/
NOTE: /note(?![\w])/
HEADING: /heading(?![\w])/
STRING: /"(?:[^"\\\n]|\\.)*"/
WORD: /[^\s"{}()=]+/
_NL: /\n+/

%ignore /[ \t]+/
"""


@functools.cache
def parser() -> Lark:
    return Lark(GRAMMAR, parser="lalr", lexer="contextual", propagate_positions=True, maybe_placeholders=False)
