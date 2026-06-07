"""Five parser strategies for cross-repo enum drift extraction — ADR-0031 §I1.

Each parser is a *small lexical scanner with a targeted extractor* (not a
regex-only matcher and not an arbitrary Java/TS parser): a comment-strip
pre-pass that preserves string literals, then a tight extractor for the
declaration shape the strategy targets. Unknown shapes raise ParseError →
exit 2 at the caller. The fixture matrix in tests pins every known shape;
new shapes require a new strategy + tests added to KNOWN_STRATEGIES.

ADR-0031 §I2: order is preserved in the returned list for the report's
extracted field, but set-equality is what the guard tests; per-strategy
duplicate detection is intentional (a duplicate enum value or tuple entry
is itself a value-level drift bug).
"""
from __future__ import annotations

import re
from typing import Callable


class ParseError(ValueError):
    """Raised when a parser cannot extract a value list from the given source.

    Exit code 2 at the caller — distinct from drift (exit 1) so the gate
    never silently passes an unparseable canonical/mirror.
    """


# ----------------------------------------------------------------------
# Comment strip — shared helper (Java and TS use the same comment syntax)
# ----------------------------------------------------------------------


def strip_comments(src: str) -> str:
    """Strip // line and /* block */ comments. PRESERVES string literals verbatim
    (so that 'http://foo' inside a string is not corrupted).

    Single, double, and back-tick quotes are tracked. Escaped quotes inside
    strings (e.g. `"a \"b\" c"`) are honored. This is intentionally permissive
    on TS template literal interpolation `${...}` (treated as opaque string
    content) — the parsers we ship never read interpolated values.

    Java does not have back-tick strings; including them is harmless for Java
    sources and necessary for TS.
    """
    out: list[str] = []
    i = 0
    n = len(src)
    while i < n:
        c = src[i]
        # block comment
        if c == "/" and i + 1 < n and src[i + 1] == "*":
            end = src.find("*/", i + 2)
            if end == -1:
                raise ParseError("unterminated /* block comment */")
            # collapse to a single space so token boundaries are preserved
            out.append(" ")
            i = end + 2
            continue
        # line comment
        if c == "/" and i + 1 < n and src[i + 1] == "/":
            end = src.find("\n", i + 2)
            if end == -1:
                # comment runs to EOF; keep the (implicit) newline preserved
                break
            out.append(" ")
            i = end  # newline preserved on next loop
            continue
        # string literal — copy verbatim through to the matching close quote
        if c in ('"', "'", "`"):
            quote = c
            out.append(c)
            i += 1
            while i < n:
                cc = src[i]
                out.append(cc)
                if cc == "\\" and i + 1 < n:
                    # copy escape sequence (e.g. \", \\, \n) verbatim
                    out.append(src[i + 1])
                    i += 2
                    continue
                if cc == quote:
                    i += 1
                    break
                i += 1
            else:
                raise ParseError(f"unterminated string literal opened with {quote!r}")
            continue
        out.append(c)
        i += 1
    return "".join(out)


# ----------------------------------------------------------------------
# Balanced-delimiter extractor
# ----------------------------------------------------------------------


def extract_balanced(src: str, start: int, open_char: str, close_char: str) -> tuple[int, int]:
    """Given that src[start] == open_char, return (start+1, end) where end is
    the index of the matching close_char. Honors nested delimiters and string
    literals (call AFTER strip_comments so comments cannot leak open/close).
    Raises ParseError on unbalanced.
    """
    if start >= len(src) or src[start] != open_char:
        raise ParseError(f"expected {open_char!r} at index {start}")
    depth = 1
    i = start + 1
    n = len(src)
    while i < n:
        c = src[i]
        if c in ('"', "'", "`"):
            # skip string literal verbatim
            quote = c
            i += 1
            while i < n:
                cc = src[i]
                if cc == "\\" and i + 1 < n:
                    i += 2
                    continue
                if cc == quote:
                    i += 1
                    break
                i += 1
            else:
                raise ParseError(f"unterminated string at index {i}")
            continue
        if c == open_char:
            depth += 1
        elif c == close_char:
            depth -= 1
            if depth == 0:
                return start + 1, i
        i += 1
    raise ParseError(f"unbalanced {open_char}{close_char} starting at {start}")


