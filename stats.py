"""Is a difference between two groups real or chance? Welch's t-test for means, a two-proportion
z-test for rates. DuckDB computes the group sizes, means and spreads; the p-value is computed here,
because DuckDB has no distribution functions. Standard library only."""

import math

ALPHA = 0.05
SMALL_GROUP = 30


def _betacf(a, b, x):
    """Continued fraction for the regularized incomplete beta function (Lentz's method)."""
    tiny, qab, qap, qam = 1e-300, a + b, a + 1, a - 1
    c, d = 1.0, 1 - qab * x / qap
    d = 1 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 300):
        m2 = 2 * m
        for aa in (m * (b - m) * x / ((qam + m2) * (a + m2)), -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))):
            d = 1 + aa * d
            d = 1 / (d if abs(d) > tiny else tiny)
            c = 1 + aa / c
            c = c if abs(c) > tiny else tiny
            h *= d * c
        if abs(d * c - 1) < 1e-14:
            break
    return h


def _betainc(a, b, x):
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    front = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1 - x))
    if x < (a + 1) / (a + b + 2):
        return front * _betacf(a, b, x) / a
    return 1 - front * _betacf(b, a, 1 - x) / b


def t_p_value(t, df):
    """Two-sided p-value of Student's t with df degrees of freedom."""
    return _betainc(df / 2, 0.5, df / (df + t * t))


def z_p_value(z):
    return math.erfc(abs(z) / math.sqrt(2))


def welch(n1, m1, s1, n2, m2, s2):
    """(t, df, p) for two means; None when a group is too small or has no spread."""
    if n1 < 2 or n2 < 2:
        return None
    v1, v2 = (s1 or 0) ** 2 / n1, (s2 or 0) ** 2 / n2
    if v1 + v2 == 0:
        return None
    t = (m1 - m2) / math.sqrt(v1 + v2)
    df = (v1 + v2) ** 2 / ((v1 ** 2 / (n1 - 1) if v1 else 0) + (v2 ** 2 / (n2 - 1) if v2 else 0))
    return t, df, t_p_value(t, df)


def proportions(k1, n1, k2, n2):
    """(z, p) for two rates k/n with a pooled standard error; None when it cannot be computed."""
    if not n1 or not n2:
        return None
    pool = (k1 + k2) / (n1 + n2)
    se = math.sqrt(pool * (1 - pool) * (1 / n1 + 1 / n2))
    if se == 0:
        return None
    z = (k1 / n1 - k2 / n2) / se
    return z, z_p_value(z)


def verdict(p, n1, n2):
    """Plain words for a p-value, with the cautions that matter."""
    if p is None:
        return "Cannot test: a group has fewer than 2 rows or no spread."
    if p < 0.001:
        text = "p < 0.001: a difference this large would be very rare if the groups were the same."
    elif p < ALPHA:
        text = f"p = {p:.3f}: likely a real difference (below the usual 0.05 line)."
    else:
        text = f"p = {p:.3f}: this difference could easily be chance (0.05 or more)."
    if min(n1, n2) < SMALL_GROUP:
        text += f" A group has only {min(n1, n2)} rows, so treat this as a rough check."
    return text + " A real difference can still be too small to matter, and a difference is not a cause."
