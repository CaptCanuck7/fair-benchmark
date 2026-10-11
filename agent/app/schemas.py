"""Pydantic models for every task's input (from api) and output (from the model).

Output models carry the checks the API's structured-output schema can't
express; llm.py validates every reply against them and retries once.
"""

import re
from typing import Literal

from pydantic import BaseModel, Field, ValidationInfo, field_validator, model_validator

# --- Shared input ---------------------------------------------------------------


class RiskEntry(BaseModel):
    """The parts of a register entry a task needs. People's names are left out:
    no task needs them, so they are never sent to the model."""

    title: str | None = None
    category: str | None = None
    asset_ids: list[str] = Field(default_factory=list)
    environment: str | None = None
    risk_action: str | None = None
    baseline_impact: int | None = None
    baseline_likelihood: int | None = None
    baseline_score: int | None = None
    mitigation_plan: str | None = None
    structured: bool = True
    # risk_statement, detailed_analysis, baseline_controls, exploit_paths,
    # preamble; or raw when unstructured.
    sections: dict[str, str] = Field(default_factory=dict)


class RuleGap(BaseModel):
    field: str
    problem: str


# --- Quality check (section 9.1) ------------------------------------------------


class QualityRequest(BaseModel):
    risk: RiskEntry
    rule_gaps: list[RuleGap] = Field(default_factory=list)


GapField = Literal["assets", "environment", "risk_owner", "baseline_impact", "baseline_likelihood", "risk_action",
                   "mitigation_plan", "risk_statement", "detailed_analysis", "baseline_controls", "exploit_paths",
                   "risk_analysis"]


class QualityGap(BaseModel):
    field: GapField = Field(description="The register field or analysis section the problem is in. "
                                        "risk_analysis means the analysis as a whole.")
    problem: str = Field(max_length=300, description="What is missing or unclear, in one plain sentence.")


class QualityJudgement(BaseModel):
    names_asset: bool = Field(description="The analysis names what is at risk.")
    names_condition: bool = Field(description="The analysis names the weakness or condition behind the risk.")
    names_loss_path: bool = Field(description="The analysis describes how loss could happen and what would be lost.")
    gaps: list[QualityGap] = Field(max_length=10, description="Problems the rule checks can't see. Empty if none.")
    questions: list[str] = Field(max_length=8, description="Specific questions for the analyst, one per gap.")

    @model_validator(mode="after")
    def _short_questions(self) -> "QualityJudgement":
        for q in self.questions:
            if not q.strip() or len(q) > 300:
                raise ValueError("each question must be non-empty and at most 300 characters")
        return self


# --- Triage (section 9.2) -------------------------------------------------------


class TriageRule(BaseModel):
    status: Literal["qualifies", "screened_out"]
    score: int | None = None
    threshold: int
    rule: str


class TriageRequest(BaseModel):
    risk: RiskEntry
    rule: TriageRule


class TriageNote(BaseModel):
    reason: str = Field(max_length=400, description="Why the rule gave this result, in one or two plain sentences.")
    advisory: str | None = Field(
        default=None, max_length=300,
        description="A note for the analyst if the entry suggests a second look; null otherwise. Never a status.",
    )


# --- Condition classification (section 7) ---------------------------------------

ConditionType = Literal["unsupported_software", "missing_control", "misconfiguration", "process_gap",
                        "third_party", "other"]


class ClassifyRequest(BaseModel):
    risk: RiskEntry


class Classification(BaseModel):
    primary_type: ConditionType
    secondary_type: ConditionType | None = None
    confidence: Literal["low", "med", "high"]
    reason: str = Field(max_length=300, description="One plain sentence.")

    @model_validator(mode="after")
    def _distinct(self) -> "Classification":
        if self.secondary_type is not None and self.secondary_type == self.primary_type:
            raise ValueError("secondary_type must differ from primary_type, or be null")
        return self


# --- What every task endpoint returns -------------------------------------------


class TaskResult(BaseModel):
    output: dict
    model: str
    prompt_version: str
    input_tokens: int
    output_tokens: int
    attempts: int


# --- Scenario scoping (section 9.3) ---------------------------------------------

# The analysis document's existing values (CLAUDE.md section 3).
ThreatType = Literal["Malicious, external", "Malicious, internal", "Error (accidental)",
                     "Failure (system or vendor)", "Natural"]
Effect = Literal["Confidentiality", "Integrity", "Availability"]
NON_MALICIOUS = ("Error (accidental)", "Failure (system or vendor)", "Natural")


class ClassificationIn(BaseModel):
    primary_type: str
    secondary_type: str | None = None


class ScenarioRequest(BaseModel):
    risk: RiskEntry
    classification: ClassificationIn | None = None


