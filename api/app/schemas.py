"""The analysis document, compatible with the prototype's JSON export.

Field names are snake_case in Python and camelCase on the wire. Missing
fields are filled with the same defaults as the prototype's blankAnalysis()
and blankState(); a null where an object or string is expected also falls
back to the default, as the prototype's normalize() does.
"""

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.alias_generators import to_camel

MAX_ITERATIONS = 200_000
ALLOWED_ITERATIONS = (1_000, 10_000, 50_000, 100_000)


def new_id() -> str:
    return uuid.uuid4().hex[:16]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class Doc(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="ignore")

    @model_validator(mode="before")
    @classmethod
    def _null_means_default(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        out = dict(data)
        for name, field in cls.model_fields.items():
            key = field.alias or name
            for k in (key, name):
                if k in out and out[k] is None and (field.default is not None or field.default_factory):
                    del out[k]
        return out


class Dist(Doc):
    min: float | None = None
    ml: float | None = None
    max: float | None = None
    conf: str = "med"
    src: str = ""

    @field_validator("conf", mode="before")
    @classmethod
    def _conf(cls, v: Any) -> str:
        # The prototype falls back to medium for an unknown confidence.
        return v if v in ("low", "med", "high") else "med"


class LefInputs(Doc):
    mode: Literal["tef_vuln", "cf_poa", "lef"] = "tef_vuln"
    vuln_mode: Literal["direct", "tcap_rs"] = "direct"
    lef: Dist = Field(default_factory=Dist)
    tef: Dist = Field(default_factory=Dist)
    cf: Dist = Field(default_factory=Dist)
    poa: Dist = Field(default_factory=Dist)
    vuln: Dist = Field(default_factory=Dist)
    tcap: Dist = Field(default_factory=Dist)
    rs: Dist = Field(default_factory=Dist)


class PrimaryLoss(Doc):
    productivity: Dist = Field(default_factory=Dist)
    response: Dist = Field(default_factory=Dist)
    replacement: Dist = Field(default_factory=Dist)


class SecondaryLoss(Doc):
    response: Dist = Field(default_factory=Dist)
    fines: Dist = Field(default_factory=Dist)
    competitive: Dist = Field(default_factory=Dist)
    reputation: Dist = Field(default_factory=Dist)


class State(Doc):
    id: str = Field(default_factory=new_id)
    name: str = "Current state"
    notes: str = ""
    cost: float | None = None  # annual cost; treatments only
    lef: LefInputs = Field(default_factory=LefInputs)
    primary: PrimaryLoss = Field(default_factory=PrimaryLoss)
    slef: Dist = Field(default_factory=Dist)
    secondary: SecondaryLoss = Field(default_factory=SecondaryLoss)


class Scope(Doc):
    asset: str = ""
    threat_community: str = ""
    threat_type: str = "Malicious, external"
    effect: str = "Confidentiality"
    condition: str = ""
    controls: str = ""
    notes: str = ""


class Settings(Doc):
    iterations: int = Field(10_000, ge=100, le=MAX_ITERATIONS)
    seed: int = 20260930
    threshold: float | None = Field(None, ge=0)


class Analysis(Doc):
    format: str = "fair-workbench"
    version: int = 1
    id: str = Field(default_factory=new_id)
    title: str = "Untitled analysis"
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)
    scope: Scope = Field(default_factory=Scope)
    settings: Settings = Field(default_factory=Settings)
    states: list[State] = Field(default_factory=lambda: [State()], min_length=1)
    active: int = 0
    summary: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _clamp_active(self) -> "Analysis":
        self.active = min(max(0, self.active), len(self.states) - 1)
        return self


class DocumentError(ValueError):
    """The uploaded document can't be read as an analysis."""


def normalize_import(raw: Any) -> Analysis:
    """Mirror the prototype's normalize() for an imported document.

    Rejects anything without a `states` array, fills missing fields with
    defaults, names unnamed states as the prototype does, assigns a new
    analysis id and drops any exported summary.
    """
    if not isinstance(raw, dict):
        raise DocumentError("The file is not a FAIR workbench analysis: expected a JSON object.")
    if "states" not in raw and isinstance(raw.get("analysis"), dict):
        raw = raw["analysis"]  # the prototype also accepts {"analysis": {...}}
    states = raw.get("states")
    if not isinstance(states, list):
        raise DocumentError("The file is not a FAIR workbench analysis: it has no \"states\" array.")
    doc = dict(raw)
    fixed = []
    for i, s in enumerate(states or [{}]):
        s = dict(s) if isinstance(s, dict) else {}
        if s.get("name") is None:
            s["name"] = f"Treatment option {i}" if i else "Current state"
        if not s.get("id"):
            s["id"] = new_id()
        fixed.append(s)
    doc["states"] = fixed
    doc.pop("summary", None)
    doc["id"] = new_id()
    if not isinstance(doc.get("active"), int):
        doc["active"] = 0
    return Analysis.model_validate(doc)


def dump(model: BaseModel) -> dict:
    """Serialize to the camelCase wire format."""
    return model.model_dump(by_alias=True, mode="json")


def input_hash(analysis: Analysis) -> str:
    """SHA-256 of the inputs that affect a run: scope, states and settings.

    Names and notes are left out, so renaming an option or editing notes
    doesn't mark the results as stale.
    """
    scope = dump(analysis.scope)
    scope.pop("notes", None)
    states = []
    for s in analysis.states:
        d = dump(s)
        d.pop("name", None)
        d.pop("notes", None)
        states.append(d)
    canonical = json.dumps(
        {"scope": scope, "states": states, "settings": dump(analysis.settings)},
        sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
