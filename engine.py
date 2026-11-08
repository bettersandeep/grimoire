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
    ".json": "json", ".jsonl": "json", ".ndjson": "json",
    ".parquet": "parquet", ".pq": "parquet",
    ".sqlite": "sqlite", ".sqlite3": "sqlite", ".db": "sqlite",
}
COMPRESSED = (".gz", ".zst")  # DuckDB reads these CSV and JSON files directly
READERS = {"csv": "read_csv", "json": "read_json_auto", "parquet": "read_parquet"}
MAX_REJECTS = 20
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


def kind_of(path):
    """csv, json, parquet or sqlite from the file name, or None."""
    suffixes = [s.lower() for s in Path(path).suffixes]
    if suffixes and suffixes[-1] in COMPRESSED:
        suffixes.pop()
        kind = KINDS.get(suffixes[-1]) if suffixes else None
        return kind if kind in ("csv", "json") else None
    return KINDS.get(suffixes[-1]) if suffixes else None


def dataset_name(path, name=None):
    base = Path(str(path)).name.split(".", 1)[0]
    return safe_name(name or base)


class Engine:
    def __init__(self):
        self._sources = {}  # dataset name -> (path, kind)
        self._tables = {}   # dataset name -> list of table references
        self._merges = {}   # dataset name -> {(table, column): {from_value: to_value}}
        self._rejects = {}  # (path, mtime, size) -> (count, first rejected lines)
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

    def attach(self, path, name=None, merges=None):
        """merges: {(table, column): {from_value: to_value}} applied to every query of this dataset."""
        real = os.path.realpath(os.path.expanduser(str(path)))
        try:
            os.stat(real)
        except PermissionError as exc:
            raise EngineError(
                f"macOS or your system blocked access to {path}. Allow Hermes in System Settings > "
                "Privacy & Security > Files and Folders, or move the file to another folder."
            ) from exc
        except OSError:
            pass
        if not os.path.isfile(real):
            raise EngineError(f"File not found: {path}")
        if not os.access(real, os.R_OK):
            raise EngineError(f"No permission to read {path}.")
        kind = kind_of(real)
        if kind is None:
            raise EngineError(
                f"Unsupported file type '{''.join(Path(real).suffixes)}'. "
                "Use CSV, TSV, JSON, NDJSON (also .gz or .zst), Parquet or SQLite."
            )
        dataset = dataset_name(real, name)
        with self._lock:
            previous = self._sources.get(dataset), self._merges.get(dataset)
            self._sources[dataset] = (real, kind)
            self._merges[dataset] = merges or {}
            try:
                self._rebuild()
            except Exception as exc:
                if previous[0] is None:
                    self._sources.pop(dataset)
                    self._merges.pop(dataset)
                else:
                    self._sources[dataset], self._merges[dataset] = previous
                self._rebuild()
                raise EngineError(f"Cannot read {path}: {exc}") from exc
        return dataset, kind

    def forget(self, dataset):
        with self._lock:
            if self._sources.pop(dataset, None) is None:
                raise EngineError(f"Unknown dataset '{dataset}'.")
            self._merges.pop(dataset, None)
            self._rebuild()

    def set_merges(self, dataset, merges):
        """Replace the merge rules of an attached dataset and rebuild, so the next query follows them."""
        with self._lock:
            if dataset not in self._sources:
                raise EngineError(f"Unknown dataset '{dataset}'. Attach it first.")
            previous = self._merges.get(dataset)
            self._merges[dataset] = merges
            try:
                self._rebuild()
            except Exception as exc:
                self._merges[dataset] = previous
                self._rebuild()
                raise EngineError(f"Cannot apply the merge: {exc}") from exc

    def merges(self, dataset):
        return dict(self._merges.get(dataset) or {})

    def rejects(self, dataset):
        """(count, [(line, error, text)]) for rows the CSV reader skipped; (0, []) for other kinds."""
        path, kind = self._sources.get(dataset, (None, None))
        if kind != "csv":
            return 0, []
        return self._rejects.get(_file_key(path), (0, []))

    def _rebuild(self):
        """Build a fresh locked connection. Locked settings cannot change, so every attach rebuilds."""
        con = _duckdb().connect(":memory:", config={
            "autoinstall_known_extensions": False,
            "autoload_known_extensions": False,
        })
        tables, readable = {}, []
        for dataset, (path, kind) in self._sources.items():
            merges = self._merges.get(dataset) or {}
            if kind == "sqlite":
                tables[dataset] = _copy_sqlite(con, dataset, path)
                for ref in tables[dataset]:
                    _merge_in_place(con, ref, merges)
                continue
            source = f"{READERS[kind]}({literal(path)}"
            if kind == "csv":
                # Skip malformed lines instead of guessing one text column; the skipped lines are reported.
                source += ", ignore_errors = true"
                key = _file_key(path)
                if key not in self._rejects:
                    self._rejects[key] = _scan_rejects(con, path)
            source += ")"
            own = merges_for(merges, dataset)
            if own:
                con.execute(f"CREATE VIEW {ident(dataset + '_raw')} AS SELECT * FROM {source}")
            con.execute(f"CREATE VIEW {ident(dataset)} AS {_merged_select(con, source, own)}")
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

    def issues(self, table, profile_rows):
        """Data problems worth asking the user about, as short dicts. Reads only aggregates."""
        found = []
        for r in profile_rows:
            col, typ = r["column_name"], str(r["column_type"]).upper()
            empty = float(r.get("null_percentage") or 0)
            if empty:
                found.append({"column": col, "issue": "empty values", "percent": empty})
            if typ != "VARCHAR":
                continue
            c = ident(col)
            for target, label in (("DOUBLE", "number"), ("DATE", "date")):
                filled, ok = self.query(
                    f"SELECT count({c}), count(try_cast({c} AS {target})) FROM {table}")[1][0]
                if filled and ok < filled and ok >= 0.9 * filled:
                    bad = [row[0] for row in self.query(
                        f"SELECT DISTINCT {c} FROM {table} WHERE {c} IS NOT NULL "
                        f"AND try_cast({c} AS {target}) IS NULL LIMIT 3")[1]]
                    found.append({"column": col, "issue": f"text column that is almost all {label}s",
                                  "bad_rows": filled - ok, "examples": bad})
            if (r.get("approx_unique") or 0) <= 1000:
                rows = self.query(
                    f"SELECT lower(regexp_replace({c}, '[^A-Za-z0-9]', '', 'g')) AS k, {c}, count(*) "
                    f"FROM {table} WHERE {c} IS NOT NULL GROUP BY 1, 2 "
                    f"QUALIFY count(*) OVER (PARTITION BY k) > 1 ORDER BY k, 3 DESC")[1]
                groups = {}
                for key, value, n in rows:
                    groups.setdefault(key, []).append({"value": value, "rows": n})
                for variants in list(groups.values())[:5]:
                    found.append({"column": col, "issue": "spelling variants of one value", "variants": variants})
        return found


