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
commands, engine, guard, schemas, store, tools, verify = (
    pkg.commands, pkg.engine, pkg.guard, pkg.schemas, pkg.store, pkg.tools, pkg.verify)


# A real reply from a Hermes session (2026-11-08) with the results it was based on.
REAL_REPLY = """Total revenue per region, highest first (amount_paise ÷ 100 = rupees):

Raw region values as stored [q6]
  North       66,134,849.68   (6,613,484,968 paise)
  South       54,379,325.19   (5,437,932,519 paise)
  north        6,053,658.30     (605,365,830 paise)
After trimming/case-folding [q7]
  NORTH       72,188,507.98   (7,218,850,798 paise)
- "N. Region" is separate; if it also means North, North becomes 76,840,174.17.
- 50,000 rows total in the file; 5 rows are in the two malformed labels.
"""
REAL_RESULTS = [
    [["North", 6613484968, 66134849.68], ["South", 5437932519, 54379325.19], ["north ", 605365830, 6053658.3],
     ["N. Region", 465166619, 4651666.19]],
    [["NORTH", 7218850798, 72188507.98], ["SOUTH", 5437932519, 54379325.19], ["N. REGION", 465166619, 4651666.19]],
    [50000],  # attach row count
]


def test_verify():
    # precision, suffixes, percent, ignored spans
    vals = [76840174.17, 14.2, 0.383, 2436]
    assert verify.check("North made 76.8M", vals) == (["76.8M"], [])
    assert verify.check("North made ₹76,840,174.17", vals) == (["76,840,174.17"], [])
    assert verify.check("growth was 14.2%", vals) == (["14.2%"], [])
    assert verify.check("38.3% are empty", vals) == (["38.3%"], [])  # matches 0.383
    assert verify.check("2,436 rows", vals) == (["2,436"], [])
    assert verify.check("2,437 rows", vals) == ([], ["2,437"])
    skipped = "In 2026 on 2026-01-03 at 10:30, see [q7] and q12, `SELECT 42`, divide by 100, 4xx codes.\n1. first"
    assert verify.check(skipped, vals) == ([], []), verify.extract(skipped)
    assert verify.check("top 3 regions", vals, ignore=["3"]) == ([], [])
    assert verify.footer([], []) == ""
    # the real reply: the derived total and the invented count have no source
    sourced, unsourced = verify.check(REAL_REPLY, verify.numeric_values(REAL_RESULTS))
    assert unsourced == ["76,840,174.17", "5"], unsourced
    assert len(sourced) == 9, sourced


