"""Text charts for chats and a self-contained HTML report of saved queries (every number with its SQL)."""

import datetime
import html
import re

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


_TIME = re.compile(r"^\d{4}(-\d{2}(-\d{2}([T ]\d{2}:\d{2}(:\d{2})?)?)?)?$")


def is_time(values):
    """True when every label is a year, month, date or timestamp written in ISO form."""
    vals = [str(v) for v in values if v is not None]
    return len(vals) >= 3 and all(_TIME.match(v) for v in vals)


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


def _short(v):
    """A chart label: 91M or 4.1K for big numbers, the exact value otherwise (tables keep exact values)."""
    return compact(v) if _numeric(v) and abs(v) >= 10000 else _fmt(v)


def compact(v):
    """Short axis label: 8.17M, 4.09K, 12."""
    for size, unit in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(v) >= size:
            return f"{v / size:.3g}{unit}"
    return f"{v:.3g}"


def _svg_line(q, li, vi):
    rows = sorted((r for r in q["rows"] if _numeric(r[vi]) and r[li] is not None), key=lambda r: str(r[li]))[:120]
    vals = [r[vi] for r in rows]
    lo, hi = min(0, min(vals)), max(vals) or 1
    marks = (lo, (lo + hi) / 2, hi)
    w, h, bottom = 560, 200, 24
    left = 14 + 7 * max(len(compact(v)) for v in marks)
    x = lambda i: left + (w - left - 10) * (i / max(1, len(rows) - 1))
    y = lambda v: 8 + (h - bottom - 8) * (1 - (v - lo) / ((hi - lo) or 1))
    pts = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(vals))
    every = max(1, len(rows) // 6)
    anchor = lambda i: "start" if i == 0 else "end" if i == len(rows) - 1 else "middle"  # keep edge labels inside
    ticks = "".join(f'<text x="{x(i):.1f}" y="{h - 6}" text-anchor="{anchor(i)}" class="lbl">{html.escape(str(r[li])[:10])}</text>'
                    for i, r in enumerate(rows) if i % every == 0 and len(rows) - 1 - i >= every / 2 or i == len(rows) - 1)
    grid = "".join(f'<line x1="{left}" x2="{w - 10}" y1="{y(v):.1f}" y2="{y(v):.1f}" class="grid"/>'
                   f'<text x="{left - 6}" y="{y(v) + 4:.1f}" text-anchor="end" class="lbl">{html.escape(compact(v))}</text>'
                   for v in marks)
    dots = "".join(f'<circle cx="{x(i):.1f}" cy="{y(v):.1f}" r="2.5" class="dot"><title>{html.escape(str(r[li]))}: '
                   f'{html.escape(_fmt(v))}</title></circle>' for i, (r, v) in enumerate(zip(rows, vals)))
    return (f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="{html.escape(q["columns"][vi])} over '
            f'{html.escape(q["columns"][li])}">{grid}<polyline points="{pts}" class="line"/>{dots}{ticks}</svg>')


def chart_kind(columns, rows):
    """Which chart fits a result: line (time), heatmap (two labels and a number), histogram (equal
    buckets and counts), scatter (two numbers), bars (a label and a number), or None."""
    if not rows or len(rows) < 2:
        return None
    nums = _number_columns(columns, rows)
    texts = [i for i in range(len(columns)) if i not in nums]
    if len(columns) == 3 and len(nums) >= 1 and _heatmap_axes(columns, rows, nums):
        return "heatmap"
    if not texts and len(nums) >= 2:
        if _even_steps([r[nums[0]] for r in rows]) and all((r[nums[1]] or 0) >= 0 for r in rows):
            return "histogram"
        return "scatter" if len(rows) >= 5 else "bars"
    pick = chart_columns(columns, rows)
    if not pick:
        return None
    return "line" if is_time([r[pick[0]] for r in rows]) else "bars"


def _number_columns(columns, rows):
    return [i for i in range(len(columns)) if all(_numeric(r[i]) or r[i] is None for r in rows)
            and any(_numeric(r[i]) for r in rows)]


def _heatmap_axes(columns, rows, nums):
    """(x index, y index, value index) when two columns label a grid of at most 31 by 31, else None."""
    value = nums[-1]
    x, y = [i for i in range(3) if i != value]
    xs, ys = {r[x] for r in rows}, {r[y] for r in rows}
    if None in xs or None in ys or not (2 <= len(xs) <= 31 and 2 <= len(ys) <= 31):
        return None
    if len({(r[x], r[y]) for r in rows}) != len(rows) or len(rows) < 0.5 * len(xs) * len(ys):
        return None  # each cell once, and at least half of the grid filled
    if x in nums and y in nums and len(xs) > 12 and len(ys) > 12:
        return None  # two wide number columns: a scatter, not a grid
    return x, y, value


def _even_steps(values):
    """True for ascending bucket starts with one step: 0, 10, 20, 30 ..."""
    if len(values) < 3 or any(not _numeric(v) for v in values):
        return False
    steps = [b - a for a, b in zip(values, values[1:])]
    return steps[0] > 0 and all(abs(st - steps[0]) <= 1e-9 + 0.01 * steps[0] for st in steps)


_DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
           "november", "december"]