class ScenarioControl(BaseModel):
    control: str = Field(max_length=300, description="The baseline control, as the register names it.")
    factor: Literal["frequency", "susceptibility", "magnitude"] = Field(
        description="frequency: how often the threat acts; susceptibility: whether an attempt succeeds; "
                    "magnitude: how much is lost.")
    helps: bool = Field(description="False when the control doesn't reduce loss in this scenario.")
    note: str | None = Field(default=None, max_length=300, description="Required when helps is false: why not.")

    @model_validator(mode="after")
    def _note_when_unhelpful(self) -> "ScenarioControl":
        if not self.helps and not (self.note or "").strip():
            raise ValueError("a control that doesn't help in this scenario needs a note saying why")
        return self


class ScenarioAlternative(BaseModel):
    title: str = Field(max_length=150)
    asset: str = Field(max_length=200)
    threat_community: str = Field(max_length=200)
    threat_type: ThreatType
    effect: Effect
    split_reason: Literal["threat_type_or_effect_differs", "data_exposure_differs", "mitigation_differs"]
    reason: str = Field(max_length=400, description="Why splitting this path out would help, in plain words.")


class Scenario(BaseModel):
    asset: str = Field(max_length=200)
    threat_community: str = Field(max_length=200)
    threat_type: ThreatType
    effect: Effect
    condition: str = Field(max_length=600, description="The weakness, kept separate from the risk.")
    controls: list[ScenarioControl] = Field(max_length=15)
    scenario_sentence: str = Field(max_length=500)
    notes: list[str] = Field(max_length=8, description="Assumptions and open questions.")
    alternatives: list[ScenarioAlternative] = Field(max_length=4)

    @model_validator(mode="after")
    def _sentence_shape(self) -> "Scenario":
        s = self.scenario_sentence.strip()
        # "causes" or "cause": threat communities are often plural ("cybercriminals cause ...").
        if not re.search(r"\bcauses?\b", s) or not re.search(r"\bthrough\b", s) or not s.endswith("."):
            raise ValueError('scenario_sentence must read "{threat community} causes {effect} to {asset} '
                             'through {method}."')
        for alt in self.alternatives:
            if alt.split_reason == "threat_type_or_effect_differs" and \
                    (alt.threat_type, alt.effect) == (self.threat_type, self.effect):
                raise ValueError(f"alternative '{alt.title}' gives threat_type_or_effect_differs as its reason "
                                 "but has the same threat type and effect as the default scenario")
        return self


# --- Attack vectors and failure paths (section 9.4) -----------------------------

# Operational detail that has no place in a risk write-up: commands, code,
# tool names used to run attacks, and injection strings.
OPERATIONAL = re.compile(
    r"`|\$\(|\bsudo\b|\bcurl\s+-|\bwget\s+http|\bpowershell\s+-|\bcmd\.exe\b|\bmsfconsole\b|\bmetasploit\b|"
    r"\bmimikatz\b|\bsqlmap\b|\bhydra\s+-|\bnmap\s+-|\bpython3?\s+-c\b|<script|\bSELECT\s+\*\s+FROM\b|"
    r"'\s*OR\s+'?1'?\s*=\s*'?1|\bUNION\s+SELECT\b|/etc/passwd|\bchmod\s+[0-7]{3}",
    re.IGNORECASE,
)


STEP_NUMBER = re.compile(r"^\s*(?:\(?\d{1,2}[.)]|step\s+\d{1,2}[:.])\s+", re.IGNORECASE)


def operational_detail(text: str) -> str | None:
    m = OPERATIONAL.search(text or "")
    return m.group(0) if m else None


class VectorsRequest(BaseModel):
    risk: RiskEntry
    scenario: dict  # the approved (or analyst-edited) scenario


class PathStep(BaseModel):
    text: str = Field(max_length=400, description="One step, at the level of a risk write-up.")
    controls: list[str] = Field(max_length=8, description="Baseline controls that matter at this step. May be empty.")

    @field_validator("text")
    @classmethod
    def _no_own_numbering(cls, v: str) -> str:
        # Steps are numbered when shown; drop "1." or "(1)" the model added itself.
        return STEP_NUMBER.sub("", v).strip()


class ThreatPath(BaseModel):
    title: str = Field(max_length=150)
    origin: Literal["from_register", "agent_drafted"]
    steps: list[PathStep] = Field(min_length=1, max_length=8)
    # Failure paths only (non-malicious threat types).
    what_fails: str | None = Field(default=None, max_length=300)
    makes_worse: list[str] = Field(default_factory=list, max_length=6)
    limits: list[str] = Field(default_factory=list, max_length=6)


