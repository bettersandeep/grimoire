"""SQL for a chart the user builds on the Data page: group by one column, measure one number, one optional filter.

The page sends names and choices, never SQL. Every name must be a real column; values go in as literals.
"""

from .engine import ident, literal

MEASURES = {"count": "count(*)", "sum": "sum({})", "avg": "avg({})", "min": "min({})", "max": "max({})"}
WORDS = {"count": "Rows", "sum": "Total", "avg": "Average", "min": "Smallest", "max": "Largest"}
BUCKETS = {"day": "%Y-%m-%d", "month": "%Y-%m", "year": "%Y"}
OPS = {"=", "!=", ">", "<", ">=", "<="}
TIME_TYPES = ("DATE", "TIMESTAMP")


class BuildError(ValueError):
    pass


def kind(typ):
    t = typ.upper()
    if t.startswith(TIME_TYPES):
        return "time"
    if any(w in t for w in ("INT", "DOUBLE", "FLOAT", "DECIMAL", "REAL", "NUMERIC", "HUGEINT")):
        return "number"
    return "text"


def build(table_sql, types, spec):
    """(sql, purpose) for spec {group, bucket, measure, column, filter: {column, op, value}}; types: {column: type}."""
    if not isinstance(spec, dict) or not isinstance(spec.get("filter") or {}, dict):
        raise BuildError("Send the chart choices as an object.")

    def column(name, want=None):
        if not isinstance(name, str) or name not in types:
            raise BuildError(f"No column '{name}'.")
        if want and kind(types[name]) != want:
            raise BuildError(f"'{name}' is not a {want} column.")
        return ident(name)

    measure = spec.get("measure") or "count"
    if not isinstance(measure, str) or measure not in MEASURES:
        raise BuildError(f"Unknown measure '{measure}'.")
    if measure == "count":
        expr, label = MEASURES["count"], "rows"
        words = "Rows"
    else:
        expr = MEASURES[measure].format(column(spec.get("column") or "", "number"))
        label = f"{measure}_{spec['column']}"
        words = f"{WORDS[measure]} {spec['column']}"
    select, tail, by = [], "", ""
    group = spec.get("group")
    if group:
        g = column(group)
        bucket = spec.get("bucket")
        if bucket:
            if not isinstance(bucket, str) or bucket not in BUCKETS or kind(types[group]) != "time":
                raise BuildError(f"Cannot group '{group}' by {bucket}.")
            select.append(f"strftime({g}, '{BUCKETS[bucket]}') AS {ident(bucket)}")
            tail, by = " GROUP BY 1 ORDER BY 1", f" per {bucket}"
        else:
            select.append(f"{g} AS {g}")
            # time and numbers read in order; categories read best from largest to smallest
            tail = " GROUP BY 1 ORDER BY 1" if kind(types[group]) != "text" else " GROUP BY 1 ORDER BY 2 DESC NULLS LAST"
            by = f" per {group}"
        group2 = spec.get("group2")
        if group2:  # a second label: one row per pair, for a pivot table or a heatmap
            if group2 == group:
                raise BuildError("Pick two different columns.")
            g2 = column(group2)
            select.append(f"{g2} AS {g2}")
            tail, by = " GROUP BY 1, 2 ORDER BY 1, 2", by + f" and {group2}"
    select.append(f"{expr} AS {ident(label)}")
    where, when = "", ""
    f = spec.get("filter") or {}
    if f.get("column"):
        op = f.get("op") or "="
        if not isinstance(op, str) or op not in OPS:
            raise BuildError(f"Unknown filter '{op}'.")
        value = str(f.get("value", ""))
        if not value:
            raise BuildError("Type a value for the filter.")
        where = f" WHERE {column(f['column'])} {op} {literal(value)}"
        when = f", where {f['column']} {op} {value}"
    sql = f"SELECT {', '.join(select)} FROM {table_sql}{where}{tail}"
    return sql, f"{words}{by}{when} (made on the Data page)"
