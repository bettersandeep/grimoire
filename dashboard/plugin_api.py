"""Desktop API for Grimoire: read the saved catalog and queries, change learning settings and merges.

Hermes imports this file standalone and serves it at /api/plugins/grimoire. It loads the sibling
store, learning and commands modules by path, and opens the profile's plugin database per request.
It never opens DuckDB; the chat process applies merge and forget changes before its next query.
"""

import hashlib
import importlib.util
import re
import sys
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
router = APIRouter()


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
    for name, path, kind in store.datasets(db):
        datasets.append({
            "name": name, "path": path, "kind": kind,
            "missing": not Path(path).exists() and not any(ch in path for ch in "*?["),
            "notes": [{"column": col, "note": text} for _t, col, text in store.notes(db, name)],
            "merges": _merge_lines(store.merges(db, name)),
            "issues": store.get_json(db, f"issues:{name}", []),
            "health": store.get_json(db, f"health:{name}", None),
        })
    size = store.get_json(db, "call_size", {})
    lean_tip = size if size.get("tools", 0) > store.LEAN_TOOLS and store.get_setting(db, "lean_card", "") != "hidden" else None
    pending = [{"dataset": d, "column": c, "from": a, "to": b} for d, _t, c, a, b in store.pending_merges(db)]
    return {
        "version": _version(), "learn": learn,
        "predict": learn and store.get_setting(db, "predict", "off") == "on",
        "predictions": store.get_json(db, "predictions", {"asked": 0, "close": 0}),
        "datasets": datasets, "pending": pending,
        "metrics": [{"name": n, "expression": e} for n, e in store.metrics(db).items()],
        "lean_tip": lean_tip,
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
    return {"id": q["id"], "text": learning.explain(q["sql"], q["question"], q["columns"])}


@router.post("/settings")
def settings(body: dict = Body(...)):
    db = _db()
    if "learn" in body:
        store.set_setting(db, "learn", "on" if body["learn"] else "off")
        if not body["learn"]:
            store.set_setting(db, "predict", "off")
    if body.get("hide_lean_tip"):
        store.set_setting(db, "lean_card", "hidden")
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
