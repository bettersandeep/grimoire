"""Benchmark questions on real public data: NYC yellow taxi trips, January to June 2024 (20.3M rows).

Get the data (about 340 MB from the NYC Taxi and Limousine Commission):
  for m in 01 02 03 04 05 06; do curl -o ~/grimoire-bench/nyc/yellow_2024-$m.parquet \\
    https://d37ci6vzurychx.cloudfront.net/trip-data/yellow_tripdata_2024-$m.parquet; done
The CSV case is the same rows written by DuckDB as one 2 GB file:
  COPY (SELECT * FROM '~/grimoire-bench/nyc/yellow_2024-*.parquet') TO '~/grimoire-bench/nyc_trips_h1.csv' (HEADER)

True answers come from SQL written for this file (by hand, not by Grimoire), run once with DuckDB.
"""

FILES = {"parquet": "nyc/yellow_2024-*.parquet", "csv": "nyc_trips_h1.csv"}

QUESTIONS = [
    ("trips", "How many trips (rows) are in {path}?"),
    ("avg_fare", "What is the average fare_amount in {path}, over trips with fare_amount above 0? Two decimals."),
    ("busy_hour", "Which pickup hour of the day (0 to 23, from tpep_pickup_datetime) has the most trips in {path}, "
                  "and how many trips start in that hour?"),
    ("card_share", "What percent of trips in {path} were paid by credit card (payment_type = 1)? One decimal."),
    ("top_zone", "Which PULocationID has the most pickups in {path}, and how many pickups?"),
    ("tip_rate", "For credit card trips (payment_type = 1) with fare_amount above 0 in {path}, what is the total "
                 "tip_amount divided by the total fare_amount, as a percent with one decimal?"),
]

SQL = {
    "trips": "SELECT count(*) FROM t",
    "avg_fare": "SELECT round(avg(fare_amount), 2) FROM t WHERE fare_amount > 0",
    "busy_hour": "SELECT hour(tpep_pickup_datetime) AS h, count(*) AS n FROM t GROUP BY 1 ORDER BY 2 DESC LIMIT 1",
    "card_share": "SELECT round(100 * count_if(payment_type = 1) / count(*), 1) FROM t",
    "top_zone": "SELECT PULocationID, count(*) FROM t GROUP BY 1 ORDER BY 2 DESC LIMIT 1",
    "tip_rate": "SELECT round(100 * sum(tip_amount) / sum(fare_amount), 1) FROM t WHERE payment_type = 1 AND fare_amount > 0",
}


def truth(path):
    """{question key: (numbers that must appear, words that must appear)}."""
    import duckdb  # dev-only: the benchmark runs with an environment that has DuckDB
    con = duckdb.connect()
    con.execute(f"CREATE VIEW t AS SELECT * FROM '{path}'")
    out = {}
    for key, sql in SQL.items():
        row = con.execute(sql).fetchone()
        out[key] = ([float(v) for v in row], [])
    return out