# ----------------------------------------------------------------------
# Quoted literal scanner
# ----------------------------------------------------------------------


_QUOTED = re.compile(
    r"""(?P<dq>"(?:\\.|[^"\\])*")|(?P<sq>'(?:\\.|[^'\\])*')""",
    flags=re.DOTALL,
)


def extract_quoted_literals(src: str) -> list[str]:
    """Extract every quoted string literal (double or single quote) from src,
    in order. Escape sequences are decoded as JSON-compatible (\\n, \\t, \\\\,
    \\", \\').

    Caller is responsible for restricting the slice (e.g. inside the args of
    `Set.of(...)`) before calling.
    """
    out: list[str] = []
    for m in _QUOTED.finditer(src):
        raw = m.group("dq") or m.group("sq")
        body = raw[1:-1]
        # decode minimal escapes — JSON-style sufficient for the enum
        # vocabulary we guard (uppercase ASCII identifiers, lowercase wdac etc).
        decoded = (
            body.replace(r"\\", "\x00")  # placeholder
            .replace(r"\n", "\n")
            .replace(r"\t", "\t")
            .replace(r"\r", "\r")
            .replace(r"\"", '"')
            .replace(r"\'", "'")
            .replace("\x00", "\\")
        )
        out.append(decoded)
    return out


# ----------------------------------------------------------------------
# java_enum
# ----------------------------------------------------------------------


_JAVA_ENUM_HEADER = re.compile(
    r"\b(?:public|private|protected)?\s*"  # access
    r"(?:static\s+)?"
    r"(?:strictfp\s+)?"
    r"enum\s+(?P<sym>[A-Za-z_$][A-Za-z0-9_$]*)\s*"
    r"(?:implements\s+[A-Za-z0-9_$,\s.<>]+)?"
    r"\{",
)

# enum value heads — identifier optionally followed by argument list (...)
# or annotation. We greedy-strip annotations + arg lists then read the bare
# identifier.
_ANNOTATION = re.compile(r"@[A-Za-z_$][A-Za-z0-9_$.]*(?:\s*\([^)]*\))?")
_JAVA_IDENT = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")


def parse_java_enum(src: str, symbol: str) -> list[str]:
    """Extract enum values from `public enum <symbol> { A, B, C }`.

    Handles:
      - trailing `;` followed by enum body methods
      - inline `// comment` after a value (stripped by strip_comments)
      - `@Deprecated` / other annotations on a value
      - per-value constructor args (e.g. `RED("red")`)
      - implements clauses
      - trailing comma before `;`
    """
    stripped = strip_comments(src)
    for m in _JAVA_ENUM_HEADER.finditer(stripped):
        if m.group("sym") != symbol:
            continue
        open_idx = m.end() - 1  # index of `{`
        body_start, body_end = extract_balanced(stripped, open_idx, "{", "}")
        body = stripped[body_start:body_end]
        # truncate body at first `;` outside any nested () — `;` marks end of
        # value list, start of methods.
        head = _split_at_top_level_semicolon(body)
        values: list[str] = []
        for part in _split_top_level_commas(head):
            # strip annotations
            without_anns = _ANNOTATION.sub(" ", part).strip()
            # strip per-value arg list `NAME(args)` → `NAME`
            paren = without_anns.find("(")
            if paren != -1:
                without_anns = without_anns[:paren].strip()
            # strip per-value body `NAME { ... }` (anonymous-class style)
            brace = without_anns.find("{")
            if brace != -1:
                without_anns = without_anns[:brace].strip()
            if not without_anns:
                # trailing comma case
                continue
            if not _JAVA_IDENT.match(without_anns):
                raise ParseError(
                    f"java_enum {symbol}: unexpected token in value position: {without_anns!r}"
                )
            values.append(without_anns)
        if not values:
            raise ParseError(f"java_enum {symbol}: empty value list")
        return values
    raise ParseError(f"java_enum {symbol}: declaration not found")


def _split_at_top_level_semicolon(body: str) -> str:
    depth_paren = 0
    depth_brace = 0
    for i, c in enumerate(body):
        if c == "(":
            depth_paren += 1
        elif c == ")":
            depth_paren -= 1
        elif c == "{":
            depth_brace += 1
        elif c == "}":
            depth_brace -= 1
        elif c == ";" and depth_paren == 0 and depth_brace == 0:
            return body[:i]
    return body


