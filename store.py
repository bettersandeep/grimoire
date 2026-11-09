"""Durable state in the plugin's SQLite database: datasets, column profiles and notes, and queries."""

import json
import sqlite3
import time

# A chat that sends more tools than this runs full Hermes; a Grimoire-only bot sends fewer.
LEAN_TOOLS = 15

SCHEMA = """
CREATE TABLE IF NOT EXISTS datasets (
    name        TEXT PRIMARY KEY,
    path        TEXT NOT NULL,
    kind        TEXT NOT NULL,
    attached_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS columns (
    dataset   TEXT NOT NULL,
    tbl       TEXT NOT NULL,
    col       TEXT NOT NULL,
    type      TEXT,
    profile   TEXT,
    note      TEXT,
    PRIMARY KEY (dataset, tbl, col)
);
CREATE TABLE IF NOT EXISTS merges (
    dataset    TEXT NOT NULL,
    tbl        TEXT NOT NULL,
    col        TEXT NOT NULL,
    from_value TEXT NOT NULL,
    to_value   TEXT NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY (dataset, tbl, col, from_value)
);
CREATE TABLE IF NOT EXISTS pending_merges (
    dataset    TEXT NOT NULL,
    tbl        TEXT NOT NULL,
    col        TEXT NOT NULL,
    from_value TEXT NOT NULL,
    to_value   TEXT NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY (dataset, tbl, col, from_value)
);
CREATE TABLE IF NOT EXISTS metrics (
    name       TEXT PRIMARY KEY,
    expression TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS queries (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT,
    sql        TEXT NOT NULL,
    purpose    TEXT,
    columns    TEXT NOT NULL,
    rows       TEXT NOT NULL,
    truncated  INTEGER NOT NULL,
    created_at REAL NOT NULL
);
"""


def init(db):
    db.executescript(SCHEMA)
    cols = {row[1] for row in db.execute("PRAGMA table_info(queries)")}
    # datasets (0.4.1): which files a query read, so forget can delete it; question (0.5.0): the user's words
    for col in ("datasets", "question"):
        if col not in cols:
            try:
                db.execute(f"ALTER TABLE queries ADD COLUMN {col} TEXT")
            except sqlite3.OperationalError as exc:  # two page requests can migrate at the same time
                if "duplicate column" not in str(exc):
                    raise
    db.commit()


def get_json(db, key, default=None):
    value = get_setting(db, key)
    return default if value is None else json.loads(value)


def set_json(db, key, value):
    set_setting(db, key, json.dumps(value))


def get_setting(db, key, default=None):
    row = db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row[0] if row else default


def set_setting(db, key, value):
    db.execute("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
               (key, str(value)))
    db.commit()


def save_dataset(db, name, path, kind):
    db.execute(
        "INSERT INTO datasets (name, path, kind, attached_at) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(name) DO UPDATE SET path = excluded.path, kind = excluded.kind, attached_at = excluded.attached_at",
        (name, path, kind, time.time()),
    )
    db.commit()


def forget_dataset(db, name):
    """Delete everything saved about one dataset: profile, notes, merges and the queries that read it."""
    db.execute("DELETE FROM settings WHERE key IN (?, ?, ?, ?)",
               (f"issues:{name}", f"shape:{name}", f"health:{name}", f"rows:{name}"))
    counts = {}
    for table, where in (("datasets", "name = ?"), ("columns", "dataset = ?"), ("merges", "dataset = ?"),
                         ("pending_merges", "dataset = ?"),
                         ("queries", "instr(',' || coalesce(datasets, '') || ',', ',' || ? || ',') > 0")):
        counts[table] = db.execute(f"DELETE FROM {table} WHERE {where}", (name,)).rowcount
    _prune_steps(db)
    db.commit()
    return counts


def _prune_steps(db):
    """Saved plain-words steps hold result values: drop those whose query is gone."""
    db.execute("DELETE FROM settings WHERE key LIKE 'steps:q%' "
               "AND CAST(substr(key, 8) AS INTEGER) NOT IN (SELECT id FROM queries)")


