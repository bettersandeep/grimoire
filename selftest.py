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
commands, engine, guard, learning, schemas, store, tools, verify = (
    pkg.commands, pkg.engine, pkg.guard, pkg.learning, pkg.schemas, pkg.store, pkg.tools, pkg.verify)
drivers_mod = pkg.drivers
relations = pkg.relations


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
    chk = lambda text, v=vals, **kw: verify.check(text, v, **kw)
    assert chk("North made 76.8M") == (["76.8M"], [], [])
    assert chk("North made $76,840,174.17") == (["76,840,174.17"], [], [])
    assert chk("North made ₹76,840,174.17") == (["76,840,174.17"], [], [])  # other currency symbols work too
    assert chk("growth was 14.2%") == (["14.2%"], [], [])
    assert chk("38.3% are empty") == (["38.3%"], [], [])  # matches 0.383
    assert chk("2,436 rows") == (["2,436"], [], [])
    assert chk("2,437 rows") == ([], [], ["2,437"])
    skipped = ("In 2026 on 2026-01-03 at 10:30, see [q7] and q12, `SELECT 42`, divide by 100 or 100.0, "
               "April (2026-04), 4xx codes.\n1. first")
    assert chk(skipped) == ([], [], []), verify.extract(skipped)
    assert chk("top 3 regions", ignore=["3"]) == ([], [], [])
    assert verify.footer([], []) == ""
    # derived numbers: simple arithmetic on shown numbers, unit changes, column totals
    v = [50000, 1996, 189759.34, 72188507.98, 4651666.19]
    assert chk("50,000 rows, 1,996 empty, so 48,004 kept", v) == (["50,000", "1,996"], ["48,004"], [])
    assert chk("$189,759.34 (18,975,934 cents)", v) == (["189,759.34"], ["18,975,934"], [])
    assert chk("72,188,507.98 and 4,651,666.19 make 76,840,174.17", v)[1] == ["76,840,174.17"]
    assert chk("Total $300", [100, 200], totals=[300])[1] == ["300"]
    assert chk("964 of 1000 rows have an amount (36 skipped)", [1000, 964]) == (["964"], ["36"], [])
    assert chk("about 2,000 empty", v) == ([], [], ["2,000"])  # rounded: still flagged
    # the real reply: the derived total is now traced by arithmetic; the invented count is still flagged
    sourced, derived, unsourced = verify.check(REAL_REPLY, verify.numeric_values(REAL_RESULTS))
    assert unsourced == ["5"], (unsourced, derived)
    assert derived == ["76,840,174.17"] and len(sourced) == 9, (sourced, derived)
    assert "1 by simple arithmetic: 76,840,174.17" in verify.footer(sourced, unsourced, derived)


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


def test_learning(tmp, db):
    tools.setup(db=db, eng=None)
    csv = tmp / "orders.csv"
    csv.write_text("region,amount\nNorth,100\nnorth ,50\nSouth,250\nSouth,\n")
    call(tools.attach, path=str(csv))
    call(tools.profile, dataset="orders")
    # off by default: no card, status says off
    assert "Learning mode: off" in commands.run("")
    tools.remember_user_message("test", "What is the total amount per region, highest first?")
    r = call(tools.query, sql="SELECT region, sum(amount) AS total FROM orders GROUP BY region ORDER BY total DESC",
             purpose="total per region")
    qid = r["id"]
    reply = f"South leads with 250 [{qid}], then North 100."
    assert "Learning mode" not in tools.check_reply(reply, "test")
    # explain: the user's words next to the SQL parts
    text = commands.run(f"explain {qid}")
    assert "Your question: What is the total amount per region" in text, text
    assert '"total' in text and "sum(amount)" in text, text
    assert '"per' in text and "GROUP BY region" in text, text
    assert '"highest' in text and "ORDER BY total DESC" in text, text
    # learning on: a card with one idea and one better question from the profile issues
    assert "Predictions are on" not in commands.run("learn predict on")  # needs learning first
    assert "on" in commands.run("learn on")
    out = tools.check_reply(reply, "test")
    assert "Learning mode" in out and "Learn:" in out and f"/grimoire explain {qid}" in out, out
    assert "Ask next:" in out and "'North'" in out, out
    out2 = tools.check_reply(reply, "test")
    assert out2.split("Learn:")[1][:40] != out.split("Learn:")[1][:40], "the next card teaches a new idea"
    # predictions: the clarify answer is scored against the main number of the reply
    assert "Predictions are on" in commands.run("learn predict on")
    assert "Prediction mode is on" in learning.PREDICT_CONTEXT
    tools.record_guess("test", json.dumps({"responses": [{"status": "answered", "user_response": "240"}]}))
    out = tools.check_reply(reply, "test")
    assert "Your guess: 240. Answer: 250. Close by 4%." in out and "1 of 1" in out, out
    tools.record_guess("test", json.dumps({"responses": [{"user_response": "about 500"}]}))
    out = tools.check_reply(reply, "test")
    assert "Off by 100%" in out and "1 of 2" in out, out
    assert "Predictions: on (1 of 2 guesses within 10%)" in commands.run("")
    commands.run("learn off")
    assert "Learning mode" not in tools.check_reply(reply, "test")
    # clause splitter keeps subqueries and strings whole
    parts = learning.clauses("SELECT a FROM (SELECT * FROM t WHERE x = 'GROUP BY') s WHERE b > 1 ORDER BY a LIMIT 5")
    assert [p[0] for p in parts] == ["SELECT", "FROM", "WHERE", "ORDER BY", "LIMIT"], parts


