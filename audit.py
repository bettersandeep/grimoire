"""Check the queries behind an answer: the filters they assume, common analysis pitfalls, and a verdict.

Plain code over the saved SQL and a few small read-only count queries; no model call.
Each check is best effort: if it cannot tell, it says nothing rather than guess.
"""

import calendar
import datetime
import re

from . import engine, learning, sqltree

AUDIT_TIMEOUT_S = 2  # per extra query; a slow check is skipped, the reply is never held up long
MAX_QUERIES = 3      # audit at most the last 3 cited queries

# a result column named like a rate: pct, conversion_rate, churn_ratio (not "separate" or "duration")
_RATE_NAME = re.compile(r"(?:^|[^a-z])(?:pct|percent[a-z]*|share|rate|ratio)(?:$|[^a-z])", re.I)


def _clause(parts, name):
    return next((text for n, text in parts if n == name), None)


_memo = {}  # (sql, files as opened) -> value; a changed file changes the key, so nothing goes stale


def _rows(eng, sql):
    """Rows of a small read-only query, remembered per file version; None when it fails or is slow."""
    if not sql:
        return None
    key = (sql, tuple(sorted((eng._opened or {}).items())))
    if key not in _memo:
        try:
            _memo[key] = eng.query(sql, AUDIT_TIMEOUT_S)[1]
        except engine.EngineError:
            _memo[key] = None  # also remembered: a count that is too slow is not tried again on every reply
        if len(_memo) > 512:
            _memo.pop(next(iter(_memo)))
    return _memo[key]


def _value(eng, sql):
    """First cell of a small read-only query; None when it fails or is slow."""
    rows = _rows(eng, sql)
    return rows[0][0] if rows else None


def _plain(cond):
    """A WHERE condition in plain words, for the common shapes; else the condition as written, shortened."""
    tree = sqltree.parse(f"SELECT 1 WHERE {cond}")
    where = tree.where if tree else None
    if where and where.get("type") == "COMPARE_IN":  # CAST(region AS VARCHAR) IN ('North', 'South'), as grimoire_compare writes it
        first, *rest = where["children"]
        name, values = sqltree.column(first.get("child", first)), [sqltree.constant(v) for v in rest]
        if name and all(isinstance(v, str) for v in values):
            return f"{name} is " + " or ".join(values)
    pieces = where["children"] if where and where.get("type") == "CONJUNCTION_AND" else [where] if where else []
    empty = [sqltree.column(p["children"][0]) for p in pieces if p.get("type") == "OPERATOR_IS_NOT_NULL"]
    if pieces and len(empty) == len(pieces) and all(empty):
        return "empty " + " or ".join(empty)
    text = cond.strip()  # already one space between words, and quoted values as written (learning.clauses)
    return text if len(text) <= 80 else text[:77] + "..."


def assumptions(q, eng):
    """Short sentences about what a query left out or cut off."""
    tree = sqltree.parse(q["sql"])
    out = []
    where = _clause(learning.clauses(q["sql"]), "WHERE")
    if where:
        cond = where[len("WHERE"):].strip()
        # the same FROM, joins and WITH, counted with and without the filter (two small counts)
        total = _value(eng, tree.count_sql(where=False)) if tree else None
        kept = _value(eng, tree.count_sql()) if tree else None
        if total is not None and kept is not None:
            if total > kept:
                out.append(f"left out {total - kept:,} of {total:,} rows ({_plain(cond)})")
        else:
            out.append(f"keeps only rows where {_plain(cond)}")
    if tree and tree.order and (tree.limit or 0) > 1:
        out.append(f"shows the top {tree.limit} only")
    if q.get("truncated"):
        out.append(f"the result was cut at {len(q['rows'])} rows")
    zone = _time_zone(q, eng, tree)
    if zone:
        out.append(zone)
    return out


def _unit_factor(v):
    """True for 0, 1, 2 and powers of ten: unit changes and halves are not assumptions."""
    return v in (0, 1, 2) or (v == int(v) and str(int(v)).strip("0") == "1")


