"""The /grimoire slash command. It runs plugin code only: no model call, no tokens."""

import re
from pathlib import Path

import datetime
import json
import os
import tempfile

from . import audit, engine, learning, metrics, report, store, tools, walkthrough

HELP = """Commands:
  /grimoire                          status
  /grimoire setup                    use fewer tokens: a Data bot with only Grimoire's tools
  /grimoire sql q12                  the SQL and result behind a query id
  /grimoire explain q12              how your question became that SQL
  /grimoire chart q12                a bar chart of a result
  /grimoire rerun q12                run the SQL again and check the result still holds
  /grimoire report [dataset]         an HTML report of the last session's queries (or one file's)
  /grimoire learn on | off           learning mode: a short lesson after data answers
  /grimoire learn plain | sql        lesson style: how the answer was made in plain words, or the SQL
  /grimoire learn predict on | off   guess the answer before you see it (needs learning mode)
  /grimoire define <name> = <expr>   save a metric, e.g. revenue = sum(amount_cents) / 100
  /grimoire metrics                  saved metrics; /grimoire undefine <name> removes one
  /grimoire rejects [dataset]        malformed lines skipped when a file was read
  /grimoire merges [dataset]         merge rules, applied and waiting for approval
  /grimoire merges approve | reject  apply or drop the merges waiting for approval
  /grimoire unmerge <dataset> [column]   remove merge rules (one column, or all)
  /grimoire forget <dataset>         delete everything saved about one file
  /grimoire clear history            delete all saved queries and results
  /grimoire reset confirm            delete everything Grimoire saved"""


SETUP = """Use fewer tokens: chat with a Data bot that has only Grimoire's tools.
Full Hermes sends every tool (terminal, browser, web and more) with every model call.
A bot with only Grimoire's tools sends about a fifth of that, and answers faster.

In Hermes Desktop:
  1. Open the Bots tab, click +, then New bot. Name it data.
  2. Click Advanced (below Description). Under General, clone from the profile that has Grimoire (usually default).
  3. Open Capabilities, then Tools. Scroll down to the Build for Hermes box and switch off the switch in it (all tools).
     Then search for grimoire and switch it on. Do the same for Clarifying Questions.
  4. Click Create bot, then ask data questions in the data bot's chat.
Already made a bot? Open its menu, choose Edit..., then Advanced and Capabilities.
Your main agent keeps all its tools. Grimoire never changes your settings.

In a terminal: hermes chat -t grimoire,clarify"""


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
            return _status(db, eng, kwargs.get("session_id"))
        if cmd == "setup":
            return SETUP
        if cmd == "sql" and rest:
            return _sql(db, rest[0])
        if cmd == "explain" and rest:
            return _explain(db, rest[0], eng)
        if cmd == "chart" and rest:
            q = store.get_query(db, rest[0])
            return report.text_chart(q) if q else f"No query {rest[0]}."
        if cmd == "rerun" and rest:
            return _rerun(db, eng, rest[0])
        if cmd == "report":
            return _report(db, rest[0] if rest else None, eng)
        if cmd == "define":
            return _define(db, eng, (raw_args or "").split(None, 1)[1] if len(words) > 1 else "")
        if cmd == "metrics":
            saved = store.metrics(db)
            return "\n".join(f"{n}() = {e}" for n, e in saved.items()) or (
                "No saved metrics. Example: /grimoire define revenue = sum(amount_cents) / 100")
        if cmd == "undefine" and len(rest) == 1:
            return f"Removed {rest[0]}()." if store.drop_metric(db, rest[0].lower().rstrip("()")) else f"No metric {rest[0]}."
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


def _status(db, eng, session_id=None):
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
    style = store.get_setting(db, "learn_style", "plain")
    lines.append(f"Learning mode: {'on' if learn else 'off'} ({'plain words' if style == 'plain' else 'SQL'}) · "
                 f"Predictions: {'on' if predict else 'off'}{score}")
    size = tools.call_size(session_id)
    if size:
        lean = size[0] <= tools.LEAN_TOOLS
        lines.append(f"This chat: {size[0]} tools, about {size[1]:,} tokens per model call"
                     + (" (lean setup)" if lean else ". For fewer tokens: /grimoire setup"))
    return "\n".join(lines + ["", HELP])


def _define(db, eng, text):
    name, sep, expression = text.partition("=")
    name, expression = name.strip().lower().rstrip("()").strip(), expression.strip()
    if not sep or not name or not expression:
        return "Use: /grimoire define <name> = <SQL expression>, for example revenue = sum(amount_cents) / 100"
    try:
        works = metrics.validate(eng, name, expression)
    except engine.EngineError as exc:
        return f"Not saved: {exc}"
    store.define_metric(db, name, expression)
    return (f"Saved {name}() = {expression}. It works on: {', '.join(works)}. "
            f"Ask in plain words; Grimoire tells the model to use {name}() so every answer computes it the same way.")


