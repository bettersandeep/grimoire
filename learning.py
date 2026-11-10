"""Learning mode: explain how a question became SQL, short teach-me cards, and predictions.

Everything here is plain code over the saved SQL, the user's words and the profile: no model call.
"""

import re

from . import verify

# Top-level SQL clauses, in the order a reader meets them.
_CLAUSES = ["WITH", "SELECT", "FROM", "WHERE", "GROUP BY", "HAVING", "QUALIFY", "ORDER BY", "LIMIT"]
_CLAUSE_RE = re.compile(r"\b(" + "|".join(c.replace(" ", r"\s+") for c in _CLAUSES) + r")\b", re.I)

# Words people use, and the SQL they turn into.
_WORDS = [
    (r"\b(total|sum|revenue|overall)\b", "SELECT", r"sum\("),
    (r"\b(average|avg|mean|typical)\b", "SELECT", r"avg\("),
    (r"\b(how many|number of|count)\b", "SELECT", r"count\("),
    (r"\b(distinct|unique|different)\b", "SELECT", "distinct"),
    (r"\b(per|by|each|for every|breakdown)\b", "GROUP BY", ""),
    (r"\b(highest|most|top|largest|biggest|best|max(imum)?)\b", "ORDER BY", "desc"),
    (r"\b(lowest|least|smallest|worst|min(imum)?|bottom)\b", "ORDER BY", ""),
    (r"\b(skip|exclude|ignore|without|only|empty|missing|where)\b", "WHERE", ""),
    (r"\b(month|monthly|week|year|daily|quarter)\b", "", "date_trunc|strftime|month|year|week"),
]

_EXPLAIN = {
    "WITH": "names a helper result first, so the main query can read it like a table",
    "SELECT": "picks what to show, and computes it",
    "FROM": "says which table to read",
    "WHERE": "keeps only the rows that match, before anything is added up",
    "GROUP BY": "splits the rows into one group per value, so totals are per group",
    "HAVING": "keeps only the groups that match, after they are added up",
    "QUALIFY": "filters on a window calculation, such as a rank",
    "ORDER BY": "sorts the result",
    "LIMIT": "keeps only the first rows of the sorted result",
}

# SQL ideas a teach-me card can explain, most specific first: (pattern in SQL, key, lesson).
_CONCEPTS = [
    (r"\bcorr\s*\(", "correlation", "corr(x, y) runs from -1 to 1 and says how closely two columns move "
     "together. It does not say which one causes the other, or whether a third thing drives both."),
    (r"\bregr_slope\s*\(", "trend", "regr_slope(y, x) fits a straight line and returns how much y changes per "
     "step of x. Extending the line into the future is a rough guess: it ignores seasons and sudden changes."),
    (r"\bover\s*\(", "window", "A window function, like sum(...) OVER (...), computes a value per row "
     "from other rows (a running total or a share) without collapsing rows the way GROUP BY does."),
    (r"\bcount\s*\(\s*\*\s*\)", "count-star", "count(*) counts rows; count(column) counts only rows where "
     "that column is not empty. The difference is how many values are missing."),
    (r"\bcount\s*\(\s*distinct\b", "count-distinct", "count(DISTINCT x) counts different values, so a "
     "customer with 10 orders counts once."),
    (r"\bis\s+not\s+null\b", "not-null", "WHERE x IS NOT NULL drops empty values. Sums skip empty values "
     "anyway, but averages and counts change, so say which rows you kept."),
    (r"\bcase\s+when\b", "case", "CASE WHEN ... THEN ... END makes a new value from a rule, for example "
     "putting amounts into 'small' and 'large' buckets."),
    (r"\b(date_trunc|strftime|month\s*\(|year\s*\()", "dates", "date_trunc('month', d) turns every date "
     "into the first day of its month, so GROUP BY can total each month."),
    (r"\bhaving\b", "having", "WHERE filters rows before grouping; HAVING filters groups after the totals "
     "exist, for example 'regions with revenue over $1 million'."),
    (r"\border\s+by\b.*\blimit\b", "top-n", "ORDER BY x DESC LIMIT 1 sorts from the largest down and keeps "
     "the first row: that is how 'which is highest' becomes SQL."),
    (r"\bgroup\s+by\b", "group-by", "GROUP BY makes one result row per value; every other column in SELECT "
     "must be added up (sum, avg, count) or be part of the group."),
    (r"\b(sum|avg)\s*\(", "aggregate", "sum() and avg() add up a column over all matching rows. The database "
     "does the arithmetic, so the number is exact and repeatable."),
]

def clauses(sql):
    """[(clause name, clause text)] for the top level of a query (parentheses are skipped over)."""
    # drop comments first (strings stay): on one line, a -- comment would hide the conditions after it
    sql = re.sub(r"('(?:[^']|'')*')|--[^\n]*|/\*.*?\*/", lambda m: m.group(1) or " ", sql, flags=re.S)
    # one space between words, but not inside quotes: 'New  York' must stay as written, or the row counts
    # that the audit and the learning card run from this text come out wrong
    text = re.sub(r"""('(?:[^']|'')*'|"(?:[^"]|"")*")|\s+""", lambda m: m.group(1) or " ", sql.strip().rstrip(";"))
    depth, starts = 0, []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "'":
            end = text.find("'", i + 1)
            i = len(text) if end < 0 else end + 1
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif depth == 0:
            m = _CLAUSE_RE.match(text, i)
            if m and (i == 0 or not (text[i - 1].isalnum() or text[i - 1] == "_")):
                starts.append((i, re.sub(r"\s+", " ", m.group(1)).upper()))
                i = m.end()
                continue
        i += 1
    out = []
    for n, (pos, name) in enumerate(starts):
        end = starts[n + 1][0] if n + 1 < len(starts) else len(text)
        out.append((name, text[pos:end].strip()))
    return out


