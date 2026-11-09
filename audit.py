"""Check the queries behind an answer: the filters they assume, common analysis pitfalls, and a verdict.

Plain code over the saved SQL and a few small read-only count queries; no model call.
Each check is best effort: if it cannot tell, it says nothing rather than guess.
"""

import calendar
import datetime
import re

from . import engine, learning

AUDIT_TIMEOUT_S = 2  # per extra query; a slow check is skipped, the reply is never held up long
MAX_QUERIES = 3      # audit at most the last 3 cited queries

_TABLE = r'("?[\w]+"?(?:\."?[\w]+"?)?)'
_SIMPLE_FROM = re.compile(rf"^FROM\s+{_TABLE}(?:\s+(?:AS\s+)?\w+)?$", re.I)
_JOIN = re.compile(
    rf"^FROM\s+{_TABLE}(?:\s+(?:AS\s+)?(\w+))?\s+(?:(?:LEFT|RIGHT|INNER|FULL)\s+)?(?:OUTER\s+)?JOIN\s+{_TABLE}"
    r"(?:\s+(?:AS\s+)?(\w+))?\s+(?:USING\s*\(\s*\"?(\w+)\"?\s*\)|ON\s+(\w+)\.\"?(\w+)\"?\s*=\s*(\w+)\.\"?(\w+)\"?)\s*$",
    re.I)
_MONTH = re.compile(r"date_trunc\(\s*'month'\s*,\s*\"?(\w+)\"?\s*\)|strftime\(\s*\"?(\w+)\"?\s*,\s*'%Y-%m'\s*\)", re.I)
_YEAR = re.compile(r"date_trunc\(\s*'year'\s*,\s*\"?(\w+)\"?\s*\)|\byear\(\s*\"?(\w+)\"?\s*\)", re.I)
_DAY = re.compile(r"date_trunc\(\s*'(?:day|hour|week)'\s*,\s*\"?(\w+)\"?\s*\)|\b(?:hour|dayname|dayofweek|isodow)\(\s*\"?(\w+)\"?\s*\)"
                  r"|CAST\(\s*\"?(\w+)\"?\s+AS\s+DATE\s*\)|\"?(\w+)\"?::DATE|strftime\(\s*\"?(\w+)\"?\s*,\s*'[^']*%[dHa]", re.I)
# A rate: divided by a count or sum (not by 100 for units), or named like one.
_RATIO = re.compile(r"/\s*\(?\s*(?:nullif\s*\(\s*)?(?:count|sum)\s*\(|\b(?:pct|percent\w*|share|rate|ratio)\b", re.I)
_IN = re.compile(r"^(?:CAST\(\s*)?\"?(\w+)\"?(?:\s+AS\s+VARCHAR\s*\))?\s+IN\s*\(((?:\s*'[^',]*'\s*,?)+)\)$", re.I)
_FACTOR = re.compile(r"[*/]\s*\(?\s*(\d+(?:\.\d+)?)\b(?!\s*\))?|\b(\d+(?:\.\d+)?)\s*\*")
_NOT_NULL = re.compile(r'^\(?\s*"?(\w+)"?\s+IS\s+NOT\s+NULL\s*\)?$', re.I)


def _clause(parts, name):
    return next((text for n, text in parts if n == name), None)


_memo = {}  # (sql, files as opened) -> value; a changed file changes the key, so nothing goes stale


def _rows(eng, sql):
    """Rows of a small read-only query, remembered per file version; None when it fails or is slow."""
    key = (sql, tuple(sorted((eng._opened or {}).items())))
    if key not in _memo:
        try:
            _memo[key] = eng.query(sql, AUDIT_TIMEOUT_S)[1]
        except engine.EngineError:
            return None
        if len(_memo) > 512:
            _memo.pop(next(iter(_memo)))
    return _memo[key]


def _value(eng, sql):
    """First cell of a small read-only query; None when it fails or is slow."""
    rows = _rows(eng, sql)
    return rows[0][0] if rows else None


_count = _value


def _plain(cond):
    """A WHERE condition in plain words, for the common shapes; else the condition itself, shortened."""
    m = _IN.match(cond.strip())
    if m:  # CAST(region AS VARCHAR) IN ('North', 'South'), as grimoire_compare writes it
        return f"{m.group(1)} is " + " or ".join(v.strip().strip("'") for v in m.group(2).split(","))
    pieces = re.split(r"\s+AND\s+", cond.strip(), flags=re.I)
    empty = [m.group(1) for m in (_NOT_NULL.match(p) for p in pieces) if m]
    if empty and len(empty) == len(pieces):
        return "empty " + " or ".join(empty)
    text = re.sub(r"\s+", " ", cond.strip())
    return text if len(text) <= 80 else text[:77] + "..."


