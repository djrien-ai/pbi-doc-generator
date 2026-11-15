"""
Readable SQL pretty-formatter for native queries extracted from Power Query (M).

- SQL that already has a hand-written multi-line layout with `--` comments is preserved: it is dedented,
  trailing whitespace is trimmed, and runs of blank lines are collapsed.
- SQL crammed onto one or a few long lines is reflowed: one clause per line, one select-list item per line,
  AND/OR conditions and JOINs on their own lines, CASE expressions and subqueries cleanly indented.
- Parameter placeholders such as `{{PARAM_YEAR}}` are preserved intact.
"""

from __future__ import annotations

import re
import textwrap

_TOKEN_RE = re.compile(
    r"""
    (?P<ws>\s+)
  | (?P<comment>--[^\n]*|/\*.*?\*/)
  | (?P<ph>\{\{.*?\}\})
  | (?P<str>'(?:[^']|'')*')
  | (?P<qid>"(?:[^"]|"")*"|\[[^\]]*\]|`[^`]*`)
  | (?P<num>\d+(?:\.\d+)?)
  | (?P<word>[A-Za-z_][\w$#@]*(?:\.[A-Za-z_*][\w$#@]*)*(?:\.\*)?)
  | (?P<op><>|!=|<=|>=|\|\||::|[-+*/%=<>,;().])
  | (?P<other>.)
    """,
    re.S | re.X,
)

_KEYWORDS = {
    "select", "distinct", "top", "from", "where", "group", "by", "order", "having", "limit", "offset", "qualify",
    "union", "all", "intersect", "except", "minus", "with", "as", "on", "and", "or", "not", "in", "is", "null",
    "like", "between", "exists", "case", "when", "then", "else", "end", "join", "inner", "left", "right", "full",
    "outer", "cross", "lateral", "apply", "asc", "desc", "over", "partition", "rows", "range", "preceding",
    "following", "unbounded", "current", "row", "cast", "into", "values", "insert", "update", "delete", "set",
    "nulls", "first", "last", "within", "filter", "using", "natural", "true", "false", "interval",
}
_CLAUSES = {
    "select", "from", "where", "having", "limit", "offset", "qualify",
    "union", "intersect", "except", "minus", "with", "values", "set",
}
_JOIN_START = {"join", "inner", "left", "right", "full", "cross", "natural"}
_LIST_CLAUSES = {"select", "group by", "order by", "set", "with"}
_NO_CALL = {
    "AND", "OR", "IN", "ON", "NOT", "WHERE", "WHEN", "THEN", "ELSE", "EXISTS", "IS",
    "SELECT", "FROM", "AS", "JOIN", "BY", "HAVING", "OVER", "VALUES", "USING", "CASE",
    ",", "=", "<", ">", "<>", "<=", ">=", "+", "-", "*", "/",
}


def _needs_reflow(sql: str) -> bool:
    lines = [l for l in sql.splitlines() if l.strip()]
    if not lines:
        return False
    longest = max(len(l) for l in lines)
    return len(lines) <= 2 or longest > 220 or (len(sql) / max(1, len(lines)) > 160)


def _tidy(sql: str) -> str:
    text = sql.replace("\r\n", "\n").replace("\r", "\n").expandtabs(4)
    lines = [l.rstrip() for l in text.split("\n")]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    if len(lines) > 1:
        rest = textwrap.dedent("\n".join(lines[1:])).split("\n")
        lines = [lines[0].strip()] + rest
    out, blank = [], 0
    for l in lines:
        blank = blank + 1 if not l.strip() else 0
        if blank <= 1:
            out.append(l)
    return "\n".join(out)


def _between_pending(tokens: list[tuple[str, str]], i: int) -> bool:
    """True when this AND belongs to `BETWEEN x AND y` (keep it on the same line)."""
    j, steps = i - 1, 0
    while j >= 0 and steps < 6:
        low = tokens[j][1].lower()
        if low == "between":
            return True
        if low in ("and", "or", "where", "on", "having"):
            return False
        j -= 1
        steps += 1
    return False


def _join(tokens: list[str]) -> str:
    out, prev = "", ""
    for t in tokens:
        if not out:
            out = t
        elif t in (",", ")", ";", ".") or prev in ("(", "."):
            out += t
        elif t == "(" and prev.upper() not in _NO_CALL and re.match(r'[\w\]"`]', prev[-1:]):
            out += t
        else:
            out += " " + t
        prev = t
    return out


