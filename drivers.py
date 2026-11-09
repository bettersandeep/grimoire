"""What drives a change: split the change of a measure between two periods by each category column.

One generated SELECT (saved as a normal query, so answers can cite it). Periods are date prefixes:
'2026' (a year), '2026-03' (a month) or '2026-03-15' (a day).
"""

import re

from . import engine

MAX_DIMENSIONS = 6
MAX_ROWS = 15
_PERIOD = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$")


def additive(measure):
    """True for a plain sum or count, optionally scaled by a constant (shares of the change add up)."""
    core = re.sub(r"\s*[/*]\s*\d+(\.\d+)?\s*$", "", measure.strip())
    core = re.sub(r"^\((.*)\)$", r"\1", core.strip()).strip()
    # count(DISTINCT x) is not additive: a customer in two regions counts once in total, twice in the parts
    return bool(re.fullmatch(r"(sum|count)\s*\([^()]*\)", core, re.I)) and not re.search(r"\bdistinct\b", core, re.I)


def build_sql(table, measure, time_column, before, after, dimensions):
    for p in (before, after):
        if not _PERIOD.match(p):
            raise engine.EngineError(f"Period '{p}' must look like 2026, 2026-03 or 2026-03-15.")
    t = engine.ident(time_column)
    label = f"strftime({t}, '%Y-%m-%d')"
    base = (f"SELECT *, CASE WHEN {label} LIKE {engine.literal(before + '%')} THEN 'before' "
            f"WHEN {label} LIKE {engine.literal(after + '%')} THEN 'after' END AS grimoire_period FROM {table}")
    parts = [f"base AS (SELECT * FROM ({base}) WHERE grimoire_period IS NOT NULL)",
             f"total AS (SELECT grimoire_period, {measure} AS m FROM base GROUP BY 1)"]
    unions = []
    for i, d in enumerate(dimensions):
        c = engine.ident(d)
        parts.append(f"g{i} AS (SELECT CAST({c} AS VARCHAR) AS value, grimoire_period, {measure} AS m "
                     f"FROM base GROUP BY 1, 2)")
        unions.append(f"SELECT {engine.literal(d)} AS dimension, value, "
                      f"max(m) FILTER (WHERE grimoire_period = 'before') AS before, "
                      f"max(m) FILTER (WHERE grimoire_period = 'after') AS after FROM g{i} GROUP BY 1, 2")
    parts.append("seg AS (" + " UNION ALL ".join(unions) + ")")
    parts.append("tot AS (SELECT max(m) FILTER (WHERE grimoire_period = 'before') AS before, "
                 "max(m) FILTER (WHERE grimoire_period = 'after') AS after FROM total)")
    change = "coalesce(after, 0) - coalesce(before, 0)"
    return (
        "WITH " + ", ".join(parts) + " "
        f"SELECT '(total)' AS dimension, NULL AS value, round(before, 2) AS before, round(after, 2) AS after, "
        f"round({change}, 2) AS change, 100.0 AS pct_of_change FROM tot "
        "UNION ALL (SELECT dimension, value, round(seg.before, 2), round(seg.after, 2), "
        f"round(coalesce(seg.after, 0) - coalesce(seg.before, 0), 2) AS change, "
        "round(100 * (coalesce(seg.after, 0) - coalesce(seg.before, 0)) / nullif(tot.after - tot.before, 0), 1) "
        f"FROM seg, tot ORDER BY abs(coalesce(seg.after, 0) - coalesce(seg.before, 0)) DESC LIMIT {MAX_ROWS})"
    )
