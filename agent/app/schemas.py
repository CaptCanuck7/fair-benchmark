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
    # Whether the register names a risk owner. The name itself is never sent.
    has_risk_owner: bool = False
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


# --- First-pass estimates (section 9.6) -----------------------------------------

# Units as stored in the analysis document (CLAUDE.md section 3).
FACTOR_KIND: dict[str, str] = {
    "lef": "freq", "tef": "freq", "cf": "freq", "poa": "pct", "vuln": "pct", "tcap": "score", "rs": "score",
    "slef": "pct", **{f"primary.{k}": "money" for k in ("productivity", "response", "replacement")},
    **{f"secondary.{k}": "money" for k in ("response", "fines", "competitive", "reputation")},
}


def group_of_factor(factor: str) -> str | None:
    return next((g for g, keys in FACTOR_GROUPS.items() if factor in keys), None)


def required_factors(mode: str, vuln_mode: str) -> list[tuple[str, ...]]:
    """What a method needs: each tuple is satisfied by any one of its factors."""
    vuln = [("vuln",)] if vuln_mode == "direct" else [("tcap",), ("rs",)]
    freq = {"lef": [("lef",)], "tef_vuln": [("tef",), *vuln], "cf_poa": [("cf",), ("poa",), *vuln]}[mode]
    return [*freq, FACTOR_GROUPS["primary"], ("slef",), FACTOR_GROUPS["secondary"][1:]]


class EvidenceIn(BaseModel):
    id: int
    origin: Literal["internal", "external"]
    source_type: str
    source_name: str
    citation: str
    summary: str
    value: float | None = None
    unit: str | None = None
    factors: list[str] = Field(default_factory=list)
    stale: bool = False


class RequestIn(BaseModel):
    id: int
    team: str
    question: str
    factor: str
    status: str
    answer: str | None = None


class EstimatesRequest(BaseModel):
    agent_run_id: str | None = None
    risk: RiskEntry
    scenario: dict
    vectors: dict | None = None
    evidence: list[EvidenceIn]
    data_requests: list[RequestIn] = Field(default_factory=list)


class MethodOut(BaseModel):
    mode: Literal["tef_vuln", "cf_poa", "lef"]
    vuln_mode: Literal["direct", "tcap_rs"]
    reason: str = Field(max_length=500, description="Why this method fits the evidence, in plain words.")


class EstimateOut(BaseModel):
    factor: FactorKey
    min: float
    ml: float
    max: float
    conf: Literal["low", "med", "high"]
    rationale: str = Field(max_length=900, description="How the evidence leads to this range, citing it.")
    evidence_ids: list[int] = Field(min_length=1, max_length=12)


class NewRequestOut(BaseModel):
    team: Team
    question: str = Field(min_length=15, max_length=400)
    reason: str = Field(max_length=400)

    @model_validator(mode="after")
    def _plain(self) -> "NewRequestOut":
        m = FAIR_JARGON.search(self.question)
        if m:
            raise ValueError(f"the question uses the FAIR term '{m.group(0)}'; ask in words the {self.team} team uses")
        return self


class UnestimatedOut(BaseModel):
    factor: FactorKey
    reason: str = Field(max_length=400)
    data_request_id: int | None = Field(default=None, description="An existing data request for this gap.")
    new_request: NewRequestOut | None = Field(default=None, description="Only when no existing request fits.")


