"""Schemas for structured agent outputs (model-infra: reliable JSON, not parsed prose).

The hypothesis step and the adjudicator emit JSON validated against these models, so the
brief no longer depends on regex-parsing free-form text. A model that fails to produce
valid JSON falls back to the text path (see nodes.py), so robustness is preserved.
"""

from typing import Literal

from pydantic import BaseModel, Field


class Hypotheses(BaseModel):
    hypotheses: list[str] = Field(default_factory=list)


class KeyJudgment(BaseModel):
    judgment: str
    citations: list[str] = Field(default_factory=list)  # evidence labels, e.g. ["E1", "E3"]


class Finding(BaseModel):
    """The adjudicator's structured finding — the brief's backbone."""

    key_judgments: list[KeyJudgment] = Field(default_factory=list)
    confidence: Literal["low", "moderate", "high"] = "low"
    confidence_rationale: str = ""
    alternative_hypothesis: str = ""
    collection_requirement: str = ""
    intelligence_gaps: list[str] = Field(default_factory=list)