def clear_history(db):
    n = db.execute("DELETE FROM queries").rowcount
    _prune_steps(db)
    db.commit()
    return n


def reset(db):
    for table in ("datasets", "columns", "merges", "pending_merges", "queries", "settings", "metrics"):
        db.execute(f"DELETE FROM {table}")
    db.execute("DELETE FROM sqlite_sequence WHERE name = 'queries'")
    db.commit()


def datasets(db):
    return db.execute("SELECT name, path, kind FROM datasets ORDER BY attached_at").fetchall()


def save_columns(db, dataset, table, cols):
    """cols: list of (name, type, profile dict or None). Keeps existing notes."""
    db.executemany(
        "INSERT INTO columns (dataset, tbl, col, type, profile) VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(dataset, tbl, col) DO UPDATE SET type = excluded.type, "
        "profile = COALESCE(excluded.profile, columns.profile)",
        [(dataset, table, name, typ, json.dumps(prof) if prof else None) for name, typ, prof in cols],
    )
    db.commit()


def set_note(db, dataset, column, note):
    """column may be 'col' or 'table.col'. Returns the number of columns updated."""
    table, _, col = column.rpartition(".")
    if table:
        cur = db.execute(
            "UPDATE columns SET note = ? WHERE dataset = ? AND col = ? AND (tbl = ? OR tbl = ?)",
            (note, dataset, col, table, f"{dataset}.{table}"),
        )
    else:
        cur = db.execute("UPDATE columns SET note = ? WHERE dataset = ? AND col = ?", (note, dataset, col))
    db.commit()
    return cur.rowcount


def notes(db, dataset):
    return db.execute(
        "SELECT tbl, col, note FROM columns WHERE dataset = ? AND note IS NOT NULL ORDER BY tbl, col", (dataset,)
    ).fetchall()


def propose_merge(db, dataset, table, column, values, into):
    """Save a merge the model proposed. It applies only after the user approves it."""
    _upsert_merge(db, "pending_merges", dataset, table, column, values, into)


def pending_merges(db, dataset=None):
    """[(dataset, table, column, from_value, to_value)], oldest first."""
    sql = "SELECT dataset, tbl, col, from_value, to_value FROM pending_merges"
    args = ()
    if dataset:
        sql, args = sql + " WHERE dataset = ?", (dataset,)
    return db.execute(sql + " ORDER BY created_at", args).fetchall()


def approve_merges(db):
    """Move every pending merge into the active rules. Returns the datasets that changed."""
    rows = pending_merges(db)
    for dataset, tbl, col, a, b in rows:
        save_merge(db, dataset, tbl, col, [a], b)
    db.execute("DELETE FROM pending_merges")
    db.commit()
    return sorted({r[0] for r in rows})


def reject_merges(db):
    n = db.execute("DELETE FROM pending_merges").rowcount
    db.commit()
    return n


def save_merge(db, dataset, table, column, values, into):
    """Map each of values to into in dataset.table.column. A value merged before is re-pointed."""
    _upsert_merge(db, "merges", dataset, table, column, values, into)


def _upsert_merge(db, target, dataset, table, column, values, into):
    """Save value -> into rules, kept as chains of one step: after A -> B and then B -> C, A goes to C."""
    now = time.time()
    where = "dataset = ? AND tbl = ? AND col = ?"
    row = db.execute(f"SELECT to_value FROM {target} WHERE {where} AND from_value = ?",
                     (dataset, table, column, into)).fetchone()
    into = row[0] if row else into  # into is itself merged away: point at its final value
    db.executemany(f"UPDATE {target} SET to_value = ? WHERE {where} AND to_value = ?",
                   [(into, dataset, table, column, v) for v in values if v != into])
    db.execute(f"DELETE FROM {target} WHERE {where} AND from_value = to_value", (dataset, table, column))
    db.executemany(
        f"INSERT INTO {target} (dataset, tbl, col, from_value, to_value, created_at) VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(dataset, tbl, col, from_value) DO UPDATE SET to_value = excluded.to_value, "
        "created_at = excluded.created_at",
        [(dataset, table, column, v, into, now) for v in values if v != into],
    )
    db.commit()


