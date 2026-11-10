"""Read-only DuckDB engine over the files the user attaches.

Safety model:
- DuckDB runs in memory. CSV and Parquet files are views; SQLite tables are copied in.
- After setup, only the attached files are readable (allowed_paths), all other file
  access is off, extension install and load are off, and the configuration is locked,
  so a query cannot write files, read other files, download code or undo the settings.
- Only read statements are accepted, results are capped, and slow queries are interrupted.
"""

import csv
import datetime
import decimal
import glob
import math
import os
import re
import shutil
import sqlite3
import tempfile
import threading
import time
import uuid
from pathlib import Path

from . import guard

MAX_ROWS = 200
TIMEOUT_S = 30          # one model query
SETUP_TIMEOUT_S = 120   # opening, scanning or profiling a file
SAMPLE_ROWS = 1_000_000  # profile issue checks read a sample of bigger tables
# ponytail: SQLite tables are copied into memory; stream them if large SQLite files matter.
MAX_SQLITE_BYTES = 2 * 1024**3

KINDS = {
    ".csv": "csv", ".tsv": "csv", ".txt": "csv",
    ".json": "json", ".jsonl": "json", ".ndjson": "json",
    ".parquet": "parquet", ".pq": "parquet",
    ".sqlite": "sqlite", ".sqlite3": "sqlite", ".db": "sqlite",
}
COMPRESSED = (".gz", ".zst")  # DuckDB reads these CSV and JSON files directly
READERS = {"csv": "read_csv", "json": "read_json_auto", "parquet": "read_parquet"}
MAX_REJECTS = 20
MAX_FILES = 500  # files in one folder or pattern dataset


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


def cut(value, limit=60):
    """A value from a file, shortened before it reaches the model: long text there could carry instructions."""
    if not isinstance(value, str) or len(value) <= limit:
        return value
    return value[: limit - 1] + "…"


def sql_ref(ref):
    """A table reference for SQL: 'shop' -> "shop", 'db.orders' -> "db"."orders"."""
    return ".".join(ident(part) for part in ref.split(".", 1))


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


def is_many(path):
    """True for a folder or a glob pattern (several files read as one table)."""
    return os.path.isdir(path) or any(ch in str(path) for ch in "*?[")


def files_of(path):
    """The data files behind a path: itself, the data files in a folder, or a glob's matches."""
    if os.path.isdir(path):
        found = [os.path.join(path, n) for n in sorted(os.listdir(path)) if kind_of(n)]
    elif is_many(path):
        found = sorted(glob.glob(path))
    else:
        return [path]
    return [os.path.realpath(f) for f in found if os.path.isfile(f)][:MAX_FILES]


def dataset_name(path, name=None):
    text = str(path).rstrip("/")
    if os.path.isdir(text):
        base = Path(text).name
    elif is_many(text):
        stem = re.split(r"[*?\[]", Path(text).name, 1)[0].split(".", 1)[0].rstrip("_-")
        base = stem or Path(text).parent.name
    else:
        base = Path(text).name.split(".", 1)[0]
    return safe_name(name or base)


def _memory_limit(share=2):
    """A share of physical memory (half by default), so one query cannot take the whole machine."""
    try:
        return f"{os.sysconf('SC_PAGE_SIZE') * os.sysconf('SC_PHYS_PAGES') // share // 1024**2}MiB"
    except (AttributeError, ValueError, OSError):
        return "4GiB"