def test_auto_attach(tmp, db):
    tools.setup(db=db, eng=None)
    (tmp / "shop").mkdir(exist_ok=True)
    f = tmp / "shop" / "visits.csv"
    f.write_text("day,visits\n2026-01-01,5\n2026-01-02,7\n")
    ctx = tools.auto_attach("How many visits in total in shop/visits.csv?", "auto", cwd=str(tmp))
    assert "is table \"visits\" (2 rows): day DATE, visits BIGINT" in ctx, ctx
    assert 'tool_call with name "grimoire_query"' in ctx, ctx
    assert call(tools.query, sql="SELECT sum(visits) FROM visits")["rows"] == [[12]]
    assert tools.auto_attach("hello there", "auto") is None
    assert "grimoire_drivers" not in ctx  # plain questions do not pay for the drivers hint
    assert "grimoire_drivers" in tools.auto_attach("Why did visits drop in shop/visits.csv?", "auto", cwd=str(tmp))
    hint = tools.auto_attach("what about nope/missing.csv?", "auto", cwd=str(tmp))
    assert hint.startswith("[Grimoire] Data file mentioned: nope/missing.csv"), hint
    # an unchanged file is not reopened; a changed one is
    eng = tools._get()[1]
    before = eng._con
    tools.auto_attach("again shop/visits.csv", "auto", cwd=str(tmp))
    assert eng._con is before
    f.write_text("day,visits\n2026-01-01,5\n2026-01-02,7\n2026-01-03,1\n")
    assert "(3 rows)" in tools.auto_attach("and shop/visits.csv now", "auto", cwd=str(tmp))


def test_data_plugin(tmp, db):
    tools.setup(db=db, eng=None)
    # a folder or a pattern reads several files as one table, with a filename column
    folder = tmp / "months"
    folder.mkdir(exist_ok=True)
    (folder / "jan.csv").write_text("day,amount\n2026-01-01,5\n2026-01-01,5\n")
    (folder / "feb.csv").write_text("day,amount,note\n2026-02-01,7,x\n")
    r = call(tools.attach, path=str(folder / "*.csv"), name="months")
    assert r["tables"][0]["rows"] == 3 and "filename VARCHAR" in r["tables"][0]["columns"], r
    assert call(tools.query, sql="SELECT sum(amount), count(note) FROM months")["rows"] == [[17, 1]]
    (folder / "mar.csv").write_text("day,amount\n2026-03-01,100\n")  # a new file joins on the next attach
    assert call(tools.attach, path=str(folder / "*.csv"), name="months")["tables"][0]["rows"] == 4
    assert call(tools.attach, path=str(folder))["dataset"] == "months"
    assert "error" in call(tools.attach, path=str(tmp / "nothing" / "*.csv"))
    # duplicates and per-column statistics
    p = call(tools.profile, dataset="months")
    assert p["issues"][0] == {"issue": "duplicate rows", "rows": 1}, p["issues"]
    st = call(tools.profile, dataset="months", column="amount")
    assert st["median"] == 6.0 and st["max"] == 100 and st["outliers"]["rows"] == 1, st
    assert st["outliers"]["most_extreme"] == [100], st
    st = call(tools.profile, dataset="months", column="day")
    assert st["rows_per_month"] == [["2026-01", 2], ["2026-02", 1], ["2026-03", 1]], st
    assert "error" in call(tools.profile, dataset="months", column="nope")
    # chart, rerun, report
    q = call(tools.query, sql="SELECT strftime(day, '%Y-%m') AS month, sum(amount) AS total FROM months GROUP BY 1 ORDER BY 1",
             purpose="total per month")
    chart = commands.run(f"chart {q['id']}")
    assert "2026-03  ████████████████████████████ 100" in chart, chart
    assert "still holds" in commands.run(f"rerun {q['id']}")
    (folder / "mar.csv").write_text("day,amount\n2026-03-01,1\n")
    call(tools.attach, path=str(folder / "*.csv"), name="months")
    assert "changed since it was saved" in commands.run(f"rerun {q['id']}")
    out = commands.run("report months")
    path = out.split(": ", 1)[1].split("\n")[0]
    page = Path(path).read_text()
    assert "total per month" in page and "SQL behind these numbers" in page and "<svg" in page, out
    assert "<polyline" in page  # months get a line chart
    rep = pkg.report
    assert rep.is_time(["2026-01", "2026-02", "2026-03"]) and rep.is_time(["2024", "2025", "2026"])
    assert not rep.is_time(["2026-01", "North", "2026-03"]) and not rep.is_time(["2026-01", "2026-02"])
    assert [rep.compact(v) for v in (8171280.52, 4085.6, 12, 0)] == ["8.17M", "4.09K", "12", "0"]
    Path(path).unlink()
    # changes made in the Desktop panel (another process: store only) apply before the next query
    (tmp / "regions.csv").write_text("region,n\nNorth,1\nnorth ,2\n")
    call(tools.attach, path=str(tmp / "regions.csv"))
    store.propose_merge(db, "regions", "regions", "region", ["north "], "North")
    store.approve_merges(db)
    assert call(tools.query, sql="SELECT count(DISTINCT region) FROM regions")["rows"] == [[1]]
    store.forget_dataset(db, "regions")
    assert "error" in call(tools.query, sql="SELECT * FROM regions")