def explain(sql, question=None, columns=()):
    """Plain-text walk-through: which words of the question became which part of the SQL."""
    parts = clauses(sql)
    lines = []
    if question:
        lines.append(f"Your question: {question.strip()}")
    lines.append("How it became SQL:")
    q = (question or "").lower()
    for name, text in parts:
        words = _matching_words(q, name, text, columns)
        said = f'"{", ".join(words)}" -> ' if words else ""
        lines.append(f"  {said}{text}")
        lines.append(f"      {name} {_EXPLAIN.get(name, '')}".rstrip())
    lesson = concept(sql)
    if lesson:
        lines.append(f"Idea to remember: {lesson[1]}")
    return "\n".join(lines)


def _matching_words(question, clause, text, columns):
    if not question:
        return []
    found, low = [], text.lower()
    for pattern, where, sql_hint in _WORDS:
        m = re.search(pattern, question)
        if not m:
            continue
        if where and where != clause:
            continue
        if sql_hint and not re.search(sql_hint, low):
            continue
        found.append(m.group(0))
    for col in columns:
        spoken = col.lower().replace("_", " ")
        if (col.lower() in question or spoken in question) and col.lower() in low and col.lower() not in found:
            found.append(spoken)
    return list(dict.fromkeys(found))[:3]


def concept(sql, seen=()):
    """(key, lesson) for the most specific SQL idea in sql, preferring ones not in seen."""
    hits = [(key, text) for pattern, key, text in _CONCEPTS if re.search(pattern, sql, re.I | re.S)]
    fresh = [h for h in hits if h[0] not in seen]
    return (fresh or hits or [None])[0]


def better_question(issues, shape=None):
    """One question the data raises: from profile issues first, then from correlations and column roles."""
    for issue in issues or []:
        if issue.get("issue") == "duplicate rows":
            return (f"{issue['rows']:,} rows are exact copies of other rows. Are they real repeat orders, "
                    "or should each count once?")
    for issue in issues or []:
        if issue.get("issue") == "spelling variants of one value":
            vs = issue["variants"]
            names = " and ".join(f"'{v['value']}'" for v in vs[:3])
            return f"Are {names} in {issue['column']} the same thing? Merging them changes the totals."
    for issue in issues or []:
        if issue.get("issue") == "empty values" and (issue.get("percent") or 0) >= 1:
            return (f"{issue['percent']:.1f}% of {issue['column']} is empty. Do empty values mean zero, "
                    "or unknown? The answer changes averages and counts.")
    for issue in issues or []:
        if issue.get("issue", "").startswith("text column"):
            ex = ", ".join(map(str, issue.get("examples") or []))
            return f"{issue['column']} has values that are not numbers ({ex}). Should those rows count?"
    for issue in issues or []:
        kind, col, n = issue.get("issue", ""), issue.get("column"), issue.get("rows") or 0
        if kind == "negative values":
            return f"{n:,} rows have a negative {col}. Refunds, or errors? Leave them in or filter them out?"
        if kind == "dates in the future":
            return f"{n:,} rows have {col} after today (latest {issue.get('max')}). Typos, or planned items?"
        if kind.endswith("may be a placeholder"):
            return f"{n:,} rows have {col} = {issue['value']:g}. A real value, or a code for unknown?"
        if kind.startswith("placeholder text"):
            return f"{n:,} rows of {col} hold text like 'N/A' or '-'. Should they count as empty?"
    shape = shape or {}
    for a, b, r in shape.get("correlations") or []:
        return f"{a} and {b} move together (r = {r}). Does one drive the other, or does a third thing drive both?"
    role = shape.get("roles") or {}
    if role.get("metrics") and role.get("dimensions"):
        per = f" per month of {role['time'][0]}" if role.get("time") else ""
        return f"Try: {role['metrics'][0]} by {role['dimensions'][0]}{per}. Which group grows fastest?"
    return None


def card(sql, qid, issues=None, seen=(), shape=None):
    """(card text, concept key) for a teach-me card, or ("", None)."""
    lesson = concept(sql, seen)
    lines = []
    if lesson:
        lines.append(f"Learn: {lesson[1]}")
    better = better_question(issues, shape)
    if better:
        lines.append(f"Ask next: {better}")
    if not lines:
        return "", None
    lines.append(f"See how your question became SQL: /grimoire explain {qid}")
    return "\n\n---\nLearning mode\n" + "\n".join(lines), (lesson[0] if lesson else None)


PREDICT_CONTEXT = (
    "[Grimoire] Prediction mode is on. When you have the query result, do not state it yet: first ask the "
    "user to guess the main number with the clarify tool (one short open question, no choices), then give "
    "the answer. Ask only once per question."
)


def guess_feedback(guess, main_raw, main_value):
    """(feedback line, close) comparing the user's guess with the answer's main number.

    close is True within 10%, None when there is nothing to compare.
    """
    claims = verify.extract(guess or "")
    word = (guess or "").strip()
    if not word:
        return None, None
    if not claims or main_value is None:
        return f"Your guess: {word}.", None
    g = claims[0]["value"]
    off = abs(main_value - g) / max(abs(main_value), 1e-9)
    close = off <= 0.10
    return f"Your guess: {claims[0]['raw']}. Answer: {main_raw}. {'Close' if close else 'Off'} by {off:.0%}.", close
