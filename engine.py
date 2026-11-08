"""Read-only DuckDB engine over the files the user attaches.

Safety model:
- DuckDB runs in memory. CSV and Parquet files are views; SQLite tables are copied in.
- After setup, only the attached files are readable (allowed_paths), all other file
  access is off, extension install and load are off, and the configuration is locked,
  so a query cannot write files, read other files, download code or undo the settings.
- Only read statements are accepted, results are capped, and slow queries are interrupted.
"""

import datetime
import decimal
import math
import os
import re
import sqlite3
import threading
import uuid
from pathlib import Path

MAX_ROWS = 200
TIMEOUT_S = 15

KINDS = {
    ".csv": "csv", ".tsv": "csv", ".txt": "csv",
    ".parquet": "parquet", ".pq": "parquet",
    ".sqlite": "sqlite", ".sqlite3": "sqlite", ".db": "sqlite",
}
_READ_ONLY = re.compile(
    r"^\s*\(*\s*(select|with|from|describe|summarize|show|pivot|unpivot|values|table)\b", re.I
)


class EngineError(Exception):
    """A problem the user or the model can fix (bad path, bad SQL, timeout)."""


def _duckdb():
    """Import DuckDB on first use, so the plugin still loads (and explains) when it is missing."""
    try:
        import duckdb
    except ImportError as exc:
        raise EngineError(
            "DuckDB is not installed. Reinstall or re-enable the grimoire plugin and accept its Python dependencies."
        ) from exc
    return duckdb


def ident(name):
    return '"' + name.replace('"', '""') + '"'


def literal(text):
    return "'" + text.replace("'", "''") + "'"


def safe_name(text):
    name = re.sub(r"[^a-z0-9_]+", "_", text.lower()).strip("_") or "data"
    return f"t_{name}" if name[0].isdigit() else name


def to_json_value(value):
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return None if math.isnan(value) or math.isinf(value) else value
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, (datetime.date, datetime.datetime, datetime.time)):
        return value.isoformat()
    if isinstance(value, bytes):
        return f"<{len(value)} bytes>"
    if isinstance(value, (datetime.timedelta, uuid.UUID)):
        return str(value)
    if isinstance(value, (list, tuple)):
        return [to_json_value(v) for v in value]
    if isinstance(value, dict):
        return {str(k): to_json_value(v) for k, v in value.items()}
    return str(value)


