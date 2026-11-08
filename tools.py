"""Tool handlers. Each returns a JSON string, also on error, and never raises."""

import json
import os
import threading

from . import engine
from . import store

_lock = threading.Lock()
_state = {"db": None, "engine": None}


def open_db():
    from plugins.plugin_storage import plugin_db  # Hermes runtime only; the self-test injects its own db
    return plugin_db("grimoire")


def setup(db=None, eng=None):
    """Create the state, or replace it (the self-test passes an in-memory db)."""
    with _lock:
        _state["db"] = db
        _state["engine"] = eng


def _get():
    with _lock:
        if _state["db"] is None:
            _state["db"] = open_db()
        if _state["engine"] is None:
            store.init(_state["db"])
            eng = engine.Engine()
            for name, path, _kind in store.datasets(_state["db"]):
                if os.path.isfile(path):
                    try:
                        eng.attach(path, name)
                    except engine.EngineError:
                        pass  # the file changed or broke; the catalog still lists it as missing
            _state["engine"] = eng
        return _state["db"], _state["engine"]


def _ok(**data):
    return json.dumps(data, ensure_ascii=False, default=str)


def _err(message):
    return json.dumps({"error": message})


def _resolve_table(eng, dataset, table=None):
    tables = eng.tables(dataset)
    if table:
        for ref in tables:
            if table in (ref, ref.split(".", 1)[-1]):
                return ref
        raise engine.EngineError(f"Table '{table}' not in dataset '{dataset}'. Tables: {', '.join(tables)}")
    if len(tables) != 1:
        raise engine.EngineError(f"Dataset '{dataset}' has several tables; pass one of: {', '.join(tables)}")
    return tables[0]


def _sql_ref(ref):
    return ".".join(engine.ident(part) for part in ref.split(".", 1))


def attach(args, **kwargs):
    try:
        db, eng = _get()
        name, kind = eng.attach(args.get("path", ""), args.get("name"))
        path = eng.datasets[name][0]
        store.save_dataset(db, name, path, kind)
        tables = []
        for ref in eng.tables(name):
            sql_ref = _sql_ref(ref)
            cols = eng.schema(sql_ref)
            store.save_columns(db, name, ref, [(c, t, None) for c, t in cols])
            tables.append({"table": ref, "rows": eng.row_count(sql_ref), "columns": [f"{c} {t}" for c, t in cols]})
        return _ok(dataset=name, kind=kind, tables=tables,
                   hint=f"Query with FROM {_sql_ref(eng.tables(name)[0])}. Profile with grimoire_profile.")
    except engine.EngineError as exc:
        return _err(str(exc))
    except Exception as exc:  # never let a tool crash the turn
        return _err(f"attach failed: {exc}")


def profile(args, **kwargs):
    try:
        db, eng = _get()
        dataset = args.get("dataset", "")
        ref = _resolve_table(eng, dataset, args.get("table"))
        rows = eng.profile(_sql_ref(ref))
        compact, saved = [], []
        for r in rows:
            prof = {
                "null_pct": r.get("null_percentage"),
                "distinct": r.get("approx_unique"),
                "min": _short(r.get("min")),
                "max": _short(r.get("max")),
            }
            saved.append((r["column_name"], r["column_type"], prof))
            compact.append([r["column_name"], r["column_type"], prof["null_pct"], prof["distinct"], prof["min"], prof["max"]])
        store.save_columns(db, dataset, ref, saved)
        return _ok(table=ref, columns=["column", "type", "null_pct", "distinct", "min", "max"], profile=compact)
    except engine.EngineError as exc:
        return _err(str(exc))
    except Exception as exc:
        return _err(f"profile failed: {exc}")


def query(args, session_id=None, **kwargs):
    try:
        db, eng = _get()
        sql = args.get("sql", "")
        columns, rows, truncated = eng.query(sql)
        qid = store.save_query(db, session_id, sql, args.get("purpose"), columns, rows, truncated)
        result = {"id": qid, "columns": columns, "rows": rows}
        if truncated:
            result["truncated"] = f"Only the first {engine.MAX_ROWS} rows are shown. Aggregate in SQL instead."
        result["cite"] = f"Cite numbers from this result as [{qid}]."
        return _ok(**result)
    except engine.EngineError as exc:
        return _err(str(exc))
    except Exception as exc:
        return _err(f"query failed: {exc}")


def note(args, **kwargs):
    try:
        db, _eng = _get()
        updated = store.set_note(db, args.get("dataset", ""), args.get("column", ""), args.get("note", ""))
        if not updated:
            return _err("No such column in that dataset. Attach or profile the dataset first.")
        return _ok(saved=True, dataset=args.get("dataset"), column=args.get("column"))
    except Exception as exc:
        return _err(f"note failed: {exc}")


def catalog(args, **kwargs):
    try:
        db, eng = _get()
        items = []
        for name, path, kind in store.datasets(db):
            entry = {"dataset": name, "kind": kind, "path": path}
            if name in eng.datasets:
                entry["tables"] = eng.tables(name)
            else:
                entry["status"] = "file missing or unreadable"
            entry["notes"] = [f"{tbl}.{col}: {text}" if "." not in tbl else f"{tbl.split('.', 1)[1]}.{col}: {text}"
                              for tbl, col, text in store.notes(db, name)]
            items.append(entry)
        recent = [{"id": f"q{i}", "purpose": p or s[:80]} for i, p, s in store.recent_queries(db)]
        return _ok(datasets=items, recent_queries=recent)
    except Exception as exc:
        return _err(f"catalog failed: {exc}")


def _short(value, limit=40):
    text = value if isinstance(value, str) else (None if value is None else str(value))
    return text if text is None or len(text) <= limit else text[: limit - 1] + "…"
