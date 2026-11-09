"""Make the benchmark sales files (same seed, same data every time).

python bench/make_data.py OUT_DIR  ->  sales_1k.csv, sales_50k.csv, sales_1m.csv
"""

import csv
import random
import sys
from pathlib import Path

REGIONS = ["North"] * 30 + ["north "] * 3 + ["N. Region"] + ["South"] * 25 + ["West"] * 20 + ["East"] * 20
CATEGORIES = ["Electronics", "Grocery", "Clothing", "Home", "Toys"]
SIZES = {"1k": 1_000, "50k": 50_000, "1m": 1_000_000}


def make(path, rows, seed=7):
    rng = random.Random(seed)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["order_id", "order_date", "region", "category", "amount_cents", "units", "customer_id"])
        for i in range(rows):
            day = "" if rng.random() < 0.02 else f"2026-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}"
            amount = "" if rng.random() < 0.04 else rng.randint(5_000, 400_000)
            w.writerow([100000 + i, day, rng.choice(REGIONS), rng.choice(CATEGORIES), amount,
                        rng.randint(1, 9), rng.randint(1, max(50, rows // 20))])


if __name__ == "__main__":
    out = Path(sys.argv[1]).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    for name, rows in SIZES.items():
        make(out / f"sales_{name}.csv", rows)
        print(out / f"sales_{name}.csv")
