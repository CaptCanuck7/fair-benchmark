"""PERT sampling and range validation for factor estimates."""

import math

import numpy as np

from app.content.factors import CONF
from app.schemas import Dist

ERR_INCOMPLETE = "Enter all three values: minimum, most likely and maximum."
ERR_NEGATIVE = "Values can’t be negative."
ERR_OVER_100 = "Use values between 0 and 100."
ERR_ORDER = "Keep minimum ≤ most likely ≤ maximum."


def dist_status(d: Dist | None, kind: str) -> tuple[str, str | None]:
    """Return ("empty" | "ok" | "error", message), as the prototype's distStatus()."""
    if d is None:
        return "empty", None
    vals = [d.min, d.ml, d.max]
    if all(v is None for v in vals):
        return "empty", None
    if any(v is None or not math.isfinite(v) for v in vals):
        return "error", ERR_INCOMPLETE
    if any(v < 0 for v in vals):
        return "error", ERR_NEGATIVE
    # Checking max alone matches the prototype; a larger min fails the order check.
    if kind in ("pct", "score") and d.max > 100:
        return "error", ERR_OVER_100
    if not (d.min <= d.ml <= d.max):
        return "error", ERR_ORDER
    return "ok", None


def is_ok(d: Dist | None, kind: str) -> bool:
    return dist_status(d, kind)[0] == "ok"


def pert_params(a: float, m: float, b: float, conf: str) -> tuple[float, float]:
    lam = CONF.get(conf, CONF["med"])["lam"]
    alpha = 1 + lam * (m - a) / (b - a)
    beta = 1 + lam * (b - m) / (b - a)
    return alpha, beta


def pert_mean(a: float, m: float, b: float, conf: str) -> float:
    lam = CONF.get(conf, CONF["med"])["lam"]
    return (a + lam * m + b) / (lam + 2)


def sample_pert(rng: np.random.Generator, d: Dist, size: int, scale: float = 1.0) -> np.ndarray:
    """Draw `size` samples from the PERT distribution of a valid Dist.

    `scale` converts stored units (0.01 for pct factors). When max equals
    min the result is the constant most likely value.
    """
    a, m, b = d.min * scale, d.ml * scale, d.max * scale
    if b - a <= 0:
        return np.full(size, m, dtype=float)
    alpha, beta = pert_params(a, m, b, d.conf)
    return a + rng.beta(alpha, beta, size) * (b - a)
