import json
from pathlib import Path

import pytest

from app.schemas import Analysis, Dist, State

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def dist(a, m, b, conf="med", src="test") -> Dist:
    return Dist(min=a, ml=m, max=b, conf=conf, src=src)


def simple_state(**kw) -> State:
    """A valid state: LEF entered directly, one primary form."""
    s = State()
    s.lef.mode = "lef"
    s.lef.lef = dist(0.1, 0.3, 0.8)
    s.primary.response = dist(10_000, 50_000, 200_000)
    for k, v in kw.items():
        setattr(s, k, v)
    return s


@pytest.fixture
def product_x() -> Analysis:
    return Analysis.model_validate(load_fixture("product_x.json"))
