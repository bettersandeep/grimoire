"""What a table is made of and how it connects: column roles, correlated metrics, join keys to other files.

Small read-only queries with a time cap; each part is skipped when it cannot be computed.
"""

import re

from . import engine

_ID = re.compile(r"(^|_)(id|key|code|uuid|number|no)$", re.I)
_NUMERIC = ("INT", "DOUBLE", "FLOAT", "DECIMAL", "REAL", "NUMERIC")
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
        elif any(t in typ for t in _NUMERIC):
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
            sql_ref = ".".join(engine.ident(p) for p in ref.split(".", 1))
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