def test_audit(tmp, db):
    tools.setup(db=db, eng=None)
    (tmp / "orders.csv").write_text(
        "id,customer_id,day,amount\n1,10,2026-01-05,100\n2,10,2026-01-20,\n3,11,2026-02-03,50\n4,12,2026-02-10,70\n")
    (tmp / "visits.csv").write_text("customer_id,channel\n10,web\n10,app\n11,web\n")
    call(tools.attach, path=str(tmp / "orders.csv"))
    call(tools.attach, path=str(tmp / "visits.csv"))
    run = lambda sql: call(tools.query, sql=sql)
    eng = tools._get()[1]
    # assumptions: what a filter left out, top-N, plain words for IS NOT NULL
    q = store.get_query(db, run("SELECT sum(amount) AS total FROM orders WHERE amount IS NOT NULL")["id"])
    assert pkg.audit.assumptions(q, eng) == ["left out 1 of 4 rows (empty amount)"], pkg.audit.assumptions(q, eng)
    q = store.get_query(db, run("SELECT id, amount FROM orders ORDER BY amount DESC LIMIT 2")["id"])
    assert pkg.audit.assumptions(q, eng) == ["shows the top 2 only"]
    # pitfalls: incomplete last month, average of averages, a join that repeats rows on both sides
    q = store.get_query(db, run("SELECT strftime(day, '%Y-%m') AS m, sum(amount) AS t FROM orders GROUP BY 1 ORDER BY 1")["id"])
    assert any("the last month (2026-02) has data only up to 2026-02-10" in w for w in pkg.audit.pitfalls(q, eng))
    q = store.get_query(db, run("SELECT avg(a) FROM (SELECT customer_id, avg(amount) AS a FROM orders GROUP BY 1)")["id"])
    assert any(w.startswith("average of averages") for w in pkg.audit.pitfalls(q, eng))
    q = store.get_query(db, run("SELECT sum(o.amount) FROM orders o JOIN visits v USING (customer_id)")["id"])
    assert any("join on customer_id matches several rows on both sides" in w for w in pkg.audit.pitfalls(q, eng))
    q = store.get_query(db, run("SELECT count(*) FROM orders")["id"])
    assert pkg.audit.pitfalls(q, eng) == [] and pkg.audit.assumptions(q, eng) == []
    # the footer: verdict follows the number check and the warnings
    qid = run("SELECT sum(amount) AS total FROM orders WHERE amount IS NOT NULL")["id"]
    out = tools.check_reply(f"Total is 220 [{qid}].", "test")
    assert "Verdict: ready to share." in out and "Assumes: left out 1 of 4 rows (empty amount)" in out, out
    out = tools.check_reply(f"Total is 999 [{qid}].", "test")
    assert "Verdict: needs revision." in out, out
    mid = run("SELECT strftime(day, '%Y-%m') AS m, sum(amount) AS t FROM orders GROUP BY 1 ORDER BY 1")["id"]
    out = tools.check_reply(f"February brought 120 [{mid}].", "test")
    assert "Verdict: share with caveats." in out and "Watch out:" in out, out


