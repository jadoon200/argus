"""DSPy program for the intelligence brief — the optimizable core (innovation #3).

Instead of hand-tuning the prompt, DSPy COMPILES it against the eval metric on the
local model. Free: the LM is the user's Ollama. This module defines the program; the
optimization run lives in `compile.py`.
"""

from typing import Any

import dspy

from argus.config import Settings, get_settings


def configure_lm(settings: Settings | None = None) -> None:
    """Point DSPy at the local Ollama model (free)."""
    s = settings or get_settings()
    lm = dspy.LM(
        f"ollama_chat/{s.ollama_model}",
        api_base=s.ollama_url,
        api_key="",
        temperature=0.2,
    )
    dspy.configure(lm=lm)


class IntelligenceBrief(dspy.Signature):
    """Assess an intelligence question from open-source evidence.

    Cite evidence by its [E#] label only; never invent a citation. Calibrate confidence
    to source reliability and corroboration — a single low-reliability source warrants
    only low confidence."""

    question: str = dspy.InputField()
    evidence: str = dspy.InputField(
        desc="evidence items, each with an [E#] label and an Admiralty rating"
    )
    key_judgments: list[str] = dspy.OutputField(
        desc="2-4 judgments, each ending with its supporting [E#] citation(s)"
    )
    confidence: str = dspy.OutputField(desc="exactly one of: low, moderate, high")


class BriefProgram(dspy.Module):
    def __init__(self) -> None:
        super().__init__()
        self.generate = dspy.ChainOfThought(IntelligenceBrief)

    def forward(self, question: str, evidence: str) -> Any:
        return self.generate(question=question, evidence=evidence)
