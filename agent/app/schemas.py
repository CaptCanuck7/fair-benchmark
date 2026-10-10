"""Pydantic models for every task's input (from api) and output (from the model).

Output models carry the checks the API's structured-output schema can't
express; llm.py validates every reply against them and retries once.
"""

from typing import Literal

from pydantic import BaseModel, Field, model_validator

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