def test_analysis_checks(tmp, db):
    tools.setup(db=db, eng=None)
    csv = tmp / "visits.csv"
    lines = ["ts,converted"]
    for month, n in ((1, 5), (2, 10), (3, 40), (4, 12), (5, 3)):  # March has 4x the rows of February
        lines += [f"2026-{month:02d}-{1 + i % 27:02d} {i % 24:02d}:15:00,{i % 3 == 0}" for i in range(n)]
    lines.append("2002-01-05 10:00:00,true")  # a stray date, filtered out below: must not count as a period
    csv.write_text("\n".join(lines) + "\n")
    call(tools.attach, path=str(csv))
    run = lambda sql: call(tools.query, sql=sql)
    rate = ("SELECT date_trunc('month', ts) AS m, round(100 * count_if(converted) / count(*), 1) AS pct FROM visits "
            "WHERE ts >= '2026-01-01' GROUP BY 1 ORDER BY 1")
    q = store.get_query(db, run(rate)["id"])
    assert any("rows per month range from 10 to 40" in w for w in pkg.audit.pitfalls(q, eng_of())), pkg.audit.pitfalls(q, eng_of())
    # a total per month is not a rate, and a division by 100 is a unit change: no warning
    for sql in ("SELECT date_trunc('month', ts) AS m, count(*) AS n FROM visits GROUP BY 1 ORDER BY 1",
                "SELECT date_trunc('month', ts) AS m, count(*) / 100 AS hundreds FROM visits GROUP BY 1 ORDER BY 1"):
        q = store.get_query(db, run(sql)["id"])
        assert not any("rows per month" in w for w in pkg.audit.pitfalls(q, eng_of())), sql
    # bucketing a timestamp by hour or day says which clock it uses
    q = store.get_query(db, run("SELECT hour(ts) AS h, count(*) FROM visits GROUP BY 1 ORDER BY 1")["id"])
    assert "ts has no time zone, so days and hours are as written in the file" in pkg.audit.assumptions(q, eng_of())
    q = store.get_query(db, run("SELECT ts::DATE AS d, count(*) FROM visits GROUP BY 1 ORDER BY 1")["id"])
    assert any("no time zone" in a for a in pkg.audit.assumptions(q, eng_of()))
    q = store.get_query(db, run("SELECT count(*) FROM visits")["id"])
    assert pkg.audit.assumptions(q, eng_of()) == []
    # a rate typed into the SQL is an assumption; unit factors are not
    q = store.get_query(db, run("SELECT round(count(*) / 100.0 / 86.5, 2) AS usd, count(*) * 1000 AS m FROM visits")["id"])
    assert "uses 86.5, written into the SQL, not taken from the data" in pkg.audit.pitfalls(q, eng_of())
    assert pkg.audit._constants("sum(x) / 100, avg(y) * 2, 0.18 * fare, z / 1000") == ["0.18"]
    assert pkg.audit._constants("floor(fare_amount / 5) * 5 AS bucket, count(*)") == []  # a bucket width


def eng_of():
    return tools._get()[1]


def test_metrics(tmp, db):
    tools.setup(db=db, eng=None)
    (tmp / "pay.csv").write_text("region,amount_cents\nNorth,1000\nNorth,2500\nSouth,\n")
    call(tools.attach, path=str(tmp / "pay.csv"))
    out = commands.run("define revenue = sum(amount_cents) / 100")
    assert out.startswith("Saved revenue() = sum(amount_cents) / 100") and "pay" in out, out
    for bad, why in [("define sum = sum(x)", "already a DuckDB function"), ("define r = sum(nope)", "does not work"),
                     ("define r = 1; DROP VIEW pay", "one SQL expression"), ("define Bad Name = 1", "lower-case name"),
                     ("define revenue", "Use: /grimoire define")]:
        assert why in commands.run(bad), (bad, commands.run(bad))
    r = call(tools.query, sql="SELECT region, Revenue() AS rev FROM pay GROUP BY 1 ORDER BY 1")
    assert r["rows"] == [["North", 35.0], ["South", None]] and "revenue()" in r["metrics"], r
    assert "(sum(amount_cents) / 100)" in store.get_query(db, r["id"])["sql"]  # the receipt shows the real SQL
    assert "revenue() = sum(amount_cents) / 100" in tools.auto_attach(f"total in {tmp / 'pay.csv'}", "m")
    assert call(tools.catalog)["metrics"] == {"revenue()": "sum(amount_cents) / 100"}
    assert "error" in call(tools.query, sql="SELECT revenue(); SELECT 1")  # expansion keeps the one-SELECT rule
    assert commands.run("metrics") == "revenue() = sum(amount_cents) / 100"
    assert commands.run("undefine revenue") == "Removed revenue()."
    assert "error" in call(tools.query, sql="SELECT revenue() FROM pay")  # gone: no silent fallback


