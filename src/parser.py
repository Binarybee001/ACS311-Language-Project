"""
parser.py - A recursive-descent parser for a practical subset of Python 3.

It consumes the tokens produced by lexer.py and builds an Abstract Syntax
Tree (AST) made of generic `Node` objects.

Grammar covered (enough for typical scripts and class-based programs):

  statements   def, class, decorators, if/elif/else, while, for, try/except/
               else/finally, with, return, pass, break, continue, import,
               from-import, raise, assert, global/nonlocal, del,
               assignment (=, chained, tuple-unpacking, +=, ..., x: T = v)
  expressions  lambda, ternary, or/and/not, comparisons (in, not in, is,
               is not, ==, <, ...), | ^ & << >> + - * / // % @ **, unary
               - + ~, calls (keyword args, *args, **kwargs), attributes,
               subscripts/slices, tuples, lists, dicts, sets, list/dict/set
               comprehensions, generator expressions, f-strings

Not supported: async/await, yield, match, walrus, decorators-with-newlines
inside parentheses, nested format specs inside f-strings.

Usage:
    python parser.py bank.py            # summary report
    python parser.py bank.py --ast      # full AST dump
    python parser.py bank.py --tokens   # token stream (from lexer)
"""

import argparse
import ast as _pyast
import re
import sys
from collections import Counter

from lexer import LexError, tokenize


# ---------------------------------------------------------------------------
# AST node
# ---------------------------------------------------------------------------

class Node:
    """Generic AST node: a `kind`, a source `line`, and named `fields`."""

    def __init__(self, kind, line, **fields):
        self.kind = kind
        self.line = line
        self.fields = fields

    def __getattr__(self, name):
        try:
            return self.__dict__["fields"][name]
        except KeyError:
            raise AttributeError(name) from None

    def children(self):
        for value in self.fields.values():
            if isinstance(value, Node):
                yield value
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, Node):
                        yield item

    def dump(self, level=0):
        pad = "  " * level
        scalars = [
            f" {k}={v!r}" for k, v in self.fields.items()
            if not isinstance(v, (Node, list)) and (v is not None or self.kind == "Constant")
        ]
        out = [f"{pad}{self.kind}{''.join(scalars)}  [line {self.line}]"]
        for key, value in self.fields.items():
            if isinstance(value, Node):
                out.append(f"{pad}  {key}:")
                out.append(value.dump(level + 2))
            elif isinstance(value, list) and value:
                out.append(f"{pad}  {key}:")
                for item in value:
                    out.append(item.dump(level + 2) if isinstance(item, Node)
                               else f"{pad}    {item!r}")
        return "\n".join(out)

    def __repr__(self):
        return f"Node({self.kind}, line={self.line})"


def walk(node):
    """Yield `node` and every node below it (depth-first)."""
    yield node
    for child in node.children():
        yield from walk(child)


class ParseError(Exception):
    def __init__(self, message, token):
        super().__init__(f"Syntax error at line {token.line}, column {token.col}: {message}")
        self.token = token


# ---------------------------------------------------------------------------
# Helpers for literals
# ---------------------------------------------------------------------------

def parse_number(text):
    t = text.replace("_", "")
    for conv in (lambda s: int(s, 0), int):
        try:
            return conv(t)
        except ValueError:
            pass
    return float(t)


def split_string(text):
    """'f"abc"' -> ('f', 'abc')."""
    m = re.match(r"""([A-Za-z]*)('''|\"\"\"|'|")""", text)
    quote = m.group(2)
    return m.group(1), text[m.end():-len(quote)]


def parse_expression_source(src, line):
    """Parse the text of one f-string replacement field, e.g. 'x.y + 1'."""
    parser = Parser(tokenize("(" + src.strip() + ")", first_line=line))
    expr = parser.testlist()
    parser.expect_type("NEWLINE")
    return expr


