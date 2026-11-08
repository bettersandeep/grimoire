"""Tool handlers. Each returns a JSON string, also on error, and never raises."""

import json
import os
import re
import threading
from collections import OrderedDict

from . import engine
from . import store
from . import verify

_lock = threading.Lock()
_state = {"db": None, "engine": None}

# Numbers each session's Grimoire tools returned, and numbers the user typed, for the reply check.
# ponytail: in memory, last 50 sessions and 50k values each; lost on restart (cited query ids still work).
_MAX_SESSIONS, _MAX_VALUES = 50, 50000
_values = OrderedDict()
_user_numbers = OrderedDict()
_last = {"session": None}


def _bucket(table, session_id):
    key = session_id or ""
    bucket = table.setdefault(key, [])
    table.move_to_end(key)
    while len(table) > _MAX_SESSIONS:
        table.popitem(last=False)
    return bucket


def remember(session_id, result):
    numbers = verify.numeric_values(result)
    with _lock:
        bucket = _bucket(_values, session_id)
        bucket.extend(numbers)
        del bucket[:-_MAX_VALUES]
        _last["session"] = session_id or ""


def remember_user_message(session_id, text):
    raws = [c["raw"].split()[0].rstrip("%") for c in verify.extract(text)]
    with _lock:
        _bucket(_user_numbers, session_id).extend(raws)


def check_reply(text, session_id=None):
    """Footer for a final reply, or "" when Grimoire was not used or the reply has no numbers."""
    with _lock:
        key = session_id if session_id in _values else (_last["session"] if not session_id else None)
        values = list(_values.get(key, [])) if key is not None else []
        ignore = list(_user_numbers.get(session_id or "", []))
    cited = re.findall(r"\bq(\d+)\b", text or "", re.I)
    if cited:
        db, _eng = _get()
        for qid in dict.fromkeys(cited):
            q = store.get_query(db, qid)
            if q:
                values.extend(verify.numeric_values(q["rows"]))
    if not values:
        return ""
    sourced, unsourced = verify.check(text, values, ignore=ignore)
    return verify.footer(sourced, unsourced)


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
                        eng.attach(path, name, merges=store.merges(_state["db"], name))
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


def attach(args, session_id=None, **kwargs):
    try:
        db, eng = _get()
        path_arg = args.get("path", "")
        wanted = engine.dataset_name(path_arg, args.get("name"))
        name, kind = eng.attach(path_arg, args.get("name"), merges=store.merges(db, wanted))
        path = eng.datasets[name][0]
        store.save_dataset(db, name, path, kind)
        tables = []
        for ref in eng.tables(name):
            sql_ref = _sql_ref(ref)
            cols = eng.schema(sql_ref)
            store.save_columns(db, name, ref, [(c, t, None) for c, t in cols])
            tables.append({"table": ref, "rows": eng.row_count(sql_ref), "columns": [f"{c} {t}" for c, t in cols]})
        remember(session_id, [t["rows"] for t in tables])
        result = {"dataset": name, "kind": kind, "tables": tables}
        skipped, first = eng.rejects(name)
        if skipped:
            result["skipped_lines"] = {
                "count": skipped,
                "first": [f"line {line}: {err}: {text}" for line, err, text in first[:5]],
                "note": "These lines are malformed and are not in any query result. Tell the user.",
            }
        rules = _merge_lines(eng.merges(name))
        if rules:
            result["merges"] = rules
            result["merges_note"] = (f"Queries use the merged values. The data without merges is "
                                     f"FROM {engine.ident(name + '_raw')} (CSV, JSON, Parquet).")
        result["hint"] = f"Query with FROM {_sql_ref(eng.tables(name)[0])}. Profile with grimoire_profile."
        remember(session_id, [skipped])
        return _ok(**result)
    except engine.EngineError as exc:
        return _err(str(exc))
    except Exception as exc:  # never let a tool crash the turn
        return _err(f"attach failed: {exc}")


def profile(args, session_id=None, **kwargs):
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
        issues = eng.issues(_sql_ref(ref), rows)
        remember(session_id, [row[2:] for row in compact])
        remember(session_id, issues)
        result = {"table": ref, "columns": ["column", "type", "null_pct", "distinct", "min", "max"], "profile": compact}
        if issues:
            result["issues"] = issues
            result["issues_note"] = (
                "Tell the user about these problems and ask what they mean before you rely on them "
                "(for example: do empty amounts mean 0?). If the user says variants are the same value, "
                "save it with grimoire_merge so every later query uses it.")
        return _ok(**result)
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
        remember(session_id, rows)
        result = {"id": qid, "columns": columns, "rows": rows}
        if truncated:
            result["truncated"] = f"Only the first {engine.MAX_ROWS} rows are shown. Aggregate in SQL instead."
        result["cite"] = f"Cite numbers from this result as [{qid}]."
        return _ok(**result)
    except engine.EngineError as exc:
        return _err(str(exc))
    except Exception as exc:
        return _err(f"query failed: {exc}")


def merge(args, **kwargs):
    try:
        db, eng = _get()
        dataset = args.get("dataset", "")
        ref = _resolve_table(eng, dataset, args.get("table"))
        column, into = args.get("column", ""), args.get("into")
        values = [v for v in (args.get("values") or []) if isinstance(v, str)]
        if not values or not isinstance(into, str):
            return _err("Pass values (a list of text values) and into (the value to use instead).")
        types = dict(eng.schema(_sql_ref(ref)))
        if column not in types:
            return _err(f"No column '{column}' in {ref}. Columns: {', '.join(types)}")
        if types[column] != "VARCHAR":
            return _err(f"Column '{column}' is {types[column]}. Merges work on text columns only.")
        store.save_merge(db, dataset, ref, column, values, into)
        eng.set_merges(dataset, store.merges(db, dataset))
        return _ok(saved=True, rule=f"{column}: {', '.join(repr(v) for v in values)} -> {into!r}",
                   applies_to=f"Every later query on {dataset}, also in new sessions. The file does not change.",
                   undo=f"/grimoire unmerge {dataset} {column}")
    except engine.EngineError as exc:
        return _err(str(exc))
    except Exception as exc:
        return _err(f"merge failed: {exc}")


def _merge_lines(merges):
    lines = []
    for (tbl, col), mapping in merges.items():
        name = col if "." not in tbl else f"{tbl.split('.', 1)[1]}.{col}"
        lines += [f"{name}: {a!r} -> {b!r}" for a, b in mapping.items()]
    return lines


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
            rules = _merge_lines(store.merges(db, name))
            if rules:
                entry["merges"] = rules
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
