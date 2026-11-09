"""Benchmark questions and their true answers, computed with the stdlib csv module (not DuckDB)."""

import csv
from collections import Counter, defaultdict

QUESTIONS = [
    ("rows", "How many orders (data rows) are in {path}?"),
    ("revenue", "What is the total revenue in US dollars in {path}? amount_cents is in cents; skip empty amounts."),
    ("regions", "What is the revenue in US dollars per region in {path}? amount_cents is in cents. Treat region "
                "names that differ only in case or spaces as one region ('north ' is North); keep 'N. Region' "
                "separate. Skip empty amounts."),
    ("units", "Which category sold the most units in {path}, and how many units?"),
    ("aov", "What is the average order value in US dollars in {path}, over orders that have an amount? "
            "amount_cents is in cents."),
    ("missing", "How many orders in {path} have an empty amount_cents?"),
    ("month", "Which month had the highest revenue in {path}, and how much in US dollars? amount_cents is in "
              "cents; skip rows with no date or no amount."),
    ("customers", "How many distinct customers (customer_id) are in {path}?"),
]

MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
          "October", "November", "December"]


def truth(path):
    """{question key: (numbers that must appear, words that must appear)}."""
    rows = list(csv.DictReader(open(path, newline="")))
    paid = [r for r in rows if r["amount_cents"]]
    dollars = lambda rs: sum(int(r["amount_cents"]) for r in rs) / 100
    regions = defaultdict(list)
    for r in paid:
        regions[r["region"].strip().lower()].append(r)
    units = Counter()
    for r in rows:
        units[r["category"]] += int(r["units"])
    cat, n_units = units.most_common(1)[0]
    months = defaultdict(list)
    for r in paid:
        if r["order_date"]:
            months[int(r["order_date"][5:7])].append(r)
    best = max(months, key=lambda m: dollars(months[m]))
    return {
        "rows": ([len(rows)], []),
        "revenue": ([dollars(paid)], []),
        "regions": ([dollars(v) for v in regions.values()], []),
        "units": ([n_units], [cat]),
        "aov": ([dollars(paid) / len(paid)], []),
        "missing": ([len(rows) - len(paid)], []),
        "month": ([dollars(months[best])], [MONTHS[best - 1]]),
        "customers": ([len({r["customer_id"] for r in rows})], []),
    }
