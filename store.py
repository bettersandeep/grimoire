"""Durable state in the plugin's SQLite database: datasets, column profiles and notes, and queries."""

import json
import time

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
    db.commit()


def save_dataset(db, name, path, kind):
    db.execute(
        "INSERT INTO datasets (name, path, kind, attached_at) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(name) DO UPDATE SET path = excluded.path, kind = excluded.kind, attached_at = excluded.attached_at",
        (name, path, kind, time.time()),
    )
    db.commit()


def forget_dataset(db, name):
    db.execute("DELETE FROM datasets WHERE name = ?", (name,))
    db.execute("DELETE FROM columns WHERE dataset = ?", (name,))
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


def save_query(db, session_id, sql, purpose, columns, rows, truncated):
    cur = db.execute(
        "INSERT INTO queries (session_id, sql, purpose, columns, rows, truncated, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (session_id, sql, purpose, json.dumps(columns), json.dumps(rows), int(truncated), time.time()),
    )
    db.commit()
    return f"q{cur.lastrowid}"


def get_query(db, query_id):
    row = db.execute(
        "SELECT id, session_id, sql, purpose, columns, rows, truncated, created_at FROM queries WHERE id = ?",
        (_number(query_id),),
    ).fetchone()
    if row is None:
        return None
    return {
        "id": f"q{row[0]}", "session_id": row[1], "sql": row[2], "purpose": row[3],
        "columns": json.loads(row[4]), "rows": json.loads(row[5]), "truncated": bool(row[6]), "created_at": row[7],
    }


def recent_queries(db, limit=5):
    return db.execute(
        "SELECT id, purpose, sql FROM queries ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()


def _number(query_id):
    text = str(query_id).strip().lower().lstrip("q")
    return int(text) if text.isdigit() else -1
