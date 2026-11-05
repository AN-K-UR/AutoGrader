"""A small C lexer and function finder shared by the source-only analyzers.

This does not parse C fully and never needs to: it never executes anything, and
it handles what the analyzers depend on, namely separating comments and strings
from code (so ``// printf`` is not a call) and finding function bodies by brace
matching. Macro-generated functions are invisible to it, which is documented in
the limitations.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Set

C_KEYWORDS = frozenset("""
auto break case char const continue default do double else enum extern float for goto
if inline int long register restrict return short signed sizeof static struct switch
typedef union unsigned void volatile while _Bool _Complex _Noreturn _Static_assert
""".split())

_TOKEN = re.compile(r"""
    (?P<comment>//[^\n]*|/\*.*?(?:\*/|\Z))
  | (?P<preproc>^[ \t]*\#(?:[^\n\\]|\\.)*)
  | (?P<string>"(?:[^"\\\n]|\\.)*"?)
  | (?P<char>'(?:[^'\\\n]|\\.)*'?)
  | (?P<number>\.?\d(?:[eEpP][+-]|[\w.])*)
  | (?P<identifier>[A-Za-z_]\w*)
  | (?P<operator>\.\.\.|<<=|>>=|->|\+\+|--|<<|>>|<=|>=|==|!=|&&|\|\||[-+*/%&|^]=|[^\s\w])
  | (?P<space>\s+)
""", re.VERBOSE | re.MULTILINE | re.DOTALL)

_NOT_FUNCTIONS = frozenset({"if", "for", "while", "switch", "return", "sizeof"})
_CONTROL = frozenset({"if", "for", "while", "switch", "else", "do"})


@dataclass(frozen=True)
class Token:
    kind: str
    text: str
    line: int


@dataclass
class Function:
    name: str
    start_line: int
    end_line: int
    parameters: int
    max_nesting: int
    calls: Set[str]

    @property
    def length(self) -> int:
        return self.end_line - self.start_line + 1


@dataclass
class Comment:
    line: int
    text: str


class CSource:
    """Tokens, comments and function structure of one C source file."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.lines = text.splitlines()
        self.tokens: List[Token] = []
        self.comments: List[Comment] = []
        self.preprocessor: List[Token] = []
        self._tokenize()
        self.functions = self._find_functions()

    def _tokenize(self) -> None:
        position, line = 0, 1
        length = len(self.text)
        while position < length:
            match = _TOKEN.match(self.text, position)
            if match is None or match.end() == position:
                position += 1  # Stray byte; skip it, the compiler will complain.
                continue
            kind, value = match.lastgroup or "space", match.group()
            if kind == "comment":
                self.comments.append(Comment(line, value))
            elif kind == "preproc":
                self.preprocessor.append(Token(kind, value.strip(), line))
            elif kind != "space":
                self.tokens.append(Token(kind, value, line))
            line += value.count("\n")
            position = match.end()

    def code_tokens(self) -> List[Token]:
        return self.tokens

    def _find_functions(self) -> List[Function]:
        functions: List[Function] = []
        tokens = self.tokens
        index, depth = 0, 0
        while index < len(tokens):
            token = tokens[index]
            if token.text == "{":
                depth += 1
            elif token.text == "}":
                depth = max(0, depth - 1)
            elif (depth == 0 and token.kind == "identifier" and token.text not in _NOT_FUNCTIONS
                  and index + 1 < len(tokens) and tokens[index + 1].text == "("):
                close = self._matching(index + 1, "(", ")")
                if close is not None and close + 1 < len(tokens) and tokens[close + 1].text == "{":
                    end = self._matching(close + 1, "{", "}")
                    if end is not None:
                        functions.append(self._build(index, close, end))
                        index = end + 1
                        continue
            index += 1
        return functions

    def _matching(self, start: int, opener: str, closer: str) -> Optional[int]:
        depth = 0
        for index in range(start, len(self.tokens)):
            text = self.tokens[index].text
            if text == opener:
                depth += 1
            elif text == closer:
                depth -= 1
                if depth == 0:
                    return index
        return None

    def _build(self, name_index: int, paren_close: int, body_end: int) -> Function:
        tokens = self.tokens
        parameter_tokens = tokens[name_index + 2:paren_close]
        parameters = 0
        if parameter_tokens and not (len(parameter_tokens) == 1
                                     and parameter_tokens[0].text == "void"):
            parameters = 1 + sum(1 for token in parameter_tokens if token.text == ",")
        calls: Set[str] = set()
        depth, deepest = 0, 0
        body = tokens[paren_close + 1:body_end + 1]
        for offset, token in enumerate(body):
            if token.text == "{":
                depth += 1
                deepest = max(deepest, depth)
            elif token.text == "}":
                depth -= 1
            elif (token.kind == "identifier" and token.text not in C_KEYWORDS
                  and offset + 1 < len(body) and body[offset + 1].text == "("):
                calls.add(token.text)
        return Function(tokens[name_index].text, tokens[name_index].line,
                        tokens[body_end].line, parameters, max(0, deepest - 1), calls)

    def function(self, name: str) -> Optional[Function]:
        return next((item for item in self.functions if item.name == name), None)

    def called_names(self) -> Set[str]:
        names: Set[str] = set()
        for function in self.functions:
            names |= function.calls
        return names

    def tokens_in_function(self, function: Function) -> List[Token]:
        return [token for token in self.tokens
                if function.start_line <= token.line <= function.end_line]

    def identifier_counts(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for token in self.tokens:
            if token.kind == "identifier" and token.text not in C_KEYWORDS:
                counts[token.text] = counts.get(token.text, 0) + 1
        return counts


def is_control_keyword(text: str) -> bool:
    return text in _CONTROL
