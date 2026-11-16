"""
interpreter.py - A tree-walking interpreter for the Python subset handled by
lexer.py and parser.py.

Pipeline:   source text --lexer--> tokens --parser--> AST --interpreter--> run

The interpreter walks the AST produced by parser.py and executes it directly:

  * Scopes      : module / function / class / comprehension scopes, closures,
                  `global` and `nonlocal`, Python's "class scope is not visible
                  inside methods" rule.
  * Functions   : positional + default + *args + keyword-only + **kwargs
                  arguments, lambdas, decorators, recursion.
  * Classes     : built as real Python classes (so inheritance, super(),
                  @property, @staticmethod, @classmethod, isinstance() and
                  subclassing Exception all work).
  * Control flow: if/elif/else, while, for (with else), break, continue,
                  try/except/else/finally, raise, with, assert, del.
  * Expressions : all operators, chained comparisons, short-circuit and/or,
                  ternary, comprehensions, generator expressions, f-strings.
  * Library     : `import` / `from ... import` load real standard-library
                  modules (random, re, math, ...), and the normal built-ins
                  (print, input, len, range, float, ...) are available.

NOTE: this is a teaching interpreter, not a sandbox. Imported modules and
built-ins are the real ones, so scripts can do anything normal Python can.
Not supported (the parser rejects them): yield/generators, async, match,
walrus. eval/exec/compile/globals/locals/vars are intentionally unavailable.

Usage:
    python interpreter.py bank.py
    python interpreter.py script.py arg1 arg2      # extra args go to sys.argv
"""

import argparse
import builtins
import contextlib
import importlib
import operator
import re
import sys
import types

from lexer import LexError
from parser import ParseError, parse, parse_expression_source


# ---------------------------------------------------------------------------
# Control-flow signals (BaseException so user `except Exception` can't catch them)
# ---------------------------------------------------------------------------

class ReturnSignal(BaseException):
    def __init__(self, value):
        self.value = value


class BreakSignal(BaseException):
    pass


class ContinueSignal(BaseException):
    pass


CONTROL = (ReturnSignal, BreakSignal, ContinueSignal)

_MISSING = object()

HIDDEN_BUILTINS = {"eval", "exec", "compile", "globals", "locals", "vars",
                   "__import__", "breakpoint"}
BUILTINS = {k: v for k, v in vars(builtins).items()
            if k not in HIDDEN_BUILTINS and not k.startswith("__")}

BINOPS = {
    "+": operator.add, "-": operator.sub, "*": operator.mul, "/": operator.truediv,
    "//": operator.floordiv, "%": operator.mod, "**": operator.pow,
    "@": operator.matmul, "|": operator.or_, "^": operator.xor, "&": operator.and_,
    "<<": operator.lshift, ">>": operator.rshift,
}
INPLACE = {
    "+=": operator.iadd, "-=": operator.isub, "*=": operator.imul,
    "/=": operator.itruediv, "//=": operator.ifloordiv, "%=": operator.imod,
    "**=": operator.ipow, "&=": operator.iand, "|=": operator.ior,
    "^=": operator.ixor, ">>=": operator.irshift, "<<=": operator.ilshift,
}
COMPARISONS = {
    "==": operator.eq, "!=": operator.ne, "<": operator.lt, "<=": operator.le,
    ">": operator.gt, ">=": operator.ge, "is": operator.is_, "is not": operator.is_not,
    "in": lambda a, b: a in b, "not in": lambda a, b: a not in b,
}
UNARYOPS = {"-": operator.neg, "+": operator.pos, "~": operator.invert,
            "not": operator.not_}
CONVERSIONS = {"r": repr, "s": str, "a": ascii}


# ---------------------------------------------------------------------------
# Scopes
# ---------------------------------------------------------------------------