def test_drivers(tmp, db):
    tools.setup(db=db, eng=None)
    (tmp / "shop.csv").write_text("day,region,item,amount\n"
                                  "2026-02-01,North,a,100\n2026-02-02,South,a,100\n2026-02-03,South,b,50\n"
                                  "2026-03-01,North,a,160\n2026-03-02,South,a,40\n2026-03-05,West,b,50\n")
    call(tools.attach, path=str(tmp / "shop.csv"))
    r = call(tools.drivers, dataset="shop", measure="sum(amount)", time_column="day", before="2026-02", after="2026-03")
    assert r["split_by"] == ["region", "item"], r
    rows = {(x[0], x[1]): x[2:] for x in r["rows"]}
    assert rows[("(total)", None)] == [250, 250, 0, 100.0], rows
    assert rows[("region", "North")][:3] == [100, 160, 60] and rows[("region", "West")][:3] == [None, 50, 50], rows
    assert "add up to 100" in r["how_to_read"]
    assert store.get_query(db, r["id"])["purpose"].startswith("What drives the change")  # citable receipt
    r = call(tools.drivers, dataset="shop", measure="avg(amount)", time_column="day", before="2026-02", after="2026-03",
             dimensions=["region"])
    assert r["split_by"] == ["region"] and "does not add up" in r["how_to_read"], r
    r = call(tools.drivers, dataset="shop", measure="amount", time_column="day", before="2026-02", after="2026-03")
    assert r["rows"][0][2:5] == [250, 250, 0], r  # a bare column is summed
    assert drivers_mod.additive("sum(x) / 100") and drivers_mod.additive("count(*)") and not drivers_mod.additive("avg(x)")
    assert not drivers_mod.additive("sum(a) / sum(b)")
    for bad in [dict(before="Feb", after="2026-03"), dict(before="2030-01", after="2030-02"), dict(time_column="nope")]:
        args = dict(dataset="shop", time_column="day", before="2026-02", after="2026-03") | bad
        assert "error" in call(tools.drivers, **args), bad


def test_relations(tmp, db):
    tools.setup(db=db, eng=None)
    (tmp / "people.csv").write_text("person_id,team\n1,a\n2,b\n3,a\n")
    rows = "".join(f"{i},{(i % 3) + 1},{'xy'[i % 2]},2026-01-{(i % 28) + 1:02d},{i * 2},{i * 4 + 1}\n" for i in range(1, 41))
    (tmp / "jobs.csv").write_text("job_id,person_id,kind,day,hours,cost\n" + rows)
    call(tools.attach, path=str(tmp / "people.csv"))
    call(tools.attach, path=str(tmp / "jobs.csv"))
    p = call(tools.profile, dataset="jobs")
    assert p["roles"] == {"dimensions": ["kind"], "metrics": ["hours", "cost"], "time": ["day"]}, p["roles"]
    assert p["correlations"] == [["hours", "cost", 1.0]], p.get("correlations")
    assert p["join_keys"] == [{"column": "person_id", "with": "people.person_id", "match_pct": 100.0}], p.get("join_keys")
    shape = store.get_json(db, "shape:jobs")
    assert learning.better_question([], shape).startswith("hours and cost move together")
    assert learning.better_question([], {"roles": p["roles"]}) == "Try: hours by kind per month of day. Which group grows fastest?"
    assert learning.better_question([{"issue": "duplicate rows", "rows": 2}], shape).startswith("2 rows are exact copies")


