"""The /grimoire slash command. It runs plugin code only: no model call, no tokens."""

import re
from pathlib import Path

from . import store, tools

HELP = """Commands:
  /grimoire                         status
  /grimoire sql q12                 the SQL and result behind a query id
  /grimoire rejects [dataset]       malformed lines skipped when a file was read
  /grimoire merges [dataset]        saved merge rules
  /grimoire unmerge <dataset> <column>   remove the merge rules of a column"""


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
        if cmd == "rejects":
            return _rejects(eng, rest[0] if rest else None)
        if cmd == "merges":
            return _merges(db, rest[0] if rest else None)
        if cmd == "unmerge" and len(rest) == 2:
            removed = store.delete_merges(db, rest[0], rest[1])
            if not removed:
                return f"No merge rules for {rest[1]} in {rest[0]}."
            if rest[0] in eng.datasets:
                eng.set_merges(rest[0], store.merges(db, rest[0]))
            return f"Removed {removed} merge rule(s) from {rest[0]}.{rest[1]}. Later queries use the original values."
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
    lines.append("Learning mode: not available yet")
    return "\n".join(lines + ["", HELP])


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
            out.append(f"{name}:")
            out += [f"  {line}" for line in lines]
    return "\n".join(out) or "No merge rules saved."