def _file_key(path):
    st = os.stat(path)
    return path, st.st_mtime_ns, st.st_size


def _scan_rejects(con, path):
    """Read the whole CSV once and keep the lines the reader could not parse."""
    con.execute(
        f"SELECT count(COLUMNS(*)) FROM read_csv({literal(path)}, store_rejects = true, "
        "rejects_table = 'grimoire_rejects', rejects_scan = 'grimoire_scans')"
    ).fetchall()
    count = con.execute("SELECT count(*) FROM grimoire_rejects").fetchone()[0]
    first = con.execute(
        "SELECT line, error_type, left(csv_line, 200) FROM grimoire_rejects ORDER BY line LIMIT ?",
        [MAX_REJECTS]).fetchall()
    con.execute("DROP TABLE grimoire_rejects")
    con.execute("DROP TABLE grimoire_scans")
    return count, [(int(line), str(err), text) for line, err, text in first]


def merges_for(merges, table):
    """{column: {from: to}} for one table from {(table, column): {from: to}}."""
    return {col: m for (tbl, col), m in merges.items() if tbl == table and m}


def _merged_select(con, source, merges):
    """SELECT over source with each merged text column mapped; columns that are gone are skipped."""
    if not merges:
        return f"SELECT * FROM {source}"
    types = {row[0]: row[1] for row in con.execute(f"DESCRIBE SELECT * FROM {source}").fetchall()}
    parts = [f"{_case(col, m)} AS {ident(col)}" for col, m in merges.items() if types.get(col) == "VARCHAR"]
    return f"SELECT * REPLACE ({', '.join(parts)}) FROM {source}" if parts else f"SELECT * FROM {source}"


def _case(col, mapping):
    whens = " ".join(f"WHEN {literal(a)} THEN {literal(b)}" for a, b in mapping.items())
    return f"CASE {ident(col)} {whens} ELSE {ident(col)} END"


def _merge_in_place(con, ref, merges):
    """SQLite tables are in-memory copies, so merges update the copy (never the file)."""
    dataset, table = ref.split(".", 1)
    target = f"{ident(dataset)}.{ident(table)}"
    types = {row[0]: row[1] for row in con.execute(f"DESCRIBE {target}").fetchall()}
    for col, mapping in merges_for(merges, ref).items():
        if types.get(col) != "VARCHAR":
            continue  # the column is gone or no longer text
        con.execute(f"UPDATE {target} SET {ident(col)} = {_case(col, mapping)}")


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