def format_sql(sql: str, indent: str = "    ") -> str:
    """Return a clean, readable version of `sql`."""
    if not sql or not sql.strip():
        return ""
    if not _needs_reflow(sql) or ("--" in sql and "\n" in sql.strip()):
        return _tidy(sql)

    tokens = [(m.lastgroup or "other", m.group()) for m in _TOKEN_RE.finditer(sql.strip()) if m.lastgroup != "ws"]
    lines: list[str] = []
    cur: list[str] = []
    state = {"ind": 0}
    level = 0
    paren_stack: list[tuple[str, int]] = []
    case_base: list[int] = []
    clause = ""

    def emit(next_ind: int) -> None:
        nonlocal cur
        if cur:
            lines.append(indent * state["ind"] + _join(cur))
        cur = []
        state["ind"] = next_ind

    i = 0
    while i < len(tokens):
        kind, val = tokens[i]
        low = val.lower()
        nxt = tokens[i + 1][1].lower() if i + 1 < len(tokens) else ""
        in_fn = any(p[0] == "fn" for p in paren_stack)
        if kind == "word" and low in _KEYWORDS:
            val = val.upper()

        if kind == "comment":
            emit(state["ind"])
            lines.append(indent * state["ind"] + val.strip())
            i += 1
            continue

        if kind == "word" and not in_fn and not case_base:
            two = f"{low} {nxt}"
            if two in ("group by", "order by", "union all") or low in _CLAUSES:
                emit(level)
                if two in ("group by", "order by", "union all"):
                    clause = two
                    cur = [val, tokens[i + 1][1].upper()]
                    i += 2
                else:
                    clause = low
                    cur = [val]
                    i += 1
                    if low == "select":
                        while i < len(tokens) and tokens[i][1].lower() in ("distinct", "top"):
                            cur.append(tokens[i][1].upper())
                            if tokens[i][1].lower() == "top" and i + 1 < len(tokens):
                                i += 1
                                cur.append(tokens[i][1])
                            i += 1
                set_op = clause.startswith("union") or clause in ("intersect", "except", "minus")
                emit(level if set_op else level + 1)
                continue
            if low in _JOIN_START and (low == "join" or "join" in [t[1].lower() for t in tokens[i : i + 4]]):
                emit(level + 1)
                clause = "join"
                while i < len(tokens) and tokens[i][1].lower() != "join":
                    cur.append(tokens[i][1].upper())
                    i += 1
                cur.append("JOIN")
                i += 1
                continue
            if low == "on" and clause == "join":
                emit(level + 2)
                cur = [val]
                i += 1
                continue
            if low in ("and", "or") and clause in ("where", "having", "join", "qualify") and not _between_pending(tokens, i):
                emit(level + (2 if clause == "join" else 1))
                cur = [val]
                i += 1
                continue

        if kind == "word" and low == "case":
            case_base.append(state["ind"])
            cur.append(val)
            i += 1
            continue
        if kind == "word" and low in ("when", "else") and case_base:
            emit(case_base[-1] + 1)
            cur = [val]
            i += 1
            continue
        if kind == "word" and low == "end" and case_base:
            emit(case_base[-1])
            case_base.pop()
            cur = [val]
            i += 1
            continue

        if val == "(":
            if nxt in ("select", "with"):
                cur.append("(")
                paren_stack.append(("sub", level))
                level = state["ind"] + 1
                emit(level)
                clause = ""
            else:
                paren_stack.append(("fn", level))
                cur.append("(")
            i += 1
            continue
        if val == ")":
            kind_p, prev_level = paren_stack.pop() if paren_stack else ("fn", level)
            if kind_p == "sub":
                emit(max(0, level - 1))
                level = prev_level
                cur = [")"]
                clause = "from"
            else:
                cur.append(")")
            i += 1
            continue
        if val == "," and not in_fn and not case_base and clause in _LIST_CLAUSES:
            cur.append(",")
            emit(level + 1)
            i += 1
            continue
        if val == ";":
            cur.append(";")
            emit(0)
            lines.append("")
            clause = ""
            level = 0
            i += 1
            continue
        cur.append(val)
        i += 1

    emit(0)
    text = "\n".join(lines).strip()
    return re.sub(r"\n{3,}", "\n\n", text)
