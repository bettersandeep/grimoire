"""Tool schemas: what the model reads to decide when and how to call each tool.

Kept short on purpose: with `hermes chat -t grimoire` every schema is sent on every model call.
The first sentence of each description is what Hermes Tool Search lists (80 characters at most).
Longer guidance lives in the skill (skills/explore-data/SKILL.md), which the model reads only when needed.
"""

_DATASET = {"type": "string", "description": "Dataset name from grimoire_attach."}
_TABLE = {"type": "string", "description": "Only for SQLite files with several tables."}

ATTACH = {
    "name": "grimoire_attach",
    "description": (
        "Open a CSV, TSV, Parquet or SQLite file for SQL questions; never read it raw. "
        "Also JSON, NDJSON, .gz/.zst, a folder or a glob. Returns tables, columns, row counts."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "name": {"type": "string", "description": "Optional dataset name."},
        },
        "required": ["path"],
    },
}

PROFILE = {
    "name": "grimoire_profile",
    "description": (
        "Profile a data table: column types, empty values, distinct counts, ranges. "
        "Also data problems and how columns relate. Ask the user about problems."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "dataset": _DATASET,
            "table": _TABLE,
            "column": {"type": "string", "description": "One column in depth: quantiles, outliers, top values."},
        },
        "required": ["dataset"],
    },
}

QUERY = {
    "name": "grimoire_query",
    "description": (
        "Answer questions about attached data files with one read-only SQL query. "
        "DuckDB; returns an id like q7 and up to 200 rows. Compute every number you state in SQL "
        "and cite the id, like 'grew 14.2% [q7]'. Use saved metrics by name, like revenue()."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "sql": {"type": "string", "description": "One SELECT."},
            "purpose": {"type": "string", "description": "What it answers, in a few words."},
        },
        "required": ["sql"],
    },
}

DRIVERS = {
    "name": "grimoire_drivers",
    "description": (
        "Explain what drives a change between two periods, split by category columns. "
        "Returns the segments that moved most; citable query id."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "dataset": _DATASET,
            "measure": {"type": "string", "description": "SQL aggregate or saved metric; default count(*)."},
            "time_column": {"type": "string"},
            "before": {"type": "string", "description": "2026, 2026-02 or 2026-02-15."},
            "after": {"type": "string"},
            "dimensions": {"type": "array", "items": {"type": "string"}, "description": "Optional columns to split by."},
            "table": _TABLE,
        },
        "required": ["dataset", "time_column", "before", "after"],
    },
}

COMPARE = {
    "name": "grimoire_compare",
    "description": (
        "Test if two groups really differ (averages or rates); p-value, citable id."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "dataset": _DATASET,
            "measure": {"type": "string", "description": "Number column, or a condition like x = 'y' for a rate."},
            "group_column": {"type": "string"},
            "a": {"type": "string"},
            "b": {"type": "string"},
            "table": _TABLE,
        },
        "required": ["dataset", "measure", "group_column", "a", "b"],
    },
}

NOTE = {
    "name": "grimoire_note",
    "description": "Save what a data column means (unit, code, caveat) for later sessions.",
    "parameters": {
        "type": "object",
        "properties": {
            "dataset": _DATASET,
            "column": {"type": "string", "description": "Column, or table.column for SQLite."},
            "note": {"type": "string"},
        },
        "required": ["dataset", "column", "note"],
    },
}

MERGE = {
    "name": "grimoire_merge",
    "description": (
        "Propose merging spelling variants of a value, like 'north ' into 'North'. "
        "It applies only after the user types /grimoire merges approve; tell them."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "dataset": _DATASET,
            "column": {"type": "string"},
            "values": {"type": "array", "items": {"type": "string"}},
            "into": {"type": "string"},
            "table": _TABLE,
        },
        "required": ["dataset", "column", "values", "into"],
    },
}

CATALOG = {
    "name": "grimoire_catalog",
    "description": "List data files, column notes and queries saved from earlier sessions.",
    "parameters": {"type": "object", "properties": {}},
}

ALL = [ATTACH, PROFILE, QUERY, DRIVERS, COMPARE, NOTE, MERGE, CATALOG]
