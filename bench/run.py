"""Run the benchmark: the same questions on two Hermes profiles that differ only in Grimoire.

Setup once:
  hermes profile create gbplain --no-skills --no-alias
  hermes profile create gbgrim --no-skills --no-alias
  hermes -p gbgrim plugins install bettersandeep/grimoire --yes-deps --enable
  python bench/make_data.py ~/grimoire-bench

Run (resumes; finished runs are skipped):
  python bench/run.py run --data ~/grimoire-bench --out bench/results.jsonl --sizes 50k --repeats 3
Report:
  python bench/run.py report --out bench/results.jsonl
"""

import argparse
import json
import re
import sqlite3
import statistics
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
from questions import QUESTIONS, MONTHS, truth  # noqa: E402
import verify  # noqa: E402  (pure module, no Hermes or DuckDB imports)

PROFILES = {"plain": "gbplain", "grimoire": "gbgrim"}
# Option (a): free models cost $0, so tokens are priced at a typical paid list price, per million tokens.
PRICE_IN, PRICE_CACHE, PRICE_OUT = 3.00, 0.30, 15.00
TIMEOUT_S = 480


def score(answer, numbers, words):
    """Share of the true numbers and words the answer contains (1.0 = fully correct)."""
    claims = verify.extract(answer)
    # verify skips years and powers of ten (1996, 1000), which can be real answers here
    claims += [{"value": float(n.replace(",", "")), "tol": 0.5}
               for n in re.findall(r"(?<![\d.])\d[\d,]*(?![\d.])", answer)]
    found = 0
    for t in numbers:
        if any(abs(c["value"] - t) <= max(c["tol"], 0.001 * abs(t)) + 1e-9 for c in claims):
            found += 1
    text = answer.lower()
    for w in words:
        alts = [w.lower()]
        if w in MONTHS:
            m = MONTHS.index(w) + 1
            alts += [w[:3].lower() + " ", f"2026-{m:02d}", f"month {m}"]
        found += any(a in text for a in alts)
    return found / (len(numbers) + len(words))


def session(profile, sid):
    db = Path.home() / ".hermes" / "profiles" / profile / "state.db"
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        row = con.execute(
            "SELECT input_tokens, output_tokens, cache_read_tokens, api_call_count, tool_call_count "
            "FROM sessions WHERE id = ?", (sid,)).fetchone()
    finally:
        con.close()
    keys = ["input_tokens", "output_tokens", "cache_read_tokens", "api_calls", "tool_calls"]
    return dict(zip(keys, row)) if row else {}


def _text(data):
    return data.decode(errors="replace") if isinstance(data, bytes) else (data or "")


def run(args):
    out = Path(args.out)
    done = set()
    if out.exists():
        for line in out.read_text().splitlines():
            r = json.loads(line)
            done.add((r["size"], r["setup"], r["q"], r["rep"]))
    for size in args.sizes.split(","):
        path = Path(args.data).expanduser() / f"sales_{size}.csv"
        answers = truth(path)
        for rep in range(args.repeats):
            for key, template in QUESTIONS:
                for setup in args.setups.split(","):
                    if (size, setup, key, rep) in done:
                        continue
                    profile = PROFILES[setup]
                    cmd = ["hermes", "-p", profile, "chat", "--source", "tool", "-Q", "-m", args.model,
                           "--run-budget", "300", "-q", template.format(path=path)]
                    start = time.time()
                    try:
                        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT_S,
                                              cwd=path.parent)
                        output, errors = proc.stdout, proc.stderr
                        status = "ok" if proc.returncode == 0 else f"exit {proc.returncode}"
                    except subprocess.TimeoutExpired as exc:
                        output, errors, status = _text(exc.stdout), _text(exc.stderr), "timeout"
                    seconds = round(time.time() - start, 1)
                    m = re.findall(r"session_id:\s*(\S+)", output + "\n" + errors)
                    sid = m[-1] if m else None
                    answer = re.sub(r"(?m)^\s*(session_id|Session):.*$", "", output).strip()
                    numbers, words = answers[key]
                    record = {"size": size, "setup": setup, "q": key, "rep": rep, "model": args.model,
                              "status": status, "seconds": seconds, "session": sid,
                              "score": score(answer, numbers, words) if status == "ok" else 0.0,
                              **(session(profile, sid) if sid else {}), "answer": answer[-4000:]}
                    with out.open("a") as f:
                        f.write(json.dumps(record) + "\n")
                    print(f"{size} {setup:8} {key:9} rep{rep} {status:8} {seconds:6.1f}s "
                          f"in={record.get('input_tokens')} score={record['score']:.2f}", flush=True)


def report(args):
    rows = [json.loads(line) for line in Path(args.out).read_text().splitlines()]
    med = lambda xs: statistics.median(xs) if xs else 0
    print("| File | Setup | Runs | Correct | Input tokens (median) | Output tokens | Time (median) | "
          "Cost per answer* | Tool calls |")
    print("|---|---|---|---|---|---|---|---|---|")
    for size in dict.fromkeys(r["size"] for r in rows):
        for setup in ("plain", "grimoire"):
            rs = [r for r in rows if r["size"] == size and r["setup"] == setup]
            if not rs:
                continue
            cost = [((r.get("input_tokens") or 0) * PRICE_IN + (r.get("cache_read_tokens") or 0) * PRICE_CACHE
                     + (r.get("output_tokens") or 0) * PRICE_OUT) / 1e6 for r in rs]
            correct = sum(r["score"] == 1.0 for r in rs)
            print(f"| {size} rows | {setup} | {len(rs)} | {correct}/{len(rs)} ({100 * correct / len(rs):.0f}%) | "
                  f"{med([(r.get('input_tokens') or 0) + (r.get('cache_read_tokens') or 0) for r in rs]):,.0f} | "
                  f"{med([r.get('output_tokens') or 0 for r in rs]):,.0f} | {med([r['seconds'] for r in rs]):.0f} s | "
                  f"${med(cost):.4f} | {med([r.get('tool_calls') or 0 for r in rs]):.0f} |")
    print(f"\nInput tokens include cached input. *Free model, so tokens are priced per million at ${PRICE_IN:.2f} "
          f"input, ${PRICE_CACHE:.2f} cached input and ${PRICE_OUT:.2f} output.")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=["run", "report"])
    p.add_argument("--data", default="~/grimoire-bench")
    p.add_argument("--out", default=str(HERE / "results.jsonl"))
    p.add_argument("--sizes", default="1k,50k,1m")
    p.add_argument("--setups", default="plain,grimoire")
    p.add_argument("--repeats", type=int, default=1)
    p.add_argument("--model", default="meituan/longcat-2.5:free")
    a = p.parse_args()
    run(a) if a.action == "run" else report(a)
