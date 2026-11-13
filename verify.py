"""Check the numbers in a reply against the values Grimoire tools returned.

A number is "sourced" when some tool result holds the same value at the precision the reply
shows it (so "76.8M" matches 76,840,174.17 and "14.2%" matches 14.2 or 0.142).
Pure functions only; no Hermes or DuckDB imports.
"""

import bisect
import math
import re
from typing import NamedTuple

_CODE = re.compile(r"```.*?```|`[^`\n]*`", re.S)
_CITE = re.compile(r"\[\s*q\d+(?:\s*,\s*q\d+)*\s*\]|\bq\d+\b", re.I)
_DATE = re.compile(r"\b\d{4}-\d{2}(?:-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?)?)?\b|\b\d{1,2}:\d{2}(?::\d{2})?\b")
# Written dates: "November 11, 2026", "Nov. 3", "11 November 2026", "May 2026". The day and year are not claims. Month first needs a year
# or punctuation after the day, so "May 12 orders" is still read; month names are capitalised, so "may 12" is too.
_MONTH = r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?"
_DAY = r"(?:[1-9]|[12]\d|3[01])(?:st|nd|rd|th)?"
_WRITTEN_DATE = re.compile(rf"\b{_MONTH}\s+{_DAY}(?:,?\s+(?:19|20)\d\d\b|(?=[.,;:)!?]|\s*$))"
                           rf"|\b{_DAY}\s+{_MONTH}(?![a-z])(?:,?\s+(?:19|20)\d\d\b)?|\b{_MONTH}\s+(?:19|20)\d\d\b")
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
    """Return the numeric claims in text as dicts: raw, value, tol, percent, and skip: why the number may not be
    a claim ("looks like a year", "a round factor"), or None."""
    text = _CODE.sub(_blank, text or "")
    for pattern in (_CITE, _DATE, _WRITTEN_DATE):
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
            claims.append({"raw": core + clock.group(0), "value": float(hour), "tol": 0.5, "percent": False,
                           "skip": None, "written": None, "at": m.start(), "end": m.end() + clock.end()})
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
        whole = number == int(number) and "," not in core and not unit
        skip = ("looks like a year" if plain_int and 1900 <= number <= 2100 else
                "a round factor" if whole and number >= 10 and str(int(number)).strip("0") == "1" else None)
        mult = _MULT.get(unit, 1.0)
        claims.append({
            "raw": (core + (suffix.group(0) if suffix else "")).strip(),
            "value": number * mult,
            "tol": 0.5 * 10 ** -decimals * mult,
            "percent": unit in ("%", "percent"),
            "skip": skip,
            # "$29.05M" also matches 29.05 as written: SQL often computes in millions (revenue_musd)
            # not for small whole numbers: "$15M" must not match a count of 15
            "written": number if mult != 1.0 and not (number < 100 and number == int(number)) else None,
            "written_tol": 0.5 * 10 ** -decimals,
            "at": m.start(), "end": m.end() + (suffix.end() if suffix else 0),  # where it stands in the text
        })
    return claims