def _split_top_level_commas(text: str) -> list[str]:
    parts: list[str] = []
    depth_paren = 0
    depth_brace = 0
    last = 0
    for i, c in enumerate(text):
        if c == "(":
            depth_paren += 1
        elif c == ")":
            depth_paren -= 1
        elif c == "{":
            depth_brace += 1
        elif c == "}":
            depth_brace -= 1
        elif c == "," and depth_paren == 0 and depth_brace == 0:
            parts.append(text[last:i])
            last = i + 1
    parts.append(text[last:])
    return parts


# ----------------------------------------------------------------------
# java_set_of
# ----------------------------------------------------------------------


_SET_OF_HEADER = re.compile(
    r"\b(?:public|private|protected)?\s*"
    r"(?:static\s+)?"
    r"(?:final\s+)?"
    r"Set\s*<\s*String\s*>\s+"
    r"(?P<sym>[A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*"
    r"Set\s*\.\s*(?:<\s*String\s*>\s*)?of\s*\(",
)


def parse_java_set_of(src: str, symbol: str) -> list[str]:
    """Extract values from `public static final Set<String> <SYMBOL> = Set.of("A", "B", "C");`.

    Handles:
      - single-line and multi-line declarations
      - `Set.<String>of(...)` explicit type witness
      - trailing comma
      - argument list broken across multiple lines
    Rejects: a quoted literal with an unmatched embedded quote (ParseError).
    """
    stripped = strip_comments(src)
    for m in _SET_OF_HEADER.finditer(stripped):
        if m.group("sym") != symbol:
            continue
        open_idx = m.end() - 1  # `(`
        body_start, body_end = extract_balanced(stripped, open_idx, "(", ")")
        body = stripped[body_start:body_end]
        literals = extract_quoted_literals(body)
        if not literals:
            raise ParseError(f"java_set_of {symbol}: no quoted literals in Set.of(...) body")
        # The body MUST contain ONLY literal commas + whitespace between the
        # quoted args. If we find any other content (identifier, function call)
        # the source is not a literal-only Set.of and we refuse.
        residual = re.sub(_QUOTED, "", body)
        # acceptable residual chars: whitespace and commas
        if residual.strip(" \t\r\n,"):
            raise ParseError(
                f"java_set_of {symbol}: non-literal content in Set.of(...) body: "
                f"{residual.strip()!r}"
            )
        return literals
    raise ParseError(f"java_set_of {symbol}: declaration not found")


# ----------------------------------------------------------------------
# ts_const_tuple
# ----------------------------------------------------------------------


_TS_CONST_HEADER = re.compile(
    r"\b(?:export\s+)?const\s+"
    r"(?P<sym>[A-Za-z_$][A-Za-z0-9_$]*)"
    r"\s*(?::[^=]*)?"  # optional type annotation `: readonly Foo[]`
    r"\s*=\s*\[",
)


def parse_ts_const_tuple(src: str, symbol: str) -> list[str]:
    """Extract values from a TS `const <SYMBOL> = ['a', 'b', 'c'] as const;`.

    Handles:
      - bare `const` and `export const`
      - typed `const X: readonly Foo[] = [...]`
      - `as const`, `as const satisfies readonly Foo[]`
      - single, double, and back-tick (template) quotes
      - trailing comma
    Rejects: spread elements, computed values (any non-literal entry).
    """
    stripped = strip_comments(src)
    for m in _TS_CONST_HEADER.finditer(stripped):
        if m.group("sym") != symbol:
            continue
        open_idx = m.end() - 1  # `[`
        body_start, body_end = extract_balanced(stripped, open_idx, "[", "]")
        body = stripped[body_start:body_end]
        literals = _extract_ts_string_literals(body)
        if not literals:
            raise ParseError(f"ts_const_tuple {symbol}: no string literals in tuple body")
        residual = re.sub(
            r"""(?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`)""",
            "",
            body,
            flags=re.DOTALL,
        )
        if residual.strip(" \t\r\n,"):
            raise ParseError(
                f"ts_const_tuple {symbol}: non-literal entry in tuple body: "
                f"{residual.strip()!r}"
            )
        return literals
    raise ParseError(f"ts_const_tuple {symbol}: declaration not found")


