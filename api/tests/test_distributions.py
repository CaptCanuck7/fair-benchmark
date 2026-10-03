import numpy as np
import pytest

from app.engine.distributions import (
    ERR_INCOMPLETE,
    ERR_NEGATIVE,
    ERR_ORDER,
    ERR_OVER_100,
    dist_status,
    pert_mean,
    sample_pert,
)
from app.schemas import Dist
from conftest import dist


def test_constant_when_min_equals_max():
    rng = np.random.default_rng(1)
    out = sample_pert(rng, dist(7.5, 7.5, 7.5), 1000)
    assert np.all(out == 7.5)


@pytest.mark.parametrize("conf", ["low", "med", "high"])
@pytest.mark.parametrize("abm", [(10, 30, 100), (0, 100_000, 1_000_000), (2, 8, 20)])
def test_sample_mean_matches_pert_mean(conf, abm):
    a, m, b = abm
    rng = np.random.default_rng(42)
    out = sample_pert(rng, dist(a, m, b, conf), 200_000)
    expected = pert_mean(a, m, b, conf)
    assert abs(out.mean() - expected) / expected < 0.01


@pytest.mark.parametrize("conf", ["low", "med", "high"])
def test_samples_within_bounds(conf):
    rng = np.random.default_rng(7)
    out = sample_pert(rng, dist(50_000, 150_000, 400_000, conf), 200_000)
    assert out.min() >= 50_000 and out.max() <= 400_000


def test_pct_scaling():
    rng = np.random.default_rng(3)
    out = sample_pert(rng, dist(2, 8, 20), 200_000, 0.01)
    assert out.min() >= 0.02 and out.max() <= 0.20
    assert abs(out.mean() - pert_mean(2, 8, 20, "med") / 100) < 0.001


def test_unknown_confidence_falls_back_to_medium():
    assert Dist(min=1, ml=2, max=3, conf="extreme").conf == "med"


@pytest.mark.parametrize(
    "vals,kind,expected",
    [
        ((None, None, None), "money", ("empty", None)),
        ((1, 2, 3), "money", ("ok", None)),
        ((1, None, 3), "money", ("error", ERR_INCOMPLETE)),
        ((1, float("inf"), 3), "money", ("error", ERR_INCOMPLETE)),
        ((-1, 2, 3), "money", ("error", ERR_NEGATIVE)),
        ((10, 50, 150), "pct", ("error", ERR_OVER_100)),
        ((10, 50, 101), "score", ("error", ERR_OVER_100)),
        ((10, 50, 150), "money", ("ok", None)),
        ((5, 3, 10), "freq", ("error", ERR_ORDER)),
        ((5, 12, 10), "freq", ("error", ERR_ORDER)),
    ],
)
def test_dist_status(vals, kind, expected):
    a, m, b = vals
    assert dist_status(Dist(min=a, ml=m, max=b), kind) == expected
