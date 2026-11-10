"""Plain-words learning: how an answer was made, step by step, with the row count at each step.

The counts come from small read-only queries built from the saved SQL (memoized per file version,
2 s cap, like the audit). A query too complex to retell (WITH, UNION, subqueries in FROM) gets the
result line only, and the SQL lesson stays one command away.
"""

import re

from . import audit, engine, learning

_AGG = (("sum", "added up {}"), ("avg", "averaged {}"), ("min", "took the smallest {}"),
        ("max", "took the largest {}"), ("median", "took the middle {}"))
_TIME = ((r"strftime\(\s*\"?(\w+)\"?\s*,\s*'%Y-%m'", "month of {}"), (r"date_trunc\(\s*'month'\s*,\s*\"?(\w+)", "month of {}"),
         (r"date_trunc\(\s*'year'\s*,\s*\"?(\w+)", "year of {}"), (r"\byear\(\s*\"?(\w+)", "year of {}"),
         (r"\bdayname\(\s*\"?(\w+)", "weekday of {}"), (r"\bhour\(\s*\"?(\w+)", "hour of {}"),
         (r"\bfloor\(\s*\"?(\w+)\"?\s*/\s*(\d+(?:\.\d+)?)", "{} in steps of {}"))


def split_list(select):
    """The items of a SELECT list, split on top-level commas."""
    body = re.sub(r"^SELECT\s+(DISTINCT\s+)?", "", select, flags=re.I)
    items, depth, cur = [], 0, ""
    for ch in body:
        depth += ch == "("
        depth -= ch == ")"
        if ch == "," and depth == 0:
            items.append(cur.strip())
            cur = ""
        else:
            cur += ch
    return [i for i in items + [cur.strip()] if i]


def _alias(item):
    m = re.search(r"\s+AS\s+\"?(\w+)\"?\s*$", item, re.I)
    return m.group(1) if m else None


def describe(item):
    """Plain words for one SELECT item that computes something; None for a plain column."""
    words = []
    if re.search(r"\bcount\s*\(\s*\*\s*\)", item, re.I):
        words.append("counted rows")
    elif m := re.search(r"\bcount\s*\(\s*DISTINCT\s+\"?(\w+)", item, re.I):
        words.append(f"counted different {m.group(1)} values")
    elif m := re.search(r"\bcount\s*\(\s*\"?(\w+)", item, re.I):
        words.append(f"counted rows that have a {m.group(1)}")
    if m := re.search(r"\bcount_if\s*\(([^)]*)\)", item, re.I):
        words.append(f"counted rows where {m.group(1).strip()}")
    for fn, text in _AGG:
        if m := re.search(rf"\b{fn}\s*\(\s*\"?(\w+)", item, re.I):
            words.append(text.format(m.group(1)))
    for m in re.finditer(r"([*/])\s*(\d+(?:\.\d+)?)\b", item):
        words.append(("divided by " if m.group(1) == "/" else "multiplied by ") + m.group(2))
    if m := re.search(r"\bround\s*\(.*,\s*(\d+)\s*\)", item, re.I):
        words.append(f"rounded to {m.group(1)} decimals")
    return ", then ".join(words) or None


def _label(item):
    for pattern, text in _TIME:
        if m := re.search(pattern, item, re.I):
            return text.format(*m.groups())
    return _alias(item) or item.strip('"')


def _fmt(v):
    if isinstance(v, float):
        return f"{v:,.2f}"
    if isinstance(v, int):
        return f"{v:,}"
    return str(v)


