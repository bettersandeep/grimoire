"""Self-test for the engine, the store and the tools. Run: python -I selftest.py (needs duckdb)."""

import importlib
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
pkg = importlib.import_module(HERE.name)
engine, store, tools = pkg.engine, pkg.store, pkg.tools


def call(handler, **args):
    return json.loads(handler(args, session_id="test"))


def main():
    tmp = Path(tempfile.mkdtemp())
    csv = tmp / "sales.csv"
    csv.write_text("region,amount,day\nNorth,100,2026-01-01\nSouth,250,2026-01-02\nNorth,50,2026-01-03\n")
    secret = tmp / "secret.csv"
    secret.write_text("x\n1\n")
    lite = tmp / "shop.db"
    con = sqlite3.connect(lite)
    con.execute("CREATE TABLE orders (id INTEGER, total REAL, note TEXT)")
    con.executemany("INSERT INTO orders VALUES (?, ?, ?)", [(1, 9.5, "a"), (2, 20.0, None)])
    con.commit()
    con.close()

    db = sqlite3.connect(":memory:", check_same_thread=False)
    tools.setup(db=db, eng=None)

    # attach and profile
    r = call(tools.attach, path=str(csv))
    assert r["dataset"] == "sales" and r["tables"][0]["rows"] == 3, r
    r = call(tools.profile, dataset="sales")
    assert {row[0] for row in r["profile"]} == {"region", "amount", "day"}, r

    # query returns an id and correct numbers
    r = call(tools.query, sql="SELECT region, sum(amount) AS total FROM sales GROUP BY region ORDER BY region")
    assert r["id"] == "q1" and r["rows"] == [["North", 150], ["South", 250]], r
    assert store.get_query(db, "q1")["rows"] == [["North", 150], ["South", 250]]

    # SQLite through the stdlib reader
    r = call(tools.attach, path=str(lite))
    assert r["dataset"] == "shop" and r["tables"][0]["table"] == "shop.orders", r
    r = call(tools.query, sql="SELECT sum(total) FROM shop.orders")
    assert r["rows"] == [[29.5]], r
    r = call(tools.profile, dataset="shop", table="orders")
    assert "error" not in r, r

    # safety: no writes, no other files, no settings changes, no extensions, one statement
    for bad in [
        "DROP VIEW sales",
        f"COPY sales TO '{tmp / 'out.csv'}'",
        f"SELECT * FROM read_csv('{secret}')",
        "SET enable_external_access = true",
        "INSTALL httpfs",
        "SELECT 1; SELECT 2",
    ]:
        r = call(tools.query, sql=bad)
        assert "error" in r, (bad, r)
    assert not (tmp / "out.csv").exists()

    # row cap
    r = call(tools.query, sql="SELECT * FROM range(500)")
    assert len(r["rows"]) == engine.MAX_ROWS and "truncated" in r, len(r["rows"])

    # notes and catalog survive a new engine (a new session)
    r = call(tools.note, dataset="sales", column="amount", note="in cents")
    assert r.get("saved"), r
    tools.setup(db=db, eng=None)
    r = call(tools.catalog)
    sales = next(d for d in r["datasets"] if d["dataset"] == "sales")
    assert sales["notes"] == ["sales.amount: in cents"], sales
    r = call(tools.query, sql="SELECT count(*) FROM sales")
    assert r["rows"] == [[3]], r

    # errors are JSON, never exceptions
    assert "error" in call(tools.attach, path=str(tmp / "missing.csv"))
    assert "error" in call(tools.profile, dataset="nope")

    print("selftest passed")


if __name__ == "__main__":
    main()
