"""Simulation runs, validation and stateless simulation.

These endpoints are plain `def` so FastAPI runs the CPU-bound simulation in
its thread pool instead of blocking the event loop.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.engine.checks import has_errors
from app.engine.simulate import PreCheckError, SimulationError, run_analysis, validate_analysis
from app.errors import ApiError
from app.models import RunRow
from app.routers.analyses import get_row
from app.schemas import Analysis, dump, input_hash, new_id

router = APIRouter(prefix="/api", tags=["simulation"])


def _run(analysis: Analysis) -> dict:
    """Run the simulation, turning engine errors into 422 responses."""
    try:
        return run_analysis(analysis)
    except PreCheckError as exc:
        errors = [c for c in exc.checks if c["level"] == "error"]
        first = errors[0]
        state = analysis.states[first["stateIndex"]]
        raise ApiError(422, f"Fix {state.name}: {first['message']}", errors) from exc
    except SimulationError as exc:
        raise ApiError(422, str(exc)) from exc


def run_out(run: RunRow, full: bool = True) -> dict:
    out = {
        "id": run.id,
        "analysisId": run.analysis_id,
        "runAt": run.run_at,
        "iterations": run.iterations,
        "seed": run.seed,
        "threshold": run.results.get("threshold"),
        "inputHash": run.input_hash,
    }
    if full:
        out["results"] = run.results
        out["documentSnapshot"] = run.document_snapshot
    else:
        out["options"] = [
            {k: s[k] for k in ("stateId", "name", "meanAnnualLoss", "p90", "p95", "chanceAnyLoss")}
            for s in run.results["states"]
        ]
    return out


def get_run(session: Session, analysis_id: str, run_id: str) -> RunRow:
    get_row(session, analysis_id)
    run = session.get(RunRow, run_id)
    if run is None or run.analysis_id != analysis_id:
        raise ApiError(404, "Run not found.")
    return run


@router.post("/validate")
def validate(analysis: Analysis) -> dict:
    checks = validate_analysis(analysis)
    return {
        "valid": not has_errors(checks),
        "inputHash": input_hash(analysis),
        "states": [
            {"stateId": s.id, "index": i, "checks": [c for c in checks if c["stateIndex"] == i]}
            for i, s in enumerate(analysis.states)
        ],
    }


@router.post("/simulate")
def simulate(analysis: Analysis) -> dict:
    return {"inputHash": input_hash(analysis), **_run(analysis)}


@router.post("/analyses/{analysis_id}/runs", status_code=201)
def create_run(analysis_id: str, session: Session = Depends(get_session)) -> dict:
    row = get_row(session, analysis_id)
    analysis = Analysis.model_validate(row.document)
    results = _run(analysis)
    run = RunRow(
        id=new_id(),
        analysis_id=analysis_id,
        run_at=results["runAt"],
        iterations=analysis.settings.iterations,
        seed=analysis.settings.seed,
        input_hash=input_hash(analysis),
        document_snapshot=dump(analysis),
        results=results,
    )
    session.add(run)
    session.commit()
    return run_out(run)


@router.get("/analyses/{analysis_id}/runs")
def list_runs(analysis_id: str, session: Session = Depends(get_session)) -> list[dict]:
    get_row(session, analysis_id)
    runs = session.scalars(
        select(RunRow).where(RunRow.analysis_id == analysis_id).order_by(RunRow.run_at.desc())
    ).all()
    return [run_out(r, full=False) for r in runs]


@router.get("/analyses/{analysis_id}/runs/{run_id}")
def fetch_run(analysis_id: str, run_id: str, session: Session = Depends(get_session)) -> dict:
    return run_out(get_run(session, analysis_id, run_id))