def _rerun(db, eng, qid):
    q = store.get_query(db, qid)
    if q is None:
        return f"No query {qid}."
    try:
        _cols, rows, _trunc = eng.query(q["sql"])
    except Exception as exc:
        return f"{q['id']} could not run again: {exc}"
    norm = lambda rs: json.loads(json.dumps(rs, default=str))
    if norm(rows) == norm(q["rows"]):
        return f"{q['id']} still holds: the same {len(rows)} row(s) as when it was saved."
    diff = next((i for i, (a, b) in enumerate(zip(norm(rows), norm(q["rows"]))) if a != b), min(len(rows), len(q["rows"])))
    return (f"{q['id']} changed since it was saved: {len(q['rows'])} row(s) then, {len(rows)} now; "
            f"first difference at row {diff + 1}. The file or a merge rule changed. Answers that cite "
            f"{q['id']} are out of date.")


def _report(db, dataset, eng=None):
    queries = store.queries_for(db, dataset)
    if not queries:
        return "No saved queries to report yet." if not dataset else f"No saved queries for {dataset}."
    title = f"Grimoire report: {dataset}" if dataset else "Grimoire report"
    folder = os.path.join(store.data_dir(db) or tempfile.gettempdir(), "reports")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"report-{datetime.datetime.now():%Y%m%d-%H%M%S}.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(report.html_report(queries, title, _report_context(db, eng, queries)))
    return f"Saved a report of {len(queries)} query(ies): {path}\nOpen it in a browser: file://{path}"


def _report_context(db, eng, queries):
    """What the report shows besides results: caveats from the audit, data health, metrics and notes."""
    caveats = {}
    if eng is not None:
        for q in queries:
            try:
                lines = audit.assumptions(q, eng) + audit.pitfalls(q, eng)
            except Exception:
                lines = []  # a check that fails leaves that query without caveats, never breaks the report
            if lines:
                caveats[q["id"]] = lines
    names = sorted({n for q in queries for n in q["datasets"]})
    files = [{"name": n, "health": store.get_json(db, f"health:{n}", None), "issues": store.get_json(db, f"issues:{n}", []),
              "notes": [(col, text) for _t, col, text in store.notes(db, n)]} for n in names]
    used = {n: e for n, e in store.metrics(db).items() if any(re.search(rf"\b{re.escape(n)}\(", q["question"] or "", re.I)
                                                              or f"({e})" in q["sql"] for q in queries)}
    return {"caveats": caveats, "files": files, "metrics": used}


def _learn(db, rest):
    if rest in (["on"], ["off"]):
        store.set_setting(db, "learn", rest[0])
        if rest[0] == "on":
            return ("Learning mode is on. After answers about your data you see how the answer was made, step by "
                    "step, and one question worth asking. /grimoire learn sql switches to SQL lessons; "
                    "/grimoire learn predict on asks you to guess answers first.")
        return "Learning mode is off. Answers have no lessons or predictions."
    if rest in (["plain"], ["sql"]):
        store.set_setting(db, "learn_style", rest[0])
        return ("Lessons now walk through how each answer was made, step by step, in plain words."
                if rest[0] == "plain" else "Lessons now teach one SQL idea from each answer.") + (
            "" if store.get_setting(db, "learn", "off") == "on" else " Turn learning mode on with /grimoire learn on")
    if rest in (["predict", "on"], ["predict", "off"]):
        if rest[1] == "on" and store.get_setting(db, "learn", "off") != "on":
            return "Turn on learning mode first: /grimoire learn on"
        store.set_setting(db, "predict", rest[1])
        return ("Predictions are on. Before an answer, you are asked to guess the main number."
                if rest[1] == "on" else "Predictions are off.")
    learn, predict = tools.learning_state()
    return (f"Learning mode: {'on' if learn else 'off'} · Predictions: {'on' if predict else 'off'}\n"
            "Change with /grimoire learn on|off and /grimoire learn predict on|off")


def _explain(db, qid, eng=None):
    q = store.get_query(db, qid)
    if q is None:
        return f"No query {qid}."
    head = f"{q['id']}: {q['purpose'] or ''}".rstrip(": ")
    try:
        lines = walkthrough.steps(q, eng) if eng is not None else []
        if lines:
            store.set_json(db, f"steps:{q['id']}", lines)  # for Desktop's Explain
        plain = "\n".join(lines)
    except Exception:
        plain = ""
    plain = f"\nIn plain words:\n{plain}\n" if plain else ""
    return head + plain + "\n" + learning.explain(q["sql"], q["question"], q["columns"])


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
            out += [f"  {where}: {err}: {text}" for where, err, text in first]
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
