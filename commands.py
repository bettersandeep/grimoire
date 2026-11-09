"""The /grimoire slash command. It runs plugin code only: no model call, no tokens."""

import re
from pathlib import Path

from . import learning, store, tools

HELP = """Commands:
  /grimoire                          status
  /grimoire sql q12                  the SQL and result behind a query id
  /grimoire explain q12              how your question became that SQL
  /grimoire learn on | off           learning mode: a short lesson after data answers
  /grimoire learn predict on | off   guess the answer before you see it (needs learning mode)
  /grimoire rejects [dataset]        malformed lines skipped when a file was read
  /grimoire merges [dataset]         merge rules, applied and waiting for approval
  /grimoire merges approve | reject  apply or drop the merges waiting for approval
  /grimoire unmerge <dataset> [column]   remove merge rules (one column, or all)
  /grimoire forget <dataset>         delete everything saved about one file
  /grimoire clear history            delete all saved queries and results
  /grimoire reset confirm            delete everything Grimoire saved"""


def version():
    text = (Path(__file__).resolve().parent / "plugin.yaml").read_text(encoding="utf-8")
    m = re.search(r'^version:\s*"?([^"\n]+)"?', text, re.M)
    return m.group(1) if m else "?"


def run(raw_args="", **kwargs):
    try:
        db, eng = tools._get()
        words = (raw_args or "").split()
        cmd, rest = (words[0].lower(), words[1:]) if words else ("status", [])
        if cmd in ("status", "help"):
            return _status(db, eng)
        if cmd == "sql" and rest:
            return _sql(db, rest[0])
        if cmd == "explain" and rest:
            return _explain(db, rest[0])
        if cmd == "learn":
            return _learn(db, rest)
        if cmd == "rejects":
            return _rejects(eng, rest[0] if rest else None)
        if cmd == "merges" and rest[:1] == ["approve"]:
            changed = store.approve_merges(db)
            for name in changed:
                if name in eng.datasets:
                    eng.set_merges(name, store.merges(db, name))
            return (f"Applied. Later queries on {', '.join(changed)} use the merged values. "
                    "The files did not change.") if changed else "No merges are waiting for approval."
        if cmd == "merges" and rest[:1] == ["reject"]:
            n = store.reject_merges(db)
            return f"Dropped {n} proposed merge(s)." if n else "No merges are waiting for approval."
        if cmd == "merges":
            return _merges(db, rest[0] if rest else None)
        if cmd == "unmerge" and rest and len(rest) <= 2:
            dataset, column = rest[0], (rest[1] if len(rest) == 2 else None)
            removed = store.delete_merges(db, dataset, column)
            where = f"{dataset}.{column}" if column else dataset
            if not removed:
                return f"No merge rules for {where}."
            if dataset in eng.datasets:
                eng.set_merges(dataset, store.merges(db, dataset))
            return f"Removed {removed} merge rule(s) from {where}. Later queries use the original values."
        if cmd == "forget" and len(rest) == 1:
            counts = store.forget_dataset(db, rest[0])
            if rest[0] in eng.datasets:
                eng.forget(rest[0])
            if not any(counts.values()):
                return f"Nothing saved for {rest[0]}."
            tools.forget_values()
            return (f"Deleted {rest[0]}: {counts['columns']} column profile(s) and notes, "
                    f"{counts['merges'] + counts['pending_merges']} merge rule(s), {counts['queries']} saved "
                    "query(ies). The file did not change. Hermes chat history keeps its own copy of past "
                    "results; delete those sessions in Hermes to remove it.")
        if cmd == "clear" and rest == ["history"]:
            n = store.clear_history(db)
            tools.forget_values()
            return f"Deleted {n} saved query(ies) and their results. Files, notes and merges stay."
        if cmd == "reset":
            if rest != ["confirm"]:
                return ("This deletes every saved file entry, column note, merge rule and query, and cannot "
                        "be undone. Type /grimoire reset confirm to do it.")
            store.reset(db)
            for name in list(eng.datasets):
                eng.forget(name)
            tools.forget_values()
            return "Deleted everything Grimoire saved. Your files did not change."
        return f"Unknown command: /grimoire {raw_args}\n{HELP}"
    except Exception as exc:  # a command must never crash the chat
        return f"/grimoire failed: {exc}"


