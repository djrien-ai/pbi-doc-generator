"""
Small, dependency-free Power Query (M) scanner.

Understands strings ("" escapes), quoted identifiers (#"..."), comments and bracket nesting well
enough to: split `let ... in` into steps (with exact character offsets), split function arguments,
and pull native SQL out of `Query = ...` options and `Value.NativeQuery(...)`, including SQL that is
assembled with `&` from text pieces and parameters.
"""

from __future__ import annotations

import re

from .dataflows import decode_m_escapes

_OPEN = "([{"
_CLOSE = ")]}"
_WORD_RE = re.compile(r"[A-Za-z_][\w.]*")


def _skip_string(s: str, i: int) -> int:
    """`s[i]` is a double quote; return index after the closing quote."""
    j = i + 1
    n = len(s)
    while j < n:
        if s[j] == '"':
            if j + 1 < n and s[j + 1] == '"':
                j += 2
                continue
            return j + 1
        j += 1
    return n


def _skip_comment(s: str, i: int) -> int:
    if s.startswith("//", i):
        j = s.find("\n", i)
        return len(s) if j < 0 else j
    if s.startswith("/*", i):
        j = s.find("*/", i + 2)
        return len(s) if j < 0 else j + 2
    return i


def iter_top_level(s: str, start: int = 0, end: int | None = None):
    """Yield `(index, char, depth)` for characters outside strings/comments."""
    end = len(s) if end is None else end
    depth = 0
    i = start
    while i < end:
        ch = s[i]
        if ch == '"':
            i = _skip_string(s, i)
            continue
        if ch == "#" and s.startswith('#"', i):
            i = _skip_string(s, i + 1)
            continue
        if ch == "/" and (s.startswith("//", i) or s.startswith("/*", i)):
            i = _skip_comment(s, i)
            continue
        if ch in _OPEN:
            yield i, ch, depth
            depth += 1
            i += 1
            continue
        if ch in _CLOSE:
            depth -= 1
            yield i, ch, depth
            i += 1
            continue
        yield i, ch, depth
        i += 1


def split_top_level(s: str, sep: str = ",") -> list[str]:
    parts, last = [], 0
    for i, ch, depth in iter_top_level(s):
        if ch == sep and depth == 0:
            parts.append(s[last:i])
            last = i + 1
    parts.append(s[last:])
    return [p.strip() for p in parts if p.strip()] if any(p.strip() for p in parts) else []


def matching_close(s: str, open_idx: int) -> int:
    """Index of the bracket closing the one at `open_idx` (or len(s))."""
    target = None
    for i, ch, depth in iter_top_level(s, open_idx):
        if i == open_idx:
            target = depth
            continue
        if ch in _CLOSE and depth == target:
            return i
    return len(s)


def call_args(expr: str) -> tuple[str, list[str]] | None:
    """`Table.SelectRows(x, each ...)` -> ("Table.SelectRows", ["x", "each ..."])."""
    m = re.match(r"\s*([A-Za-z_][\w]*(?:\.[A-Za-z_][\w]*)+)\s*\(", expr)
    if not m:
        return None
    open_idx = m.end() - 1
    close = matching_close(expr, open_idx)
    return m.group(1), split_top_level(expr[open_idx + 1 : close])


def string_literals(expr: str) -> list[str]:
    return [m.group(1).replace('""', '"') for m in re.finditer(r'(?<!#)"((?:[^"]|"")*)"', expr or "")]


def unquote_ident(name: str) -> str:
    name = (name or "").strip()
    if name.startswith('#"') and name.endswith('"'):
        return name[2:-1].replace('""', '"')
    return name


# ---------------------------------------------------------------------------
# let ... in  -> steps
# ---------------------------------------------------------------------------
def _is_kw(s: str, i: int, kw: str) -> bool:
    if not s.startswith(kw, i):
        return False
    before = s[i - 1] if i > 0 else " "
    after = s[i + len(kw)] if i + len(kw) < len(s) else " "
    return not (before.isalnum() or before in "_.#\"") and not (after.isalnum() or after in "_.")


def parse_let_steps(code: str) -> tuple[list[dict], str]:
    """Return (`[{name, expr, start, end}]`, final_expression). Offsets index into `code`."""
    s = code or ""
    let_idx = None
    for i, ch, depth in iter_top_level(s):
        if depth == 0 and ch == "l" and _is_kw(s, i, "let"):
            let_idx = i
            break
        if depth == 0 and not ch.isspace():
            break  # expression does not start with `let`
    if let_idx is None:
        return [], s.strip()

    steps: list[dict] = []
    seg_start = let_idx + 3
    nested_let = 0
    in_idx = None
    for i, ch, depth in iter_top_level(s, let_idx + 3):
        if depth != 0:
            continue
        if ch == "l" and _is_kw(s, i, "let"):
            nested_let += 1
        elif ch == "i" and _is_kw(s, i, "in"):
            if nested_let:
                nested_let -= 1
                continue
            in_idx = i
            steps.append((seg_start, i))
            break
        elif ch == "," and not nested_let:
            steps.append((seg_start, i))
            seg_start = i + 1
    out: list[dict] = []
    for a, b in steps:
        # Skip whitespace and comments placed above the step (`// 1. Get the current year`)
        while a < b:
            if s[a].isspace():
                a += 1
            elif s.startswith("//", a) or s.startswith("/*", a):
                a = min(b, _skip_comment(s, a))
            else:
                break
        seg = s[a:b]
        m = re.match(r'\s*(#"(?:[^"]|"")*"|[A-Za-z_][\w.]*)\s*=(?!=)\s*', seg)
        if not m:
            continue
        lead = len(seg) - len(seg.lstrip())
        out.append(
            {
                "name": unquote_ident(m.group(1)),
                "expr": seg[m.end() :].strip(),
                "start": a + lead,
                "end": a + len(seg.rstrip()),
            }
        )
    final = s[in_idx + 2 :].strip() if in_idx is not None else ""
    return out, final


