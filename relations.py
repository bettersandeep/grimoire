"""What a table is made of and how it connects: column roles, correlated metrics, join keys to other files.

Small read-only queries with a time cap; each part is skipped when it cannot be computed.
"""

import re

from . import engine

_ID = re.compile(r"(^|_)(id|key|code|uuid|number|no)$", re.I)
TIMEOUT_S = 10
MAX_METRICS = 6
MAX_JOINS = 3


def roles(profile_rows):
    """{"dimensions": [...], "metrics": [...], "time": [...]} from SUMMARIZE rows."""
    out = {"dimensions": [], "metrics": [], "time": []}
    for r in profile_rows:
        col, typ = r["column_name"], str(r["column_type"]).upper()
        distinct = r.get("approx_unique") or 0
        if "DATE" in typ or "TIMESTAMP" in typ:
            out["time"].append(col)
        elif engine.is_number_type(typ):
            if not _ID.search(col):  # by name only: unique amounts are common, so uniqueness is no sign of an ID
                out["metrics"].append(col)
        elif typ in ("VARCHAR", "BOOLEAN") and 2 <= distinct <= 50:
            out["dimensions"].append(col)
    return out


def correlations(eng, table, metrics, threshold=0.5):
    """[[a, b, r]] for metric pairs with |r| >= threshold, strongest first, at most 5."""
    cols = metrics[:MAX_METRICS]
    pairs = [(a, b) for i, a in enumerate(cols) for b in cols[i + 1:]]
    if not pairs:
        return []
    sql = "SELECT " + ", ".join(f"corr({engine.ident(a)}, {engine.ident(b)})" for a, b in pairs) + f" FROM {table}"
    try:
        values = eng.query(sql, TIMEOUT_S)[1][0]
    except engine.EngineError:
        return []
    found = [[a, b, round(r, 2)] for (a, b), r in zip(pairs, values) if r is not None and abs(r) >= threshold]
    return sorted(found, key=lambda x: -abs(x[2]))[:5]


def join_keys(eng, dataset, table, columns):
    """[{"column", "with", "match_pct"}]: ID-like columns this table shares with other attached tables, and
    the share of this table's distinct values found there."""
    out = []
    mine = {c for c in columns if _ID.search(c)}
    for other in eng.datasets:
        if other == dataset or len(out) >= MAX_JOINS:
            continue
        for ref in eng.tables(other):
            sql_ref = engine.sql_ref(ref)
            try:
                theirs = {c for c, _t in eng.schema(sql_ref)}
            except engine.EngineError:
                continue
            for col in sorted(mine & theirs):
                c = engine.ident(col)
                try:
                    total, matched = eng.query(
                        f"SELECT count(DISTINCT {c}), count(DISTINCT {c}) FILTER (WHERE {c} IN "
                        f"(SELECT {c} FROM {sql_ref})) FROM {table}", TIMEOUT_S)[1][0]
                except engine.EngineError:
                    continue
                if total and matched:
                    out.append({"column": col, "with": f"{ref}.{col}", "match_pct": round(100 * matched / total, 1)})
                if len(out) >= MAX_JOINS:
                    return out
    return out


def health(profile_rows, issues, rows, skipped=0):
    """A 0 to 100 score for one table, with the reason for every point taken off.
    Empty cells cost their average percentage (up to 30), duplicate rows and skipped lines their
    percentage of rows (at least 1, up to 20 each), every other problem 3 points (up to 30)."""
    cols = [float(r.get("null_percentage") or 0) for r in profile_rows]
    off = []
    empty = round(sum(cols) / len(cols)) if cols else 0
    if empty:
        off.append((min(30, empty), "empty values"))
    dupes = next((i["rows"] for i in issues if i.get("issue") == "duplicate rows"), 0)
    for n, label in ((dupes, "duplicate rows"), (skipped, "skipped lines")):
        if n and rows:
            off.append((min(20, max(1, round(100 * n / rows))), label))
    other = [i for i in issues if i.get("issue") not in ("duplicate rows", "empty values")]
    if other:
        off.append((min(30, 3 * len(other)), f"{len(other)} other problem{'s' if len(other) > 1 else ''}"))
    return {"score": 100 - sum(n for n, _ in off), "off": [f"-{n} {label}" for n, label in off]}
