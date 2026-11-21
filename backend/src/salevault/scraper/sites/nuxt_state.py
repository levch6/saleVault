"""Read the state a Nuxt 2 page embeds for its scripts (`window.__NUXT__=...`), without running it.

Nuxt 2 writes the state with devalue: a function expression that takes every value used more
than once as a parameter, fills in the objects that refer to each other with assignments and
returns the state, called with the values of its parameters:

    window.__NUXT__=(function(a,b,c){a.title=b;return {data:[a],count:c}}({},"Text",72));

This module reads exactly that subset of JavaScript as data: string, number and regular
expression literals, `true`, `false`, `null`, `void 0`, object and array literals (with holes),
parameter names, the constructors devalue writes (`Array(n)`, `Object(...)`,
`Object.create(null)`, `Object.assign(...)`, `new Date(n)`, `new Set`, `new Map`) and the
statements of the function body (`a.key=...`, `a[0]=...`, `a["key"]=...`, `a.add(...)`,
`a.set(...)`, `return ...`). Nothing is executed and anything else is an error.
"""

import re
from typing import Any

_PREFIX = re.compile(r"<script[^>]*>\s*window\.__NUXT__\s*=", re.IGNORECASE)

_TOKEN = re.compile(
    r"""\s*(
        "(?:[^"\\\n]|\\.)*"
      | '(?:[^'\\\n]|\\.)*'
      | (?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?
      | [A-Za-z_$][A-Za-z0-9_$]*
      | /(?:[^/\\\[\n]|\\.|\[(?:[^\]\\\n]|\\.)*\])+/[a-z]*
      | \S
    )""",
    re.VERBOSE | re.DOTALL,
)
"""Strings, numbers, names, regular expressions (there is no division in this subset) and
single characters; the reader rejects whatever it does not expect."""

_ESCAPE = re.compile(r"\\(u\{[0-9a-fA-F]{1,6}\}|u[0-9a-fA-F]{4}|x[0-9a-fA-F]{2}|\r\n|.)", re.DOTALL)
_SIMPLE_ESCAPES = {
    "n": "\n",
    "t": "\t",
    "r": "\r",
    "b": "\b",
    "f": "\f",
    "v": "\v",
    "0": "\0",
    "\n": "",  # line continuations
    "\r": "",
    "\r\n": "",
    "\u2028": "",
    "\u2029": "",
}
_SURROGATE = re.compile("[\ud800-\udfff]")

_MAX_DEPTH = 200
_MAX_ARRAY = 1_000_000
_OPENERS = frozenset("{[(")
_CLOSERS = frozenset("}])")


class NuxtStateError(ValueError):
    """The page's state is missing or is not in the expected form."""


def find_state_script(html: str) -> str | None:
    """The JavaScript after `window.__NUXT__=` in the page, or None if there is none."""
    match = _PREFIX.search(html)
    if match is None:
        return None
    end = html.find("</script>", match.end())
    if end < 0:
        raise NuxtStateError("The state script is not closed")
    return html[match.end() : end]


def read_nuxt_state(html: str) -> Any:
    """The state embedded in a page, as dicts, lists and plain values (None if the page has
    none). Objects used in several places are shared, as in the page."""
    script = find_state_script(html)
    if script is None:
        return None
    return read_state_script(script)


def read_state_script(script: str) -> Any:
    """The value of the JavaScript after `window.__NUXT__=`."""
    tokens = _TOKEN.findall(script)
    if tokens and tokens[-1] == ";":
        tokens.pop()
    reader = _Reader(tokens)
    value = reader.program()
    if reader.pos != len(tokens):
        raise NuxtStateError(f"Unexpected {reader.peek()!r} after the state")
    return value


def js_string(tok: str) -> str:
    """The value of a quoted string literal."""
    body = tok[1:-1]
    if "\\" not in body:
        return body
    text = _ESCAPE.sub(_unescape, body)
    if _SURROGATE.search(text):
        # \uD83D\uDE00 and similar pairs are one character
        text = text.encode("utf-16", "surrogatepass").decode("utf-16", "replace")
    return text


def _unescape(match: re.Match[str]) -> str:
    escape = match.group(1)
    if escape[0] == "u" and len(escape) > 1:
        code = int(escape[2:-1] if escape[1] == "{" else escape[1:], 16)
        if code > 0x10FFFF:
            raise NuxtStateError(f"Invalid escape \\{escape}")
        return chr(code)
    if escape[0] == "x" and len(escape) == 3:
        return chr(int(escape[1:], 16))
    return _SIMPLE_ESCAPES.get(escape, escape)