def decode_escapes(text):
    """Turn backslash escapes (\\n, \\t, \\u00e9 ...) in literal text into characters."""
    try:
        return text.encode("latin-1", "backslashreplace").decode("unicode_escape")
    except UnicodeDecodeError:
        return text


def parse_fstring(body, line, raw=False):
    """Split an f-string body into Constant and FormattedValue nodes."""
    parts, buf, i = [], "", 0

    def flush():
        nonlocal buf
        if buf:
            parts.append(Node("Constant", line, value=buf if raw else decode_escapes(buf)))
            buf = ""

    while i < len(body):
        c = body[i]
        if c == "{" and body[i + 1:i + 2] == "{":
            buf += "{"
            i += 2
        elif c == "}" and body[i + 1:i + 2] == "}":
            buf += "}"
            i += 2
        elif c == "{":
            flush()
            depth, j, expr_end = 0, i + 1, None
            while j < len(body):                      # find the matching '}'
                ch = body[j]
                if ch in "([{":
                    depth += 1
                elif ch in ")]}":
                    if depth == 0 and ch == "}":
                        break
                    depth -= 1
                elif ch in "'\"":
                    j = body.find(ch, j + 1)
                    if j < 0:
                        break
                elif depth == 0 and expr_end is None and (
                        ch == ":" or (ch == "!" and body[j + 1:j + 2] != "=")):
                    expr_end = j                       # start of !r or :format
                j += 1
            if j < 0 or j >= len(body):
                raise ParseError("unterminated '{' in f-string",
                                 type("T", (), {"line": line, "col": 0})())
            field = body[i + 1:j]
            cut = expr_end - i - 1 if expr_end is not None else len(field)
            spec = field[cut:] or None
            parts.append(Node("FormattedValue", line,
                              value=parse_expression_source(field[:cut], line),
                              format_spec=spec))
            i = j + 1
        else:
            buf += c
            i += 1
    flush()
    return parts


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

LEVELS = [("|",), ("^",), ("&",), ("<<", ">>"), ("+", "-"), ("*", "/", "//", "%", "@")]
COMPARE_OPS = ("<", ">", "==", ">=", "<=", "!=")
AUG_OPS = ("+=", "-=", "*=", "/=", "//=", "%=", "**=", "&=", "|=", "^=", ">>=", "<<=")
CONSTANTS = {"True": True, "False": False, "None": None}


class Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    # ---- token utilities --------------------------------------------------

    @property
    def tok(self):
        return self.tokens[self.pos]

    def peek(self, k=1):
        return self.tokens[min(self.pos + k, len(self.tokens) - 1)]

    def advance(self):
        t = self.tokens[self.pos]
        if t.type != "EOF":
            self.pos += 1
        return t

    def is_(self, *values, tok=None):
        """Is the (current) token an OP/KEYWORD with one of these values?"""
        t = tok or self.tok
        return t.type in ("OP", "KEYWORD") and t.value in values

    def accept(self, *values):
        return self.advance() if self.is_(*values) else None

    def error(self, message, tok=None):
        return ParseError(message, tok or self.tok)

    def describe(self, t):
        return t.type if t.type in ("NEWLINE", "INDENT", "DEDENT", "EOF") \
            else f"{t.value!r}"

    def expect(self, value):
        if not self.is_(value):
            raise self.error(f"expected {value!r} but found {self.describe(self.tok)}")
        return self.advance()

    def expect_type(self, kind):
        if self.tok.type != kind:
            raise self.error(f"expected {kind} but found {self.describe(self.tok)}")
        return self.advance()

    def expect_name(self):
        return self.expect_type("NAME").value

    def at_stmt_end(self):
        return self.tok.type in ("NEWLINE", "EOF") or self.is_(";")

    def starts_expr(self):
        t = self.tok
        if t.type in ("NAME", "NUMBER", "STRING"):
            return True
        if t.type == "KEYWORD":
            return t.value in ("None", "True", "False", "not", "lambda")
        return t.type == "OP" and t.value in ("(", "[", "{", "-", "+", "~", "...", "*")

    # ---- program & statements --------------------------------------------

    def parse_file(self):
        body = []
        while self.tok.type != "EOF":
            body.extend(self.statement())
        return Node("Module", 1, body=body)

    def statement(self):
        """Parse one statement; returns a list of nodes (a line may hold several)."""
        t = self.tok
        if self.is_("@"):
            return [self.decorated()]
        if t.type == "KEYWORD":
            handler = {
                "def": self.funcdef, "class": self.classdef, "if": self.if_stmt,
                "while": self.while_stmt, "for": self.for_stmt,
                "try": self.try_stmt, "with": self.with_stmt,
            }.get(t.value)
            if handler:
                return [handler()]
        return self.simple_line()

    def simple_line(self):
        stmts = [self.simple_stmt()]
        while self.accept(";"):
            if self.tok.type == "NEWLINE":
                break
            stmts.append(self.simple_stmt())
        self.expect_type("NEWLINE")
        return stmts

    def block(self):
        self.expect(":")
        if self.tok.type == "NEWLINE":
            self.advance()
            self.expect_type("INDENT")
            body = []
            while self.tok.type not in ("DEDENT", "EOF"):
                body.extend(self.statement())
            self.expect_type("DEDENT")
            return body
        return self.simple_line()          # e.g.  if x: return 1

    def decorated(self):
        decorators = []
        while self.accept("@"):
            decorators.append(self.test())
            self.expect_type("NEWLINE")
        if self.is_("def"):
            node = self.funcdef()
        elif self.is_("class"):
            node = self.classdef()
        else:
            raise self.error("expected 'def' or 'class' after decorator")
        node.fields["decorators"] = decorators
        return node

    def funcdef(self):
        line = self.expect("def").line
        name = self.expect_name()
        self.expect("(")
        params = self.parameters(")")
        self.expect(")")
        returns = self.test() if self.accept("->") else None
        return Node("FunctionDef", line, name=name, params=params,
                    returns=returns, body=self.block(), decorators=[])

    def parameters(self, end):
        params = []
        while not self.is_(end):
            if self.is_("/"):
                self.advance()
            else:
                tk = self.tok
                star = self.advance().value if self.is_("*", "**") else ""
                name = "" if (star == "*" and self.is_(",", end)) else self.expect_name()
                annotation = self.test() if (name and end == ")" and self.accept(":")) else None
                default = self.test() if (name and self.accept("=")) else None
                params.append(Node("Param", tk.line, name=star + name,
                                   annotation=annotation, default=default))
            if not self.accept(","):
                break
        return params

    def classdef(self):
        line = self.expect("class").line
        name = self.expect_name()
        bases, keywords = [], []
        if self.accept("("):
            bases, keywords = self.call_args()
            self.expect(")")
        return Node("ClassDef", line, name=name, bases=bases,
                    keywords=keywords, body=self.block(), decorators=[])

    def if_stmt(self):
        tk = self.advance()                       # 'if' or 'elif'
        test = self.test()
        body = self.block()
        orelse = []
        if self.is_("elif"):
            orelse = [self.if_stmt()]
        elif self.accept("else"):
            orelse = self.block()
        return Node("If", tk.line, test=test, body=body, orelse=orelse)

    def while_stmt(self):
        tk = self.advance()
        test = self.test()
        body = self.block()
        orelse = self.block() if self.accept("else") else []
        return Node("While", tk.line, test=test, body=body, orelse=orelse)

    def for_stmt(self):
        tk = self.advance()
        target = self.target_list()
        self.expect("in")
        iterable = self.testlist()
        body = self.block()
        orelse = self.block() if self.accept("else") else []
        return Node("For", tk.line, target=target, iter=iterable, body=body, orelse=orelse)

    def try_stmt(self):
        tk = self.advance()
        body = self.block()
        handlers, orelse, final = [], [], []
        while self.is_("except"):
            et = self.advance()
            exc_type = name = None
            if not self.is_(":"):
                exc_type = self.test()
                if self.accept("as"):
                    name = self.expect_name()
            handlers.append(Node("ExceptHandler", et.line, exc_type=exc_type,
                                 name=name, body=self.block()))
        if handlers and self.accept("else"):
            orelse = self.block()
        if self.accept("finally"):
            final = self.block()
        if not handlers and not final:
            raise self.error("'try' needs an 'except' or 'finally' clause", tk)
        return Node("Try", tk.line, body=body, handlers=handlers,
                    orelse=orelse, finalbody=final)

    def with_stmt(self):
        tk = self.advance()
        items = []
        while True:
            ctx = self.test()
            var = self.binary(0) if self.accept("as") else None
            items.append(Node("WithItem", ctx.line, context=ctx, var=var))
            if not self.accept(","):
                break
        return Node("With", tk.line, items=items, body=self.block())

    # ---- simple statements -----------------------------------------------

    def dotted_name(self):
        name = self.expect_name()
        while self.accept("."):
            name += "." + self.expect_name()
        return name

    def alias(self, dotted):
        tk = self.tok
        name = self.dotted_name() if dotted else self.expect_name()
        asname = self.expect_name() if self.accept("as") else None
        return Node("Alias", tk.line, name=name, asname=asname)

    def simple_stmt(self):
        tk = self.tok
        if tk.type == "KEYWORD":
            v = tk.value
            if v in ("pass", "break", "continue"):
                self.advance()
                return Node(v.capitalize(), tk.line)
            if v == "return":
                self.advance()
                value = None if self.at_stmt_end() else self.testlist()
                return Node("Return", tk.line, value=value)
            if v == "import":
                self.advance()
                names = [self.alias(True)]
                while self.accept(","):
                    names.append(self.alias(True))
                return Node("Import", tk.line, names=names)
            if v == "from":
                self.advance()
                level = 0
                while self.is_(".", "..."):
                    level += len(self.advance().value)
                module = "" if self.is_("import") else self.dotted_name()
                self.expect("import")
                if self.accept("*"):
                    names = [Node("Alias", tk.line, name="*", asname=None)]
                else:
                    paren = self.accept("(")
                    names = [self.alias(False)]
                    while self.accept(","):
                        if paren and self.is_(")"):
                            break
                        names.append(self.alias(False))
                    if paren:
                        self.expect(")")
                return Node("ImportFrom", tk.line, module=module, level=level, names=names)
            if v == "raise":
                self.advance()
                exc = cause = None
                if not self.at_stmt_end():
                    exc = self.test()
                    if self.accept("from"):
                        cause = self.test()
                return Node("Raise", tk.line, exc=exc, cause=cause)
            if v == "assert":
                self.advance()
                test = self.test()
                msg = self.test() if self.accept(",") else None
                return Node("Assert", tk.line, test=test, msg=msg)
            if v in ("global", "nonlocal"):
                self.advance()
                names = [self.expect_name()]
                while self.accept(","):
                    names.append(self.expect_name())
                return Node(v.capitalize(), tk.line, names=names)
            if v == "del":
                self.advance()
                return Node("Delete", tk.line, target=self.testlist())
        return self.expr_stmt()

    def expr_stmt(self):
        tk = self.tok
        first = self.testlist()
        if self.is_("="):
            targets, value = [first], None
            while self.accept("="):
                value = self.testlist()
                if self.is_("="):
                    targets.append(value)
            return Node("Assign", tk.line, targets=targets, value=value)
        if self.is_(*AUG_OPS):
            op = self.advance().value
            return Node("AugAssign", tk.line, target=first, op=op, value=self.testlist())
        if self.accept(":"):
            annotation = self.test()
            value = self.test() if self.accept("=") else None
            return Node("AnnAssign", tk.line, target=first, annotation=annotation, value=value)
        return Node("Expr", tk.line, value=first)

    # ---- expressions (lowest precedence first) -----------------------------

    def testlist(self):
        """expr {, expr} [,]   -> a Tuple when there is a comma."""
        tk = self.tok
        first = self.star_expr()
        if not self.is_(","):
            return first
        elts = [first]
        while self.accept(","):
            if not self.starts_expr():
                break
            elts.append(self.star_expr())
        return Node("Tuple", tk.line, elts=elts)

    def star_expr(self):
        if self.is_("*"):
            tk = self.advance()
            return Node("Starred", tk.line, value=self.binary(0))
        return self.test()

    def target_list(self):
        """Targets of a `for` (stops before the `in` keyword)."""
        tk = self.tok
        first = self.binary(0)
        if not self.is_(","):
            return first
        elts = [first]
        while self.accept(","):
            if self.is_("in"):
                break
            elts.append(self.binary(0))
        return Node("Tuple", tk.line, elts=elts)

    def test(self):
        if self.is_("lambda"):
            tk = self.advance()
            params = self.parameters(":")
            self.expect(":")
            return Node("Lambda", tk.line, params=params, body=self.test())
        tk = self.tok
        expr = self.or_test()
        if self.accept("if"):
            cond = self.or_test()
            self.expect("else")
            return Node("IfExp", tk.line, test=cond, body=expr, orelse=self.test())
        return expr

    def bool_op(self, op, sub):
        tk = self.tok
        first = sub()
        if not self.is_(op):
            return first
        values = [first]
        while self.accept(op):
            values.append(sub())
        return Node("BoolOp", tk.line, op=op, values=values)

    def or_test(self):
        return self.bool_op("or", self.and_test)

    def and_test(self):
        return self.bool_op("and", self.not_test)

    def not_test(self):
        if self.is_("not"):
            tk = self.advance()
            return Node("UnaryOp", tk.line, op="not", operand=self.not_test())
        return self.comparison()

    def comparison(self):
        tk = self.tok
        left = self.binary(0)
        ops, comparators = [], []
        while True:
            if self.is_(*COMPARE_OPS):
                op = self.advance().value
            elif self.accept("in"):
                op = "in"
            elif self.is_("not") and self.is_("in", tok=self.peek()):
                self.advance()
                self.advance()
                op = "not in"
            elif self.accept("is"):
                op = "is not" if self.accept("not") else "is"
            else:
                break
            ops.append(op)
            comparators.append(self.binary(0))
        if not ops:
            return left
        return Node("Compare", tk.line, left=left, ops=ops, comparators=comparators)

    def binary(self, level=0):
        if level == len(LEVELS):
            return self.factor()
        tk = self.tok
        left = self.binary(level + 1)
        while self.is_(*LEVELS[level]):
            op = self.advance().value
            right = self.binary(level + 1)
            left = Node("BinOp", tk.line, op=op, left=left, right=right)
        return left

    def factor(self):
        if self.is_("-", "+", "~"):
            tk = self.advance()
            return Node("UnaryOp", tk.line, op=tk.value, operand=self.factor())
        tk = self.tok
        base = self.atom_expr()
        if self.accept("**"):
            return Node("BinOp", tk.line, op="**", left=base, right=self.factor())
        return base

    def atom_expr(self):
        node = self.atom()
        while True:
            tk = self.tok
            if self.accept("("):
                args, keywords = self.call_args()
                self.expect(")")
                node = Node("Call", tk.line, func=node, args=args, keywords=keywords)
            elif self.accept("["):
                index = self.subscript()
                self.expect("]")
                node = Node("Subscript", tk.line, value=node, index=index)
            elif self.accept("."):
                node = Node("Attribute", tk.line, value=node, attr=self.expect_name())
            else:
                return node

    def call_args(self):
        args, keywords = [], []
        while not self.is_(")"):
            tk = self.tok
            if self.accept("*"):
                args.append(Node("Starred", tk.line, value=self.test()))
            elif self.accept("**"):
                keywords.append(Node("Keyword", tk.line, name=None, value=self.test()))
            elif tk.type == "NAME" and self.is_("=", tok=self.peek()):
                self.advance()
                self.advance()
                keywords.append(Node("Keyword", tk.line, name=tk.value, value=self.test()))
            else:
                expr = self.test()
                if self.is_("for"):
                    expr = Node("GeneratorExp", tk.line, elt=expr,
                                generators=self.comp_clauses())
                args.append(expr)
            if not self.accept(","):
                break
        return args, keywords

    def subscript(self):
        tk = self.tok

        def part():
            return None if self.is_(":", "]", ",") else self.test()

        def one():
            lower = part()
            if self.accept(":"):
                upper = part()
                step = part() if self.accept(":") else None
                return Node("Slice", tk.line, lower=lower, upper=upper, step=step)
            return lower

        first = one()
        if not self.is_(","):
            return first
        elts = [first]
        while self.accept(","):
            if self.is_("]"):
                break
            elts.append(one())
        return Node("Tuple", tk.line, elts=elts)

    def comp_clauses(self):
        clauses = []
        while self.is_("for"):
            tk = self.advance()
            target = self.target_list()
            self.expect("in")
            iterable = self.or_test()
            ifs = []
            while self.accept("if"):
                ifs.append(self.or_test())
            clauses.append(Node("Comprehension", tk.line, target=target,
                                iter=iterable, ifs=ifs))
        return clauses

    # ---- atoms ----------------------------------------------------------

    def atom(self):
        t = self.tok
        if t.type == "NAME":
            self.advance()
            return Node("Name", t.line, id=t.value)
        if t.type == "NUMBER":
            self.advance()
            return Node("Constant", t.line, value=parse_number(t.value))
        if t.type == "STRING":
            return self.strings()
        if t.type == "KEYWORD" and t.value in CONSTANTS:
            self.advance()
            return Node("Constant", t.line, value=CONSTANTS[t.value])
        if self.is_("..."):
            self.advance()
            return Node("Constant", t.line, value=Ellipsis)
        if self.is_("("):
            return self.paren_atom()
        if self.is_("["):
            return self.list_atom()
        if self.is_("{"):
            return self.brace_atom()
        raise self.error(f"unexpected {self.describe(t)}")

    def strings(self):
        tk = self.tok
        parts, is_f = [], False
        while self.tok.type == "STRING":
            t = self.advance()
            prefix, body = split_string(t.value)
            if "f" in prefix.lower():
                is_f = True
                parts.extend(parse_fstring(body, t.line, raw="r" in prefix.lower()))
            else:
                try:
                    value = _pyast.literal_eval(t.value)
                except (ValueError, SyntaxError):
                    value = body
                parts.append(Node("Constant", t.line, value=value))
        if is_f:
            return Node("JoinedStr", tk.line, values=parts)
        values = [p.value for p in parts]
        joined = values[0] if len(values) == 1 else (
            "".join(values) if isinstance(values[0], str) else b"".join(values))
        return Node("Constant", tk.line, value=joined)

    def paren_atom(self):
        tk = self.advance()
        if self.accept(")"):
            return Node("Tuple", tk.line, elts=[])
        first = self.star_expr()
        if self.is_("for"):
            node = Node("GeneratorExp", tk.line, elt=first, generators=self.comp_clauses())
        elif self.is_(","):
            elts = [first]
            while self.accept(","):
                if self.is_(")"):
                    break
                elts.append(self.star_expr())
            node = Node("Tuple", tk.line, elts=elts)
        else:
            node = first
        self.expect(")")
        return node

    def list_atom(self):
        tk = self.advance()
        if self.accept("]"):
            return Node("List", tk.line, elts=[])
        first = self.star_expr()
        if self.is_("for"):
            node = Node("ListComp", tk.line, elt=first, generators=self.comp_clauses())
        else:
            elts = [first]
            while self.accept(","):
                if self.is_("]"):
                    break
                elts.append(self.star_expr())
            node = Node("List", tk.line, elts=elts)
        self.expect("]")
        return node

    def brace_atom(self):
        tk = self.advance()
        if self.accept("}"):
            return Node("Dict", tk.line, keys=[], values=[])
        first = self.test()
        if self.accept(":"):
            value = self.test()
            if self.is_("for"):
                node = Node("DictComp", tk.line, key=first, value=value,
                            generators=self.comp_clauses())
            else:
                keys, values = [first], [value]
                while self.accept(","):
                    if self.is_("}"):
                        break
                    keys.append(self.test())
                    self.expect(":")
                    values.append(self.test())
                node = Node("Dict", tk.line, keys=keys, values=values)
        elif self.is_("for"):
            node = Node("SetComp", tk.line, elt=first, generators=self.comp_clauses())
        else:
            elts = [first]
            while self.accept(","):
                if self.is_("}"):
                    break
                elts.append(self.test())
            node = Node("Set", tk.line, elts=elts)
        self.expect("}")
        return node