class Scope:
    """A namespace. Scopes are chained through `parent` (lexical nesting)."""

    def __init__(self, parent=None, is_class=False, func=None, first_arg=None):
        self.vars = {}
        self.parent = parent
        self.is_class = is_class
        self.func = func              # the PyFunction running in this scope (if any)
        self.first_arg = first_arg    # its first argument (used by bare super())
        self.globals = set()          # names declared `global` here
        self.nonlocals = set()        # names declared `nonlocal` here
        self.root = parent.root if parent else self

    def lookup(self, name):
        if name in self.globals:
            return self.root.vars.get(name, _MISSING)
        scope, first = self, True
        while scope is not None:
            # class scopes are invisible to code nested inside them
            if (first or not scope.is_class) and name in scope.vars:
                return scope.vars[name]
            first = False
            scope = scope.parent
        return _MISSING

    def assign(self, name, value):
        if name in self.globals:
            self.root.vars[name] = value
        elif name in self.nonlocals:
            scope = self.parent
            while scope is not None:
                if not scope.is_class and name in scope.vars:
                    scope.vars[name] = value
                    return
                scope = scope.parent
            raise SyntaxError(f"no binding for nonlocal {name!r} found")
        else:
            self.vars[name] = value

    def delete(self, name):
        target = self.root.vars if name in self.globals else self.vars
        if name not in target:
            raise NameError(f"name {name!r} is not defined")
        del target[name]


# ---------------------------------------------------------------------------
# User-defined functions
# ---------------------------------------------------------------------------

class PyFunction:
    """A function defined in interpreted code. It is a normal Python callable,
    and a descriptor, so it binds as a method when stored on a class."""

    def __init__(self, interp, name, params, body, closure, is_lambda=False):
        self.interp = interp
        self.__name__ = self.__qualname__ = name
        self.__doc__ = None
        self.body = body
        self.closure = closure
        self.is_lambda = is_lambda
        self.owner = None             # class this function was defined in (for super())

        self.pos, self.kwonly, self.defaults = [], [], {}
        self.vararg = self.kwarg = None
        seen_star = False
        for p in params:
            if p.name.startswith("**"):
                self.kwarg = p.name[2:]
                continue
            if p.name == "*":
                seen_star = True
                continue
            if p.name.startswith("*"):
                self.vararg = p.name[1:]
                seen_star = True
                continue
            (self.kwonly if seen_star else self.pos).append(p.name)
            if p.default is not None:                 # evaluated once, at definition
                self.defaults[p.name] = interp.evaluate(p.default, closure)

    # -- argument binding ----------------------------------------------------

    def bind(self, variables, args, kwargs):
        name = self.__name__
        if len(args) > len(self.pos) and not self.vararg:
            raise TypeError(f"{name}() takes {len(self.pos)} positional argument(s) "
                            f"but {len(args)} were given")
        for pname, value in zip(self.pos, args):
            variables[pname] = value
        if self.vararg:
            variables[self.vararg] = tuple(args[len(self.pos):])
        extra = {}
        for key, value in kwargs.items():
            if key in self.pos or key in self.kwonly:
                if key in variables:
                    raise TypeError(f"{name}() got multiple values for argument {key!r}")
                variables[key] = value
            elif self.kwarg:
                extra[key] = value
            else:
                raise TypeError(f"{name}() got an unexpected keyword argument {key!r}")
        if self.kwarg:
            variables[self.kwarg] = extra
        for pname in self.pos + self.kwonly:
            if pname not in variables:
                if pname in self.defaults:
                    variables[pname] = self.defaults[pname]
                else:
                    raise TypeError(f"{name}() missing required argument: {pname!r}")

    # -- calling ----------------------------------------------------------------

    def __call__(self, *args, **kwargs):
        interp = self.interp
        scope = Scope(parent=self.closure, func=self,
                      first_arg=args[0] if args else None)
        self.bind(scope.vars, args, kwargs)

        call_line = interp.line
        interp.stack.append((self.__name__, call_line))
        try:
            if self.is_lambda:
                result = interp.evaluate(self.body, scope)
            else:
                try:
                    interp.exec_block(self.body, scope)
                    result = None
                except ReturnSignal as signal:
                    result = signal.value
        except BaseException as exc:
            if not isinstance(exc, CONTROL) and not hasattr(exc, "_pyi_where"):
                try:                       # remember where the error happened
                    exc._pyi_where = (interp.line, list(interp.stack))
                except AttributeError:
                    pass
            raise
        finally:
            interp.stack.pop()
        interp.line = call_line
        return result

    def __get__(self, obj, objtype=None):
        return self if obj is None else types.MethodType(self, obj)

    def __repr__(self):
        return f"<function {self.__name__}>"