class VectorsOutput(BaseModel):
    kind: Literal["attack_vectors", "failure_paths"]
    paths: list[ThreatPath] = Field(min_length=1, max_length=6)

    @model_validator(mode="after")
    def _rules(self, info: ValidationInfo) -> "VectorsOutput":
        ctx = info.context or {}
        if "non_malicious" in ctx:
            want = "failure_paths" if ctx["non_malicious"] else "attack_vectors"
            if self.kind != want:
                raise ValueError(f"kind must be {want} for this scenario's threat type")
        if self.kind == "failure_paths":
            for p in self.paths:
                if not (p.what_fails or "").strip():
                    raise ValueError(f"failure path '{p.title}' needs what_fails")
        if "from_register" in ctx:
            want_origin = "from_register" if ctx["from_register"] else "agent_drafted"
            if any(p.origin != want_origin for p in self.paths):
                raise ValueError(f"every path's origin must be {want_origin}")
            if not ctx["from_register"] and len(self.paths) > 3:
                raise ValueError("draft at most three paths when the register has no exploit paths")
        for p in self.paths:
            for text in [p.title, p.what_fails or "", *p.makes_worse, *p.limits, *(s.text for s in p.steps)]:
                found = operational_detail(text)
                if found:
                    raise ValueError(f"'{p.title}' contains operational detail ({found!r}); describe steps at "
                                     "the level of a risk write-up, with no commands, code or tool instructions")
        return self


# --- Evidence gathering (section 9.5) -------------------------------------------

FactorKey = Literal["lef", "tef", "cf", "poa", "vuln", "tcap", "rs", "primary.productivity", "primary.response",
                    "primary.replacement", "slef", "secondary.response", "secondary.fines", "secondary.competitive",
                    "secondary.reputation"]
Team = Literal["SOC", "Asset Management", "Vulnerability Management", "IAM", "Internal Audit", "Third-Party Risk",
               "Finance", "Legal"]

# The four groups of factors evidence gathering must cover, each with evidence
# or a data request.
FACTOR_GROUPS: dict[str, tuple[str, ...]] = {
    "frequency": ("lef", "tef", "cf", "poa"),
    "susceptibility": ("vuln", "tcap", "rs"),
    "primary": ("primary.productivity", "primary.response", "primary.replacement"),
    "secondary": ("slef", "secondary.response", "secondary.fines", "secondary.competitive", "secondary.reputation"),
}

# FAIR terms a team without FAIR knowledge can't answer. Data request
# questions must use plain words instead.
FAIR_JARGON = re.compile(
    r"\b(threat event frequency|loss event frequency|contact frequency|probability of action|threat capability|"
    r"resistance strength|loss magnitude|secondary loss|primary loss|susceptibility|TEF|LEF|SLEF|PERT|FAIR)\b",
    re.IGNORECASE,
)


class EvidenceRequest(BaseModel):
    agent_run_id: str | None = None
    risk: RiskEntry
    scenario: dict
    vectors: dict | None = None
    classification: ClassificationIn | None = None


class EvidenceItemOut(BaseModel):
    citation: str = Field(max_length=500, description="Exactly as a tool returned it.")
    summary: str = Field(max_length=500, description="One or two sentences in your own words.")
    value: float | None = None
    unit: str | None = Field(default=None, max_length=100)
    factors: list[FactorKey] = Field(min_length=1, max_length=6)


class DataRequestOut(BaseModel):
    team: Team
    question: str = Field(min_length=15, max_length=400)
    factor: FactorKey
    reason: str = Field(max_length=400)

    @model_validator(mode="after")
    def _plain_question(self) -> "DataRequestOut":
        m = FAIR_JARGON.search(self.question)
        if m:
            raise ValueError(f"the question uses the FAIR term '{m.group(0)}'; ask in words the {self.team} team "
                             "uses, about counts, dates, costs or test results")
        return self


class EvidenceOutput(BaseModel):
    items: list[EvidenceItemOut] = Field(max_length=40)
    data_requests: list[DataRequestOut] = Field(max_length=12)


# --- Reference library refresh (section 7) --------------------------------------

LibrarySource = Literal["Verizon Data Breach Investigations Report", "IBM Cost of a Data Breach Report",
                        "Cyentia Information Risk Insights Study"]


class LibraryRequest(BaseModel):
    agent_run_id: str | None = None
    existing: list[dict] = Field(default_factory=list)


class LibraryEntryOut(BaseModel):
    metric: str = Field(min_length=3, max_length=300)
    value: float
    unit: str = Field(min_length=1, max_length=100)
    segment: str | None = Field(default=None, max_length=200)
    source: LibrarySource
    edition: str = Field(min_length=4, max_length=100, description="For example '2025'.")
    url: str = Field(max_length=500, description="The page you read the figure on, exactly as fetched.")
    page: str | None = Field(default=None, max_length=32)
    quote: str = Field(min_length=10, max_length=600, description="The sentence on that page stating the figure.")


class LibraryOutput(BaseModel):
    entries: list[LibraryEntryOut] = Field(max_length=25)