def _order(values):
    """Numbers ascending; weekday and month names in calendar order (full or 3-letter); other text A to Z."""
    def key(v):
        if _numeric(v):
            return (0, v, "")
        t = str(v).strip().lower()
        for group, names in ((1, _DAYS), (2, _MONTHS)):
            hit = next((i for i, n in enumerate(names) if t in (n, n[:3])), None)
            if hit is not None:
                return (group, hit, "")
        return (3, 0, t)
    return sorted(values, key=key)


def _svg_heatmap(q):
    x, y, vi = _heatmap_axes(q["columns"], q["rows"], _number_columns(q["columns"], q["rows"]))
    if len({r[x] for r in q["rows"]}) < len({r[y] for r in q["rows"]}):
        x, y = y, x  # the axis with more values runs across
    xs, ys = _order({r[x] for r in q["rows"]}), _order({r[y] for r in q["rows"]})
    cell = {(r[x], r[y]): r[vi] for r in q["rows"] if _numeric(r[vi])}
    lo, hi = min(cell.values(), default=0), max(cell.values(), default=1)
    w, ch, top = 560, 22, 22
    left = 14 + 7 * max(len(str(v)[:14]) for v in ys)
    cw = (w - left - 4) / len(xs)
    h = top + ch * len(ys)
    every = max(1, -(-7 * max(len(str(v)[:8]) for v in xs) // max(1, int(cw) - 4)))
    parts = [f'<text x="{left + cw * i + cw / 2:.1f}" y="14" text-anchor="middle" class="lbl">{html.escape(str(v)[:8])}</text>'
             for i, v in enumerate(xs) if i % every == 0]
    for j, yv in enumerate(ys):
        parts.append(f'<text x="{left - 8}" y="{top + ch * j + 15}" text-anchor="end" class="lbl">{html.escape(str(yv)[:14])}</text>')
        for i, xv in enumerate(xs):
            v = cell.get((xv, yv))
            if v is None:
                continue
            level = 0.12 + 0.88 * ((v - lo) / ((hi - lo) or 1))  # one hue, light to dark
            parts.append(f'<rect x="{left + cw * i + 1:.1f}" y="{top + ch * j + 1}" width="{max(1, cw - 2):.1f}" height="{ch - 2}" '
                         f'rx="2" class="cell" fill-opacity="{level:.2f}"><title>{html.escape(str(xv))}, {html.escape(str(yv))}: '
                         f'{html.escape(_fmt(v))}</title></rect>')
    parts.append(f'<text x="{left}" y="{h + 16}" class="lbl">Stronger color = more {html.escape(q["columns"][vi])}: '
                 f'from {html.escape(_fmt(lo))} to {html.escape(_fmt(hi))}.</text>')
    return (f'<svg viewBox="0 0 {w} {h + 22}" role="img" aria-label="{html.escape(q["columns"][vi])} by '
            f'{html.escape(q["columns"][x])} and {html.escape(q["columns"][y])}">' + "".join(parts) + "</svg>")


def _axis(lo, hi):
    return (lo, (lo + hi) / 2, hi)


def _svg_histogram(q):
    rows = q["rows"][:120]
    starts, counts = [r[0] for r in rows], [r[1] or 0 for r in rows]
    step = starts[1] - starts[0]
    top = max(counts) or 1
    w, h, bottom = 560, 200, 24
    left = 14 + 7 * max(len(compact(v)) for v in _axis(0, top))
    bw = (w - left - 10) / len(rows)
    y = lambda v: 8 + (h - bottom - 8) * (1 - v / top)
    grid = "".join(f'<line x1="{left}" x2="{w - 10}" y1="{y(v):.1f}" y2="{y(v):.1f}" class="grid"/>'
                   f'<text x="{left - 6}" y="{y(v) + 4:.1f}" text-anchor="end" class="lbl">{html.escape(compact(v))}</text>'
                   for v in _axis(0, top))
    bars = "".join(f'<rect x="{left + bw * i + 1:.1f}" y="{y(c):.1f}" width="{max(1, bw - 2):.1f}" height="{max(0, y(0) - y(c)):.1f}" '
                   f'rx="2" class="bar"><title>{html.escape(_fmt(s_))} to {html.escape(_fmt(s_ + step))}: {html.escape(_fmt(c))}'
                   f'</title></rect>' for i, (s_, c) in enumerate(zip(starts, counts)))
    every = max(1, len(rows) // 6)
    ticks = "".join(f'<text x="{left + bw * i:.1f}" y="{h - 6}" text-anchor="middle" class="lbl">{html.escape(compact(s_))}</text>'
                    for i, s_ in enumerate(starts) if i % every == 0)
    return (f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="{html.escape(q["columns"][1])} per bucket of '
            f'{html.escape(q["columns"][0])}">{grid}{bars}{ticks}</svg>')


def _svg_scatter(q):
    pts = [(r[0], r[1]) for r in q["rows"] if _numeric(r[0]) and _numeric(r[1])]
    xs, ys = [p_[0] for p_ in pts], [p_[1] for p_ in pts]
    xlo, xhi, ylo, yhi = min(xs), max(xs), min(0, min(ys)), max(ys)
    w, h, bottom, top = 560, 240, 40, 22
    left = 14 + 7 * max(len(compact(v)) for v in _axis(ylo, yhi))
    x = lambda v: left + 6 + (w - left - 20) * ((v - xlo) / ((xhi - xlo) or 1))
    y = lambda v: top + (h - bottom - top) * (1 - (v - ylo) / ((yhi - ylo) or 1))
    grid = "".join(f'<line x1="{left}" x2="{w - 10}" y1="{y(v):.1f}" y2="{y(v):.1f}" class="grid"/>'
                   f'<text x="{left - 6}" y="{y(v) + 4:.1f}" text-anchor="end" class="lbl">{html.escape(compact(v))}</text>'
                   for v in _axis(ylo, yhi))
    ticks = "".join(f'<text x="{x(v):.1f}" y="{h - 22}" text-anchor="middle" class="lbl">{html.escape(compact(v))}</text>'
                    for v in _axis(xlo, xhi))
    names = (f'<text x="{left}" y="12" class="lbl">{html.escape(q["columns"][1])} ↑</text>'
             f'<text x="{(left + w) / 2:.1f}" y="{h - 4}" text-anchor="middle" class="lbl">{html.escape(q["columns"][0])} →</text>')
    dots = "".join(f'<circle cx="{x(a):.1f}" cy="{y(b):.1f}" r="4" class="pt"><title>{html.escape(q["columns"][0])} '
                   f'{html.escape(_fmt(a))}, {html.escape(q["columns"][1])} {html.escape(_fmt(b))}</title></circle>' for a, b in pts)
    return (f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="{html.escape(q["columns"][1])} against '
            f'{html.escape(q["columns"][0])}">{grid}{ticks}{names}{dots}</svg>')


def chart_svg(q):
    """The chart that fits a saved query result, as inline SVG; "" when none fits."""
    kind = chart_kind(q["columns"], q["rows"])
    try:
        if kind == "heatmap":
            return _svg_heatmap(q)
        if kind == "histogram":
            return _svg_histogram(q)
        if kind == "scatter":
            return _svg_scatter(q)
    except (TypeError, ValueError, ZeroDivisionError):
        return ""  # mixed or odd values: show the table only
    return _svg_bars(q) if kind in ("bars", "line") else ""


def _svg_bars(q):
    pick = chart_columns(q["columns"], q["rows"])
    if not pick:
        return ""
    li, vi = pick
    if is_time([r[li] for r in q["rows"]]):
        return _svg_line(q, li, vi)
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
        parts.append(f'<text x="{label_w + w + 6:.1f}" y="{y + 15}" class="val">{html.escape(_short(r[vi]))}</text>')
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
        body = chart_svg(q) + _table(q)
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
.cell{fill:var(--accent)}.pt{fill:var(--accent);stroke:var(--card);stroke-width:2}
.line{fill:none;stroke:var(--accent);stroke-width:2}.dot{fill:var(--accent)}.grid{stroke:var(--line);stroke-width:1}.lbl{fill:var(--muted)}
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