# ---------------------------------------------------------------------------
# The interpreter
# ---------------------------------------------------------------------------

class Interpreter:
    def __init__(self):
        self.line = 0           # line of the statement being executed
        self.stack = []         # [(function name, line it was called from), ...]
        sys.setrecursionlimit(max(sys.getrecursionlimit(), 10000))

    # ---- entry point -----------------------------------------------------

    def run(self, source, filename="<script>"):
        tree = parse(source)
        scope = Scope()
        scope.vars.update(__name__="__main__", __file__=filename)
        self.exec_block(tree.body, scope)
        return scope

    # ---- dispatch -----------------------------------------------------------

    def exec_block(self, statements, scope):
        for stmt in statements:
            self.execute(stmt, scope)

    def execute(self, node, scope):
        self.line = node.line
        handler = getattr(self, "exec_" + node.kind, None)
        if handler is None:
            raise NotImplementedError(f"statement {node.kind!r} is not supported")
        handler(node, scope)

    def evaluate(self, node, scope):
        handler = getattr(self, "eval_" + node.kind, None)
        if handler is None:
            raise NotImplementedError(f"expression {node.kind!r} is not supported")
        return handler(node, scope)

    # =======================================================================
    # Statements
    # =======================================================================

    def exec_Expr(self, node, scope):
        self.evaluate(node.value, scope)

    def exec_Pass(self, node, scope):
        pass

    def exec_Break(self, node, scope):
        raise BreakSignal()

    def exec_Continue(self, node, scope):
        raise ContinueSignal()

    def exec_Return(self, node, scope):
        raise ReturnSignal(None if node.value is None else self.evaluate(node.value, scope))

    def exec_Global(self, node, scope):
        scope.globals.update(node.names)

    def exec_Nonlocal(self, node, scope):
        scope.nonlocals.update(node.names)

    def exec_Assign(self, node, scope):
        value = self.evaluate(node.value, scope)
        for target in node.targets:
            self.store(target, value, scope)

    def exec_AnnAssign(self, node, scope):
        if node.value is not None:
            self.store(node.target, self.evaluate(node.value, scope), scope)

    def exec_AugAssign(self, node, scope):
        op, target = INPLACE[node.op], node.target
        if target.kind == "Name":
            current = self.evaluate(target, scope)
            scope.assign(target.id, op(current, self.evaluate(node.value, scope)))
        elif target.kind == "Attribute":
            obj = self.evaluate(target.value, scope)
            current = getattr(obj, target.attr)
            setattr(obj, target.attr, op(current, self.evaluate(node.value, scope)))
        elif target.kind == "Subscript":
            obj = self.evaluate(target.value, scope)
            index = self.eval_index(target.index, scope)
            obj[index] = op(obj[index], self.evaluate(node.value, scope))
        else:
            raise SyntaxError(f"cannot apply {node.op} to {target.kind}")

    def exec_Delete(self, node, scope):
        self.delete(node.target, scope)

    def delete(self, target, scope):
        if target.kind == "Name":
            scope.delete(target.id)
        elif target.kind == "Attribute":
            delattr(self.evaluate(target.value, scope), target.attr)
        elif target.kind == "Subscript":
            del self.evaluate(target.value, scope)[self.eval_index(target.index, scope)]
        elif target.kind == "Tuple":
            for element in target.elts:
                self.delete(element, scope)
        else:
            raise SyntaxError(f"cannot delete {target.kind}")

    def exec_Assert(self, node, scope):
        if not self.evaluate(node.test, scope):
            if node.msg is not None:
                raise AssertionError(self.evaluate(node.msg, scope))
            raise AssertionError()

    def exec_Raise(self, node, scope):
        if node.exc is None:
            raise                                   # re-raise the active exception
        exc = self.evaluate(node.exc, scope)
        if node.cause is not None:
            raise exc from self.evaluate(node.cause, scope)
        raise exc

    def exec_If(self, node, scope):
        branch = node.body if self.evaluate(node.test, scope) else node.orelse
        self.exec_block(branch, scope)

    def exec_While(self, node, scope):
        while self.evaluate(node.test, scope):
            try:
                self.exec_block(node.body, scope)
            except BreakSignal:
                break
            except ContinueSignal:
                continue
        else:
            self.exec_block(node.orelse, scope)

    def exec_For(self, node, scope):
        for item in self.evaluate(node.iter, scope):
            self.store(node.target, item, scope)
            try:
                self.exec_block(node.body, scope)
            except BreakSignal:
                break
            except ContinueSignal:
                continue
        else:
            self.exec_block(node.orelse, scope)

    def exec_Try(self, node, scope):
        try:
            try:
                self.exec_block(node.body, scope)
            except BaseException as exc:
                if isinstance(exc, CONTROL):
                    raise
                handler = self.find_handler(node.handlers, exc, scope)
                if handler is None:
                    raise
                if handler.name:
                    scope.assign(handler.name, exc)
                try:
                    self.exec_block(handler.body, scope)
                finally:
                    if handler.name:
                        scope.vars.pop(handler.name, None)
            else:
                self.exec_block(node.orelse, scope)
        finally:
            self.exec_block(node.finalbody, scope)

    def find_handler(self, handlers, exc, scope):
        for handler in handlers:
            if handler.exc_type is None:
                return handler
            if isinstance(exc, self.evaluate(handler.exc_type, scope)):
                return handler
        return None

    def exec_With(self, node, scope):
        with contextlib.ExitStack() as stack:
            for item in node.items:
                value = stack.enter_context(self.evaluate(item.context, scope))
                if item.var is not None:
                    self.store(item.var, value, scope)
            self.exec_block(node.body, scope)

    # ---- imports --------------------------------------------------------------

    def exec_Import(self, node, scope):
        for alias in node.names:
            module = importlib.import_module(alias.name)
            if alias.asname:
                scope.assign(alias.asname, module)
            else:
                top = alias.name.split(".")[0]
                scope.assign(top, sys.modules[top])

    def exec_ImportFrom(self, node, scope):
        if node.level:
            raise ImportError("relative imports are not supported")
        module = importlib.import_module(node.module)
        for alias in node.names:
            if alias.name == "*":
                public = getattr(module, "__all__",
                                 [n for n in dir(module) if not n.startswith("_")])
                for name in public:
                    scope.assign(name, getattr(module, name))
                continue
            try:
                value = getattr(module, alias.name)
            except AttributeError:
                value = importlib.import_module(f"{node.module}.{alias.name}")
            scope.assign(alias.asname or alias.name, value)

    # ---- definitions ------------------------------------------------------------

    def exec_FunctionDef(self, node, scope):
        func = PyFunction(self, node.name, node.params, node.body, scope)
        for decorator in reversed(node.decorators):
            func = self.evaluate(decorator, scope)(func)
        scope.assign(node.name, func)

    def exec_ClassDef(self, node, scope):
        bases = tuple(self.evaluate(b, scope) for b in node.bases)
        options = {k.name: self.evaluate(k.value, scope) for k in node.keywords}
        metaclass = options.pop("metaclass", type)

        class_scope = Scope(parent=scope, is_class=True)
        class_scope.vars.update(__module__="__main__", __qualname__=node.name)
        self.exec_block(node.body, class_scope)

        cls = metaclass(node.name, bases, dict(class_scope.vars), **options)
        for member in class_scope.vars.values():     # let bare super() find its class
            func = getattr(member, "__func__", member)
            if isinstance(func, PyFunction):
                func.owner = cls
        for decorator in reversed(node.decorators):
            cls = self.evaluate(decorator, scope)(cls)
        scope.assign(node.name, cls)

    # ---- assignment targets ---------------------------------------------------

    def store(self, target, value, scope):
        kind = target.kind
        if kind == "Name":
            scope.assign(target.id, value)
        elif kind == "Attribute":
            setattr(self.evaluate(target.value, scope), target.attr, value)
        elif kind == "Subscript":
            self.evaluate(target.value, scope)[self.eval_index(target.index, scope)] = value
        elif kind in ("Tuple", "List"):
            self.unpack(target.elts, value, scope)
        elif kind == "Starred":
            self.store(target.value, value, scope)
        else:
            raise SyntaxError(f"cannot assign to {kind}")

    def unpack(self, targets, value, scope):
        values = list(value)
        star = next((i for i, t in enumerate(targets) if t.kind == "Starred"), None)
        if star is None:
            if len(values) != len(targets):
                word = "many" if len(values) > len(targets) else "few"
                raise ValueError(f"too {word} values to unpack "
                                 f"(expected {len(targets)}, got {len(values)})")
            for target, item in zip(targets, values):
                self.store(target, item, scope)
            return
        after = len(targets) - star - 1
        if len(values) < len(targets) - 1:
            raise ValueError(f"not enough values to unpack (expected at least "
                             f"{len(targets) - 1}, got {len(values)})")
        for target, item in zip(targets[:star], values[:star]):
            self.store(target, item, scope)
        middle_end = len(values) - after
        self.store(targets[star].value, values[star:middle_end], scope)
        for target, item in zip(targets[star + 1:], values[middle_end:]):
            self.store(target, item, scope)

    # =======================================================================
    # Expressions
    # =======================================================================

    def eval_Constant(self, node, scope):
        return node.value

    def eval_Name(self, node, scope):
        value = scope.lookup(node.id)
        if value is not _MISSING:
            return value
        try:
            return BUILTINS[node.id]
        except KeyError:
            raise NameError(f"name {node.id!r} is not defined") from None

    def eval_JoinedStr(self, node, scope):
        return "".join(str(self.evaluate(part, scope)) for part in node.values)

    def eval_FormattedValue(self, node, scope):
        value = self.evaluate(node.value, scope)
        spec, conversion = node.format_spec or "", None
        if spec.startswith("!"):
            conversion, spec = spec[1], spec[2:]
        spec = spec[1:] if spec.startswith(":") else ""
        if "{" in spec:                                  # nested fields: {x:{width}}
            spec = re.sub(
                r"\{([^{}]*)\}",
                lambda m: str(self.evaluate(parse_expression_source(m.group(1), node.line), scope)),
                spec)
        if conversion:
            value = CONVERSIONS[conversion](value)
        return format(value, spec)

    def eval_BinOp(self, node, scope):
        return BINOPS[node.op](self.evaluate(node.left, scope), self.evaluate(node.right, scope))

    def eval_UnaryOp(self, node, scope):
        return UNARYOPS[node.op](self.evaluate(node.operand, scope))

    def eval_BoolOp(self, node, scope):
        value = None
        for operand in node.values:
            value = self.evaluate(operand, scope)
            if (node.op == "and") != bool(value):        # short-circuit
                return value
        return value

    def eval_Compare(self, node, scope):
        left = self.evaluate(node.left, scope)
        for op, comparator in zip(node.ops, node.comparators):
            right = self.evaluate(comparator, scope)
            if not COMPARISONS[op](left, right):
                return False
            left = right
        return True

    def eval_IfExp(self, node, scope):
        branch = node.body if self.evaluate(node.test, scope) else node.orelse
        return self.evaluate(branch, scope)

    def eval_Lambda(self, node, scope):
        return PyFunction(self, "<lambda>", node.params, node.body, scope, is_lambda=True)

    def eval_Call(self, node, scope):
        func_node = node.func
        if (func_node.kind == "Name" and func_node.id == "super"
                and not node.args and not node.keywords
                and scope.lookup("super") is _MISSING):
            return self.zero_arg_super(scope)

        func = self.evaluate(func_node, scope)
        args, kwargs = [], {}
        for arg in node.args:
            if arg.kind == "Starred":
                args.extend(self.evaluate(arg.value, scope))
            else:
                args.append(self.evaluate(arg, scope))
        for keyword in node.keywords:
            value = self.evaluate(keyword.value, scope)
            if keyword.name is None:
                kwargs.update(value)
            else:
                kwargs[keyword.name] = value
        return func(*args, **kwargs)

    def zero_arg_super(self, scope):
        frame = scope
        while frame is not None and frame.func is None:
            frame = frame.parent
        if frame is None or frame.func.owner is None or frame.first_arg is None:
            raise RuntimeError("super(): no arguments and not inside a method")
        return super(frame.func.owner, frame.first_arg)

    def eval_Attribute(self, node, scope):
        return getattr(self.evaluate(node.value, scope), node.attr)

    def eval_Subscript(self, node, scope):
        return self.evaluate(node.value, scope)[self.eval_index(node.index, scope)]

    def eval_index(self, node, scope):
        if node.kind == "Slice":
            part = lambda n: None if n is None else self.evaluate(n, scope)
            return slice(part(node.lower), part(node.upper), part(node.step))
        if node.kind == "Tuple":
            return tuple(self.eval_index(e, scope) for e in node.elts)
        return self.evaluate(node, scope)

    # ---- collections -----------------------------------------------------------

    def eval_elements(self, elts, scope):
        items = []
        for element in elts:
            if element.kind == "Starred":
                items.extend(self.evaluate(element.value, scope))
            else:
                items.append(self.evaluate(element, scope))
        return items

    def eval_Tuple(self, node, scope):
        return tuple(self.eval_elements(node.elts, scope))

    def eval_List(self, node, scope):
        return self.eval_elements(node.elts, scope)

    def eval_Set(self, node, scope):
        return set(self.eval_elements(node.elts, scope))

    def eval_Dict(self, node, scope):
        return {self.evaluate(k, scope): self.evaluate(v, scope)
                for k, v in zip(node.keys, node.values)}

    # ---- comprehensions ----------------------------------------------------------

    def comprehend(self, generators, scope, emit):
        """Lazily yield emit(comp_scope) for every combination of the clauses."""
        comp_scope = Scope(parent=scope)

        def run(i):
            if i == len(generators):
                yield emit(comp_scope)
                return
            clause = generators[i]
            iterable = self.evaluate(clause.iter, scope if i == 0 else comp_scope)
            for item in iterable:
                self.store(clause.target, item, comp_scope)
                if all(self.evaluate(cond, comp_scope) for cond in clause.ifs):
                    yield from run(i + 1)

        return run(0)

    def eval_ListComp(self, node, scope):
        return list(self.comprehend(node.generators, scope,
                                    lambda s: self.evaluate(node.elt, s)))

    def eval_SetComp(self, node, scope):
        return set(self.comprehend(node.generators, scope,
                                   lambda s: self.evaluate(node.elt, s)))

    def eval_GeneratorExp(self, node, scope):
        return self.comprehend(node.generators, scope,
                               lambda s: self.evaluate(node.elt, s))

    def eval_DictComp(self, node, scope):
        return dict(self.comprehend(
            node.generators, scope,
            lambda s: (self.evaluate(node.key, s), self.evaluate(node.value, s))))


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------

