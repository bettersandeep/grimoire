"""Check the numbers in a reply against the values Grimoire tools returned.

A number is "sourced" when some tool result holds the same value at the precision the reply
shows it (so "76.8M" matches 76,840,174.17 and "14.2%" matches 14.2 or 0.142).
Pure functions only; no Hermes or DuckDB imports.
"""

import bisect
import re

_CODE = re.compile(r"```.*?```|`[^`\n]*`", re.S)
_CITE = re.compile(r"\[\s*q\d+(?:\s*,\s*q\d+)*\s*\]|\bq\d+\b", re.I)
_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?)?\b|\b\d{1,2}:\d{2}(?::\d{2})?\b")
_LIST_MARK = re.compile(r"(?m)^(\s*)\d+[.)](?=\s)")
_NUM = re.compile(r"(?<![\w.,])\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|(?<![\w.,])\d+(?:\.\d+)?")
_SUFFIX = re.compile(
    r"\s?(%|percent|thousand|million|billion|lakh|crore|bn|mn|cr|k|m|b)(?![a-z])", re.I
)
_MULT = {
    "thousand": 1e3, "k": 1e3, "million": 1e6, "mn": 1e6, "m": 1e6,
    "billion": 1e9, "bn": 1e9, "b": 1e9, "lakh": 1e5, "crore": 1e7, "cr": 1e7,
}


def _blank(match):
    return " " * len(match.group(0))


def extract(text):
    """Return the numeric claims in text as dicts: raw, value, tol, percent."""
    text = _CODE.sub(_blank, text or "")
    for pattern in (_CITE, _DATE):
        text = pattern.sub(_blank, text)
    text = _LIST_MARK.sub(lambda m: m.group(1) + " " * (len(m.group(0)) - len(m.group(1))), text)
    claims = []
    for m in _NUM.finditer(text):
        core = m.group(0)
        after = text[m.end():]
        suffix = _SUFFIX.match(after)
        unit = suffix.group(1).lower() if suffix else ""
        if not suffix and re.match(r"[A-Za-z_\d]", after[:1]):
            continue  # part of a word or id, like 4xx, 2nd, x86
        number = float(core.replace(",", ""))
        decimals = len(core.split(".", 1)[1]) if "." in core else 0
        plain_int = decimals == 0 and "," not in core and not unit
        if plain_int and 1900 <= number <= 2100:
            continue  # a year
        if plain_int and number >= 10 and str(int(number)).strip("0") == "1":
            # ponytail: powers of ten (100, 1000) are usually unit factors ("÷ 100"); a real
            # count of exactly 100 is skipped too. Tighten with context if that ever matters.
            continue
        mult = _MULT.get(unit, 1.0)
        claims.append({
            "raw": (core + (suffix.group(0) if suffix else "")).strip(),
            "value": number * mult,
            "tol": 0.5 * 10 ** -decimals * mult,
            "percent": unit in ("%", "percent"),
        })
    return claims


def numeric_values(obj, out=None):
    """Collect every number in a tool result (nested lists and dicts), as absolute floats."""
    out = [] if out is None else out
    if isinstance(obj, bool):
        return out
    if isinstance(obj, (int, float)):
        out.append(abs(float(obj)))
    elif isinstance(obj, str):
        text = obj.strip().replace(",", "")
        try:
            out.append(abs(float(text)))
        except ValueError:
            pass
    elif isinstance(obj, dict):
        for v in obj.values():
            numeric_values(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            numeric_values(v, out)
    return out


def _near(sorted_values, value, tol):
    tol = tol + abs(value) * 1e-9
    i = bisect.bisect_left(sorted_values, value - tol)
    return i < len(sorted_values) and sorted_values[i] <= value + tol


def check(text, values, ignore=()):
    """Split the claims in text into (sourced, unsourced) lists of raw strings.

    values: numbers from tool results. ignore: raw strings to skip (numbers the user typed).
    """
    pool = sorted(set(values))
    ignored = {s.replace(",", "") for s in ignore}
    sourced, unsourced = [], []
    for claim in extract(text):
        if claim["raw"].split()[0].rstrip("%").replace(",", "") in ignored:
            continue
        value = claim["value"]
        ok = _near(pool, value, claim["tol"]) or (
            claim["percent"] and _near(pool, value / 100, claim["tol"] / 100)
        )
        (sourced if ok else unsourced).append(claim["raw"])
    return sourced, unsourced


def footer(sourced, unsourced):
    """A short plain-text footer, or "" when the reply has no numeric claims."""
    total = len(sourced) + len(unsourced)
    if not total:
        return ""
    if not unsourced:
        what = "the number matches" if total == 1 else f"all {total} numbers match"
        return f"\n\n---\nGrimoire check: {what} query results."
    missing = " · ".join(dict.fromkeys(unsourced))
    return (
        f"\n\n---\nGrimoire check: {len(sourced)} of {total} numbers match query results. "
        f"No source query for: {missing}"
    )