class Engine:
    def __init__(self, memory_share=2):
        self._memory_share = memory_share  # the Data page runs several small engines: each gets a smaller share
        self._sources = {}  # dataset name -> (path, kind)
        self._tables = {}   # dataset name -> list of table references
        self._merges = {}   # dataset name -> {(table, column): {from_value: to_value}}
        self._rejects = {}  # (path, mtime, size) -> (count, first rejected lines)
        self._opened = {}   # dataset name -> (path, mtime, size) when its view or copy was built
        self._widen = {}    # (path, mtime, size) -> {column: type} for whole-number columns with later decimals
        self._sqlite = {}   # (path, mtime, size) -> (temp folder, exported tables) for SQLite files
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

    def attach(self, path, name=None, merges=None, allow_private=False):
        """merges: {(table, column): {from_value: to_value}} applied to every query of this dataset.
        Files in private folders (credentials, app data) are refused unless allow_private; every file a
        folder or pattern expands to is checked, after links are resolved."""
        expanded = os.path.expanduser(str(path))
        if is_many(expanded):
            return self._attach_many(expanded, name, merges, allow_private)
        real = os.path.realpath(expanded)
        folder = guard.private_folder(real)  # before any file test: the answer must not say whether it exists
        if folder and not allow_private:
            raise EngineError(guard.private_error(folder))
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
        return self._add(real, kind, dataset_name(real, name), merges, path)

    def _attach_many(self, pattern, name, merges, allow_private=False):
        real = os.path.realpath(pattern)
        try:
            files = files_of(real)
        except PermissionError as exc:
            raise EngineError(f"macOS or your system blocked access to {pattern}.") from exc
        if not files:
            raise EngineError(f"No data files match {pattern}.")
        for f in files:
            folder = guard.private_folder(f)
            if folder and not allow_private:
                raise EngineError(guard.private_error(folder))
        kinds = {kind_of(f) for f in files}
        if len(kinds) != 1 or None in kinds or "sqlite" in kinds:
            raise EngineError("A folder or pattern must hold files of one kind: all CSV, all JSON or all Parquet.")
        return self._add(real, kinds.pop(), dataset_name(pattern, name), merges, pattern)

    def _add(self, real, kind, dataset, merges, shown):
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
                raise EngineError(f"Cannot read {shown}: {exc}") from exc
        return dataset, kind

    def fresh(self, dataset):
        """True when the dataset's file has not changed since it was opened."""
        path, _kind = self._sources[dataset]
        try:
            return self._opened.get(dataset) == _file_key(path)
        except OSError:
            return False

    def opened(self, dataset):
        """The file version (path, and each file's time and size) the dataset's table was built from."""
        return self._opened.get(dataset)

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
        """(count, [(where, error, text)]) for rows the CSV reader skipped; (0, []) for other kinds."""
        path, kind = self._sources.get(dataset, (None, None))
        if kind != "csv":
            return 0, []
        return self._rejects.get(_file_key(path), (0, []))

    def _rebuild(self):
        """Build a fresh locked connection. Locked settings cannot change, so every attach rebuilds."""
        con = _duckdb().connect(":memory:", config={
            "autoinstall_known_extensions": False,
            "autoload_known_extensions": False,
            "memory_limit": _memory_limit(self._memory_share),
        })
        con.execute("SET enable_progress_bar = false")
        tables, readable = {}, []
        for dataset, (path, kind) in self._sources.items():
            merges = self._merges.get(dataset) or {}
            if not os.path.isfile(path) and not (is_many(path) and files_of(path)):
                continue  # the file was deleted or moved: drop its table, keep every other dataset working
            if kind == "sqlite":
                key = _file_key(path)
                if key not in self._sqlite:  # export once per file version; every rebuild only reloads the CSVs
                    for old in [k for k in self._sqlite if k[0] == path]:  # an older version of this file
                        shutil.rmtree(self._sqlite.pop(old)[0], ignore_errors=True)
                    folder = tempfile.mkdtemp(prefix="grimoire-sqlite-")
                    try:
                        self._sqlite[key] = (folder, _export_sqlite(path, folder))
                    except Exception:
                        shutil.rmtree(folder, ignore_errors=True)
                        raise
                tables[dataset] = _load_sqlite(con, dataset, self._sqlite[key][1])
                for ref in tables[dataset]:
                    _merge_in_place(con, ref, merges)
                continue
            files = files_of(path)
            target = _list_literal(files) if is_many(path) else literal(path)
            source = f"{READERS[kind]}({target}"
            if is_many(path):
                source += ", union_by_name = true, filename = true"  # a filename column says which file
            if kind == "csv":
                # Skip malformed lines instead of guessing one text column; the skipped lines are reported.
                source += ", ignore_errors = true"
                key = _file_key(path)
                if key not in self._rejects:
                    self._rejects[key] = _with_timeout(con, SETUP_TIMEOUT_S, _scan_files, con, files, is_many(path))
            key = _file_key(path)
            if key not in self._widen:
                try:
                    self._widen[key] = _with_timeout(con, SETUP_TIMEOUT_S, _late_decimals, con, kind, source + ")")
                except Exception:
                    self._widen[key] = {}  # ponytail: a timeout keeps the sampled types; such files are huge
            source += _pin_types(con, kind, source + ")", self._widen[key])
            source += ")"
            own = merges_for(merges, dataset)
            if own:
                con.execute(f"CREATE VIEW {ident(dataset + '_raw')} AS SELECT * FROM {source}")
            con.execute(f"CREATE VIEW {ident(dataset)} AS {_merged_select(con, source, own)}")
            con.execute(f"SELECT * FROM {ident(dataset)} LIMIT 0")  # fail now on a bad file
            tables[dataset] = [dataset]
            readable.extend(files)
        con.execute("SET allowed_paths = ?", [readable])
        con.execute("SET enable_external_access = false")
        con.execute("SET lock_configuration = true")
        self._opened = {name: _file_key(path) for name, (path, _kind) in self._sources.items() if name in tables}
        old, self._con, self._tables = self._con, con, tables
        if old is not None:
            old.close()

    def query(self, sql, timeout=TIMEOUT_S):
        """Run one read statement. Returns (columns, rows, truncated)."""
        duckdb = _duckdb()
        with self._lock:
            if self._con is None:
                raise EngineError("No dataset is attached yet.")
            # DuckDB's own parser decides: exactly one statement, and it must be a SELECT
            # (this covers WITH, FROM, DESCRIBE, SUMMARIZE, SHOW, VALUES and TABLE, and
            # rejects WITH ... INSERT/UPDATE/DELETE, which start like a read).
            try:
                statements = self._con.extract_statements(sql)
            except duckdb.Error as exc:
                raise EngineError(str(exc).splitlines()[0]) from exc
            if len(statements) != 1:
                raise EngineError("Send exactly one statement.")
            if statements[0].type != duckdb.StatementType.SELECT:
                raise EngineError("Only read queries are allowed (SELECT, WITH, FROM, DESCRIBE, SUMMARIZE, SHOW).")
            timer = threading.Timer(timeout, self._con.interrupt)
            timer.start()
            try:
                cursor = self._con.execute(sql)
                columns = [d[0] for d in cursor.description or []]
                rows = cursor.fetchmany(MAX_ROWS + 1)
            except duckdb.InterruptException as exc:
                raise EngineError(f"Query took longer than {timeout} s and was stopped. "
                                  "Aggregate more, or filter to fewer rows.") from exc
            except duckdb.Error as exc:
                raise EngineError(str(exc).splitlines()[0]) from exc
            finally:
                timer.cancel()
        truncated = len(rows) > MAX_ROWS
        rows = [[to_json_value(v) for v in row] for row in rows[:MAX_ROWS]]
        return columns, rows, truncated

    def function_exists(self, name):
        with self._lock:
            if self._con is None:
                return False
            return bool(self._con.execute(
                "SELECT count(*) FROM duckdb_functions() WHERE function_name = ?", [name]).fetchone()[0])

    def row_count(self, table):
        return self.query(f"SELECT count(*) FROM {table}", SETUP_TIMEOUT_S)[1][0][0]

    def schema(self, table):
        _, rows, _ = self.query(f"DESCRIBE {table}")
        return [(r[0], r[1]) for r in rows]

    def profile(self, table):
        """(SUMMARIZE rows as dicts, the table the checks must read, sampled).
        The checks read the table once or more per column, and every read of a view parses the file again
        (800,000 rows, 27 columns: 16 s). So the rows are copied into memory once: all of them up to
        SAMPLE_ROWS, a repeatable random sample above that (sampled is then True)."""
        sampled = self.row_count(table) > SAMPLE_ROWS
        copy = (f"CREATE OR REPLACE TEMP TABLE grimoire_sample AS SELECT * FROM {table}"
                + (f" USING SAMPLE {SAMPLE_ROWS} ROWS (reservoir, 7)" if sampled else ""))
        try:
            with self._lock:
                _with_timeout(self._con, SETUP_TIMEOUT_S, self._con.execute, copy)
            source = "grimoire_sample"
        except Exception:
            if sampled:
                raise
            source = table  # no room for the copy: read the file itself, slower but the same result
        columns, rows, _ = self.query(f"SUMMARIZE {source}", SETUP_TIMEOUT_S)
        return [dict(zip(columns, row)) for row in rows], source, sampled

    def column_stats(self, table, column, typ):
        """Detailed statistics for one column: spread and outliers for numbers, top values for text,
        range and rows per month for dates."""
        c, typ = ident(column), str(typ).upper()
        q = lambda sql: self.query(sql, SETUP_TIMEOUT_S)[1]
        filled, empty = q(f"SELECT count({c}), count(*) - count({c}) FROM {table}")[0]
        out = {"column": column, "type": typ, "filled": filled, "empty": empty}
        numeric = is_number_type(typ)
        if numeric and filled:
            row = q(f"SELECT min({c}), quantile_cont({c}, [0.05, 0.25, 0.5, 0.75, 0.95]), max({c}), avg({c}), "
                    f"stddev_samp({c}), count(*) FILTER ({c} < 0), count(*) FILTER ({c} = 0) FROM {table}")[0]
            p05, q1, med, q3, p95 = row[1]
            low, high = q1 - 1.5 * (q3 - q1), q3 + 1.5 * (q3 - q1)
            outliers = q(f"SELECT count(*) FILTER ({c} < {low} OR {c} > {high}) FROM {table}")[0][0]
            extremes = [r[0] for r in q(f"SELECT {c} FROM {table} WHERE {c} < {low} OR {c} > {high} "
                                        f"ORDER BY abs({c} - {med}) DESC LIMIT 3")]
            out.update(min=row[0], p05=p05, p25=q1, median=med, p75=q3, p95=p95, max=row[2],
                       mean=row[3], stddev=row[4], negative=row[5], zero=row[6],
                       outliers={"rule": "outside 1.5 x IQR", "rows": outliers, "most_extreme": extremes})
        elif ("DATE" in typ or "TIMESTAMP" in typ) and filled:
            lo, hi = q(f"SELECT min({c}), max({c}) FROM {table}")[0]
            months = q(f"SELECT strftime(date_trunc('month', {c}), '%Y-%m') m, count(*) FROM {table} "
                       f"WHERE {c} IS NOT NULL GROUP BY 1 ORDER BY 1 LIMIT 36")
            out.update(min=lo, max=hi, rows_per_month=[[m, n] for m, n in months])
        elif filled:
            distinct, blank, shortest, longest = q(
                f"SELECT count(DISTINCT {c}), count(*) FILTER (trim({c}::VARCHAR) = ''), "
                f"min(length({c}::VARCHAR)), max(length({c}::VARCHAR)) FROM {table}")[0]
            top = q(f"SELECT {c}, count(*) n FROM {table} WHERE {c} IS NOT NULL GROUP BY 1 ORDER BY n DESC, 1 LIMIT 10")
            out.update(distinct=distinct, blank_text=blank, length=[shortest, longest],
                       top_values=[[cut(v), n] for v, n in top])
        return out

    def duplicate_rows(self, table):
        """Rows that exactly repeat another row (extra copies only)."""
        return self.query(f"SELECT (SELECT count(*) FROM {table}) - (SELECT count(*) FROM (SELECT DISTINCT * FROM {table}))",
                          SETUP_TIMEOUT_S)[1][0][0]

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
                                  "bad_rows": filled - ok, "examples": [cut(b) for b in bad]})
            if (r.get("approx_unique") or 0) <= 1000:
                counts = dict(self.query(f"SELECT {c}, count(*) FROM {table} WHERE {c} IS NOT NULL GROUP BY 1")[1])
                for group in variant_groups(counts)[:5]:
                    found.append({"column": col, "issue": "spelling variants of one value",
                                  "variants": [{"value": cut(v), "rows": counts[v]} for v in group]})
        return found + self.suspicious(table, profile_rows)

    def suspicious(self, table, profile_rows, today=None):
        """Placeholders, a column with one value, negative amounts, future dates: one read of the table."""
        checks = suspicious_checks(profile_rows, today or datetime.date.today().isoformat())
        if not checks:
            return []
        counts = self.query("SELECT " + ", ".join(sql for sql, _ in checks) + f" FROM {table}")[1][0]
        found = []
        for (sql, issue), n in zip(checks, counts):
            if issue["issue"] == "same value in every row":
                if n == 1:
                    found.append(issue)
            elif n:
                found.append({**issue, "rows": n})
        return found