class Engine:
    def __init__(self):
        self._sources = {}  # dataset name -> (path, kind)
        self._tables = {}   # dataset name -> list of table references
        self._con = None
        # ponytail: one lock for all sessions; per-connection cursors if gateway concurrency hurts.
        self._lock = threading.RLock()

    @property
    def datasets(self):
        return dict(self._sources)

    def tables(self, dataset):
        if dataset not in self._tables:
            raise EngineError(f"Unknown dataset '{dataset}'. Attach it first.")
        return list(self._tables[dataset])

    def attach(self, path, name=None):
        real = os.path.realpath(os.path.expanduser(str(path)))
        if not os.path.isfile(real):
            raise EngineError(f"File not found: {path}")
        kind = KINDS.get(Path(real).suffix.lower())
        if kind is None:
            raise EngineError(f"Unsupported file type '{Path(real).suffix}'. Use CSV, Parquet or SQLite.")
        dataset = safe_name(name or Path(real).stem)
        with self._lock:
            previous = self._sources.get(dataset)
            self._sources[dataset] = (real, kind)
            try:
                self._rebuild()
            except Exception as exc:
                if previous is None:
                    self._sources.pop(dataset)
                else:
                    self._sources[dataset] = previous
                self._rebuild()
                raise EngineError(f"Cannot read {path}: {exc}") from exc
        return dataset, kind

    def forget(self, dataset):
        with self._lock:
            if self._sources.pop(dataset, None) is None:
                raise EngineError(f"Unknown dataset '{dataset}'.")
            self._rebuild()

    def _rebuild(self):
        """Build a fresh locked connection. Locked settings cannot change, so every attach rebuilds."""
        con = _duckdb().connect(":memory:", config={
            "autoinstall_known_extensions": False,
            "autoload_known_extensions": False,
        })
        tables, readable = {}, []
        for dataset, (path, kind) in self._sources.items():
            if kind == "sqlite":
                tables[dataset] = _copy_sqlite(con, dataset, path)
            else:
                reader = "read_parquet" if kind == "parquet" else "read_csv"
                con.execute(f"CREATE VIEW {ident(dataset)} AS SELECT * FROM {reader}({literal(path)})")
                con.execute(f"SELECT * FROM {ident(dataset)} LIMIT 0")  # fail now on a bad file
                tables[dataset] = [dataset]
                readable.append(path)
        con.execute("SET allowed_paths = ?", [readable])
        con.execute("SET enable_external_access = false")
        con.execute("SET lock_configuration = true")
        old, self._con, self._tables = self._con, con, tables
        if old is not None:
            old.close()

    def query(self, sql):
        """Run one read statement. Returns (columns, rows, truncated)."""
        sql = sql.strip().rstrip(";").strip()
        if not _READ_ONLY.match(sql):
            raise EngineError("Only read queries are allowed (SELECT, WITH, FROM, DESCRIBE, SUMMARIZE, SHOW).")
        if ";" in sql:
            # ponytail: also rejects ';' inside string literals; use a parser if that ever matters.
            raise EngineError("Send one statement at a time.")
        duckdb = _duckdb()
        with self._lock:
            if self._con is None:
                raise EngineError("No dataset is attached yet.")
            timer = threading.Timer(TIMEOUT_S, self._con.interrupt)
            timer.start()
            try:
                cursor = self._con.execute(sql)
                columns = [d[0] for d in cursor.description or []]
                rows = cursor.fetchmany(MAX_ROWS + 1)
            except duckdb.InterruptException as exc:
                raise EngineError(f"Query took longer than {TIMEOUT_S} s and was stopped.") from exc
            except duckdb.Error as exc:
                raise EngineError(str(exc).splitlines()[0]) from exc
            finally:
                timer.cancel()
        truncated = len(rows) > MAX_ROWS
        rows = [[to_json_value(v) for v in row] for row in rows[:MAX_ROWS]]
        return columns, rows, truncated

    def row_count(self, table):
        return self.query(f"SELECT count(*) FROM {table}")[1][0][0]

    def schema(self, table):
        _, rows, _ = self.query(f"DESCRIBE {table}")
        return [(r[0], r[1]) for r in rows]

    def profile(self, table):
        columns, rows, _ = self.query(f"SUMMARIZE {table}")
        return [dict(zip(columns, row)) for row in rows]


def _copy_sqlite(con, dataset, path):
    """Copy SQLite tables into DuckDB with the stdlib reader (DuckDB's sqlite extension needs a download)."""
    # ponytail: copies every row into memory; fine for local databases up to a few million rows.
    src = sqlite3.connect(Path(path).as_uri() + "?mode=ro", uri=True)
    try:
        names = [r[0] for r in src.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )]
        con.execute(f"CREATE SCHEMA {ident(dataset)}")
        refs = []
        for name in names:
            cur = src.execute(f"SELECT * FROM {ident(name)}")
            cols = [d[0] for d in cur.description]
            target = f"{ident(dataset)}.{ident(name)}"
            first = cur.fetchmany(1000)
            col_defs = ", ".join(f"{ident(c)} {_duck_type(first, i)}" for i, c in enumerate(cols))
            con.execute(f"CREATE TABLE {target} ({col_defs})")
            marks = ", ".join("?" for _ in cols)
            batch = first
            while batch:
                con.executemany(f"INSERT INTO {target} VALUES ({marks})", [list(r) for r in batch])
                batch = cur.fetchmany(10000)
            refs.append(f"{dataset}.{name}")
        return refs
    finally:
        src.close()


def _duck_type(sample, index):
    """Pick a DuckDB type from sampled SQLite values (SQLite columns are loosely typed)."""
    kinds = {type(r[index]) for r in sample if r[index] is not None}
    if kinds <= {int}:
        return "BIGINT"
    if kinds <= {int, float}:
        return "DOUBLE"
    if kinds <= {bytes}:
        return "BLOB"
    return "VARCHAR"
