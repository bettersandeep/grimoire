"""DuckDB recipes for the question at hand, sent only when the user's words call for one.

The same recipes live in the explore-data skill, but a lean Data bot has no Skills toolset
(measured: it doubles the tokens of every call), so Grimoire adds the one or two that fit.
"""

import re

MAX_RECIPES = 2

RECIPES = [
    (r"\b(significan\w*|real difference|really differ\w*|by chance|statistical\w*|p-?values?|a/b|ab test)\b",
     'To test if two groups really differ, use tool_call with name "grimoire_compare" and arguments like '
     '{"dataset": "<name>", "measure": "<number column, or a condition>", "group_column": "<column>", "a": "<value>", '
     '"b": "<value>"}.'),
    (r"\b(share|percent(age)?|proportion|portion)\b|% of",
     "Share of total: round(100 * sum(x) / sum(sum(x)) OVER (), 1) AS pct with GROUP BY."),
    (r"\b(growth|grow\w*|month[- ]over[- ]month|year[- ]over[- ]year|mom|yoy|vs\.? last)\b",
     "Growth: lag(total) OVER (ORDER BY month) AS prev, then round(100 * (total - prev) / prev, 1)."),
    (r"\b(running|cumulative|to date|moving average|rolling)\b",
     "Running total: sum(x) OVER (ORDER BY d); moving average: avg(x) OVER (ORDER BY d ROWS 6 PRECEDING)."),
    (r"\btop \d+\b.*\b(per|each|by|in every)\b|\b(best|top|largest|biggest)\b.*\b(per|each|in every)\b",
     "Top N per group: QUALIFY row_number() OVER (PARTITION BY g ORDER BY x DESC) <= 3."),
    (r"\b(median|percentile|quantile|p\d\d|typical)\b",
     "Median and percentiles: median(x), quantile_cont(x, [0.25, 0.5, 0.9]); on big files approx_quantile(x, 0.5)."),
    (r"\b(cohort|retention|retain\w*|churn\w*|come back|came back|repeat customers?)\b",
     "Cohort retention: cohort = min(date_trunc('month', d)) OVER (PARTITION BY customer_id); then count(DISTINCT "
     "customer_id) per cohort and datediff('month', cohort, date_trunc('month', d)); divide by the month-0 count."),
    (r"\b(funnel|conversion|convert\w*|drop[- ]?off)\b",
     "Funnel: per user max(step = 'view')::INT AS viewed, max(step = 'cart')::INT AS carted ... GROUP BY user; "
     "then sum() each step and divide by the first step."),
    (r"\b(dedup\w*|duplicates?|latest per|most recent per|unique per)\b",
     "Deduplicate: SELECT DISTINCT *, or keep one per key with QUALIFY row_number() OVER (PARTITION BY id "
     "ORDER BY updated_at DESC) = 1."),
    (r"\b(outliers?|anomal\w*|unusual|extreme)\b",
     "Outliers: outside quantile_cont(x, 0.25) - 1.5 * IQR and quantile_cont(x, 0.75) + 1.5 * IQR, where IQR is "
     "their difference; grimoire_profile with column gives them directly."),
    (r"\b(distribution|histogram|bins?|bucket\w*|spread)\b",
     "Distribution: floor(x / w) * w AS bucket, count(*) GROUP BY 1 ORDER BY 1; spread: stddev_samp(x)."),
    (r"\b(weekday|weekend|day of (the )?week|hour of|by hour|time of day)\b",
     "Time of week: dayname(d) or isodow(d) (1 = Monday); hour: hour(ts)."),
    (r"\b(seasonal\w*|seasons?|every year|time of year)\b",
     "Seasonality: average per month of year, month(d) AS m with avg(monthly_total) across years; compare each "
     "month with the overall average; one year of data cannot show a season."),
    (r"\b(trend|forecast|projection|predict\w*|next (month|quarter|year))\b",
     "Trend: regr_slope(y, epoch(d)) per second, or regr_slope(total, month_index) over a monthly series; "
     "call any projection rough."),
]
_COMPILED = [(re.compile(p, re.I), text) for p, text in RECIPES]


def for_message(text):
    """Up to MAX_RECIPES recipe lines that fit the user's words; [] when none does."""
    out = [recipe for pattern, recipe in _COMPILED if pattern.search(text or "")]
    return out[:MAX_RECIPES]