def _constants(items):
    """Numbers that the SELECT items (tree nodes) multiply or divide by, as written, other than unit factors.
    A bucket width is not one: floor(x / 5) * 5."""
    found = []
    widths = set()
    for name, call in sqltree.calls(items, subqueries=False):
        if name == "*":  # floor(x / w) * w
            for side, other in (sqltree.args(call), sqltree.args(call)[::-1]):
                w = sqltree.constant(other)
                inner = [sqltree.constant(sqltree.args(c)[-1]) for n, c in sqltree.calls(side) if n == "/"]
                if w is not None and w in inner:
                    widths.add(w)
    for name, call in sqltree.calls(items, subqueries=False):
        if name not in ("*", "/") or len(sqltree.args(call)) != 2:
            continue
        for child in sqltree.args(call)[1:] if name == "/" else sqltree.args(call):
            v = sqltree.constant(child)
            if isinstance(v, bool) or not isinstance(v, (int, sqltree.Decimal)) or v in widths or _unit_factor(v):
                continue
            if str(v) not in found:
                found.append(str(v))
    return found[:3]


def _buckets(tree, units, functions, formats):
    """Columns that the query puts into time buckets: date_trunc with one of units, one of functions, or
    strftime with a format that holds one of formats."""
    cols = []
    for name, call in sqltree.calls(tree.tree):
        args = sqltree.args(call)
        if name == "date_trunc" and len(args) == 2 and str(sqltree.constant(args[0])).lower() in units:
            cols.append(sqltree.column(args[1]))
        elif name in functions and args:
            cols.append(sqltree.column(args[0]))
        elif name == "strftime" and len(args) == 2 and isinstance(sqltree.constant(args[1]), str):
            if any(f(sqltree.constant(args[1])) for f in formats):
                cols.append(sqltree.column(args[0]))
    return [c for c in cols if c]


def _time_zone(q, eng, tree):
    """Say which clock day and hour buckets use, when the query buckets a timestamp by day or hour."""
    if not tree:
        return None
    cols = set(_buckets(tree, ("day", "hour", "week"), ("hour", "dayname", "dayofweek", "isodow"),
                        [lambda f: re.search(r"%[dHa]", f)]))
    cols |= {sqltree.column(d.get("child")) for d in sqltree._dicts(tree.tree) if sqltree.cast_to(d) == "DATE"} - {None}
    for name in q.get("datasets") or []:
        try:
            types = dict(eng.schema(engine.ident(name)))
        except engine.EngineError:
            continue
        for col in sorted(cols):
            typ = str(types.get(col, "")).upper()
            if typ == "TIMESTAMP WITH TIME ZONE":
                zone = _value(eng, "SELECT current_setting('TimeZone')")
                return f"day and hour buckets of {col} use the {zone or 'session'} time zone"
            if typ.startswith("TIMESTAMP"):
                return f"{col} has no time zone, so days and hours are as written in the file"
    return None


def _is_rate(tree, columns):
    """True when the outer SELECT divides by a count or a sum (not by 100 for units), or names a column like a rate."""
    for name, call in sqltree.calls(tree.selects, subqueries=False):
        if name == "/" and any(n in ("count", "count_star", "sum") for n, _ in sqltree.calls(sqltree.args(call)[-1])):
            return True
    names = [e.get("alias") or "" for items in tree.selects for e in items] + list(columns or [])
    return any(_RATE_NAME.search(n) for n in names)


def pitfalls(q, eng):
    """Short warnings about mistakes that the SQL or its result make likely."""
    tree, out = sqltree.parse(q["sql"]), []
    if tree:
        averages = lambda part, deep: any(n == "avg" for n, _ in sqltree.calls(part, subqueries=deep))
        inner = [d for d in sqltree._dicts(tree.tree) if "select_list" in d and d is not tree.node]
        if averages(tree.select, False) and any(averages(d["select_list"], False) for d in inner):
            out.append("average of averages: groups of different sizes count the same; weight by row count if that matters")
        kind, *src = tree.source()
        if kind == "join":
            left, _l, right, _r, key_l, key_r = src
            dup_l = _value(eng, f"SELECT count(*) - count(DISTINCT {engine.ident(key_l)}) FROM {left}")
            dup_r = _value(eng, f"SELECT count(*) - count(DISTINCT {engine.ident(key_r)}) FROM {right}")
            if dup_l and dup_r:
                out.append(f"the join on {key_l} matches several rows on both sides, so rows can be counted more than once")
    variants = _result_variants(q)
    if variants:
        out.append(f"{variants} look like one value spelled differently; combine them with grimoire_merge "
                   "so each total counts once")
    if not tree:
        return out
    constants = _constants(tree.selects)
    if constants:
        out.append(f"uses {', '.join(constants)}, written into the SQL, not taken from the data")
    months = _buckets(tree, ("month",), (), [lambda f: f == "%Y-%m"])
    years = _buckets(tree, ("year",), ("year",), [])
    for column, kind in ([(months[0], "month")] if months else [(years[0], "year")] if years else []):
        warning = _incomplete_period(q, eng, column, kind)
        if warning:
            out.append(warning)
        if _is_rate(tree, q["columns"]) and len(q["rows"]) >= 2:
            warning = _changing_base(q, eng, column, kind)
            if warning:
                out.append(warning)
    return out


