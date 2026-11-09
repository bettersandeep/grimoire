"""Saved metric definitions: the user names an SQL expression once, and queries use it by name.

The model writes revenue(); Grimoire expands it to the saved expression before the query runs, so the
saved SQL (the receipt) shows the real arithmetic and every session computes "revenue" the same way.
"""

import re

from . import engine

_NAME = re.compile(r"^[a-z_][a-z0-9_]{0,40}$")


def validate(eng, name, expression):
    """Raise EngineError unless name is free and expression is one SQL expression that works on an
    attached table. Returns the datasets it works on."""
    if not _NAME.match(name):
        raise engine.EngineError("Use a short lower-case name: letters, digits and _ (for example revenue).")
    if ";" in expression or not expression.strip():
        raise engine.EngineError("Give one SQL expression, for example: sum(amount_cents) / 100")
    if eng.function_exists(name):
        raise engine.EngineError(f"{name} is already a DuckDB function. Pick another name.")
    works = []
    for dataset in eng.datasets:
        for ref in eng.tables(dataset):
            sql_ref = ".".join(engine.ident(p) for p in ref.split(".", 1))
            try:
                eng.query(f"SELECT {expression} FROM {sql_ref} LIMIT 0")
                works.append(ref)
            except engine.EngineError:
                pass
    if not works:
        raise engine.EngineError("That expression does not work on any attached file. Check the column names, "
                                 "or attach the file first.")
    return works


def expand(sql, saved):
    """Replace name() with (expression) for each saved metric. Returns (sql, names used)."""
    if not saved:
        return sql, []
    used = []

    def swap(m):
        name = m.group(1).lower()
        used.append(name)
        return f"({saved[name]})"

    pattern = re.compile(r"\b(" + "|".join(map(re.escape, saved)) + r")\s*\(\s*\)", re.I)
    # ponytail: also expands inside string literals; quote metric names in text if that ever matters.
    return pattern.sub(swap, sql), list(dict.fromkeys(used))