def report_error(interp, exc):
    line, stack = getattr(exc, "_pyi_where", (interp.line, []))
    print("Traceback (most recent call last):", file=sys.stderr)
    for i, (_, call_line) in enumerate(stack):
        caller = "<module>" if i == 0 else stack[i - 1][0]
        print(f"  line {call_line}, in {caller}", file=sys.stderr)
    print(f"  line {line}, in {stack[-1][0] if stack else '<module>'}", file=sys.stderr)
    print(f"{type(exc).__name__}: {exc}", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(description="Interpret a Python source file.")
    ap.add_argument("file")
    ap.add_argument("args", nargs="*", help="arguments passed to the script (sys.argv)")
    options = ap.parse_args()

    with open(options.file, encoding="utf-8") as f:
        source = f.read()
    sys.argv = [options.file] + options.args

    interp = Interpreter()
    try:
        interp.run(source, options.file)
    except (LexError, ParseError) as e:
        sys.exit(str(e))
    except SystemExit:
        raise
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(130)
    except (BreakSignal, ContinueSignal, ReturnSignal):
        sys.exit(f"Syntax error: 'break', 'continue' or 'return' outside a loop/function "
                 f"(line {interp.line})")
    except BaseException as e:
        report_error(interp, e)
        sys.exit(1)


if __name__ == "__main__":
    main()