def _extract_ts_string_literals(body: str) -> list[str]:
    """Extract every TS quoted literal (single/double/back-tick) from body, in order."""
    out: list[str] = []
    pattern = re.compile(
        r"""(?:"(?P<dq>(?:\\.|[^"\\])*)"|'(?P<sq>(?:\\.|[^'\\])*)'|`(?P<bq>(?:\\.|[^`\\])*)`)""",
        flags=re.DOTALL,
    )
    for m in pattern.finditer(body):
        raw = m.group("dq")
        if raw is None:
            raw = m.group("sq")
        if raw is None:
            raw = m.group("bq")
        decoded = (
            raw.replace(r"\\", "\x00")
            .replace(r"\n", "\n")
            .replace(r"\t", "\t")
            .replace(r"\r", "\r")
            .replace(r"\"", '"')
            .replace(r"\'", "'")
            .replace(r"\`", "`")
            .replace("\x00", "\\")
        )
        out.append(decoded)
    return out


# ----------------------------------------------------------------------
# ts_union_type
# ----------------------------------------------------------------------


_TS_UNION_HEADER = re.compile(
    r"\b(?:export\s+)?type\s+"
    r"(?P<sym>[A-Za-z_$][A-Za-z0-9_$]*)"
    r"\s*=\s*",
)


def parse_ts_union_type(src: str, symbol: str) -> list[str]:
    """Extract values from `type <SYMBOL> = 'A' | 'B' | 'C';`.

    Handles:
      - single-line and multi-line declarations
      - `export type` and bare `type`
      - leading `|` on a multi-line union
    Rejects: any non-literal in the union (e.g. `string`, a referenced type alias).
    """
    stripped = strip_comments(src)
    for m in _TS_UNION_HEADER.finditer(stripped):
        if m.group("sym") != symbol:
            continue
        body_start = m.end()
        # consume until top-level `;`
        end = _find_top_level_semicolon(stripped, body_start)
        if end == -1:
            raise ParseError(f"ts_union_type {symbol}: unterminated declaration (no `;`)")
        body = stripped[body_start:end]
        literals = _extract_ts_string_literals(body)
        if not literals:
            raise ParseError(
                f"ts_union_type {symbol}: no string literals in union (is it a non-literal type?)"
            )
        # residual must contain only `|`, whitespace, and a possibly-leading `|`
        residual = re.sub(
            r"""(?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`)""",
            "",
            body,
            flags=re.DOTALL,
        )
        if residual.strip(" \t\r\n|"):
            raise ParseError(
                f"ts_union_type {symbol}: non-literal token(s) in union: {residual.strip()!r}"
            )
        return literals
    raise ParseError(f"ts_union_type {symbol}: declaration not found")


def _find_top_level_semicolon(src: str, start: int) -> int:
    depth_paren = 0
    depth_brace = 0
    depth_bracket = 0
    i = start
    n = len(src)
    while i < n:
        c = src[i]
        if c in ('"', "'", "`"):
            quote = c
            i += 1
            while i < n:
                cc = src[i]
                if cc == "\\" and i + 1 < n:
                    i += 2
                    continue
                if cc == quote:
                    i += 1
                    break
                i += 1
            continue
        if c == "(":
            depth_paren += 1
        elif c == ")":
            depth_paren -= 1
        elif c == "{":
            depth_brace += 1
        elif c == "}":
            depth_brace -= 1
        elif c == "[":
            depth_bracket += 1
        elif c == "]":
            depth_bracket -= 1
        elif c == ";" and depth_paren == 0 and depth_brace == 0 and depth_bracket == 0:
            return i
        # newline also terminates the search if we're already at the end
        # of the statement-like region. We allow multi-line unions, so
        # treat newline as a separator only if everything is balanced AND
        # the next non-whitespace token starts a new statement. Too
        # aggressive; just rely on `;`.
        i += 1
    return -1


# ----------------------------------------------------------------------
# java_grid_column_case_literals
# ----------------------------------------------------------------------


