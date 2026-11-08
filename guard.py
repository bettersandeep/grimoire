"""Stop raw reads of large data files and point the model to Grimoire instead."""

import os
from pathlib import Path

DATA_SUFFIXES = {".csv", ".tsv", ".parquet", ".pq", ".sqlite", ".sqlite3", ".db"}
DEFAULT_LIMIT_KB = 256


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
