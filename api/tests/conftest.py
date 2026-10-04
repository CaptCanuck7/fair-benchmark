import json
import os
from pathlib import Path

import pytest

# Tests use a fresh in-memory database, never the real one on the volume.
os.environ["DATABASE_URL"] = "sqlite://"

# agent-data/ sits at the repo root locally and is mounted at /agent-data in the
# container; both are two levels above this folder.
AGENT_DATA = Path(os.environ.get("AGENT_DATA_DIR") or Path(__file__).resolve().parents[2] / "agent-data")
os.environ["AGENT_DATA_DIR"] = str(AGENT_DATA)

from app.schemas import Analysis, Dist, State  # noqa: E402

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


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app.db import Base, engine
    from app.main import app

    with TestClient(app) as c:
        yield c
    Base.metadata.drop_all(engine)
