"""Benchmark questions and their true answers, computed with the stdlib csv module (not DuckDB)."""

import csv
from collections import Counter, defaultdict

QUESTIONS = [
    ("rows", "How many orders (data rows) are in {path}?"),
    ("revenue", "What is the total revenue in rupees in {path}? amount_paise is in paise; skip empty amounts."),
    ("regions", "What is the revenue in rupees per region in {path}? amount_paise is in paise. Treat region "
                "names that differ only in case or spaces as one region ('north ' is North); keep 'N. Region' "
                "separate. Skip empty amounts."),
    ("units", "Which category sold the most units in {path}, and how many units?"),
    ("aov", "What is the average order value in rupees in {path}, over orders that have an amount? "
            "amount_paise is in paise."),
    ("missing", "How many orders in {path} have an empty amount_paise?"),
    ("month", "Which month had the highest revenue in {path}, and how much in rupees? amount_paise is in "
              "paise; skip rows with no date or no amount."),
    ("customers", "How many distinct customers (customer_id) are in {path}?"),
]

MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
          "October", "November", "December"]


def truth(path):
    """{question key: (numbers that must appear, words that must appear)}."""
    rows = list(csv.DictReader(open(path, newline="")))
    paid = [r for r in rows if r["amount_paise"]]
    rupees = lambda rs: sum(int(r["amount_paise"]) for r in rs) / 100
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
    best = max(months, key=lambda m: rupees(months[m]))
    return {
        "rows": ([len(rows)], []),
        "revenue": ([rupees(paid)], []),
        "regions": ([rupees(v) for v in regions.values()], []),
        "units": ([n_units], [cat]),
        "aov": ([rupees(paid) / len(paid)], []),
        "missing": ([len(rows) - len(paid)], []),
        "month": ([rupees(months[best])], [MONTHS[best - 1]]),
        "customers": ([len({r["customer_id"] for r in rows})], []),
    }
