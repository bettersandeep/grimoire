"""Point the model to Grimoire for data files: a hint when one is mentioned, a block on raw reads."""

import os
import re
from pathlib import Path

DATA_SUFFIXES = {".csv", ".tsv", ".parquet", ".pq", ".sqlite", ".sqlite3", ".db"}
DEFAULT_LIMIT_KB = 256
_DATA_FILE = re.compile(r"[^\s'\"`<>()]*?[\w-]\.(?:csv|tsv|parquet|pq|sqlite3?|db)\b", re.IGNORECASE)


def data_file_hint(user_message):
    """One line of context when the message names a data file; None otherwise (no cost)."""
    names = list(dict.fromkeys(m.group(0) for m in _DATA_FILE.finditer(user_message or "")))
    if not names:
        return None
    files = ", ".join(names[:3])
    return (
        f"[Grimoire] Data file mentioned: {files}. Use the Grimoire tools: grimoire_attach the file, "
        "then answer with grimoire_query (DuckDB SQL, cite query ids). Do not read the file or parse it "
        "with code. If the tools are not visible, load them with tool_describe."
    )


def check(tool_name, args, cwd=None, limit_kb=DEFAULT_LIMIT_KB):
    """Return a pre_tool_call block directive, or None to let the call run."""
    if tool_name != "read_file" or not limit_kb:
        return None
    raw = (args or {}).get("path")
    if not raw:
        return None
    path = Path(os.path.expanduser(str(raw)))
    if not path.is_absolute():
        path = Path(cwd or os.getcwd()) / path
    if path.suffix.lower() not in DATA_SUFFIXES:
        return None
    try:
        size = path.stat().st_size
    except OSError:
        return None
    if size < limit_kb * 1024:
        return None
    return {
        "action": "block",
        "message": (
            f"Grimoire stopped this read: {path.name} is a {size // 1024} KB data file, so reading it raw "
            "wastes tokens and gets cut off. Call grimoire_attach with this path instead, then answer with "
            f"grimoire_query. Path: {path}"
        ),
    }
