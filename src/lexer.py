"""
lexer.py - A lexer (tokenizer) for a practical subset of Python 3.

Turns source text into a flat list of Token objects:

    NAME      identifiers                    balance, Account
    KEYWORD   reserved words                 def, if, return, None
    NUMBER    int / float / hex literals     0, 10, 3.14
    STRING    any string literal (raw text)  "abc", f"Hi {x}", '''doc'''
    OP        operators and punctuation      +=, ==, (, :, ->
    NEWLINE   end of a logical line
    INDENT    indentation increased          (Python's block start)
    DEDENT    indentation decreased          (Python's block end)
    EOF       end of input

Like CPython, it handles:
  * indentation  -> INDENT / DEDENT tokens
  * implicit line joining inside (), [] and {}
  * backslash line continuation
  * comments and blank lines (skipped)
  * triple-quoted strings spanning several lines

Usage:
    python lexer.py GrittBank.py
"""

import re
import sys
from collections import namedtuple

Token = namedtuple("Token", "type value line col")

KEYWORDS = frozenset(
    "False None True and as assert async await break class continue def del "
    "elif else except finally for from global if import in is lambda nonlocal "
    "not or pass raise return try while with yield".split()
)

# Order matters: longest operators first so "**=" wins over "**" over "*".
OPERATORS = [
    "**=", "//=", ">>=", "<<=", "...",
    "==", "!=", "<=", ">=", "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=",
    "//", "**", "->", "<<", ">>", ":=",
    "+", "-", "*", "/", "%", "=", "<", ">", "(", ")", "[", "]", "{", "}",
    ",", ":", ".", ";", "@", "&", "|", "^", "~",
]

OP_RE = re.compile("|".join(re.escape(op) for op in OPERATORS))
NAME_RE = re.compile(r"[^\W\d]\w*")
NUMBER_RE = re.compile(
    r"0[xX][0-9a-fA-F_]+|0[oO][0-7_]+|0[bB][01_]+"
    r"|(?:\d[\d_]*\.[\d_]*|\.\d[\d_]*|\d[\d_]*)(?:[eE][+-]?\d+)?"
)
STRING_RE = re.compile(
    r"""(?i:[rbuf]{0,2})(?:
          \"\"\"(?:\\.|[^\\])*?\"\"\"
        | '''(?:\\.|[^\\])*?'''
        | "(?:\\.|[^"\\\n])*"
        | '(?:\\.|[^'\\\n])*'
    )""",
    re.VERBOSE | re.DOTALL,
)


class LexError(Exception):
    def __init__(self, message, line, col):
        super().__init__(f"Lexical error at line {line}, column {col}: {message}")
        self.line, self.col = line, col


def tokenize(source, first_line=1):
    """Convert source text into a list of Tokens (always ends with EOF)."""
    src = source.replace("\r\n", "\n").replace("\r", "\n")
    if not src.endswith("\n"):
        src += "\n"

    tokens = []
    indents = [0]          # stack of indentation widths
    depth = 0              # nesting depth of (), [], {}
    i, n = 0, len(src)
    line, line_start = first_line, 0
    at_bol = True          # at the beginning of a logical line?

    def add(kind, value, pos):
        tokens.append(Token(kind, value, line, pos - line_start + 1))

    while i < n:
        # ---- indentation handling at the start of a logical line ----------
        if at_bol and depth == 0:
            j, width = i, 0
            while src[j] in " \t":
                width = (width // 8 + 1) * 8 if src[j] == "\t" else width + 1
                j += 1
            if src[j] == "\n" or src[j] == "#":      # blank / comment-only line
                while src[j] != "\n":
                    j += 1
                i, line = j + 1, line + 1
                line_start = i
                continue
            if width > indents[-1]:
                indents.append(width)
                add("INDENT", "", j)
            else:
                while width < indents[-1]:
                    indents.pop()
                    add("DEDENT", "", j)
                if width != indents[-1]:
                    raise LexError("unindent does not match any outer level",
                                   line, j - line_start + 1)
            i, at_bol = j, False

        c = src[i]

        if c in " \t":
            i += 1
        elif c == "\n":
            if depth == 0:
                add("NEWLINE", "\\n", i)
                at_bol = True
            line += 1
            i += 1
            line_start = i
        elif c == "#":
            while src[i] != "\n":
                i += 1
        elif c == "\\" and src[i + 1:i + 2] == "\n":   # explicit line continuation
            i += 2
            line += 1
            line_start = i
        else:
            m = STRING_RE.match(src, i)
            if m:
                text = m.group()
                add("STRING", text, i)
                newlines = text.count("\n")
                if newlines:
                    line += newlines
                    line_start = i + text.rfind("\n") + 1
                i = m.end()
                continue
            if c in "'\"":
                raise LexError("unterminated string literal", line, i - line_start + 1)

            m = NUMBER_RE.match(src, i)
            if m:
                add("NUMBER", m.group(), i)
                i = m.end()
                continue

            m = NAME_RE.match(src, i)
            if m:
                word = m.group()
                add("KEYWORD" if word in KEYWORDS else "NAME", word, i)
                i = m.end()
                continue

            m = OP_RE.match(src, i)
            if m:
                op = m.group()
                if op in "([{":
                    depth += 1
                elif op in ")]}":
                    depth -= 1
                    if depth < 0:
                        raise LexError(f"unmatched {op!r}", line, i - line_start + 1)
                add("OP", op, i)
                i = m.end()
                continue

            raise LexError(f"unexpected character {c!r}", line, i - line_start + 1)

    if depth > 0:
        raise LexError("unclosed bracket at end of input", line, 1)
    if tokens and tokens[-1].type != "NEWLINE":
        add("NEWLINE", "\\n", n)
    while len(indents) > 1:
        indents.pop()
        add("DEDENT", "", n)
    add("EOF", "", n)
    return tokens


def main():
    if len(sys.argv) != 2:
        sys.exit("usage: python lexer.py <file.py>")
    with open(sys.argv[1], encoding="utf-8") as f:
        source = f.read()
    try:
        tokens = tokenize(source)
    except LexError as e:
        sys.exit(str(e))

    print(f"{'LINE':>4}:{'COL':<4} {'TYPE':<8} VALUE")
    print("-" * 50)
    for t in tokens:
        print(f"{t.line:>4}:{t.col:<4} {t.type:<8} {t.value!r}")

    counts = {}
    for t in tokens:
        counts[t.type] = counts.get(t.type, 0) + 1
    print("\nToken counts:", ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))


if __name__ == "__main__":
    main()