def test_data_quality(tmp, db):
    import gzip
    # malformed lines: good rows load with real columns, bad lines are reported
    bad = tmp / "messy.csv"
    rows = ["id,region,amount"] + [f"{i},{'North' if i % 3 else 'north '},{i}" for i in range(1, 40)]
    rows += ["40,South,40,extra", "41,N/A,7", "42,North,x1"]
    bad.write_text("\n".join(rows) + "\n")
    r = call(tools.attach, path=str(bad))
    assert r["tables"][0]["rows"] == 41, r
    assert r["skipped_lines"]["count"] == 1 and "TOO MANY COLUMNS" in r["skipped_lines"]["first"][0], r
    assert set(r["tables"][0]["columns"]) >= {"id BIGINT", "region VARCHAR"}, r
    assert "messy: 1 malformed" in commands.run("rejects")

    # profile lists problems: spelling variants, numbers stored as text
    r = call(tools.profile, dataset="messy")
    kinds = {(i["column"], i["issue"]) for i in r["issues"]}
    assert ("region", "spelling variants of one value") in kinds, r["issues"]
    assert ("amount", "text column that is almost all numbers") in kinds, r["issues"]

    # merge: the model only proposes; the user approves; then every query follows it
    r = call(tools.merge, dataset="messy", column="region", values=["north "], into="North")
    assert r["status"] == "pending", r
    q = "SELECT count(*) FROM messy WHERE region = 'North'"
    assert call(tools.query, sql=q)["rows"] == [[27]]  # not applied yet
    assert "Waiting for approval" in commands.run("merges")
    assert "Applied" in commands.run("merges approve")
    assert call(tools.query, sql=q)["rows"] == [[40]]
    tools.setup(db=db, eng=None)  # a new session
    assert call(tools.query, sql=q)["rows"] == [[40]]
    assert call(tools.query, sql="SELECT count(*) FROM messy_raw WHERE region = 'North'")["rows"] == [[27]]
    assert "north " in commands.run("merges") and "merges" in next(
        d for d in call(tools.catalog)["datasets"] if d["dataset"] == "messy")
    assert "error" in call(tools.merge, dataset="messy", column="id", values=["1"], into="2")  # not text
    assert "Removed 1" in commands.run("unmerge messy region")
    assert call(tools.query, sql=q)["rows"] == [[27]]
    call(tools.merge, dataset="messy", column="region", values=["north "], into="North")
    assert "Dropped 1" in commands.run("merges reject")
    assert call(tools.query, sql=q)["rows"] == [[27]]

    # JSON, NDJSON and compressed CSV
    (tmp / "events.ndjson").write_text('{"kind": "a", "n": 1}\n{"kind": "b", "n": 2}\n')
    assert call(tools.attach, path=str(tmp / "events.ndjson"))["tables"][0]["rows"] == 2
    with gzip.open(tmp / "zipped.csv.gz", "wt") as f:
        f.write("a,b\n1,2\n3,4\n")
    r = call(tools.attach, path=str(tmp / "zipped.csv.gz"))
    assert r["dataset"] == "zipped" and r["tables"][0]["rows"] == 2, r
    assert "error" in call(tools.attach, path=str(tmp / "x.parquet.gz"))

    # slash command: status, sql, unknown
    status = commands.run("")
    assert status.startswith("Grimoire ") and "messy" in status and "Learning mode" in status, status
    assert "SELECT region" in commands.run("sql q1")
    assert "Unknown command" in commands.run("dance")

    # forget one dataset: its queries, notes and merges go; other data stays
    call(tools.merge, dataset="messy", column="region", values=["north "], into="North")
    commands.run("merges approve")
    before = len(store.recent_queries(db, 1000))
    messy_queries = db.execute("SELECT count(*) FROM queries WHERE datasets = 'messy'").fetchone()[0]
    assert messy_queries >= 3, messy_queries
    out = commands.run("forget messy")
    assert "Deleted messy" in out, out
    assert len(store.recent_queries(db, 1000)) == before - messy_queries
    assert store.merges(db, "messy") == {} and "messy" not in commands.run("")
    assert "error" in call(tools.query, sql="SELECT count(*) FROM messy")
    assert call(tools.query, sql="SELECT count(*) FROM sales")["rows"] == [[3]]  # others untouched
    assert "Deleted" in commands.run("clear history") and store.recent_queries(db) == []
    assert "cannot be undone" in commands.run("reset")
    assert "Deleted everything" in commands.run("reset confirm")
    assert store.datasets(db) == [] and "error" in call(tools.query, sql="SELECT count(*) FROM sales")


