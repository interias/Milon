"""Kleine Trend-Statistik ohne scipy: OLS + 95%-CI der Steigung via t-Verteilung (Lookup).

EHRLICHE STATISTIK (wichtig): Signifikanz immer auf der ROHDATEN-Ebene testen
(einzelne Läufe/Tage, ~unabhängige Residuen) — NIE auf geglätteten/rollierenden
Wochenkurven (überlappende Fenster = Autokorrelation = Schein-Signifikanz).
Die geglätteten Serien sind nur Anzeige, das Urteil kommt aus linear_trend/ols."""
from __future__ import annotations

import numpy as np

# Zweiseitige 95%-Quantile der t-Verteilung; nächstkleinerer df = konservativ.
_T95 = {1: 12.71, 2: 4.30, 3: 3.18, 4: 2.78, 5: 2.57, 6: 2.45, 7: 2.36, 8: 2.31, 9: 2.26,
        10: 2.23, 12: 2.18, 14: 2.14, 16: 2.12, 18: 2.10, 20: 2.09, 25: 2.06, 30: 2.04,
        40: 2.02, 60: 2.00}


def t95(df: int) -> float:
    if df <= 0:
        return float("inf")
    keys = [k for k in _T95 if k <= df]
    return _T95[max(keys)] if keys else _T95[1]


def ols(X: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray, int, float] | None:
    """OLS mit Standardfehlern. Liefert (beta, se, df, r2) oder None (singulär/zu wenig Daten)."""
    n, k = X.shape
    if n <= k:
        return None
    try:
        xtx_inv = np.linalg.inv(X.T @ X)
    except np.linalg.LinAlgError:
        return None
    beta = xtx_inv @ X.T @ y
    resid = y - X @ beta
    df = n - k
    sigma2 = float(resid @ resid) / df
    se = np.sqrt(np.clip(np.diag(xtx_inv) * sigma2, 0, None))
    sst = float(((y - y.mean()) ** 2).sum())
    r2 = 1 - float(resid @ resid) / sst if sst > 0 else 0.0
    return beta, se, df, r2


def linear_trend(xs_days: list[float], ys: list[float]) -> dict | None:
    """Einfacher Zeittrend y ~ Tage: Steigung, 95%-CI, R². significant = CI schließt 0 aus."""
    n = len(ys)
    if n < 3 or len(xs_days) != n:
        return None
    X = np.column_stack([np.ones(n), np.asarray(xs_days, float)])
    fit = ols(X, np.asarray(ys, float))
    if fit is None:
        return None
    beta, se, df, r2 = fit
    slope, se_s = float(beta[1]), float(se[1])
    ci = t95(df) * se_s
    span = float(max(xs_days) - min(xs_days))
    return {
        "n": n,
        "days": round(span),
        "slope_per_week": round(slope * 7, 4),
        "ci_per_week": round(ci * 7, 4),
        "delta": round(slope * span, 2),  # Änderung über den beobachteten Zeitraum
        "r2": round(r2, 2),
        "significant": bool(n >= 6 and abs(slope) > ci),
    }


def assess(tr: dict | None, down_is_good: bool = True) -> dict:
    """Trend-Urteil fürs UI: besser/schlechter/unklar/wenig_daten (+ Label deutsch)."""
    if not tr or tr.get("n", 0) < 6:
        return {**(tr or {}), "verdict": "wenig_daten", "label": "zu wenig Daten"}
    if not tr.get("significant"):
        return {**tr, "verdict": "unklar", "label": "kein belastbarer Trend"}
    better = (tr["slope_per_week"] < 0) == down_is_good
    return {**tr, "verdict": "besser" if better else "schlechter",
            "label": "signifikanter Trend (95 %)"}