class EstimatesOutput(BaseModel):
    method: MethodOut
    estimates: list[EstimateOut] = Field(max_length=15)
    unestimated: list[UnestimatedOut] = Field(max_length=15)

    @model_validator(mode="after")
    def _rules(self, info: ValidationInfo) -> "EstimatesOutput":
        ctx = info.context or {}
        # The checks run whenever the context names the evidence or requests,
        # even when the list is empty: with no evidence, no range may pass.
        check_evidence, check_requests = "evidence" in ctx, "request_ids" in ctx
        evidence: dict[int, dict] = ctx.get("evidence", {})
        request_ids: set[int] = ctx.get("request_ids", set())
        problems: list[str] = []
        seen: set[str] = set()
        for e in self.estimates:
            if e.factor in seen:
                problems.append(f"{e.factor} appears twice")
            seen.add(e.factor)
            kind = FACTOR_KIND[e.factor]
            if min(e.min, e.ml, e.max) < 0:
                problems.append(f"{e.factor}: values can't be negative")
            if kind in ("pct", "score") and e.max > 100:
                problems.append(f"{e.factor}: use values from 0 to 100 (percent or percentile)")
            if not e.min <= e.ml <= e.max:
                problems.append(f"{e.factor}: keep min <= ml <= max")
            if check_evidence:
                unknown = [i for i in e.evidence_ids if i not in evidence]
                if unknown:
                    problems.append(f"{e.factor}: evidence ids {unknown} are not in the evidence list")
                cited = [evidence[i] for i in e.evidence_ids if i in evidence]
                group = group_of_factor(e.factor)
                if cited and not any(group in ev["groups"] for ev in cited):
                    problems.append(f"{e.factor}: none of the cited evidence informs the {group} group; a factor "
                                    "with no evidence of its own goes under unestimated")
                if cited and all(ev["origin"] == "external" for ev in cited) and e.conf != "low":
                    problems.append(f"{e.factor}: external base rates alone support only conf 'low'")
        for u in self.unestimated:
            if u.factor in seen:
                problems.append(f"{u.factor} appears twice")
            seen.add(u.factor)
            if (u.data_request_id is None) == (u.new_request is None):
                problems.append(f"{u.factor}: give exactly one of data_request_id or new_request")
            elif u.data_request_id is not None and check_requests and u.data_request_id not in request_ids:
                problems.append(f"{u.factor}: data request {u.data_request_id} is not in the list")
        for options in required_factors(self.method.mode, self.method.vuln_mode):
            if not seen & set(options):
                problems.append(f"the method needs {' or '.join(options)}: estimate it or list it under unestimated")
        if problems:
            raise ValueError("; ".join(problems))
        return self


# --- Task 7: input review ---------------------------------------------------------

FindingKind = Literal["no_rationale", "evidence_conflict", "scope_drift", "unexplained_change", "unit_mistake",
                      "other"]
# Kinds that are about one factor of one option.
FACTOR_FINDINGS = {"no_rationale", "evidence_conflict", "unexplained_change", "unit_mistake"}


class ReviewRequest(BaseModel):
    agent_run_id: str | None = None
    analysis: dict
    states: list[dict]
    checks: list[dict] = Field(default_factory=list)
    evidence: list[dict] = Field(default_factory=list)
    provenance: list[dict] = Field(default_factory=list)


class FindingOut(BaseModel):
    kind: FindingKind
    state_id: str | None = Field(description="The option the finding is about; null for the whole analysis.")
    factor: FactorKey | Literal["method"] | None = None
    message: str = Field(min_length=10, max_length=500, description="What looks wrong, in plain words.")
    suggestion: str | None = Field(default=None, max_length=400, description="What the analyst could check or do.")
    evidence_ids: list[int] = Field(default_factory=list, max_length=6)