# ---------------------------------------------------------------------------
# Native SQL extraction
# ---------------------------------------------------------------------------
def _read_value(s: str, i: int) -> tuple[str, int]:
    """Read an M expression starting at `i` until a top-level `,` `]` or `)`. Returns (text, end)."""
    depth = 0
    j = i
    n = len(s)
    while j < n:
        ch = s[j]
        if ch == '"':
            j = _skip_string(s, j)
            continue
        if ch == "#" and s.startswith('#"', j):
            j = _skip_string(s, j + 1)
            continue
        if ch == "/" and (s.startswith("//", j) or s.startswith("/*", j)):
            j = _skip_comment(s, j)
            continue
        if ch in _OPEN:
            depth += 1
        elif ch in _CLOSE:
            if depth == 0:
                break
            depth -= 1
        elif ch == "," and depth == 0:
            break
        j += 1
    return s[i:j], j


def _placeholder(piece: str) -> str:
    p = piece.strip()
    m = re.fullmatch(r"(?:Text\.From|Number\.ToText|Date\.ToText|DateTime\.ToText|Text\.Combine)\s*\((.*)\)", p, re.S)
    inner = m.group(1).split(",")[0].strip() if m else p
    return "{{" + unquote_ident(re.sub(r"\s+", " ", inner))[:80] + "}}"


def concat_to_sql(expr: str, steps: dict[str, str] | None = None, _depth: int = 0) -> tuple[str, list[str]]:
    """Turn `"SELECT ..." & PARAM & "..."` into SQL text with `{{PARAM}}` placeholders.

    Pieces that name another `let` step holding text (e.g. `SqlQuery = "SELECT ..."`) are inlined.
    """
    steps = steps or {}
    pieces = split_top_level(expr, "&")
    out, params = [], []
    for p in pieces:
        p = p.strip()
        ref = unquote_ident(p)
        if ref in steps and _depth < 4 and steps[ref].lstrip().startswith('"'):
            sub_sql, sub_params = concat_to_sql(steps[ref], steps, _depth + 1)
            out.append(sub_sql)
            params.extend(sub_params)
            continue
        if re.fullmatch(r'"(?:[^"]|"")*"', p, re.S):
            out.append(decode_m_escapes(p[1:-1].replace('""', '"')))
        else:
            ph = _placeholder(p)
            params.append(ph[2:-2])
            out.append(ph)
    return "".join(out), params


def extract_native_sql(code: str) -> list[dict]:
    """Find native SQL in M: `[Query = ...]` options, `Value.NativeQuery(src, sql, ...)`, `Odbc.Query(conn, sql)`."""
    s = code or ""
    found: list[dict] = []
    seen = set()

    step_exprs = {st["name"]: st["expr"] for st in parse_let_steps(s)[0]}

    def _add(expr: str, pos: int, via: str) -> None:
        sql, params = concat_to_sql(expr, step_exprs)
        sql = sql.strip()
        if not sql or not re.search(r"(?i)\b(select|with|exec|call|from)\b", sql):
            return
        key = sql
        if key in seen:
            return
        seen.add(key)
        found.append({"sql": sql, "pos": pos, "via": via, "parameters": params})

    for i, ch, depth in iter_top_level(s):
        if ch == "Q" and s.startswith("Query", i) and (i == 0 or not (s[i - 1].isalnum() or s[i - 1] in "_.")):
            m = re.match(r"Query\s*=\s*", s[i:])
            if m:
                expr, _ = _read_value(s, i + m.end())
                if expr.lstrip().startswith('"') or unquote_ident(split_top_level(expr, "&")[0] if expr.strip() else "") in step_exprs:
                    _add(expr, i, "Query option")
        elif ch in "VO" and (s.startswith("Value.NativeQuery", i) or s.startswith("Odbc.Query", i) or s.startswith("OleDb.Query", i)):
            fn_m = re.match(r"(Value\.NativeQuery|Odbc\.Query|OleDb\.Query)\s*\(", s[i:])
            if fn_m:
                open_idx = i + fn_m.end() - 1
                args = split_top_level(s[open_idx + 1 : matching_close(s, open_idx)])
                if len(args) >= 2:
                    _add(args[1], i, fn_m.group(1))
    return found