def _result_variants(q):
    """Labels in one result column that look like one value written differently (see engine.variant_groups).
    The result's last number column stands in for each label's size, so a rare variant stands out."""
    rows, cols = q["rows"], q["columns"]
    nums = [i for i in range(len(cols)) if rows and all(isinstance(r[i], (int, float)) and not isinstance(r[i], bool) for r in rows)]
    for i in range(len(cols)):
        labels = [r[i] for r in rows if isinstance(r[i], str)]
        if len(set(labels)) < 2 or len(labels) != len(rows):
            continue
        size = {}
        for r in rows:  # a label can repeat (region by month): add up its rows
            size[r[i]] = size.get(r[i], 0) + (abs(r[nums[-1]]) if nums else 1)
        groups = engine.variant_groups(size)
        if groups:
            return " and ".join(" / ".join(repr(v) for v in g) for g in groups[:2])
    return None


def _incomplete_period(q, eng, column, kind):
    """Warn when the result includes the last month or year and the data stops before it ends."""
    for name in q.get("datasets") or []:
        c = engine.ident(column)
        found = _rows(eng, f"SELECT max({c}), bool_and(day(try_cast({c} AS DATE)) = 1), "
                           f"bool_and(month(try_cast({c} AS DATE)) = 1) FROM {engine.ident(name)}")
        if not found or found[0][0] is None:
            continue  # this dataset has no such column (or the check was slow); try the next
        last, monthly, yearly = found[0]
        if (kind == "month" and monthly) or yearly and monthly:
            return None  # one row per month (or year) dated on its first day: the last period is whole
        day = datetime.date.fromisoformat(str(last)[:10])
        if kind == "month":
            label, end = day.strftime("%Y-%m"), calendar.monthrange(day.year, day.month)[1]
            complete = day.day == end
        else:
            label, complete = str(day.year), (day.month, day.day) == (12, 31)
        shown = any(str(v).startswith(label) for row in q["rows"] for v in row if isinstance(v, str))
        if shown and not complete:
            return f"the last {kind} ({label}) has data only up to {day.isoformat()}, so it looks smaller than it is"
        return None
    return None


def _changing_base(q, eng, column, kind):
    """Warn when a rate or average is compared across periods whose row counts differ a lot.
    The first and last periods are left out: they are often partial, which another check covers."""
    for name in q.get("datasets") or []:
        c = engine.ident(column)
        counts = _rows(eng, f"SELECT date_trunc('{kind}', {c}) AS p, count(*) FROM {engine.ident(name)} "
                            f"WHERE {c} IS NOT NULL GROUP BY 1 ORDER BY 1")
        if counts is None:
            continue
        shown = {str(v)[:7 if kind == "month" else 4] for row in q["rows"] for v in row if isinstance(v, str)}
        counts = [(p_, n) for p_, n in counts if str(p_)[:7 if kind == "month" else 4] in shown] or counts
        inner = [n for _p, n in counts[1:-1]]  # only the periods the result shows; stray dates elsewhere do not count
        if len(inner) >= 2 and min(inner) and max(inner) >= 2 * min(inner):
            return (f"rows per {kind} range from {min(inner):,} to {max(inner):,}, so a rate or average can "
                    "move because the base changed; show the counts next to it")
        return None
    return None


def verdict(failed, warnings):
    """failed: numbers with no source, or in the wrong row."""
    if failed:
        return "needs revision"
    return "share with caveats" if warnings else "ready to share"


def review(queries, eng, failed, caveats=()):
    """Footer lines for the cited queries: (verdict, [lines]). Empty lines when there is nothing to say.
    failed: numbers that fail the check. caveats: warnings from the number check (verify.caveats); they come first."""
    assumed, warned = [], list(caveats)
    for q in queries[-MAX_QUERIES:]:
        assumed += [f"{a} [{q['id']}]" for a in assumptions(q, eng)]
        warned += [f"{w} [{q['id']}]" for w in pitfalls(q, eng)]
    lines = []
    if assumed:
        lines.append("Assumes: " + "; ".join(dict.fromkeys(assumed)) + ".")
    if warned:
        lines.append("Watch out: " + "; ".join(dict.fromkeys(warned)) + ".")
    return verdict(failed, warned), lines