class ReviewOutput(BaseModel):
    summary: str = Field(min_length=10, max_length=600)
    findings: list[FindingOut] = Field(max_length=15)

    @model_validator(mode="after")
    def _grounded(self, info: ValidationInfo) -> "ReviewOutput":
        ctx = info.context or {}
        states: dict[str, dict] = ctx.get("states", {})
        evidence: set[int] = ctx.get("evidence", set())
        problems = []
        for i, f in enumerate(self.findings):
            where = f"findings[{i}]"
            if f.state_id is not None and states and f.state_id not in states:
                problems.append(f"{where}: state_id {f.state_id!r} isn't an option in this analysis")
                continue
            if f.kind in FACTOR_FINDINGS and (f.factor is None or f.state_id is None):
                problems.append(f"{where}: a {f.kind} finding names its option (state_id) and factor")
                continue
            st = states.get(f.state_id or "", {})
            if f.kind == "evidence_conflict":
                if not f.evidence_ids:
                    problems.append(f"{where}: an evidence_conflict finding cites the evidence ids it conflicts with")
                unknown = [e for e in f.evidence_ids if e not in evidence]
                if unknown:
                    problems.append(f"{where}: evidence ids {unknown} aren't in the linked evidence")
            if f.kind == "unexplained_change":
                if st.get("baseline"):
                    problems.append(f"{where}: unexplained_change is about a treatment option, not the current state")
                elif f.factor not in st.get("changed", set()):
                    problems.append(f"{where}: the option doesn't change {f.factor}")
            if f.kind in ("no_rationale", "unit_mistake") and st and f.factor not in st.get("factors", set()):
                problems.append(f"{where}: {f.factor} isn't used by that option's method")
        if problems:
            raise ValueError("; ".join(problems))
        return self


# --- Task 7: reports ------------------------------------------------------------------

# A figure as written in a report: $1.09M, 86%, 2.8, 10,000.
FIGURE = re.compile(r"(?<![\w.])\$?\d{1,3}(?:,\d{3})+(?:\.\d+)?[KMB%]?|(?<![\w.])\$?\d+(?:\.\d+)?(?:[KMB]\b|%)?")
FIGURE_LABELS = re.compile(r"\b[Pp](?:10|50|90|95|99)\b|\b(?:10|50|90|95|99)(?:st|nd|rd|th)?[- ]percentile\b|"
                           r"\b[A-Z]{2,}-\d+\b")
REPORT_JARGON = re.compile(r"\b(TEF|LEF|SLEF|PERT|ALE|Monte Carlo|loss event frequency|threat event frequency|"
                           r"loss exceedance|stochastic)\b", re.IGNORECASE)


def figures_in(text: str, names: list[str] | tuple[str, ...] = ()) -> list[str]:
    for name in sorted((n for n in names if n), key=len, reverse=True):
        text = text.replace(name, " ")
    return FIGURE.findall(FIGURE_LABELS.sub(" ", text))


class ReportRequest(BaseModel):
    agent_run_id: str | None = None
    analysis: dict
    risk: dict | None = None
    run: dict
    options: list[dict]
    residual_state_id: str | None = None


class ReportOutput(BaseModel):
    leadership_summary: str = Field(min_length=200, max_length=2500)
    exception_justification: str | None = Field(default=None, max_length=3000)

    @model_validator(mode="after")
    def _figures_copied(self, info: ValidationInfo) -> "ReportOutput":
        ctx = info.context or {}
        problems = []
        if ctx.get("residual") and not self.exception_justification:
            problems.append("write the exception_justification: there is a treatment option to compare")
        if not ctx.get("residual") and self.exception_justification:
            problems.append("exception_justification must be null: there is no treatment option")
        allowed: set[str] = ctx.get("figures", set())
        names = ctx.get("names", [])
        for field in ("leadership_summary", "exception_justification"):
            text = getattr(self, field) or ""
            m = REPORT_JARGON.search(text)
            if m:
                problems.append(f"{field} uses the term '{m.group(0)}'; leaders won't know it, say it plainly")
            if allowed:
                stray = [f for f in figures_in(text, names) if f not in allowed and not _is_year(f)]
                if stray:
                    problems.append(f"{field} has numbers that aren't in the figures: {', '.join(dict.fromkeys(stray))}. "
                                    "Copy figures exactly as given, write no other numbers, and write counts "
                                    "and ratios in words")
        if problems:
            raise ValueError("; ".join(problems))
        return self


def _is_year(token: str) -> bool:
    return token.isdigit() and 1990 <= int(token) <= 2100
