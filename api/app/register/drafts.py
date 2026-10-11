"""Reviewing agent drafts: approve, edit or reject (AGENT_BUILD.md section 10).

Downstream steps use a draft only once it is approved or edited. An edit is
validated here before it is stored beside the agent's version, so what the
analyst saves has the same shape as what the agent drafts.
"""

from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from app.models import DraftRow

USABLE = ("approved", "edited")

ThreatType = Literal["Malicious, external", "Malicious, internal", "Error (accidental)",
                     "Failure (system or vendor)", "Natural"]
Effect = Literal["Confidentiality", "Integrity", "Availability"]
NON_MALICIOUS = ("Error (accidental)", "Failure (system or vendor)", "Natural")


def usable(draft: DraftRow | None) -> dict | None:
    """The version downstream steps may use, or None if it isn't approved or edited."""
    return draft.effective if draft is not None and draft.status in USABLE else None


# --- What an analyst's edit must look like, per kind ----------------------------


class _Edit(BaseModel):
    model_config = {"extra": "forbid"}


class ScenarioControlEdit(_Edit):
    control: str = Field(min_length=1, max_length=300)
    factor: Literal["frequency", "susceptibility", "magnitude"]
    helps: bool
    note: str | None = Field(default=None, max_length=300)


class ScenarioAlternativeEdit(_Edit):
    title: str = Field(max_length=150)
    asset: str = Field(max_length=200)
    threat_community: str = Field(max_length=200)
    threat_type: ThreatType
    effect: Effect
    split_reason: Literal["threat_type_or_effect_differs", "data_exposure_differs", "mitigation_differs"]
    reason: str = Field(max_length=400)


class ScenarioEdit(_Edit):
    asset: str = Field(min_length=1, max_length=200)
    threat_community: str = Field(min_length=1, max_length=200)
    threat_type: ThreatType
    effect: Effect
    condition: str = Field(max_length=600)
    controls: list[ScenarioControlEdit] = Field(max_length=15)
    scenario_sentence: str = Field(min_length=1, max_length=500)
    notes: list[str] = Field(max_length=8)
    alternatives: list[ScenarioAlternativeEdit] = Field(max_length=4)


class PathStepEdit(_Edit):
    text: str = Field(min_length=1, max_length=400)
    controls: list[str] = Field(max_length=8)


class PathEdit(_Edit):
    title: str = Field(min_length=1, max_length=150)
    origin: Literal["from_register", "agent_drafted", "analyst"]
    steps: list[PathStepEdit] = Field(min_length=1, max_length=8)
    what_fails: str | None = Field(default=None, max_length=300)
    makes_worse: list[str] = Field(default_factory=list, max_length=6)
    limits: list[str] = Field(default_factory=list, max_length=6)


class VectorsEdit(_Edit):
    kind: Literal["attack_vectors", "failure_paths"]
    paths: list[PathEdit] = Field(min_length=1, max_length=6)


class ClassificationEdit(_Edit):
    primary_type: Literal["unsupported_software", "missing_control", "misconfiguration", "process_gap",
                          "third_party", "other"]
    secondary_type: Literal["unsupported_software", "missing_control", "misconfiguration", "process_gap",
                            "third_party", "other"] | None = None
    confidence: Literal["low", "med", "high"]
    reason: str = Field(max_length=300)


EDITABLE: dict[str, type[_Edit]] = {
    "scenario": ScenarioEdit,
    "vectors": VectorsEdit,
    "classification": ClassificationEdit,
}

# Fields the api adds to a draft's payload, kept through an edit.
META_KEYS = ("basedOn",)

# Why some actions aren't offered for a kind.
NOT_ALLOWED = {
    ("triage", "edit"): "Triage can’t be edited. Use the triage override, which records a reason.",
    ("triage", "reject"): "Triage can’t be rejected. Use the triage override, which records a reason.",
    ("quality", "edit"): "The quality check can’t be edited. Approve or reject it, or run the checks again.",
}


class EditError(ValueError):
    def __init__(self, errors: list[dict]):
        super().__init__("The edited draft isn’t valid.")
        self.errors = errors


def validate_edit(kind: str, original: dict[str, Any], edited: dict[str, Any]) -> dict[str, Any]:
    """Check an analyst's edit and return it with the api's own fields kept."""
    model = EDITABLE[kind]
    body = {k: v for k, v in edited.items() if k not in META_KEYS}
    try:
        clean = model.model_validate(body).model_dump(mode="json")
    except ValidationError as exc:
        raise EditError([{"path": ".".join(str(p) for p in e["loc"]), "message": e["msg"]}
                         for e in exc.errors()]) from exc
    if kind == "classification" and clean["secondary_type"] == clean["primary_type"]:
        raise EditError([{"path": "secondary_type", "message": "The second type must differ from the first."}])
    if kind == "vectors" and clean["kind"] == "failure_paths":
        missing = [p["title"] for p in clean["paths"] if not (p.get("what_fails") or "").strip()]
        if missing:
            raise EditError([{"path": "paths", "message": f"Say what fails in: {', '.join(missing)}."}])
    return {**clean, **{k: original[k] for k in META_KEYS if k in original}}


Action = Literal["approve", "edit", "reject"]
