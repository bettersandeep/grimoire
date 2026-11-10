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
    """{question key: (numbers that must appear, words that must appear)}. One streaming pass, exact cents,
    so a 10-million-row file needs little memory."""
    rows = missing = paid_n = paid_cents = 0
    region_cents = defaultdict(int)
    units = Counter()
    month_cents = defaultdict(int)
    customers = set()
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            rows += 1
            units[r["category"]] += int(r["units"])
            customers.add(r["customer_id"])
            if not r["amount_cents"]:
                missing += 1
                continue
            cents = int(r["amount_cents"])
            paid_n += 1
            paid_cents += cents
            region_cents[r["region"].strip().lower()] += cents
            if r["order_date"]:
                month_cents[int(r["order_date"][5:7])] += cents
    cat, n_units = units.most_common(1)[0]
    best = max(month_cents, key=month_cents.get)
    return {
        "rows": ([rows], []),
        "revenue": ([paid_cents / 100], []),
        "regions": ([c / 100 for c in region_cents.values()], []),
        "units": ([n_units], [cat]),
        "aov": ([paid_cents / 100 / paid_n], []),
        "missing": ([missing], []),
        "month": ([month_cents[best] / 100], [MONTHS[best - 1]]),
        "customers": ([len(customers)], []),
    }
