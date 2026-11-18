"""Parser for the git-annex matching expressions used as distribution filters.

Supported terms: include=<glob>, exclude=<glob>, metadata=<field>=<glob>,
metadata=<field><op><number> (op one of <, >, <=, >=), anything, nothing, combined with
`and`, `or`, `not` and parentheses. The parser only checks well-formedness; git-annex
evaluates the expression.
"""

from __future__ import annotations

import re

_COMPARE = re.compile(r"^metadata=[^=<>\s]+(<=|>=|<|>)-?\d+(\.\d+)?$")
_GLOB_TERM = re.compile(r"^(include|exclude)=\S+$")
_METADATA_GLOB = re.compile(r"^metadata=[^=<>\s]+=\S*$")


class FilterError(ValueError):
    pass


def _tokens(expression: str) -> list[str]:
    return expression.replace("(", " ( ").replace(")", " ) ").split()


def _is_term(token: str) -> bool:
    return (
        token in ("anything", "nothing")
        or bool(_GLOB_TERM.match(token))
        or bool(_METADATA_GLOB.match(token))
        or bool(_COMPARE.match(token))
    )


def parse(expression: str) -> None:
    """Raise FilterError when `expression` is not a well-formed matching expression."""
    tokens = _tokens(expression)
    if not tokens:
        raise FilterError("empty expression")
    pos = _or(tokens, 0)
    if pos != len(tokens):
        raise FilterError(f"unexpected {tokens[pos]!r}")


def _or(tokens: list[str], pos: int) -> int:
    pos = _and(tokens, pos)
    while pos < len(tokens) and tokens[pos] == "or":
        pos = _and(tokens, pos + 1)
    return pos


def _and(tokens: list[str], pos: int) -> int:
    pos = _not(tokens, pos)
    while pos < len(tokens) and tokens[pos] == "and":
        pos = _not(tokens, pos + 1)
    return pos


def _not(tokens: list[str], pos: int) -> int:
    if pos < len(tokens) and tokens[pos] == "not":
        return _not(tokens, pos + 1)
    return _atom(tokens, pos)


def _atom(tokens: list[str], pos: int) -> int:
    if pos >= len(tokens):
        raise FilterError("expression ends where a term is expected")
    token = tokens[pos]
    if token == "(":
        pos = _or(tokens, pos + 1)
        if pos >= len(tokens) or tokens[pos] != ")":
            raise FilterError("missing closing parenthesis")
        return pos + 1
    if not _is_term(token):
        raise FilterError(f"unknown term {token!r}")
    return pos + 1


# -- evaluating an expression against one file ----------------------------------------------------


def matches(expression: str, path: str, metadata: dict[str, list[str]]) -> bool:
    """Whether a file with this path and annex metadata satisfies the expression.

    The same terms `parse` accepts, evaluated the way git-annex evaluates a remote's wanted
    content: `include=`/`exclude=` against the path, `metadata=field=glob` against the values of
    the field, numeric comparisons against its first value.
    """
    import fnmatch

    def term(token: str) -> bool:
        if token == "anything":
            return True
        if token == "nothing":
            return False
        if token.startswith("include="):
            return fnmatch.fnmatchcase(path, token[8:])
        if token.startswith("exclude="):
            return not fnmatch.fnmatchcase(path, token[8:])
        compared = _COMPARE.match(token)
        field_name, _, rest = token.removeprefix("metadata=").partition("=")
        if compared:
            op = compared.group(1)
            field_name, number = re.split(r"<=|>=|<|>", token.removeprefix("metadata="))
            values = metadata.get(field_name) or []
            try:
                have, want = float(values[0]), float(number)
            except (IndexError, ValueError):
                return False
            return {"<": have < want, ">": have > want, "<=": have <= want, ">=": have >= want}[op]
        return any(fnmatch.fnmatchcase(v, rest) for v in metadata.get(field_name, []))

    tokens = _tokens(expression)
    pos = 0

    def parse_or() -> bool:
        nonlocal pos
        value = parse_and()
        while pos < len(tokens) and tokens[pos] == "or":
            pos += 1
            other = parse_and()
            value = value or other
        return value

    def parse_and() -> bool:
        nonlocal pos
        value = parse_not()
        while pos < len(tokens) and tokens[pos] == "and":
            pos += 1
            other = parse_not()
            value = value and other
        return value

    def parse_not() -> bool:
        nonlocal pos
        if pos < len(tokens) and tokens[pos] == "not":
            pos += 1
            return not parse_not()
        return parse_atom()

    def parse_atom() -> bool:
        nonlocal pos
        token = tokens[pos]
        pos += 1
        if token == "(":
            value = parse_or()
            pos += 1  # the closing parenthesis
            return value
        return term(token)

    parse(expression)  # well-formedness first
    return parse_or()