def steps(q, eng):
    """Numbered plain-words steps and a result line, as a list of strings."""
    parts = learning.clauses(q["sql"])
    names = [n for n, _ in parts]
    clause = dict(parts)
    lines = []
    frm = clause.get("FROM") or ""
    simple = audit._SIMPLE_FROM.match(frm) if "WITH" not in names and "UNION" not in " ".join(names) else None
    joined = audit._JOIN.match(frm) if not simple and "WITH" not in names else None
    select_items = split_list(clause.get("SELECT", ""))
    if simple or joined:
        table = (simple or joined).group(1)
        total = audit._value(eng, f"SELECT count(*) FROM {table}")
        if total is not None:
            lines.append(f"Started with {total:,} rows in {table.strip(chr(34))}")
        if joined:
            key = joined.group(5) or joined.group(7)
            lines.append(f"Matched each row with {joined.group(3).strip(chr(34))} on {key}")
        where = clause.get("WHERE")
        if where:
            cond = where[len("WHERE"):].strip()
            kept = audit._value(eng, f"SELECT count(*) {frm} WHERE {cond}")
            left = f" (left out {total - kept:,})" if kept is not None and total is not None and total > kept else ""
            count = f": {kept:,} rows{left}" if kept is not None else ""
            lines.append(f"Kept rows where {audit._plain(cond)}{count}")
        group = clause.get("GROUP BY")
        if group:
            keys = [k.strip() for k in group[len("GROUP BY"):].split(",")]
            labels = [_label(select_items[int(k) - 1]) if k.isdigit() and int(k) <= len(select_items) else _label(k) for k in keys]
            core = " ".join(t for n, t in parts if n not in ("ORDER BY", "LIMIT"))
            groups = audit._value(eng, f"SELECT count(*) FROM ({core})")
            lines.append(f"Made one group per {' and '.join(labels)}" + (f": {groups:,} groups" if groups is not None else ""))
        for item in select_items:
            text = describe(item)
            if text:
                name = _alias(item)
                lead = "For each group, worked out" if group else "Worked out"
                lines.append(f"{lead} {name + ': ' if name else ''}{text}")
        order = clause.get("ORDER BY")
        if order:
            body = order[len("ORDER BY"):].strip()
            first = body.split(",")[0].strip()
            key = re.sub(r"\s+(ASC|DESC)(\s+NULLS\s+(FIRST|LAST))?\s*$", "", first, flags=re.I).strip()
            col = key
            if key.isdigit() and int(key) <= len(select_items):
                col = _alias(select_items[int(key) - 1]) or key
            else:  # an expression that a SELECT item computes: use that item's name
                flat = lambda t: re.sub(r"\s+", "", t).lower()
                for item in select_items:
                    expr = re.sub(r"\s+AS\s+\"?\w+\"?\s*$", "", item, flags=re.I)
                    if _alias(item) and flat(key) in flat(expr):
                        col = _alias(item)
                        break
                else:
                    col = describe(key) or key
            col = col.strip(chr(34))
            down = bool(re.search(r"DESC", first, re.I))
            i = q["columns"].index(col) if col in q["columns"] else None
            if i is not None and q["rows"] and isinstance(q["rows"][0][i], str):  # names sort A to Z, not low to high
                lines.append(f"Sorted by {col}, {'Z to A' if down else 'A to Z'}")
            else:
                lines.append(f"Sorted from {'highest' if down else 'lowest'} {col}")
        limit = clause.get("LIMIT")
        if limit and re.match(r"LIMIT\s+\d+$", limit, re.I):
            n = int(limit.split()[1])
            lines.append(f"Kept the {'top' if order else 'first'} {n}" if n > 1 else f"Kept the {'top' if order else 'first'} one")
    out = [f"{i}. {line}" for i, line in enumerate(lines, 1)]
    result = _result(q, eng, parts)
    if result:
        out.append(result)
    return out


def _sort_column(order, cols, nums):
    """Index of the number column the first ORDER BY key names (by position or by name), else None."""
    m = re.match(r"ORDER\s+BY\s+(\"[^\"]+\"|[\w.]+)", order, re.I)
    if not m:
        return None
    key = m.group(1).strip('"')
    if key.isdigit():
        i = int(key) - 1
        return i if i in nums else None
    return next((i for i in nums if cols[i].lower() == key.split(".")[-1].lower()), None)


def _result(q, eng, parts):
    rows, cols = q["rows"], q["columns"]
    if not rows:
        return "Result: no rows matched."
    nums = [i for i, v in enumerate(rows[0]) if isinstance(v, (int, float)) and not isinstance(v, bool)]
    labels = [i for i in range(len(cols)) if i not in nums]
    if len(rows) == 1 and not labels:
        return "Result: " + ", ".join(f"{c} {_fmt(v)}" for c, v in zip(cols, rows[0]))
    names = [n for n, _ in parts]
    if not nums or not labels:
        return f"Result: {len(rows):,} rows."
    li, vi = labels[0], nums[0]  # the first measure, unless the rows are sorted by another one
    key = _sort_column(dict(parts).get("ORDER BY", ""), cols, nums)  # compare on the column the rows are sorted by
    if key is not None:
        vi = key
    top = rows[0]
    line = f"Result: {top[li]}, {cols[vi]} {_fmt(top[vi])}"
    second = rows[1] if len(rows) > 1 else None
    if second is None and "ORDER BY" in names and "LIMIT" in names:
        core = " ".join(t for n, t in parts if n != "LIMIT")
        found = audit._rows(eng, f"{core} LIMIT 2")
        second = found[1] if found and len(found) > 1 else None
    if second is not None and key is not None:
        a, b = top[vi], second[vi]
        if a == b:
            line += f"; the same as {second[li]}"
        elif isinstance(a, (int, float)) and isinstance(b, (int, float)) and b:
            pct = (a - b) / abs(b) * 100
            word = "more" if pct >= 0 else "less"
            line += f"; {abs(pct):.1f}% {word} than {second[li]} ({_fmt(b)})"
    elif len(rows) > 1:
        line = f"Result: {len(rows):,} rows; first is " + line[len("Result: "):]
    return line


def card(q, eng, better=None):
    """The plain-words learning card shown under an answer."""
    lines = steps(q, eng)
    if not lines:
        return ""
    text = "\n\n---\nLearning mode: how this answer was made\n" + "\n".join(lines)
    if better:
        text += f"\nAsk next: {better}"
    return text + f"\nSee each step next to its SQL: /grimoire explain {q['id']}"