def parse(source):
    """Source text -> Module node."""
    return Parser(tokenize(source)).parse_file()


# ---------------------------------------------------------------------------
# Analysis of the resulting AST
# ---------------------------------------------------------------------------

def call_name(func):
    if func.kind == "Name":
        return func.id
    if func.kind == "Attribute":
        return f"{call_name(func.value)}.{func.attr}"
    return "<expr>"


def signature(fn):
    return ", ".join(p.name for p in fn.params)


def end_line(node):
    return max(n.line for n in walk(node))


def summarize(tree):
    out = []
    imports = [a.name for n in tree.body if n.kind == "Import" for a in n.names]
    imports += [f"{n.module}.{a.name}" for n in tree.body if n.kind == "ImportFrom"
                for a in n.names]
    out.append("Imports:        " + (", ".join(imports) or "-"))

    funcs = [n for n in tree.body if n.kind == "FunctionDef"]
    classes = [n for n in tree.body if n.kind == "ClassDef"]

    out.append(f"\nClasses ({len(classes)}):")
    for c in classes:
        out.append(f"  class {c.name}  (lines {c.line}-{end_line(c)})")
        for m in (n for n in c.body if n.kind == "FunctionDef"):
            out.append(f"      def {m.name}({signature(m)})  line {m.line}")

    out.append(f"\nFunctions ({len(funcs)}):")
    for f in funcs:
        out.append(f"  def {f.name}({signature(f)})  (lines {f.line}-{end_line(f)})")

    counts = Counter(n.kind for n in walk(tree))
    branches = sum(counts[k] for k in ("If", "While", "For", "Try", "IfExp"))
    out.append("\nStatistics:")
    out.append(f"  AST nodes: {sum(counts.values())}   "
               f"branching constructs: {branches}   "
               f"returns: {counts['Return']}   "
               f"f-strings: {counts['JoinedStr']}")

    calls = Counter(call_name(n.func) for n in walk(tree) if n.kind == "Call")
    out.append("\nMost-called functions:")
    for name, count in calls.most_common(8):
        out.append(f"  {name:<28} {count}x")

    out.append("\nNode types: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description="Lex and parse a Python source file.")
    ap.add_argument("file")
    ap.add_argument("--ast", action="store_true", help="print the full AST")
    ap.add_argument("--tokens", action="store_true", help="print the token stream")
    args = ap.parse_args()

    with open(args.file, encoding="utf-8") as f:
        source = f.read()
    try:
        tokens = tokenize(source)
        if args.tokens:
            for t in tokens:
                print(f"{t.line:>4}:{t.col:<4} {t.type:<8} {t.value!r}")
            return
        tree = Parser(tokens).parse_file()
    except (LexError, ParseError) as e:
        sys.exit(str(e))

    print(tree.dump() if args.ast else summarize(tree))


if __name__ == "__main__":
    main()