def delete_merges(db, dataset, column=None):
    """column may be None (all columns), 'col' or 'table.col'. Returns the number of rules removed."""
    if not column:
        cur = db.execute("DELETE FROM merges WHERE dataset = ?", (dataset,))
        db.commit()
        return cur.rowcount
    table, _, col = column.rpartition(".")
    sql, args = "DELETE FROM merges WHERE dataset = ? AND col = ?", [dataset, col]
    if table:
        sql += " AND (tbl = ? OR tbl = ?)"
        args += [table, f"{dataset}.{table}"]
    cur = db.execute(sql, args)
    db.commit()
    return cur.rowcount


def merges(db, dataset):
    """{(table, column): {from_value: to_value}} for one dataset."""
    out = {}
    for tbl, col, a, b in db.execute(
        "SELECT tbl, col, from_value, to_value FROM merges WHERE dataset = ? ORDER BY created_at", (dataset,)
    ):
        out.setdefault((tbl, col), {})[a] = b
    return out


def define_metric(db, name, expression):
    db.execute("INSERT INTO metrics (name, expression, created_at) VALUES (?, ?, ?) ON CONFLICT(name) DO UPDATE "
               "SET expression = excluded.expression, created_at = excluded.created_at", (name, expression, time.time()))
    db.commit()


def drop_metric(db, name):
    n = db.execute("DELETE FROM metrics WHERE name = ?", (name,)).rowcount
    db.commit()
    return n


def metrics(db):
    """{name: expression}, oldest first."""
    return dict(db.execute("SELECT name, expression FROM metrics ORDER BY created_at").fetchall())


def save_query(db, session_id, sql, purpose, columns, rows, truncated, datasets=(), question=None):
    cur = db.execute(
        "INSERT INTO queries (session_id, sql, purpose, columns, rows, truncated, created_at, datasets, question) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (session_id, sql, purpose, json.dumps(columns), json.dumps(rows), int(truncated), time.time(),
         ",".join(datasets), question),
    )
    db.commit()
    return f"q{cur.lastrowid}"


def get_query(db, query_id):
    row = db.execute(
        "SELECT id, session_id, sql, purpose, columns, rows, truncated, created_at, datasets, question "
        "FROM queries WHERE id = ?",
        (_number(query_id),),
    ).fetchone()
    if row is None:
        return None
    return {
        "id": f"q{row[0]}", "session_id": row[1], "sql": row[2], "purpose": row[3],
        "columns": json.loads(row[4]), "rows": json.loads(row[5]), "truncated": bool(row[6]), "created_at": row[7],
        "datasets": [d for d in (row[8] or "").split(",") if d], "question": row[9],
    }


def queries_for(db, dataset=None, limit=30):
    """Saved queries, oldest first: of one dataset, or else of the most recent session that ran one."""
    cols = "id, session_id, sql, purpose, columns, rows, truncated, created_at, datasets, question"
    if dataset:
        rows = db.execute(f"SELECT {cols} FROM queries WHERE instr(',' || coalesce(datasets, '') || ',', "
                          "',' || ? || ',') > 0 ORDER BY id DESC LIMIT ?", (dataset, limit)).fetchall()
    else:
        last = db.execute("SELECT session_id FROM queries ORDER BY id DESC LIMIT 1").fetchone()
        if not last:
            return []
        rows = db.execute(f"SELECT {cols} FROM queries WHERE session_id IS ? ORDER BY id DESC LIMIT ?",
                          (last[0], limit)).fetchall()
    return [get_query(db, r[0]) for r in reversed(rows)]


def data_dir(db):
    """The folder that holds the plugin database, or None for an in-memory database."""
    for _seq, name, path in db.execute("PRAGMA database_list").fetchall():
        if name == "main" and path:
            return path.rsplit("/", 1)[0]
    return None


def recent_queries(db, limit=5):
    return db.execute(
        "SELECT id, purpose, sql FROM queries ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()


def _number(query_id):
    text = str(query_id).strip().lower().lstrip("q")
    return int(text) if text.isdigit() else -1
