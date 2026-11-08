"""Tool schemas: what the model reads to decide when and how to call each tool."""

ATTACH = {
    "name": "grimoire_attach",
    "description": (
        "Attach a local data file (CSV, TSV, Parquet or SQLite) so you can query it with SQL. "
        "Returns the dataset name, its tables, columns and row counts. "
        "Use this before answering any question about the contents of a data file. "
        "Never read data files into the conversation; attach and query them instead."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the file, for example ~/Downloads/sales.csv"},
            "name": {"type": "string", "description": "Optional short dataset name. Defaults to the file name."},
        },
        "required": ["path"],
    },
}

PROFILE = {
    "name": "grimoire_profile",
    "description": (
        "Profile a table: per column type, null percentage, approximate distinct count, min and max. "
        "Use it to understand a dataset before writing queries and to spot data quality problems."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "dataset": {"type": "string", "description": "Dataset name from grimoire_attach."},
            "table": {"type": "string", "description": "Table reference. Optional for CSV and Parquet (one table)."},
        },
        "required": ["dataset"],
    },
}

QUERY = {
    "name": "grimoire_query",
    "description": (
        "Run one read-only DuckDB SQL query on attached datasets. "
        "Returns a query id (like q7), the columns and up to 200 rows. "
        "Compute every number you will state (totals, averages, growth, shares, differences) in SQL, "
        "so each number in your answer appears in a query result. "
        "Cite the query id next to the numbers it supports, for example 'Revenue grew 14.2% [q7]'. "
        "Aggregate in SQL; do not fetch raw rows to count or sum them yourself."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "sql": {"type": "string", "description": "One DuckDB SELECT / WITH / FROM / DESCRIBE / SUMMARIZE statement."},
            "purpose": {"type": "string", "description": "One short line: what this query answers."},
        },
        "required": ["sql"],
    },
}

NOTE = {
    "name": "grimoire_note",
    "description": (
        "Save what a column means (unit, encoding, caveat) so later sessions know it without asking again. "
        "Example: column 'amount', note 'in cents, integer'."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "dataset": {"type": "string"},
            "column": {"type": "string", "description": "Column name, or table.column for SQLite datasets."},
            "note": {"type": "string"},
        },
        "required": ["dataset", "column", "note"],
    },
}

CATALOG = {
    "name": "grimoire_catalog",
    "description": (
        "List the datasets Grimoire knows (also from earlier sessions), their tables, saved column notes "
        "and recent queries. Call this first when the user refers to data they used before."
    ),
    "parameters": {"type": "object", "properties": {}},
}

ALL = [ATTACH, PROFILE, QUERY, NOTE, CATALOG]