PLACEHOLDERS = ("n/a", "na", "#n/a", "null", "none", "nil", "-", "--", "?", "unknown", "tbd", "missing")
SENTINELS = (-9999999, -999999, -99999, -9999, -999, 999, 9999, 99999, 999999, 9999999)
_AMOUNT = re.compile(r"amount|price|cost|revenue|sales|total|qty|quantity|units|cents|paise|fare|fee", re.I)


def _key(text):
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _one_edit(a, b):
    """True when a and b differ by one inserted, deleted or changed letter."""
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) > len(b):
        a, b = b, a
    i = next((i for i, (x, y) in enumerate(zip(a, b)) if x != y), len(a))
    return a[i + (len(a) == len(b)):] == b[i + 1:]


RARE = 0.1  # a variant has at most a tenth of the rows of the value it copies; two common values are both real
FUZZY_MAX = 300  # distinct values compared pair by pair; more than this gets only the exact check


def variant_groups(counts):
    """Groups of labels that look like one value written differently, most rows first.

    counts: {label: rows}. Three general signs, for any kind of data:
    the same letters and digits ('North', 'north '); one letter off, for words of 5 or more letters, when one
    is rare ('Electronics', 'Electroncs'); a rare abbreviation with a dot whose start fits exactly one common
    label ('Calif.' and 'California', 'N. Region' and 'North').
    """
    labels = [v for v in counts if isinstance(v, str) and _key(v)]
    parent = {v: v for v in labels}

    def root(v):
        while parent[v] != v:
            v = parent[v]
        return v

    def join(a, b):
        parent[root(a)] = root(b)

    by_key = {}
    for v in labels:
        by_key.setdefault(_key(v), []).append(v)
    for same in by_key.values():
        for v in same[1:]:
            join(v, same[0])
    keys = list(by_key)
    if len(keys) <= FUZZY_MAX:
        size = {k: sum(counts[v] for v in by_key[k]) for k in keys}
        rare = lambda a, b: min(size[a], size[b]) <= RARE * max(size[a], size[b])
        for i, a in enumerate(keys):
            for b in keys[i + 1:]:
                if min(len(a), len(b)) >= 5 and a.isalpha() and b.isalpha() and rare(a, b) and _one_edit(a, b):
                    join(by_key[a][0], by_key[b][0])
        for v in labels:
            m = re.match(r"\s*([A-Za-z]{1,6})\.", v)
            if not m:
                continue
            start = m.group(1).lower()
            fits = [k for k in keys if k != _key(v) and k.startswith(start) and len(k) > len(start)]
            if len(fits) == 1 and rare(_key(v), fits[0]):
                join(v, by_key[fits[0]][0])
    groups = {}
    for v in labels:
        groups.setdefault(root(v), []).append(v)
    out = [sorted(g, key=lambda v: -counts[v]) for g in groups.values() if len(g) > 1]
    return sorted(out, key=lambda g: -sum(counts[v] for v in g))


