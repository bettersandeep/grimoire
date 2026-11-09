"""Desktop API for Grimoire: read the saved catalog and queries, change learning settings and merges.

Hermes imports this file standalone and serves it at /api/plugins/grimoire. It loads the sibling
store, learning and commands modules by path, and opens the profile's plugin database per request.
Checks and charts made on the page run on the page's own locked, read-only DuckDB engine, so they
never touch the chat's engine and cost no model tokens. The chat process applies merges and forgets.
"""

import hashlib
import importlib.util
import re
import sys
import threading
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException

_ROOT = Path(__file__).resolve().parents[1]
_PKG = "_grimoire_dashboard_" + hashlib.sha256(str(_ROOT).encode()).hexdigest()[:12]


def _load(name):
    full = f"{_PKG}.{name}"
    if full in sys.modules:
        return sys.modules[full]
    if _PKG not in sys.modules:  # an empty package, so relative imports inside the modules resolve
        pkg = importlib.util.module_from_spec(importlib.util.spec_from_loader(_PKG, loader=None, is_package=True))
        pkg.__path__ = [str(_ROOT)]
        sys.modules[_PKG] = pkg
    spec = importlib.util.spec_from_file_location(full, _ROOT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[full] = module
    spec.loader.exec_module(module)
    return module


store = _load("store")
learning = _load("learning")
report = _load("report")
engine = _load("engine")
builder = _load("builder")
tools = _load("tools")
router = APIRouter()
_engines = {}  # dataset -> Engine with only that file; ponytail: kept for the process lifetime, few files per user
_engine_lock = threading.Lock()


def _db():
    from plugins.plugin_storage import plugin_db  # follows the active profile on every call
    db = plugin_db("grimoire")
    store.init(db)
    return db


def _version():
    m = re.search(r'^version:\s*"?([^"\n]+)"?', (_ROOT / "plugin.yaml").read_text(encoding="utf-8"), re.M)
    return m.group(1) if m else "?"


def _merge_lines(merges):
    out = []
    for (tbl, col), mapping in merges.items():
        name = col if "." not in tbl else f"{tbl.split('.', 1)[1]}.{col}"
        out += [{"column": name, "from": a, "to": b} for a, b in mapping.items()]
    return out


@router.get("/summary")
def summary():
    db = _db()
    learn = store.get_setting(db, "learn", "off") == "on"
    datasets = []
    added = dict(db.execute("SELECT name, attached_at FROM datasets").fetchall())
    for name, path, kind in store.datasets(db):
        used = db.execute("SELECT count(*) FROM queries WHERE instr(',' || coalesce(datasets, '') || ',', "
                          "',' || ? || ',') > 0", (name,)).fetchone()[0]
        datasets.append({
            "name": name, "path": path, "kind": kind, "added_at": added.get(name),
            "rows": store.get_json(db, f"rows:{name}", None), "queries": used,
            "missing": not Path(path).exists() and not any(ch in path for ch in "*?["),
            "notes": [{"column": col, "note": text} for _t, col, text in store.notes(db, name)],
            "merges": _merge_lines(store.merges(db, name)),
            "issues": store.get_json(db, f"issues:{name}", []),
            "health": store.get_json(db, f"health:{name}", None),
        })
    pending = [{"dataset": d, "column": c, "from": a, "to": b} for d, _t, c, a, b in store.pending_merges(db)]
    return {
        "version": _version(), "learn": learn,
        "predict": learn and store.get_setting(db, "predict", "off") == "on",
        "learn_style": store.get_setting(db, "learn_style", "plain"),
        "predictions": store.get_json(db, "predictions", {"asked": 0, "close": 0}),
        "datasets": datasets, "pending": pending,
        "metrics": [{"name": n, "expression": e} for n, e in store.metrics(db).items()],
        "about": store.get_setting(db, "about_card", "") != "hidden",
    }


@router.get("/queries")
def queries(dataset: str | None = None, limit: int = 30):
    db = _db()
    limit = max(1, min(limit, 100))
    if dataset:
        ids = [q["id"] for q in store.queries_for(db, dataset, limit)][::-1]
    else:
        ids = [f"q{i}" for i, _p, _s in store.recent_queries(db, limit)]
    out = []
    for qid in ids:
        q = store.get_query(db, qid)
        if q:
            q["total_rows"] = len(q["rows"])
            chart = report.chart_data(q)  # heatmap, histogram or scatter, from all rows; the page draws it
            if chart:
                q["chart"] = chart
            q["rows"] = q["rows"][:50]
            out.append(q)
    return {"queries": out}


@router.get("/queries/{qid}/explain")
def explain(qid: str):
    q = store.get_query(_db(), qid)
    if q is None:
        raise HTTPException(404, f"No query {qid}.")
    steps = store.get_json(_db(), f"steps:{q['id']}", [])  # saved when the chat computed them (needs DuckDB)
    plain = ("In plain words:\n" + "\n".join(steps) + "\n\n") if steps else ""
    return {"id": q["id"], "text": plain + learning.explain(q["sql"], q["question"], q["columns"])}


@router.post("/settings")
def settings(body: dict = Body(...)):
    db = _db()
    if "learn" in body:
        store.set_setting(db, "learn", "on" if body["learn"] else "off")
        if not body["learn"]:
            store.set_setting(db, "predict", "off")
    if body.get("learn_style") in ("plain", "sql"):
        store.set_setting(db, "learn_style", body["learn_style"])
    if body.get("hide_about"):
        store.set_setting(db, "about_card", "hidden")
    if "predict" in body:
        if body["predict"] and store.get_setting(db, "learn", "off") != "on":
            raise HTTPException(400, "Turn on learning mode first.")
        store.set_setting(db, "predict", "on" if body["predict"] else "off")
    return summary()


@router.post("/merges/approve")
def approve():
    store.approve_merges(_db())
    return summary()


@router.post("/merges/reject")
def reject():
    store.reject_merges(_db())
    return summary()


@router.post("/datasets/{name}/forget")
def forget(name: str):
    counts = store.forget_dataset(_db(), name)
    if not any(counts.values()):
        raise HTTPException(404, f"Nothing saved for {name}.")
    return summary()


def _engine_for(db, name):
    """The page's engine for one saved file, rebuilt when the file or its merges change."""
    paths = {n: p for n, p, _k in store.datasets(db)}
    if name not in paths:
        raise HTTPException(404, f"No file named {name}.")
    merges = store.merges(db, name)
    eng = _engines.get(name)
    if eng is None or eng.datasets[name][0] != paths[name] or not eng.fresh(name) or eng.merges(name) != merges:
        eng = engine.Engine()
        eng.attach(paths[name], name, merges=merges)
        _engines[name] = eng
    return eng


@router.post("/datasets/{name}/check")
def check(name: str):
    """Find data problems and score the file's health; the page asks for this for files not checked yet."""
    db = _db()
    with _engine_lock:
        try:
            eng = _engine_for(db, name)
            tables = eng.tables(name)
            if len(tables) != 1:
                raise HTTPException(400, f"{name} has {len(tables)} tables; ask in a chat to check one.")
            tools._quality(db, eng, name, tables[0])
        except engine.EngineError as exc:
            raise HTTPException(400, str(exc)) from exc
    return summary()


@router.get("/datasets/{name}/columns")
def columns(name: str):
    db = _db()
    with _engine_lock:
        try:
            eng = _engine_for(db, name)
            return {"tables": [{"table": ref, "columns": [{"name": c, "type": t, "kind": builder.kind(t)}
                                                          for c, t in eng.schema(tools._sql_ref(ref))]}
                               for ref in eng.tables(name)]}
        except engine.EngineError as exc:
            raise HTTPException(400, str(exc)) from exc


@router.post("/charts")
def chart(body: dict = Body(...)):
    """Build, run and save a chart query from the page's choices; returns its query id."""
    db = _db()
    name = str(body.get("dataset") or "")
    with _engine_lock:
        try:
            eng = _engine_for(db, name)
            refs = eng.tables(name)
            ref = body.get("table") or refs[0]
            if ref not in refs:
                raise HTTPException(400, f"No table {ref} in {name}.")
            table = tools._sql_ref(ref)
            sql, purpose = builder.build(table, dict(eng.schema(table)), body)
            cols, rows, truncated = eng.query(sql)
        except (engine.EngineError, builder.BuildError) as exc:
            raise HTTPException(400, str(exc)) from exc
    return {"id": store.save_query(db, "desktop", sql, purpose, cols, rows, truncated, datasets=[name])}