def parse_java_grid_column_case_literals(
    src: str,
    symbol: str,
    *,
    anchor: str,
) -> list[str]:
    """Narrow strategy: locate the `anchor` substring (e.g.
    `new GridColumn("prohibited_status",`) in the Java source, then read the
    next quoted SQL expression literal that follows. Inside that SQL string,
    extract the quoted literals from a flat `CASE WHEN ... THEN '<X>' ELSE '<Y>' END`.

    Refuses:
      - anchor not found
      - SQL expression literal not found
      - multiple WHEN/THEN clauses (a non-flat CASE)
      - nested CASE
      - any shape not matching CASE WHEN ... THEN ... ELSE ... END
    """
    if not anchor:
        raise ParseError(
            f"java_grid_column_case_literals {symbol}: anchor is required (spec validation should have caught this)"
        )
    stripped = strip_comments(src)
    pos = stripped.find(anchor)
    if pos == -1:
        raise ParseError(
            f"java_grid_column_case_literals {symbol}: anchor not found: {anchor!r}"
        )
    # Read the next double-quoted Java string literal AFTER the anchor.
    scan_from = pos + len(anchor)
    string_match = re.search(
        r'"(?P<sql>(?:\\.|[^"\\])*)"',
        stripped[scan_from:],
        flags=re.DOTALL,
    )
    if not string_match:
        raise ParseError(
            f"java_grid_column_case_literals {symbol}: no quoted SQL literal after anchor"
        )
    sql = string_match.group("sql")
    # Decode minimal Java string escapes
    sql_decoded = (
        sql.replace(r"\\", "\x00")
        .replace(r"\n", "\n")
        .replace(r"\t", "\t")
        .replace(r"\"", '"')
        .replace("\x00", "\\")
    )
    return _extract_case_when_then_else_literals(sql_decoded, symbol=symbol)


_CASE_FLAT_RE = re.compile(
    r"""
    \bCASE\b\s+
    WHEN\s+.+?\s+
    THEN\s+'(?P<then>[^']*)'\s+
    ELSE\s+'(?P<els>[^']*)'\s+
    END\b
    """,
    flags=re.IGNORECASE | re.VERBOSE | re.DOTALL,
)


def _extract_case_when_then_else_literals(sql: str, *, symbol: str) -> list[str]:
    # count CASE occurrences — a nested CASE is unsupported
    case_count = len(re.findall(r"\bCASE\b", sql, flags=re.IGNORECASE))
    when_count = len(re.findall(r"\bWHEN\b", sql, flags=re.IGNORECASE))
    if case_count != 1:
        raise ParseError(
            f"java_grid_column_case_literals {symbol}: expected exactly one CASE, "
            f"found {case_count}"
        )
    if when_count != 1:
        raise ParseError(
            f"java_grid_column_case_literals {symbol}: expected exactly one WHEN, "
            f"found {when_count}"
        )
    m = _CASE_FLAT_RE.search(sql)
    if not m:
        raise ParseError(
            f"java_grid_column_case_literals {symbol}: CASE shape does not match "
            f"flat CASE WHEN <cond> THEN '<X>' ELSE '<Y>' END"
        )
    return [m.group("then"), m.group("els")]


# ----------------------------------------------------------------------
# Dispatcher
# ----------------------------------------------------------------------


KNOWN_STRATEGIES: dict[str, Callable[..., list[str]]] = {
    "java_enum": parse_java_enum,
    "java_set_of": parse_java_set_of,
    "ts_const_tuple": parse_ts_const_tuple,
    "ts_union_type": parse_ts_union_type,
    "java_grid_column_case_literals": parse_java_grid_column_case_literals,
}


def parse(kind: str, src: str, symbol: str, *, anchor: str | None = None) -> list[str]:
    """Dispatch to the strategy named `kind`. Unknown kinds raise ParseError
    (caller maps to exit 2). The `anchor` arg is required when kind is
    `java_grid_column_case_literals`; spec_validator ensures this at parse
    of the spec YAML so it should never reach here otherwise.
    """
    fn = KNOWN_STRATEGIES.get(kind)
    if fn is None:
        raise ParseError(f"unknown parser strategy: {kind!r}")
    if kind == "java_grid_column_case_literals":
        return fn(src, symbol, anchor=anchor or "")
    return fn(src, symbol)
