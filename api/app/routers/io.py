"""Import and export in the prototype's formats."""

import csv
import io
import json
import re
from typing import Any

from fastapi import APIRouter, Body, Depends, Response
from sqlalchemy.orm import Session

from app.db import get_session
from app.errors import ApiError
from app.routers.analyses import doc_response, get_row, latest_run, save_new
from app.routers.simulate import get_run
from app.schemas import Analysis, DocumentError, dump, input_hash, normalize_import

router = APIRouter(prefix="/api", tags=["import-export"])

CSV_HEADER = [
    "Option", "Annual cost", "Mean annual loss", "P10", "P50", "P90", "P95", "P99",
    "Chance of any loss", "Chance above threshold", "LEF mean", "Single loss P50", "Single loss P90",
]


def _round(v: float | None) -> int | None:
    # JS Math.round: half up
    return None if v is None else int(v + 0.5) if v >= 0 else -int(-v + 0.5)


def _round4(v: float | None) -> float | None:
    return None if v is None else round(v, 4)


def summary_options(results: dict) -> list[dict]:
    """Per-state results rounded as the prototype's summary() does."""
    return [
        {
            "name": s["name"],
            "annualCost": s.get("cost"),
            "meanAnnualLoss": _round(s["meanAnnualLoss"]),
            "p10": _round(s["p10"]),
            "p50": _round(s["p50"]),
            "p90": _round(s["p90"]),
            "p95": _round(s["p95"]),
            "p99": _round(s["p99"]),
            "chanceAnyLoss": _round4(s["chanceAnyLoss"]),
            "chanceAboveThreshold": _round4(s["chanceAboveThreshold"]),
            "lefMean": _round4(s["lefMean"]),
            "lefP10": _round4(s["lefP10"]),
            "lefP90": _round4(s["lefP90"]),
            "singleLossP50": _round(s["singleLossP50"]),
            "singleLossP90": _round(s["singleLossP90"]),
            "singleLossMean": _round(s["singleLossMean"]),
            "derivedVulnerability": s["derivedVulnerability"],
            "secondaryShareOfLoss": _round4(s["secondaryShareOfLoss"]),
            "breakdown": {k: _round(v) for k, v in s["breakdown"].items()},
        }
        for s in results["states"]
    ]


def _slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-") or "fair-analysis"


def _attachment(filename: str) -> dict:
    return {"Content-Disposition": f'attachment; filename="{filename}"'}


@router.get("/analyses/{analysis_id}/export.json")
def export_json(analysis_id: str, session: Session = Depends(get_session)) -> Response:
    analysis = Analysis.model_validate(get_row(session, analysis_id).document)
    doc = dump(analysis)
    cfg = analysis.settings
    summary: dict[str, Any] = {
        "runAt": None, "iterations": cfg.iterations, "seed": cfg.seed, "threshold": cfg.threshold, "options": [],
    }
    run = latest_run(session, analysis_id)
    if run is not None:
        summary.update(runAt=run.run_at, iterations=run.iterations, seed=run.seed,
                       threshold=run.results.get("threshold"), options=summary_options(run.results))
    summary["stale"] = run is not None and run.input_hash != input_hash(analysis)
    doc["summary"] = summary
    body = json.dumps(doc, indent=2, ensure_ascii=False)
    return Response(body, media_type="application/json", headers=_attachment(f"{_slug(analysis.title)}.json"))


@router.get("/analyses/{analysis_id}/runs/{run_id}/export.csv")
def export_csv(analysis_id: str, run_id: str, session: Session = Depends(get_session)) -> Response:
    run = get_run(session, analysis_id, run_id)
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(CSV_HEADER)
    for o in summary_options(run.results):
        cells = [
            o["annualCost"], o["meanAnnualLoss"], o["p10"], o["p50"], o["p90"], o["p95"], o["p99"],
            o["chanceAnyLoss"], o["chanceAboveThreshold"], o["lefMean"], o["singleLossP50"], o["singleLossP90"],
        ]
        w.writerow([o["name"], *("" if v is None else _num(v) for v in cells)])
    title = run.document_snapshot.get("title", "")
    return Response(buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers=_attachment(f"{_slug(title)}-results.csv"))


def _num(v: float) -> int | float:
    """Write 50000.0 as 50000 and 0.0 as 0, as JavaScript's String() does."""
    return int(v) if float(v).is_integer() else v


@router.post("/import", status_code=201)
def import_analysis(response: Response, body: Any = Body(...), session: Session = Depends(get_session)) -> dict:
    try:
        analysis = normalize_import(body)
    except DocumentError as exc:
        raise ApiError(422, str(exc), [{"path": "states", "message": str(exc)}]) from exc
    save_new(session, analysis)
    return doc_response(response, analysis)
