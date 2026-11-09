"""Check the numbers in a reply against the values Grimoire tools returned.

A number is "sourced" when some tool result holds the same value at the precision the reply
shows it (so "76.8M" matches 76,840,174.17 and "14.2%" matches 14.2 or 0.142).
Pure functions only; no Hermes or DuckDB imports.
"""

import bisect
import math
import re

_CODE = re.compile(r"```.*?```|`[^`\n]*`", re.S)
_CITE = re.compile(r"\[\s*q\d+(?:\s*,\s*q\d+)*\s*\]|\bq\d+\b", re.I)
_DATE = re.compile(r"\b\d{4}-\d{2}(?:-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?)?)?\b|\b\d{1,2}:\d{2}(?::\d{2})?\b")
_LIST_MARK = re.compile(r"(?m)^(\s*)\d+[.)](?=\s)")
_NUM = re.compile(r"(?<![\w.,])\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|(?<![\w.,])\d+(?:\.\d+)?")
_SUFFIX = re.compile(
    r"\s?(%|percent|thousand|million|billion|lakh|crore|bn|mn|cr|k|m|b)(?![a-z])", re.I
)
_CLOCK = re.compile(r"\s?([ap]\.?m\.?)(?![a-z])", re.I)
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
        clock = _CLOCK.match(after)
        if clock and re.fullmatch(r"\d{1,2}", core) and 1 <= int(core) <= 12:
            hour = int(core) % 12 + (12 if clock.group(1).lower().startswith("p") else 0)
            claims.append({"raw": core + clock.group(0), "value": float(hour), "tol": 0.5, "percent": False})
            continue  # "6 PM" is the hour 18
        if not suffix and re.match(r"[A-Za-z_\d]", after[:1]):
            continue  # part of a word or id, like 4xx, 2nd, x86
        before = text[max(0, m.start() - 2):m.start()]
        if re.fullmatch(r"\w-", before) or re.match(r"\.[A-Za-z]", after):
            continue  # part of a name, like yellow_2024-05.parquet or v-2
        if len(core) > 1 and core[0] == "0" and core[1].isdigit():
            continue  # a zero-padded code, like the month 06
        number = float(core.replace(",", ""))
        if not math.isfinite(number):
            continue  # 309 or more digits: not a claim, and it would overflow later checks
        decimals = len(core.split(".", 1)[1]) if "." in core else 0
        plain_int = decimals == 0 and "," not in core and not unit
        if plain_int and 1900 <= number <= 2100:
            continue  # a year
        whole = number == int(number) and "," not in core and not unit
        if whole and number >= 10 and str(int(number)).strip("0") == "1":
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


def _matches(pool, value, tol, percent):
    return _near(pool, value, tol) or (percent and _near(pool, value / 100, tol / 100))


MAX_PAIR_POOL = 300


def _pairs(values, ratios):
    out = set()
    for i, a in enumerate(values):
        for b in values[i + 1:]:
            out |= {a + b, b - a}
            if ratios and a and b:
                out |= {b / a, 100 * b / a, a / b, 100 * a / b}
    return out


def check(text, values, ignore=(), totals=()):
    """(sourced, derived, unsourced) lists of raw strings; see check_detail."""
    return check_detail(text, values, ignore, totals)[:3]


def check_detail(text, values, ignore=(), totals=()):
    """Split the claims in text into (sourced, derived, unsourced, loose) lists of raw strings.
    loose: derived claims that only match by combining two result values the reply does not show.
    With a few hundred result values there are about 270k such combinations, so an invented number
    can match by chance; the verdict then asks the reader to check them.

    values: numbers from tool results. ignore: raw strings to skip (numbers the user typed).
    totals: column totals of cited results. A claim is "derived" when simple arithmetic on
    sourced numbers gives it: a unit change (x100, /100, x1000, /1000), the sum, difference,
    ratio or percent share of two numbers the reply shows, or a column total.
    """
    pool = sorted(set(values))
    ignored = {s.replace(",", "") for s in ignore}
    claims = [c for c in extract(text) if c["raw"].split()[0].rstrip("%").replace(",", "") not in ignored]
    sourced, rest = [], []
    for claim in claims:
        ok = _matches(pool, claim["value"], claim["tol"], claim["percent"])
        (sourced if ok else rest).append(claim)
    shown = {c["value"] for c in claims if c in sourced}
    # powers of ten are skipped as claims, but "964 of 1000 rows" still uses 1000 as a sourced number
    shown |= {float(m) for m in re.findall(r"(?<![\w.,])10+(?![\w,]|\.\d)", _CODE.sub(_blank, text or ""))
              if _near(pool, float(m), 0.5)}
    shown = sorted(shown)
    sums = sorted(_pairs(shown, ratios=False))
    # ponytail: pairs of pool values only while the pool is small (O(n^2)); cited results are usually small.
    strong = set(shown) | {abs(t) for t in totals}
    other = _pairs(sorted(strong), ratios=True) | {abs(t) for t in totals}
    units = set()  # cents to dollars, units to thousands; a percent has its own x100 rule in _matches
    for f in (100.0, 1000.0):
        units |= {v * f for v in pool} | {v / f for v in pool}
    wide, wide_pct = sorted(other | units), sorted(other)
    hidden = sorted(_pairs(sorted(strong | set(pool)), ratios=True)) if len(pool) <= MAX_PAIR_POOL else []
    derived, unsourced, loose = [], [], []
    for claim in rest:
        # ponytail: a small whole number (under 100) is easy to hit by chance, so it may only be a sum or
        # difference of two numbers the reply shows; bigger or decimal numbers may also be a unit change,
        # ratio, share or column total.
        small = claim["value"] < 100 and claim["value"] == int(claim["value"]) and not claim["percent"]
        ok = _matches(sums if small else wide_pct if claim["percent"] else wide, claim["value"], claim["tol"], claim["percent"])
        if not ok and not small and _matches(hidden, claim["value"], claim["tol"], claim["percent"]):
            ok = True
            loose.append(claim["raw"])
        (derived if ok else unsourced).append(claim["raw"])
    return [c["raw"] for c in sourced], derived, unsourced, loose


def footer(sourced, unsourced, derived=()):
    """A short plain-text footer, or "" when the reply has no numeric claims."""
    traced = len(sourced) + len(derived)
    total = traced + len(unsourced)
    if not total:
        return ""
    how = f" ({len(derived)} by simple arithmetic: {' · '.join(dict.fromkeys(derived))})" if derived else ""
    if not unsourced:
        what = "the number traces" if total == 1 else f"all {total} numbers trace"
        return f"\n\n---\nGrimoire check: {what} to query results{how}."
    missing = " · ".join(dict.fromkeys(unsourced))
    return (
        f"\n\n---\nGrimoire check: {traced} of {total} numbers trace to query results{how}. "
        f"No source query for: {missing}"
    )