def _as_number(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def suspicious_checks(profile_rows, today):
    """(SQL count expression, issue) pairs for values that look wrong. Decided from the profile, so the
    data is read once for all of them. today: an ISO date, passed in so the check is testable."""
    checks, placeholder_list = [], ", ".join(literal(v) for v in PLACEHOLDERS)
    for r in profile_rows:
        col, typ = r["column_name"], str(r["column_type"]).upper()
        c, lo, hi = ident(col), r.get("min"), r.get("max")
        if (r.get("approx_unique") or 0) <= 1 and (r.get("count") or 0) > 1 and float(r.get("null_percentage") or 0) < 100:
            checks.append((f"count(DISTINCT {c})", {"column": col, "issue": "same value in every row"}))
        if typ == "VARCHAR":
            checks.append((f"count_if(lower(trim({c})) IN ({placeholder_list}))",
                           {"column": col, "issue": "placeholder text like 'N/A', '-' or 'unknown'"}))
        elif is_number_type(typ):
            for v in {_as_number(lo), _as_number(hi)} & set(SENTINELS):
                checks.append((f"count_if({c} = {v:g})", {"column": col, "issue": f"{v:g} may be a placeholder", "value": v}))
            if _AMOUNT.search(col) and (_as_number(lo) or 0) < 0:
                checks.append((f"count_if({c} < 0)", {"column": col, "issue": "negative values"}))
        elif typ.startswith(("DATE", "TIMESTAMP")) and hi is not None and str(hi)[:10] > today:
            checks.append((f"count_if(CAST({c} AS DATE) > DATE {literal(today)})",
                           {"column": col, "issue": "dates in the future", "max": str(hi)[:19]}))
    return checks


def _file_key(path):
    """Changes when the file changes, or when a folder or pattern gains, loses or changes a file."""
    keys = []
    for f in files_of(path):
        st = os.stat(f)
        keys.append((f, st.st_mtime_ns, st.st_size))
    return path, tuple(keys)


def _list_literal(files):
    return "[" + ", ".join(literal(f) for f in files) + "]"


def _with_timeout(con, seconds, fn, *args):
    timer = threading.Timer(seconds, con.interrupt)
    timer.start()
    try:
        return fn(*args)
    finally:
        timer.cancel()


_WHOLE = {"TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT", "UTINYINT", "USMALLINT", "UINTEGER", "UBIGINT",
          "UHUGEINT"}
_FRACTION = {"DOUBLE", "FLOAT", "REAL"}


def is_number_type(typ):
    """True for a single number column; not for INTERVAL, a list such as BIGINT[], or a struct."""
    t = str(typ).upper().strip()
    return t in _WHOLE or t in _FRACTION or bool(re.fullmatch(r"(DECIMAL|NUMERIC)(\(\d+,\s*\d+\))?", t))


def _late_decimals(con, kind, source):
    """{column: 'DOUBLE'} for columns DuckDB typed as whole numbers from its sample of the first rows, but that
    hold decimals further down (30,000 rows of 100, then 0.4: the 0.4 would be read as 0). One full read."""
    whole = [c for c, t, *_ in con.execute(f"DESCRIBE SELECT * FROM {source}").fetchall() if t in _WHOLE]
    if not whole:
        return {}
    if kind == "csv":  # every value as text, so "N/A" or "0.4" cannot hide behind the sampled type
        text = source[:-1] + ", all_varchar = true)"
        frac = lambda c: f"bool_or(try_cast({ident(c)} AS DOUBLE) <> floor(try_cast({ident(c)} AS DOUBLE)))"
        found = con.execute(f"SELECT {', '.join(frac(c) for c in whole)} FROM {text}").fetchone()
        return {c: "DOUBLE" for c, yes in zip(whole, found) if yes}
    full = dict((c, t) for c, t, *_ in con.execute(f"DESCRIBE SELECT * FROM {source[:-1]}, sample_size = -1)").fetchall())
    return {c: "DOUBLE" for c in whole if full.get(c) in ("DOUBLE", "FLOAT") or str(full.get(c, "")).startswith("DECIMAL")}


def _pin_types(con, kind, source, widen):
    """Reader options that fix the widened column types: types for CSV; for JSON every column must be named."""
    if not widen:
        return ""
    if kind == "csv":
        return ", types = {" + ", ".join(f"{literal(c)}: '{t}'" for c, t in widen.items()) + "}"
    cols = [(c, widen.get(c, t)) for c, t, *_ in con.execute(f"DESCRIBE SELECT * FROM {source}").fetchall()]
    return ", columns = {" + ", ".join(f"{literal(c)}: {literal(t)}" for c, t in cols) + "}"


def _scan_files(con, files, label):
    """Skipped lines over one or more files (DuckDB cannot collect rejects across a merged read)."""
    total, first = 0, []
    for f in files:
        count, lines = _scan_rejects(con, literal(f))
        total += count
        prefix = f"{Path(f).name} " if label else ""
        first += [(f"{prefix}line {line}", err, text) for line, err, text in lines]
    return total, first[:MAX_REJECTS]


def _scan_rejects(con, target):
    """Read the whole CSV once and keep the lines the reader could not parse. target: the reader's
    arguments before the reject options (a path literal or list, plus options)."""
    con.execute(
        f"SELECT count(COLUMNS(*)) FROM read_csv({target}, store_rejects = true, "
        "rejects_table = 'grimoire_rejects', rejects_scan = 'grimoire_scans')"
    ).fetchall()
    # one bad line can be reported more than once (several errors, or by the sniffer and the scan)
    count = con.execute("SELECT count(DISTINCT line) FROM grimoire_rejects").fetchone()[0]
    first = con.execute(
        "SELECT line, string_agg(DISTINCT error_type, ', '), left(any_value(csv_line), 200) "
        "FROM grimoire_rejects GROUP BY line ORDER BY line LIMIT ?", [MAX_REJECTS]).fetchall()
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


_NULL = "\ue000"  # stands for NULL in the export; a private-use character no real text holds


def _export_sqlite(path, folder):
    """Write each SQLite table to a CSV in folder with the stdlib reader. Returns [(table, csv, [(col, type)])].
    DuckDB's own sqlite extension would need a download at run time, which Grimoire never does."""
    if os.path.getsize(path) > MAX_SQLITE_BYTES:
        raise EngineError(f"This SQLite file is over {MAX_SQLITE_BYTES // 1024**3} GB. "
                          "Export the tables you need to Parquet or CSV and attach those.")
    src = sqlite3.connect(Path(path).as_uri() + "?mode=ro", uri=True)
    deadline = time.monotonic() + SETUP_TIMEOUT_S
    src.set_progress_handler(lambda: int(time.monotonic() > deadline), 10000)  # nonzero stops a slow view
    try:
        names = [r[0] for r in src.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )]
        out = []
        for i, name in enumerate(names):
            cur = src.execute(f"SELECT * FROM {ident(name)}")
            cols = [d[0] for d in cur.description]
            types = _sqlite_types(src, name, cols)
            target = os.path.join(folder, f"t{i}.csv")
            with open(target, "w", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh, lineterminator="\n")
                for row in cur:
                    w.writerow([_NULL if v is None else v.hex() if isinstance(v, bytes) else v for v in row])
            out.append((name, target, list(zip(cols, types))))
        return out
    finally:
        src.close()


