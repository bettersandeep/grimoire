"""Text charts for chats and a self-contained HTML report of saved queries (every number with its SQL)."""

import datetime
import html

BAR = 28


def _numeric(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def chart_columns(columns, rows):
    """(label index, value index) for a label-and-number chart, or None."""
    if not rows or len(rows) < 2:
        return None
    value = next((i for i in range(len(columns)) if all(_numeric(r[i]) or r[i] is None for r in rows)
                  and any(_numeric(r[i]) for r in rows) and i > 0), None)
    if value is None:
        return None
    label = next((i for i in range(len(columns)) if i != value and not all(_numeric(r[i]) for r in rows)), 0)
    return label, value


def text_chart(q, limit=25):
    """Unicode bar chart of a saved query result, or an explanation of why not."""
    pick = chart_columns(q["columns"], q["rows"])
    if not pick:
        return f"{q['id']} has no label-and-number columns to chart (it needs 2 or more rows)."
    li, vi = pick
    rows = [r for r in q["rows"] if _numeric(r[vi])][:limit]
    top = max(abs(r[vi]) for r in rows) or 1
    width = max(len(str(r[li])) for r in rows)
    lines = [f"{q['id']}: {q['columns'][vi]} by {q['columns'][li]}"]
    for r in rows:
        n = round(abs(r[vi]) / top * BAR)
        lines.append(f"{str(r[li]):<{width}}  {'█' * n}{'▏' if n == 0 else ''} {_fmt(r[vi])}")
    if len(q["rows"]) > len(rows):
        lines.append(f"... {len(q['rows']) - len(rows)} more rows")
    return "\n".join(lines)


def _fmt(v):
    if isinstance(v, float):
        return f"{v:,.2f}"
    if isinstance(v, int):
        return f"{v:,}"
    return "" if v is None else str(v)


def _svg_bars(q):
    pick = chart_columns(q["columns"], q["rows"])
    if not pick:
        return ""
    li, vi = pick
    rows = [r for r in q["rows"] if _numeric(r[vi])][:25]
    top = max(abs(r[vi]) for r in rows) or 1
    h, bar_w = 22, 360
    label_w = 16 + 7 * max(len(str(r[li])[:20]) for r in rows)  # about 7 px per character at 12 px
    parts = [f'<svg viewBox="0 0 {label_w + bar_w + 120} {len(rows) * h + 8}" role="img" '
             f'aria-label="{html.escape(q["columns"][vi])} by {html.escape(q["columns"][li])}">']
    for i, r in enumerate(rows):
        y = i * h + 4
        w = max(1, abs(r[vi]) / top * bar_w)
        parts.append(f'<text x="{label_w - 8}" y="{y + 15}" text-anchor="end" class="lbl">'
                     f'{html.escape(str(r[li])[:20])}</text>')
        parts.append(f'<rect x="{label_w}" y="{y + 3}" width="{w:.1f}" height="{h - 8}" rx="2" class="bar"/>')
        parts.append(f'<text x="{label_w + w + 6:.1f}" y="{y + 15}" class="val">{html.escape(_fmt(r[vi]))}</text>')
    parts.append("</svg>")
    return "".join(parts)


def _table(q, limit=50):
    nums = [bool(q["rows"]) and all(_numeric(r[i]) or r[i] is None for r in q["rows"]) for i in range(len(q["columns"]))]
    head = "".join(f'<th class="{"num" if n else ""}">{html.escape(c)}</th>' for c, n in zip(q["columns"], nums))
    body = []
    for r in q["rows"][:limit]:
        cells = "".join(f'<td class="{"num" if _numeric(v) else ""}">{html.escape(_fmt(v))}</td>' for v in r)
        body.append(f"<tr>{cells}</tr>")
    more = (f'<p class="muted">{len(q["rows"]) - limit} more rows not shown.</p>'
            if len(q["rows"]) > limit else "")
    return f'<div class="tw"><table><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table></div>{more}'


def _section(q):
    title = html.escape(q["purpose"] or q["question"] or q["id"])
    question = f'<p class="q">Question: {html.escape(q["question"])}</p>' if q.get("question") else ""
    if len(q["rows"]) == 1 and len(q["columns"]) <= 4 and all(_numeric(v) or v is None for v in q["rows"][0]):
        body = '<div class="kpis">' + "".join(
            f'<div class="kpi"><div class="kv">{html.escape(_fmt(v))}</div><div class="kl">{html.escape(c)}</div></div>'
            for c, v in zip(q["columns"], q["rows"][0])) + "</div>"
    else:
        body = _svg_bars(q) + _table(q)
    when = datetime.datetime.fromtimestamp(q["created_at"]).strftime("%Y-%m-%d %H:%M")
    return (f'<section id="{q["id"]}"><h2><span class="qid">{q["id"]}</span> {title}</h2>{question}{body}'
            f'<details><summary>SQL behind these numbers</summary><pre>{html.escape(q["sql"])}</pre></details>'
            f'<p class="muted">Run {when} · files: {html.escape(", ".join(q["datasets"]) or "unknown")}</p></section>')


CSS = """
:root{--bg:#f6f7f5;--card:#fff;--fg:#1c2421;--muted:#5d6b66;--line:#dde3e0;--accent:#0f766e;--code:#eef2f0}
@media (prefers-color-scheme:dark){:root{--bg:#0f1514;--card:#162020;--fg:#e3ebe8;--muted:#93a39e;--line:#26332f;--accent:#3cc4b4;--code:#1d2a28}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.55 -apple-system,system-ui,"Segoe UI",sans-serif;padding:32px 16px}
main{max-width:860px;margin:0 auto;display:flex;flex-direction:column;gap:20px}
h1{font-size:1.7rem;margin:0}h2{font-size:1.1rem;margin:0 0 8px}.qid{font:600 .8rem ui-monospace,Menlo,monospace;color:var(--accent);margin-right:6px}
section{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:18px}
.q,.muted{color:var(--muted);font-size:.88rem;margin:4px 0}.kpis{display:flex;flex-wrap:wrap;gap:12px}
.kpi{border:1px solid var(--line);border-radius:8px;padding:10px 14px;min-width:140px}.kv{font-size:1.5rem;font-weight:650;font-variant-numeric:tabular-nums}.kl{color:var(--muted);font-size:.8rem}
svg{width:100%;max-width:620px;margin:6px 0}.bar{fill:var(--accent)}.lbl,.val{fill:var(--fg);font-size:12px}
.tw{overflow-x:auto}table{border-collapse:collapse;font-size:.88rem;margin-top:8px}th,td{text-align:left;padding:5px 10px;border-bottom:1px solid var(--line)}th.num,td.num{text-align:right;font-variant-numeric:tabular-nums}
details{margin-top:10px}pre{background:var(--code);padding:10px;border-radius:6px;overflow-x:auto;font-size:.82rem}
"""


def html_report(queries, title):
    sections = "".join(_section(q) for q in queries)
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" '
            f'content="width=device-width,initial-scale=1"><title>{html.escape(title)}</title><style>{CSS}</style>'
            f'</head><body><main><header><h1>{html.escape(title)}</h1><p class="muted">Made by Grimoire on {now}. '
            f'Every number below comes from the SQL shown under it, run with DuckDB on your files.</p></header>'
            f'{sections}</main></body></html>')
