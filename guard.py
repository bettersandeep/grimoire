"""Point the model to Grimoire for data files: a hint when one is mentioned, a block on raw reads."""

import os
import re
from pathlib import Path

# Not .json or .txt: those are often config and logs, which the read guard must not block.
DATA_SUFFIXES = {".csv", ".tsv", ".parquet", ".pq", ".sqlite", ".sqlite3", ".db", ".jsonl", ".ndjson"}
DEFAULT_LIMIT_KB = 256
_SPLIT = re.compile(r"[\s'\"`<>()]+")
_DATA_END = re.compile(r"[\w*?\]-]\.(?:csv|tsv|parquet|pq|sqlite3?|db|jsonl|ndjson)(?:\.gz|\.zst)?$", re.IGNORECASE)
MAX_TOKEN = 1024  # a longer "word" is not a path; skipping it keeps the per-message cost linear


def data_file_mentions(user_message):
    """Data file names or paths in a message, in order, at most 3. Splits into words first, then checks
    each word's ending: one pass, so a 40k-character word costs no more than its length."""
    found = []
    for word in _SPLIT.split(user_message or ""):
        word = word.rstrip(".,;:?!")
        if word and len(word) <= MAX_TOKEN and _DATA_END.search(word):
            found.append(word)
    return list(dict.fromkeys(found))[:3]


def is_data_path(path):
    """True for a data file name, also compressed: sales.csv, events.jsonl.gz. Not log.txt.gz."""
    name = Path(path).name.lower()
    for packed in (".gz", ".zst"):
        if name.endswith(packed):
            name = name[: -len(packed)]
    return Path(name).suffix in DATA_SUFFIXES


def data_file_hint(user_message):
    """One line of context when the message names a data file; None otherwise (no cost)."""
    names = data_file_mentions(user_message)
    if not names:
        return None
    return (
        f"[Grimoire] Data file mentioned: {', '.join(names)}. Call tool_call with name \"grimoire_attach\" and "
        "arguments {\"path\": \"<the path>\"}, then answer with grimoire_query (DuckDB SQL, cite query ids). "
        "Do not read the file or parse it with code."
    )


# Folders that hold credentials, app databases and Hermes's own state. Grimoire does not open files there
# unless the user sets plugins.entries.grimoire.settings.allow_private_folders: true.
_PRIVATE = (".hermes", ".ssh", ".gnupg", ".aws", ".config", ".kube", ".docker", "Library")
_PRIVATE_OK = ("Library/Mobile Documents", "Library/CloudStorage")  # iCloud Drive, Dropbox and similar


def private_folder(real_path, home=None):
    """The private folder that holds real_path, or None."""
    home = os.path.realpath(home or os.path.expanduser("~"))
    try:
        rel = Path(os.path.realpath(real_path)).relative_to(home)
    except ValueError:
        return None
    text = rel.as_posix().casefold()  # macOS and Windows file names ignore case: ~/.HERMES is ~/.hermes
    if any(text == ok.casefold() or text.startswith(ok.casefold() + "/") for ok in _PRIVATE_OK):
        return None
    top = rel.parts[0].casefold() if rel.parts else ""
    return next((p for p in _PRIVATE if p.casefold() == top), None)


def private_error(folder):
    return (f"Grimoire does not open files in ~/{folder}, which holds private app data or "
            "credentials. Copy the file to another folder, or ask the user to set "
            "plugins.entries.grimoire.settings.allow_private_folders: true.")


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
    if not is_data_path(path):
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