def test_profile_checks(tmp, db):
    tools.setup(db=db, eng=None)
    csv = tmp / "odd.csv"
    lines = ["id,city,amount,age,shipped,source,score"]
    for i in range(1, 41):
        city = ["Pune", "N/A", "-", "Delhi"][i % 4]
        amount = -5 if i in (3, 7) else 100 + i
        age = 9999 if i == 5 else 20 + i % 30
        shipped = "2999-01-01" if i == 9 else f"2026-01-{1 + i % 28:02d}"
        score = -1 if i == 2 else i  # a negative score is not an amount: not flagged
        lines.append(f"{i},{city},{amount},{age},{shipped},web,{score}")
    csv.write_text("\n".join(lines) + "\n")
    call(tools.attach, path=str(csv))
    r = call(tools.profile, dataset="odd")
    got = {(i.get("column"), i["issue"]): i for i in r["issues"]}
    assert got[("city", "placeholder text like 'N/A', '-' or 'unknown'")]["rows"] == 20, got
    assert got[("amount", "negative values")]["rows"] == 2, got
    assert got[("age", "9999 may be a placeholder")]["rows"] == 1, got
    assert got[("shipped", "dates in the future")]["rows"] == 1, got
    assert ("source", "same value in every row") in got, got
    assert not any(c == "score" for c, _ in got), got
    assert r["health"].startswith("8") and "5 other problems" in r["health"], r["health"]
    assert store.get_json(db, "health:odd", {})["score"] == int(r["health"].split("/")[0])
    # the score explains every point taken off, and stays in 0..100
    h = relations.health([{"null_percentage": 50}] * 2, [{"issue": "duplicate rows", "rows": 500}] + [{"issue": "x"}] * 20, 1000, 300)
    assert h == {"score": 100 - 30 - 20 - 20 - 30, "off": ["-30 empty values", "-20 duplicate rows", "-20 skipped lines", "-30 20 other problems"]}, h
    assert relations.health([{"null_percentage": 0}], [], 10) == {"score": 100, "off": []}
    # a date check uses the day it is given, so it is testable
    rows = [{"column_name": "d", "column_type": "DATE", "min": "2026-01-01", "max": "2026-06-01", "approx_unique": 9, "count": 9}]
    assert engine.suspicious_checks(rows, "2026-12-01") == []
    assert len(engine.suspicious_checks(rows, "2026-05-01")) == 1
    # learning mode asks about it
    assert "negative amount" in learning.better_question([{"issue": "negative values", "column": "amount", "rows": 2}])
    assert store.forget_dataset(db, "odd") and store.get_json(db, "health:odd", None) is None


def test_compare(tmp, db):
    tools.setup(db=db, eng=None)
    st = pkg.stats
    assert round(st.t_p_value(2.0, 10), 4) == 0.0734 and round(st.t_p_value(3.0, 5), 4) == 0.0301
    assert round(st.z_p_value(1.96), 3) == 0.05 and st.welch(1, 5, 0, 9, 4, 1) is None
    csv = tmp / "ab.csv"
    rows = ["variant,amount,paid"]
    rows += [f"A,{100 + i % 7},{str(i % 3 != 0).lower()}" for i in range(200)]
    rows += [f"B,{110 + i % 7},{str(i % 2 == 0).lower()}" for i in range(200)]
    rows += [f"C,{100 + i % 7},true" for i in range(5)]
    csv.write_text("\n".join(rows) + "\n")
    call(tools.attach, path=str(csv))
    r = call(tools.compare, dataset="ab", measure="amount", group_column="variant", a="A", b="B")
    assert r["test"] == "Welch's t-test" and r["rows"][0][3] == -10 and r["rows"][0][4] < 0.001, r
    assert "p < 0.001" in r["verdict"] and "not a cause" in r["verdict"]
    r = call(tools.compare, dataset="ab", measure="paid", group_column="variant", a="A", b="B")
    assert r["test"] == "two-proportion z-test" and r["columns"][2] == "pct", r
    assert abs(r["rows"][0][2] - 66.5) < 0.01 and r["rows"][1][2] == 50.0, r
    r = call(tools.compare, dataset="ab", measure="amount > 103", group_column="variant", a="A", b="C")
    assert "only 5 rows" in r["verdict"], r
    assert pkg.audit._plain("CAST(\"variant\" AS VARCHAR) IN ('A', 'C')") == "variant is A or C"
    assert pkg.audit._plain("region IN ('North')") == "region is North"
    q = store.get_query(db, r["id"])
    assert q["columns"] == ["group", "rows", "pct", "difference", "p_value"] and q["datasets"] == ["ab"]
    assert "No rows where variant is 'Z'" in call(tools.compare, dataset="ab", measure="amount", group_column="variant", a="A", b="Z")["error"]
    # the measure goes into SQL: still one read-only SELECT
    bad = call(tools.compare, dataset="ab", measure="1); DROP TABLE ab; --", group_column="variant", a="A", b="B")
    assert "error" in bad, bad
    assert "grimoire_compare" in " ".join(pkg.recipes.for_message("Is the difference statistically significant?"))