def signed_values(obj, out=None):
    """Collect every number in a tool result (nested lists and dicts), as floats with their sign."""
    out = [] if out is None else out
    if isinstance(obj, bool):
        return out
    if isinstance(obj, (int, float)):
        out.append(float(obj))
    elif isinstance(obj, str):
        text = obj.strip().replace(",", "")
        try:
            out.append(float(text))
        except ValueError:
            pass
    elif isinstance(obj, dict):
        for v in obj.values():
            signed_values(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            signed_values(v, out)
    return out


def numeric_values(obj):
    """Every number in a tool result as an absolute float: the check compares sizes ("fell 5%" is -5)."""
    return [abs(v) for v in signed_values(obj)]


def wrong_rows(text, rows):
    """[(raw, label, owner)]: numbers the reply puts next to one label (North) that the results hold only in
    another label's row (South). rows: the result rows the answer rests on; a label is a text cell.
    Precise on purpose: a stretch of text that names two labels, or none, is not read, and a number that is in
    no row (a share, a sum) is left to the number check.
    ponytail: a number worked out for North that equals South's value by chance is flagged too; rare."""
    pools, names = {}, {}
    for row in rows:
        values = numeric_values(row)
        for cell in row:
            label = cell.strip() if isinstance(cell, str) else ""
            if 2 <= len(label) <= 60 and any(ch.isalpha() for ch in label):
                names.setdefault(label.lower(), label)
                pools.setdefault(label.lower(), []).extend(values)
    if len(pools) < 2:
        return []
    pools = {key: sorted(values) for key, values in pools.items()}
    longest_first = sorted(pools, key=len, reverse=True)  # "North East" before "North"
    label_at = re.compile(r"(?<!\w)(?:" + "|".join(map(re.escape, longest_first)) + r")(?!\w)", re.I)
    text = text or ""
    found, start = [], 0
    for claim in extract(text):
        line_start = text.rfind("\n", 0, claim["at"]) + 1
        named = {m.lower() for m in label_at.findall(text, max(start, line_start), claim["at"])}
        start = claim["end"]
        if claim["skip"] or len(named) != 1:
            continue
        label = named.pop()
        holds = lambda key: _matches(pools[key], claim["value"], claim["tol"], claim["percent"]) or (
            claim["written"] is not None and _near(pools[key], claim["written"], claim["written_tol"]))
        owner = None if holds(label) else next((key for key in pools if key != label and holds(key)), None)
        if owner:
            found.append((claim["raw"], names[label], names[owner]))
    return found


# A reply can state the right size with the wrong direction: "grew 12.5%" for a result of -12.5.
_RISE = r"(?:grew|grows?|grown|growing|growth|rose|rises?|risen|rising|increas(?:e|es|ed|ing)|gain(?:s|ed|ing)?|jump(?:s|ed|ing)?|climb(?:s|ed|ing)?|surg(?:e|es|ed|ing)|up)"
# "grew 12.5%", "grew by about **12.5%**", "up ~$12.5M": only filler words, spaces, Markdown marks and signs between
_RISE_BEFORE = re.compile(rf"\b({_RISE})(?:\s+(?:by|of|about|around|roughly|nearly|almost|over|a|an|the|was|is|at))*[\s*_~≈+$€£₹]*$", re.I)
# "a 12.5% increase", "12.5% revenue growth"; not "12.5% negative growth" or "12.5% lower growth"
_RISE_AFTER = re.compile(r"[\s*_]*(?:(?!negative|lower|less|slower|weaker|smaller|no|zero)[a-z]+\s+)?(?:increase|growth|rise|gain|jump)\b", re.I)
_NOT = re.compile(r"\b(?:not|no|never|without)\b|n't\b", re.I)
# "up" is a rise only as "is up", "went up" or after a comma: not in "made up 12.5% of" or "set up 3 dashboards"
_UP_LEAD = re.compile(r"(?:\b(?:is|are|was|were|went|goes?|going|gone|moved|ticked|edged|shot)\s+|[,:;(]\s*|^\s*)$", re.I)


def rises_on_negatives(text, signed):
    """Raw claims that the text calls a rise, where the results hold that number only as a negative.
    signed: result numbers with their sign. Only this direction is checked: a fall word next to a positive
    number is often right ("fell to 1,200", or a column of drops), so it says nothing."""
    negative = sorted({-v for v in signed if v < 0})
    positive = sorted({v for v in signed if v > 0})
    if not negative:
        return []
    text = text or ""
    found = []
    for claim in extract(text):
        if claim["skip"]:
            continue  # a year or a round factor is not a size that can rise
        before = text[max(0, claim["at"] - 60):claim["at"]]
        rise = _RISE_BEFORE.search(before)
        if rise and rise.group(1).lower() == "up" and not _UP_LEAD.search(before[:rise.start()]):
            rise = None
        if rise:
            if _NOT.search(before[max(0, rise.start() - 20):rise.start()]):
                continue  # "did not grow 12.5%"
        elif not _RISE_AFTER.match(text[claim["end"]:claim["end"] + 40]) or re.search(r"[-−–(][\s*_]*[$€£₹]?\s*$", before):
            continue  # no rise word next to it, or the reply shows the minus sign itself
        if (_matches(negative, claim["value"], claim["tol"], claim["percent"])
                and not _matches(positive, claim["value"], claim["tol"], claim["percent"])):
            found.append(claim["raw"])
    return list(dict.fromkeys(found))


def caveats(loose=(), uncited=(), flipped=(), missing=(), wrong=()):
    """Warning lines for numbers that trace, but not cleanly; they make the verdict "share with caveats".
    missing: cited query ids that are not saved queries. wrong: wrong_rows results."""
    join = lambda items: " · ".join(dict.fromkeys(items))
    out = [f"{raw} is {owner}'s value, not {label}'s" for raw, label, owner in wrong]
    if missing:
        out.append(f"the answer cites {join(missing)}, which {'is' if len(set(missing)) == 1 else 'are'} not a saved "
                   "query, so the numbers were checked against every result of this chat")
    if flipped:
        out.append(f"{join(flipped)} {'is' if len(set(flipped)) == 1 else 'are'} written as a rise, but the result is "
                   "negative; check the direction")
    if uncited:
        out.append(f"{join(uncited)} match another result of this chat, not a query the answer cites, so the "
                   "match can be chance; cite that query, or compute them again")
    if loose:
        out.append(f"{join(loose)} only match by combining two values from the result; check how they were "
                   "worked out, or compute them in SQL")
    return out


def _near(sorted_values, value, tol):
    tol = tol + abs(value) * 1e-9
    i = bisect.bisect_left(sorted_values, value - tol)
    return i < len(sorted_values) and sorted_values[i] <= value + tol


def _matches(pool, value, tol, percent):
    return _near(pool, value, tol) or (percent and _near(pool, value / 100, tol / 100))


MAX_PAIR_POOL = 300
MAX_TRIPLE_SHOWN = 60  # 60 shown numbers give about 34k sums of three


def _triples(values):
    """Sums of three shown numbers, e.g. one region spelled three ways merged into one total."""
    if len(values) > MAX_TRIPLE_SHOWN:
        return set()
    return {a + b + c for i, a in enumerate(values) for j, b in enumerate(values[i + 1:], i + 1) for c in values[j + 1:]}


def _pairs(values, ratios):
    out = set()
    for i, a in enumerate(values):
        for b in values[i + 1:]:
            out |= {a + b, b - a}
            if ratios and a and b:
                out |= {b / a, 100 * b / a, a / b, 100 * a / b}
    return out


class Checked(NamedTuple):
    """The claims of a reply, as raw strings, by how they trace."""
    sourced: list    # a tool result holds the number
    derived: list    # simple arithmetic on sourced numbers gives it
    unsourced: list  # nothing gives it
    loose: list      # of derived: only two result values the reply does not show give it, so it can be chance
    unchecked: list  # a year or a round factor that no result holds, with the reason: "2024 (looks like a year)"


def check_detail(text, values, ignore=(), totals=()):
    """Sort the claims in text into a Checked. loose: with a few hundred result values there are about
    270k pairs, so an invented number can match by chance; the verdict then asks the reader to check them.
    A year or a round factor counts only when a result holds it: "÷ 100" or "in 2024" may not be a claim,
    so arithmetic that happens to give it proves nothing. It is named as not checked, never flagged.

    values: numbers from tool results. ignore: raw strings to skip (numbers the user typed).
    totals: column totals of cited results. A claim is "derived" when simple arithmetic on
    sourced numbers gives it: a unit change (x100, /100, x1000, /1000), the sum, difference,
    ratio or percent share of two numbers the reply shows, the sum of three, or a column total.
    """
    pool = sorted(set(values))
    ignored = {s.replace(",", "") for s in ignore}
    claims = [c for c in extract(text) if c["raw"].split()[0].rstrip("%").replace(",", "") not in ignored]
    sourced, rest = [], []
    for claim in claims:
        ok = _matches(pool, claim["value"], claim["tol"], claim["percent"]) or (
            claim["written"] is not None and _near(pool, claim["written"], claim["written_tol"]))
        (sourced if ok else rest).append(claim)
    shown = sorted({c["value"] for c in claims if c in sourced})
    sums = sorted(_pairs(shown, ratios=False))
    # ponytail: pairs of pool values only while the pool is small (O(n^2)); cited results are usually small.
    strong = set(shown) | {abs(t) for t in totals}
    other = _pairs(sorted(strong), ratios=True) | {abs(t) for t in totals}
    units = set()  # cents to dollars, units to thousands; a percent has its own x100 rule in _matches
    for f in (100.0, 1000.0):
        units |= {v * f for v in pool} | {v / f for v in pool}
    wide, wide_pct = sorted(other | units | _triples(shown)), sorted(other)
    hidden = sorted(_pairs(sorted(strong | set(pool)), ratios=True)) if len(pool) <= MAX_PAIR_POOL else []
    derived, unsourced, loose, unchecked = [], [], [], []
    for claim in rest:
        if claim["skip"]:
            unchecked.append(f"{claim['raw']} ({claim['skip']})")
            continue
        # ponytail: a small whole number (under 100) is easy to hit by chance, so it may only be a sum or
        # difference of two numbers the reply shows; bigger or decimal numbers may also be a unit change,
        # ratio, share or column total.
        small = claim["value"] < 100 and claim["value"] == int(claim["value"]) and not claim["percent"]
        ok = _matches(sums if small else wide_pct if claim["percent"] else wide, claim["value"], claim["tol"], claim["percent"])
        if not ok and claim["written"] is not None:  # "$66,763.08M" when the shown numbers are millions
            ok = _near(wide, claim["written"], claim["written_tol"])
        if not ok and not small and _matches(hidden, claim["value"], claim["tol"], claim["percent"]):
            ok = True
            loose.append(claim["raw"])
        (derived if ok else unsourced).append(claim["raw"])
    return Checked([c["raw"] for c in sourced], derived, unsourced, loose, unchecked)


def footer(checked, uncited=()):
    """A short plain-text footer, or "" when the reply has no number to check.
    Not counted as tracing: loose numbers (matched only by combining two hidden result values) and uncited
    numbers (found only in a result of the chat that the reply does not cite)."""
    sourced, derived, unsourced, loose, unchecked = checked
    join = lambda items: " · ".join(dict.fromkeys(items))
    derived = [d for d in derived if d not in loose]
    traced = len(sourced) + len(derived)
    total = traced + len(unsourced) + len(loose) + len(uncited)
    if not total:
        return ""
    how = f" ({len(derived)} by simple arithmetic: {join(derived)})" if derived else ""
    skipped = f" Not checked: {join(unchecked)}." if unchecked else ""
    if not (unsourced or loose or uncited):
        what = "the number traces" if total == 1 else f"all {total} numbers trace"
        return f"\n\n---\nGrimoire check: {what} to query results{how}.{skipped}"
    why, which = (("No source query for", unsourced) if unsourced else
                  ("Check how these were worked out", loose) if loose else ("Not from a cited query", uncited))
    return f"\n\n---\nGrimoire check: {traced} of {total} numbers trace to query results{how}. {why}: {join(which)}.{skipped}"