def _load_sqlite(con, dataset, tables):
    """Create the DuckDB tables from the exported CSVs: one fast read each, then the right type per column."""
    con.execute(f"CREATE SCHEMA {ident(dataset)}")
    refs = []
    for name, target, cols in tables:
        spec = "{" + ", ".join(f"'c{i}': 'VARCHAR'" for i in range(len(cols))) + "}"
        cast = {"BIGINT": "CAST(c{0} AS BIGINT)", "DOUBLE": "CAST(c{0} AS DOUBLE)", "BLOB": "unhex(c{0})"}
        select = ", ".join(f"{cast.get(t, 'c{0}').format(i)} AS {ident(c)}" for i, (c, t) in enumerate(cols)) or "*"
        con.execute(f"CREATE TABLE {ident(dataset)}.{ident(name)} AS SELECT {select} FROM read_csv({literal(target)}, "
                    f"header = false, auto_detect = false, delim = ',', quote = '\"', escape = '\"', "
                    f"new_line = '\\n', columns = {spec}, nullstr = {literal(_NULL)})")
        refs.append(f"{dataset}.{name}")
    return refs


def _sqlite_types(src, table, cols):
    """A DuckDB type per column from the storage classes of every row (SQLite columns are loosely typed:
    a DECIMAL column holds 100 as integer and 100.49 as real; a text value can come after a million numbers)."""
    if not cols:
        return []
    parts = [f"max(typeof({ident(c)}) = '{k}')" for c in cols for k in ("integer", "real", "blob", "text")]
    flags = src.execute(f"SELECT {', '.join(parts)} FROM {ident(table)}").fetchone()
    out = []
    for i in range(len(cols)):
        integer, real, blob, text = (bool(x) for x in flags[4 * i:4 * i + 4])
        out.append("VARCHAR" if text or (blob and (integer or real)) else "BLOB" if blob
                   else "DOUBLE" if real else "BIGINT")
    return out