def test_charts():
    report = pkg.report
    days = ["Sunday", "Monday", "Tuesday"]
    grid = [[d, h, 10 * h + i] for i, d in enumerate(days) for h in range(24)]
    kind = lambda cols, rows: report.chart_kind(cols, rows)
    assert kind(["day", "hour", "trips"], grid) == "heatmap"
    assert kind(["bucket", "n"], [[0, 5], [10, 9], [20, 4], [30, 1]]) == "histogram"
    assert kind(["bucket", "n"], [[0, 5], [10, 9], [25, 4], [30, 1], [40, 2]]) == "scatter"  # uneven steps
    assert kind(["fare", "tip"], [[3.5, 1], [9, 2], [12, 2.5], [30, 6], [44, 9]]) == "scatter"
    assert kind(["month", "n"], [["2026-01", 1], ["2026-02", 2], ["2026-03", 3]]) == "line"
    assert kind(["region", "n"], [["North", 1], ["South", 2]]) == "bars"
    assert kind(["n"], [[1]]) is None
    assert report._order(["Wed", "Monday", "sunday", "Jan", "x", 3, 1]) == [1, 3, "Monday", "Wed", "sunday", "Jan", "x"]
    q = {"id": "q1", "columns": ["day", "hour", "trips"], "rows": grid}
    svg = report.chart_svg(q)
    assert svg.count('class="cell"') == 72 and svg.index(">Sunday<") > svg.index(">Tuesday<") and "Stronger color" in svg
    evil = {"id": "q2", "columns": ["a<b>", "n"], "rows": [["<script>", 1], ["x", 2]]}
    assert "<script>" not in report.chart_svg(evil) and "&lt;script&gt;" in report.chart_svg(evil)
    assert report.chart_svg({"id": "q3", "columns": ["a", "b"], "rows": [[0, 1], [1, 2], [2, 3]]}).count('class="bar"') == 3
    assert report._short(91000000.0) == "91M" and report._short(950.5) == "950.50"
    # axis labels never touch, and the last one is always drawn
    for n in (2, 6, 13, 30, 120):
        shown = report.ticks(n, 500, 70)
        step = 500 / (n - 1)
        assert shown[-1] == n - 1 and all((b - a) * step >= 70 * 1.5 for a, b in zip(shown, shown[1:])), (n, shown)
    page = report.html_report([{"id": "q9", "purpose": "b", "question": None, "sql": "SELECT 1", "created_at": 0,
                                "datasets": ["t"], "columns": ["bucket", "n"], "rows": [[0.0, 5], [5.0, 9], [10.0, 4]]}], "T")
    assert ">1 query<" in page and ">5<" in page and ">5.00<" not in page
    assert report._fmt("2024-06-01T00:00:00") == "2024-06-01" and report._fmt("2024-06-01T10:30:00") == "2024-06-01T10:30:00"


class FakeCtx:
    """Just enough of the Hermes plugin context to run register() and call the hooks."""
    def __init__(self):
        self.hooks, self.tools, self.commands = {}, [], {}
    def register_tool(self, name, **kw): self.tools.append(name)
    def register_hook(self, name, fn, **kw): self.hooks[name] = fn
    def register_command(self, name, fn, **kw): self.commands[name] = fn
    def register_skill(self, *a, **kw): pass
    def get_config(self, key, default=None): return default
    def session_cwd(self): return None


def test_glob_and_names(tmp, db):
    tools.setup(db=db, eng=None)
    assert guard.data_file_mentions("rows in ~/d/yellow_2024-*.parquet?") == ["~/d/yellow_2024-*.parquet"]
    assert guard.data_file_mentions("see sales_[ab].csv and x?.tsv") == ["sales_[ab].csv", "x?.tsv"]
    for m in (1, 2):
        (tmp / f"trips_{m}.csv").write_text(f"id,v\n{m},1\n{m + 10},2\n")
    hint = tools.auto_attach(f"How many rows in {tmp}/trips_*.csv?", "glob")
    assert "(4 rows)" in hint and "2 files in one table" in hint, hint
    # numbers inside names and zero-padded codes are not claims; an invented count still is
    text = "6 files: yellow_2024-05.parquet has 3,723,833 rows (2024-01 through 06); 5 rows are odd."
    assert [c["raw"] for c in verify.extract(text)] == ["6", "3,723,833", "5"], verify.extract(text)
    assert verify.check(text, [3723833, 6])[2] == ["5"]
    # clock times: "6 PM" is the hour 18, so it traces to 18; a wrong hour is still flagged
    assert verify.check("Hour 18 (6 PM) has 1,456,754 trips", [18, 1456754]) == (["18", "6 PM", "1,456,754"], [], [])
    assert verify.check("busiest at 7 pm", [18])[2] == ["7 pm"] and verify.check("at 12 a.m.", [0])[0] == ["12 a.m."]