class _Reader:
    def __init__(self, tokens: list[str]) -> None:
        self.tokens = tokens
        self.pos = 0
        self.scope: dict[str, Any] = {}

    # --- tokens --------------------------------------------------------------------------

    def peek(self) -> str:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else ""

    def next(self) -> str:
        tok = self.peek()
        if not tok:
            raise NuxtStateError("Unexpected end of the state")
        self.pos += 1
        return tok

    def expect(self, tok: str) -> None:
        found = self.next()
        if found != tok:
            raise NuxtStateError(f"Expected {tok!r}, found {found!r} (token {self.pos})")

    def name(self) -> str:
        tok = self.next()
        if not _is_name(tok):
            raise NuxtStateError(f"Expected a name, found {tok!r} (token {self.pos})")
        return tok

    # --- the program ---------------------------------------------------------------------

    def program(self) -> Any:
        """`(function(params){body}(args))`, or a plain value when nothing is shared."""
        if self.peek() != "(":
            return self.value(0)
        self.expect("(")
        if self.next() != "function":
            raise NuxtStateError("Expected a function expression")
        self.expect("(")
        params: list[str] = []
        while self.peek() != ")":
            params.append(self.name())
            if self.peek() == ",":
                self.pos += 1
        self.expect(")")
        self.expect("{")
        body = self.pos
        self.pos = self._skip_block(body)
        self.expect("}")
        self.expect("(")
        args: list[Any] = []
        while self.peek() != ")":
            args.append(self.value(0))
            if self.peek() == ",":
                self.pos += 1
            elif self.peek() != ")":
                raise NuxtStateError(f"Unexpected {self.peek()!r} in the arguments")
        self.expect(")")
        self.expect(")")
        end = self.pos
        self.scope = dict(zip(params, args + [None] * (len(params) - len(args)), strict=False))
        self.pos = body
        result = self.body()
        self.pos = end
        return result

    def _skip_block(self, start: int) -> int:
        """Position of the `}` that closes the function body."""
        depth = 0
        for index in range(start, len(self.tokens)):
            tok = self.tokens[index]
            if tok in _OPENERS:
                depth += 1
            elif tok in _CLOSERS:
                if depth == 0:
                    if tok != "}":
                        raise NuxtStateError(f"Unbalanced {tok!r} in the function body")
                    return index
                depth -= 1
        raise NuxtStateError("The function body is not closed")

    def body(self) -> Any:
        while True:
            if self.peek() == "return":
                self.pos += 1
                value = self.value(0)
                if self.peek() == ";":
                    self.pos += 1
                if self.peek() != "}":
                    raise NuxtStateError("Statements after return")
                return value
            self.statement()
            if self.peek() == ";":
                self.pos += 1
            elif self.peek() != "return":
                raise NuxtStateError(f"Unexpected {self.peek()!r} after a statement")

    def statement(self) -> None:
        """`p.key=value`, `p[index]=value`, `p.add(value)...` or `p.set(key,value)...`."""
        name = self.name()
        if name not in self.scope:
            raise NuxtStateError(f"Assignment to unknown name {name!r}")
        target = self.scope[name]
        tok = self.next()
        if tok == "[":
            key_tok = self.next()
            key: str | int = js_string(key_tok) if _is_string(key_tok) else _index(key_tok)
            self.expect("]")
        elif tok == ".":
            key = self.name()
            if self.peek() == "(" and key in ("add", "set"):
                self._calls(target, key)
                return
        else:
            raise NuxtStateError(f"Unexpected {tok!r} in a statement")
        self.expect("=")
        _assign(target, key, self.value(0))

    def _calls(self, target: Any, method: str) -> None:
        """`s.add(a).add(b)` (a Set, read as a list) or `m.set(k,v).set(...)` (a Map, a dict)."""
        while True:
            self.expect("(")
            if method == "add" and isinstance(target, list):
                target.append(self.value(0))
            elif method == "set" and isinstance(target, dict):
                key = self.value(0)
                self.expect(",")
                target[_map_key(key)] = self.value(0)
            else:
                raise NuxtStateError(f"Unexpected .{method}() call")
            self.expect(")")
            if self.peek() != ".":
                return
            self.pos += 1
            if self.name() != method:
                raise NuxtStateError("Mixed calls in a statement")

    # --- values --------------------------------------------------------------------------

    def value(self, depth: int) -> Any:
        if depth > _MAX_DEPTH:
            raise NuxtStateError("The state is nested too deeply")
        tok = self.next()
        first = tok[0]
        if _is_string(tok):
            return js_string(tok)
        if first.isdigit() or (first == "." and len(tok) > 1):
            return _number(tok)
        if tok == "{":
            return self._object(depth)
        if tok == "[":
            return self._array(depth)
        if tok == "-":
            number = self.value(depth + 1)
            if isinstance(number, bool) or not isinstance(number, int | float):
                raise NuxtStateError("Unary minus before a value that is not a number")
            return -number
        if first == "/" and len(tok) > 1:
            return tok  # a regular expression, kept as its source text
        if _is_name(tok):
            return self._name_value(tok, depth)
        raise NuxtStateError(f"Unexpected {tok!r} (token {self.pos})")

    def _name_value(self, tok: str, depth: int) -> Any:
        match tok:
            case "true":
                return True
            case "false":
                return False
            case "null":
                return None
            case "void":
                self.value(depth + 1)
                return None
            case "new":
                return self._new(depth)
        if tok in self.scope:
            return self.scope[tok]
        match tok:
            case "undefined":
                return None
            case "NaN" | "Infinity":
                return float(tok)
            case "Array" if self.peek() == "(":
                self.pos += 1
                size = self.value(depth + 1)
                self.expect(")")
                if (
                    not isinstance(size, int)
                    or isinstance(size, bool)
                    or not (0 <= size <= _MAX_ARRAY)
                ):
                    raise NuxtStateError(f"Unexpected array size {size!r}")
                return [None] * size
            case "Object":
                return self._object_call(depth)
        raise NuxtStateError(f"Unknown name {tok!r} (token {self.pos})")

    def _object_call(self, depth: int) -> Any:
        """`Object(value)`, `Object.create(null)` or `Object.assign(target, source)`."""
        if self.peek() == "(":
            self.pos += 1
            value = self.value(depth + 1)
            self.expect(")")
            return value
        self.expect(".")
        method = self.name()
        self.expect("(")
        if method == "create":
            self.expect("null")
            self.expect(")")
            return {}
        if method == "assign":
            target = self.value(depth + 1)
            self.expect(",")
            source = self.value(depth + 1)
            self.expect(")")
            if not isinstance(target, dict) or not isinstance(source, dict):
                raise NuxtStateError("Object.assign() of something that is not an object")
            target.update(source)
            return target
        raise NuxtStateError(f"Unexpected Object.{method}()")

    def _new(self, depth: int) -> Any:
        """`new Date(n)` (kept as the number), `new Set([...])` or `new Map([[k, v], ...])`."""
        kind = self.name()
        argument: Any = None
        if self.peek() == "(":
            self.pos += 1
            if self.peek() != ")":
                argument = self.value(depth + 1)
            self.expect(")")
        if kind == "Date":
            return argument
        if kind == "Set" and isinstance(argument, list | None):
            return list(argument or [])
        if kind == "Map" and isinstance(argument, list | None):
            result: dict[Any, Any] = {}
            for pair in argument or []:
                if not isinstance(pair, list) or len(pair) != 2:
                    raise NuxtStateError("A Map entry that is not a pair")
                result[_map_key(pair[0])] = pair[1]
            return result
        raise NuxtStateError(f"Unexpected new {kind}")

    def _object(self, depth: int) -> dict[str, Any]:
        result: dict[str, Any] = {}
        while self.peek() != "}":
            tok = self.next()
            if _is_string(tok):
                key = js_string(tok)
            elif _is_name(tok) or tok[0].isdigit():
                key = tok
            else:
                raise NuxtStateError(f"Unexpected key {tok!r} (token {self.pos})")
            self.expect(":")
            result[key] = self.value(depth + 1)
            if self.peek() == ",":
                self.pos += 1
            elif self.peek() != "}":
                raise NuxtStateError(f"Unexpected {self.peek()!r} in an object")
        self.pos += 1
        return result

    def _array(self, depth: int) -> list[Any]:
        result: list[Any] = []
        while self.peek() != "]":
            if self.peek() == ",":  # a hole
                self.pos += 1
                result.append(None)
                continue
            result.append(self.value(depth + 1))
            if self.peek() == ",":
                self.pos += 1
            elif self.peek() != "]":
                raise NuxtStateError(f"Unexpected {self.peek()!r} in an array")
        self.pos += 1
        return result


_NAME = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")


def _is_name(tok: str) -> bool:
    return _NAME.fullmatch(tok) is not None


def _is_string(tok: str) -> bool:
    """A complete string literal (a lone quote is what an unclosed one leaves)."""
    return len(tok) > 1 and tok[0] in "\"'"


def _number(tok: str) -> int | float:
    try:
        return int(tok) if tok.isdigit() else float(tok)
    except ValueError:
        raise NuxtStateError(f"Invalid number {tok!r}") from None


def _index(tok: str) -> int:
    if not tok.isdigit():
        raise NuxtStateError(f"Unexpected index {tok!r}")
    return int(tok)


def _map_key(key: Any) -> Any:
    if isinstance(key, dict | list):
        raise NuxtStateError("A Map key that is an object")
    return key


def _assign(target: Any, key: str | int, value: Any) -> None:
    if isinstance(target, list):
        if not isinstance(key, int) or key >= len(target):
            raise NuxtStateError(f"Index {key!r} outside the array")
        target[key] = value
    elif isinstance(target, dict):
        target[str(key)] = value
    else:
        raise NuxtStateError("Assignment to a value that is not an object")