def _status(db, eng):
    sets = store.datasets(db)
    lines = [f"Grimoire {version()}"]
    if sets:
        lines.append("Data files:")
        for name, path, kind in sets:
            state = "" if name in eng.datasets else "  (file missing or unreadable)"
            lines.append(f"  {name}  {kind}  {path}{state}")
    else:
        lines.append("Data files: none yet. Ask a question about a CSV, JSON, Parquet or SQLite file.")
    learn, predict = tools.learning_state()
    stats = store.get_json(db, "predictions", {"asked": 0, "close": 0})
    score = f" ({stats['close']} of {stats['asked']} guesses within 10%)" if predict and stats["asked"] else ""
    lines.append(f"Learning mode: {'on' if learn else 'off'} · Predictions: {'on' if predict else 'off'}{score}")
    return "\n".join(lines + ["", HELP])


def _learn(db, rest):
    if rest in (["on"], ["off"]):
        store.set_setting(db, "learn", rest[0])
        if rest[0] == "on":
            return ("Learning mode is on. After answers about your data you get one SQL idea and one question "
                    "worth asking. Type /grimoire learn predict on to guess answers first.")
        return "Learning mode is off. Answers have no lessons or predictions."
    if rest in (["predict", "on"], ["predict", "off"]):
        if rest[1] == "on" and store.get_setting(db, "learn", "off") != "on":
            return "Turn on learning mode first: /grimoire learn on"
        store.set_setting(db, "predict", rest[1])
        return ("Predictions are on. Before an answer, you are asked to guess the main number."
                if rest[1] == "on" else "Predictions are off.")
    learn, predict = tools.learning_state()
    return (f"Learning mode: {'on' if learn else 'off'} · Predictions: {'on' if predict else 'off'}\n"
            "Change with /grimoire learn on|off and /grimoire learn predict on|off")


def _explain(db, qid):
    q = store.get_query(db, qid)
    if q is None:
        return f"No query {qid}."
    return f"{q['id']}: {q['purpose'] or ''}".rstrip(": ") + "\n" + learning.explain(q["sql"], q["question"], q["columns"])


def _sql(db, qid):
    q = store.get_query(db, qid)
    if q is None:
        return f"No query {qid}."
    out = [f"{q['id']}: {q['purpose'] or ''}".rstrip(": "), q["sql"], "", " | ".join(q["columns"])]
    out += [" | ".join("" if v is None else str(v) for v in row) for row in q["rows"][:10]]
    if len(q["rows"]) > 10 or q["truncated"]:
        out.append(f"... {len(q['rows'])}{'+' if q['truncated'] else ''} rows in total")
    return "\n".join(out)


def _rejects(eng, dataset):
    names = [dataset] if dataset else list(eng.datasets)
    out = []
    for name in names:
        try:
            count, first = eng.rejects(name)
        except Exception:
            count, first = 0, []
        if count:
            out.append(f"{name}: {count} malformed line(s) skipped")
            out += [f"  line {line}: {err}: {text}" for line, err, text in first]
    return "\n".join(out) or "No malformed lines in the attached files."


def _merges(db, dataset):
    names = [dataset] if dataset else [n for n, _p, _k in store.datasets(db)]
    out = []
    for name in names:
        lines = tools._merge_lines(store.merges(db, name))
        if lines:
            out.append(f"{name} (applied):")
            out += [f"  {line}" for line in lines]
    pending = store.pending_merges(db, dataset)
    if pending:
        out.append("Waiting for approval (/grimoire merges approve or reject):")
        out += [f"  {d}.{c}: {a!r} -> {b!r}" for d, _t, c, a, b in pending]
    return "\n".join(out) or "No merge rules saved."
