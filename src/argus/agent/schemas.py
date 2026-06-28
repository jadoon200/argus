"""Schemas for structured agent outputs (model-infra: reliable JSON, not parsed prose).

The hypothesis step and the adjudicator emit JSON validated against these models, so the
brief no longer depends on regex-parsing free-form text. A model that fails to produce
valid JSON falls back to the text path (see nodes.py), so robustness is preserved.
"""

from typing import Literal

from pydantic import BaseModel, Field


class Hypotheses(BaseModel):
    hypotheses: list[str] = Field(default_factory=list)


# --- Analysis of Competing Hypotheses (ACH) matrix --------------------------------------
# The diagnostic core of ACH: rate each hypothesis against each evidence item, then favour
# the hypothesis with the least (reliability-weighted) *disconfirming* evidence.
AchAssessment = Literal["consistent", "inconsistent", "neutral"]


class AchCell(BaseModel):
    evidence: str  # an evidence label, e.g. "E1"
    assessment: AchAssessment = "neutral"


class AchRow(BaseModel):
    hypothesis: str
    cells: list[AchCell] = Field(default_factory=list)


class AchMatrix(BaseModel):
    rows: list[AchRow] = Field(default_factory=list)


# --- Structured red-team critique -------------------------------------------------------
class Critique(BaseModel):
    """One red-team challenge, structured so the adjudicator can be made to address it."""

    target_hypothesis: str = ""  # which hypothesis / claim is under attack
    challenged_claim: str = ""  # the specific assertion being challenged
    severity: Literal["low", "moderate", "high"] = "moderate"
    rationale: str = ""
    citations: list[str] = Field(default_factory=list)  # evidence labels, e.g. ["E2"]


class Critiques(BaseModel):
    critiques: list[Critique] = Field(default_factory=list)


class KeyJudgment(BaseModel):
    judgment: str
    citations: list[str] = Field(default_factory=list)  # evidence labels, e.g. ["E1", "E3"]


class Finding(BaseModel):
    """The adjudicator's structured finding — the brief's backbone.

    Carries two Structured Analytic Techniques alongside the judgments: a Key
    Assumptions Check (the load-bearing assumptions the assessment rests on) and
    Indicators & Warnings (observable developments that would confirm or refute it).
    """

    key_judgments: list[KeyJudgment] = Field(default_factory=list)
    confidence: Literal["low", "moderate", "high"] = "low"
    confidence_rationale: str = ""
    key_assumptions: list[str] = Field(default_factory=list)  # Key Assumptions Check
    indicators: list[str] = Field(default_factory=list)  # Indicators & Warnings to watch
    alternative_hypothesis: str = ""
    collection_requirement: str = ""
    intelligence_gaps: list[str] = Field(default_factory=list)
    # How the finding answers the strongest red-team challenge (forces the adjudicator to
    # engage the critique rather than ignore it). Empty on the free-form fallback path.
    critique_response: str = ""