def test_security(tmp, db):
    tools.setup(db=db, eng=None)
    lite = tmp / "sec.db"
    con = sqlite3.connect(lite)
    con.execute("CREATE TABLE t (id INTEGER, v REAL)")
    con.executemany("INSERT INTO t VALUES (?, ?)", [(1, 10.0), (2, 20.0)])
    con.commit()
    con.close()
    assert "error" not in call(tools.attach, path=str(lite))
    # F1: data-modifying CTEs start like a read but must be refused
    for bad in ["WITH x AS (SELECT 1) INSERT INTO sec.t VALUES (3, 1)",
                "WITH x AS (SELECT 1) DELETE FROM sec.t", "WITH x AS (SELECT 1) UPDATE sec.t SET v = 0",
                "PIVOT sec.t ON id USING sum(v)", "CREATE TABLE z (a INT)", "SELECT 1; SELECT 2"]:
        assert "error" in call(tools.query, sql=bad), bad
    assert call(tools.query, sql="SELECT sum(v) FROM sec.t")["rows"] == [[30.0]]
    assert call(tools.query, sql="SELECT ';' AS semi")["rows"] == [[";"]]  # ';' inside text is fine now
    for ok in ["FROM sec.t", "DESCRIBE sec.t", "SUMMARIZE sec.t", "SHOW TABLES", "VALUES (1)",
               "WITH a AS (SELECT 1 AS x) SELECT x FROM a"]:
        assert "error" not in call(tools.query, sql=ok), ok
    # F4: results carry the untrusted-data label
    assert call(tools.query, sql="SELECT 1")["note"] == tools.UNTRUSTED
    # F6: private folders are refused unless allowed
    home = Path(tempfile.mkdtemp())
    assert guard.private_folder(str(home / ".ssh" / "x.csv"), home=str(home)) == ".ssh"
    assert guard.private_folder(str(home / "Library" / "Messages" / "chat.db"), home=str(home)) == "Library"
    assert guard.private_folder(str(home / "Library" / "Mobile Documents" / "a.csv"), home=str(home)) is None
    assert guard.private_folder(str(home / "data" / "a.csv"), home=str(home)) is None
    hermes_db = Path.home() / ".hermes" / "state.db"
    r = call(tools.attach, path=str(hermes_db))
    assert "does not open files in ~/.hermes" in r.get("error", ""), r


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

    # tool descriptions: the Tool Search listing shows only the first sentence, up to 80 characters
    for schema in schemas.ALL:
        first = schema["description"].split(". ")[0] + "."
        assert len(first) <= 80, (schema["name"], len(first), first)

    # read guard: blocks big data files only
    big = tmp / "big.csv"
    big.write_text("a,b\n" + "1,2\n" * 100000)
    assert guard.check("read_file", {"path": str(big)})["action"] == "block"
    assert guard.check("read_file", {"path": "big.csv"}, cwd=str(tmp))["action"] == "block"
    assert guard.check("read_file", {"path": str(csv)}) is None          # small file
    assert guard.check("read_file", {"path": str(big)}, limit_kb=0) is None  # turned off
    assert guard.check("terminal", {"command": f"head {big}"}) is None   # other tools
    notes = tmp / "notes.md"
    notes.write_text("x" * 400000)
    assert guard.check("read_file", {"path": str(notes)}) is None        # not a data file
    assert guard.check("read_file", {"path": str(tmp / "nope.csv")}) is None

    # discovery hint: only when a data file is mentioned
    hint = guard.data_file_hint("What is revenue per region in /tmp/data/sales.csv? Highest first.")
    assert hint and "/tmp/data/sales.csv" in hint and "grimoire_attach" in hint, hint
    assert "orders.parquet" in guard.data_file_hint("compare orders.parquet with 'shop.db'")
    for msg in ["hello", "explain the csv format", "see example.com/page", "", None, "v1.db2 release"]:
        assert guard.data_file_hint(msg) is None, msg

    # reply check through the tools: only numbers this session's tools returned count
    test_verify()
    tools.remember_user_message("test", "show the top 2 regions")
    note = tools.check_reply("North has 150 and South has 250; top 2 shown. Total 999.", "test")
    assert "2 of 3" in note and "999" in note and "No source" in note, note
    assert tools.check_reply("Sales total is 150 [q1].", "other-session").endswith("the number matches query results.")
    assert tools.check_reply("no numbers here", "test") == ""
    assert tools.check_reply("Revenue 123", "never-used-grimoire") == ""

    test_data_quality(tmp, db)
    test_security(tmp, db)
    print("selftest passed")


if __name__ == "__main__":
    main()