def assumptions(q, eng):
    """Short sentences about what a query left out or cut off."""
    parts = learning.clauses(q["sql"])
    names = [n for n, _ in parts]
    out = []
    where, frm = _clause(parts, "WHERE"), _clause(parts, "FROM")
    if where and frm:
        cond = where[len("WHERE"):].strip()
        m = _SIMPLE_FROM.match(frm) if "WITH" not in names else None
        total = kept = None
        if m:  # one plain table: count what the filter removed (two small counts)
            total = _count(eng, f"SELECT count(*) FROM {m.group(1)}")
            kept = _count(eng, f"SELECT count(*) FROM {m.group(1)} WHERE {cond}")
        if total is not None and kept is not None:
            if total > kept:
                out.append(f"left out {total - kept:,} of {total:,} rows ({_plain(cond)})")
        else:
            out.append(f"keeps only rows where {_plain(cond)}")
    limit = _clause(parts, "LIMIT")
    if limit and "ORDER BY" in names and re.match(r"LIMIT\s+\d+$", limit, re.I):
        n = int(limit.split()[1])
        if n > 1:
            out.append(f"shows the top {n} only")
    if q.get("truncated"):
        out.append(f"the result was cut at {len(q['rows'])} rows")
    zone = _time_zone(q, eng)
    if zone:
        out.append(zone)
    return out


def _constants(select):
    """Numbers the SQL multiplies or divides by, other than unit factors (10, 100, 1000 ...) and 1 or 2."""
    found = []
    buckets = set(re.findall(r"/\s*(\d+(?:\.\d+)?)\s*\)\s*\*\s*\1\b", select))  # floor(x / 5) * 5: a bucket width
    for m in _FACTOR.finditer(select):
        raw = m.group(1) or m.group(2)
        if raw in buckets:
            continue
        v = float(raw)
        if v in (0, 1, 2) or (v == int(v) and str(int(v)).strip("0") == "1"):
            continue  # unit changes and halves are not assumptions
        if raw not in found:
            found.append(raw)
    return found[:3]


def _time_zone(q, eng):
    """Say which clock day and hour buckets use, when the query buckets a timestamp by day or hour."""
    cols = {next(g for g in m.groups() if g) for m in _DAY.finditer(q["sql"])}
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


def pitfalls(q, eng):
    """Short warnings about mistakes that the SQL or its result make likely."""
    sql, out = q["sql"], []
    parts = learning.clauses(sql)
    outer_select = _clause(parts, "SELECT") or ""
    inner = sql.replace(outer_select, "", 1)
    if re.search(r"\bavg\s*\(", outer_select, re.I) and re.search(r"\bavg\s*\(", inner, re.I):
        out.append("average of averages: groups of different sizes count the same; weight by row count if that matters")
    frm = _clause(parts, "FROM") or ""
    j = _JOIN.match(frm)
    if j:
        left, right = j.group(1), j.group(3)
        key_l = j.group(5) or j.group(7)
        key_r = j.group(5) or j.group(9)
        dup_l = _count(eng, f'SELECT count(*) - count(DISTINCT "{key_l}") FROM {left}')
        dup_r = _count(eng, f'SELECT count(*) - count(DISTINCT "{key_r}") FROM {right}')
        if dup_l and dup_r:
            out.append(f"the join on {key_l} matches several rows on both sides, so rows can be counted more than once")
    constants = _constants(outer_select)
    if constants:
        out.append(f"uses {', '.join(constants)}, written into the SQL, not taken from the data")
    for pattern, kind in ((_MONTH, "month"), (_YEAR, "year")):
        m = pattern.search(sql)
        if m:
            column = m.group(1) or m.group(2)
            warning = _incomplete_period(q, eng, column, kind)
            if warning:
                out.append(warning)
            if _RATIO.search(outer_select) and len(q["rows"]) >= 2:
                warning = _changing_base(q, eng, column, kind)
                if warning:
                    out.append(warning)
            break
    return out


def _incomplete_period(q, eng, column, kind):
    """Warn when the result includes the last month or year and the data stops before it ends."""
    for name in q.get("datasets") or []:
        last = _value(eng, f'SELECT max("{column}") FROM {engine.ident(name)}')
        if last is None:
            continue  # this dataset has no such column (or the check was slow); try the next
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
        counts = _rows(eng, f'SELECT date_trunc(\'{kind}\', "{column}") AS p, count(*) FROM {engine.ident(name)} '
                            f'WHERE "{column}" IS NOT NULL GROUP BY 1 ORDER BY 1')
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


def verdict(unsourced, warnings):
    if unsourced:
        return "needs revision"
    return "share with caveats" if warnings else "ready to share"


def review(queries, eng, unsourced):
    """Footer lines for the cited queries: (verdict, [lines]). Empty lines when there is nothing to say."""
    assumed, warned = [], []
    for q in queries[-MAX_QUERIES:]:
        assumed += [f"{a} [{q['id']}]" for a in assumptions(q, eng)]
        warned += [f"{w} [{q['id']}]" for w in pitfalls(q, eng)]
    lines = []
    if assumed:
        lines.append("Assumes: " + "; ".join(dict.fromkeys(assumed)) + ".")
    if warned:
        lines.append("Watch out: " + "; ".join(dict.fromkeys(warned)) + ".")
    return verdict(unsourced, warned), lines
