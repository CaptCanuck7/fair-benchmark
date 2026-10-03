"""Summary statistics, exceedance curves and histograms."""

import math

import numpy as np

CURVE_POINTS = 121
HIST_BINS = 24


def nice_max(v: float) -> float:
    """Round up to 1, 2, 2.5, 5 or 10 x 10^n, as the prototype's niceMax()."""
    if not (v > 0) or not math.isfinite(v):
        return 1.0
    e = 10.0 ** math.floor(math.log10(v))
    f = v / e
    step = 1 if f <= 1 else 2 if f <= 2 else 2.5 if f <= 2.5 else 5 if f <= 5 else 10
    return step * e


def quantile(sorted_vals: np.ndarray, p: float) -> float:
    """Linear-interpolation percentile of an already sorted array; 0 when empty."""
    if sorted_vals.size == 0:
        return 0.0
    return float(np.quantile(sorted_vals, p))


def exceed(sorted_vals: np.ndarray, x: float | np.ndarray) -> float | np.ndarray:
    """Share of values strictly greater than x."""
    n = sorted_vals.size
    if n == 0:
        return 0.0 if np.isscalar(x) else np.zeros_like(x, dtype=float)
    return (n - np.searchsorted(sorted_vals, x, side="right")) / n


def curve_x_max(sorted_ales: list[np.ndarray], threshold: float | None) -> float:
    xmax = max((quantile(s, 0.995) for s in sorted_ales), default=0.0)
    if threshold:
        xmax = max(xmax, threshold * 1.15)
    return nice_max(xmax)


def exceedance_curve(sorted_ale: np.ndarray, x_max: float) -> list[dict]:
    xs = np.linspace(0.0, x_max, CURVE_POINTS)
    ys = exceed(sorted_ale, xs)
    return [{"x": float(x), "y": float(y)} for x, y in zip(xs, ys)]


def histogram(single_sample: np.ndarray) -> dict | None:
    """24 bins of single-event loss from 0 to niceMax(p99); the last bin takes the overflow."""
    if single_sample.size == 0:
        return None
    top = nice_max(quantile(np.sort(single_sample), 0.99))
    width = top / HIST_BINS
    idx = np.minimum((single_sample // width).astype(np.int64), HIST_BINS - 1)
    counts = np.bincount(idx, minlength=HIST_BINS)
    n = single_sample.size
    return {
        "max": top,
        "binWidth": width,
        "total": int(n),
        "bins": [
            {"x0": i * width, "x1": (i + 1) * width, "count": int(c), "share": float(c / n)}
            for i, c in enumerate(counts)
        ],
    }