def test_recipes(tmp, db):
    tools.setup(db=db, eng=None)
    recipes = pkg.recipes
    assert recipes.for_message("What is the total revenue?") == []
    assert "lag(total)" in recipes.for_message("Show month over month growth")[0]
    assert "datediff('month'" in " ".join(recipes.for_message("What is the 3-month retention by cohort?"))
    assert any("% of" in r[0] for r in recipes.RECIPES) and recipes.for_message("What % of orders are North?")
    assert len(recipes.for_message("median and share and growth and outliers")) == recipes.MAX_RECIPES
    ctx = FakeCtx()
    pkg.register(ctx)
    assert set(ctx.tools) == {s_["name"] for s_ in schemas.ALL} and "grimoire" in ctx.commands
    turn = ctx.hooks["pre_llm_call"]
    # a chat that never used Grimoire gets nothing, even for a recipe word
    assert turn(user_message="What is the median salary in my head?", session_id="norecipe") is None
    csv = tmp / "rec.csv"
    csv.write_text("customer_id,d,amount\n1,2026-01-03,10\n2,2026-02-04,20\n")
    out = turn(user_message=f"What is the monthly retention by cohort in {csv}?", session_id="rec")["context"]
    assert "Data files are attached" in out and "Cohort retention" in out, out
    plain = turn(user_message="And the total amount?", session_id="rec")
    assert plain is None or "recipe" not in plain["context"], plain
    # hooks keep only numbers from Hermes's API hooks
    ctx.hooks["pre_api_request"](session_id="rec", tool_count=8, request_messages=["secret"])
    ctx.hooks["post_api_request"](session_id="rec", usage={"prompt_tokens": 2200}, response="secret")
    assert tools.call_size("rec") == (8, 2200)


def test_lean_setup(tmp, db):
    tools.setup(db=db, eng=None)
    csv = tmp / "lean.csv"
    csv.write_text("region,amount\nNorth,100\nSouth,250\n")
    call(tools.attach, path=str(csv))
    qid = call(tools.query, sql="SELECT sum(amount) AS total FROM lean")["id"]
    reply = f"The total is 350 [{qid}]."
    # no numbers from Hermes (or bad ones): no tip, no status line
    tools.remember_call("lean", tokens="11000")
    tools.remember_call("lean", tool_count=True)
    assert "Tip:" not in tools.check_reply(reply, "lean")
    assert "This chat:" not in commands.run("", session_id="lean")
    tools.remember_call("lean", tool_count=9)  # tools known, tokens not yet: still nothing
    assert "This chat:" not in commands.run("", session_id="lean")
    # a lean chat: status says so, no tip
    tools.remember_call("lean", tokens=2100)
    assert "Tip:" not in tools.check_reply(reply, "lean")
    assert "9 tools, about 2,100 tokens per model call (lean setup)" in commands.run("", session_id="lean")
    # full Hermes: the tip shows once, with the chat's smallest call, then never again
    for tokens in (11800, 11200, 14000):
        tools.remember_call("full", tool_count=31)
        tools.remember_call("full", tokens=tokens)
    out = tools.check_reply(reply, "full")
    assert "Tip: this chat sends 31 tools and about 11,200 tokens" in out and "/grimoire setup" in out, out
    assert "Tip:" not in tools.check_reply(reply, "full")
    assert "For fewer tokens: /grimoire setup" in commands.run("", session_id="full")
    assert store.get_json(db, "call_size", {}) == {"tools": 31, "tokens": 11200}
    text = commands.run("setup")
    assert "New Agent" in text and "Grimoire never changes your settings" in text and "—" not in text
    # a chat that did not use Grimoire gets nothing
    assert tools.check_reply("Hello 42.", "other") == ""


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
    assert tools.check_reply("Sales total is 150 [q1].", "other-session").endswith(
        "the number traces to query results. Verdict: ready to share.")
    assert tools.check_reply("no numbers here", "test") == ""
    assert tools.check_reply("Revenue 123", "never-used-grimoire") == ""

    test_data_quality(tmp, db)
    test_security(tmp, db)
    test_learning(tmp, db)
    test_auto_attach(tmp, db)
    test_data_plugin(tmp, db)
    test_audit(tmp, db)
    test_analysis_checks(tmp, db)
    test_metrics(tmp, db)
    test_drivers(tmp, db)
    test_relations(tmp, db)
    test_profile_checks(tmp, db)
    test_lean_setup(tmp, db)
    test_recipes(tmp, db)
    test_glob_and_names(tmp, db)
    test_charts()
    test_compare(tmp, db)
    print("selftest passed")


if __name__ == "__main__":
    main()
