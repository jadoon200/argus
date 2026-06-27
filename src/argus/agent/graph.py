"""LangGraph deliberation: hypotheses -> analyst <-> red-team (loop) -> adjudicate.

The analyst and red team exchange `debate_rounds` times before the adjudicator issues
the finding — the agents genuinely argue the judgment out rather than one-shotting it.
"""

from typing import Any, cast

from langgraph.graph import END, START, StateGraph

from argus.agent import nodes
from argus.agent.llm import LLMBackend
from argus.agent.state import DeliberationState, EvidenceItem
from argus.config import get_settings


def build_graph(backend: LLMBackend, debate_rounds: int) -> Any:
    """Compile the deliberation graph bound to a backend and a debate depth."""
    graph = StateGraph(DeliberationState)
    graph.add_node("hypotheses", lambda s: nodes.propose_hypotheses(s, backend))
    graph.add_node("analyst", lambda s: nodes.analyst(s, backend))
    graph.add_node("red_team", lambda s: nodes.red_team(s, backend))
    graph.add_node("adjudicate", lambda s: nodes.adjudicate(s, backend))

    graph.add_edge(START, "hypotheses")
    graph.add_edge("hypotheses", "analyst")
    graph.add_edge("analyst", "red_team")
    graph.add_conditional_edges(
        "red_team",
        lambda s: "analyst" if s.get("round", 0) < debate_rounds else "adjudicate",
        {"analyst": "analyst", "adjudicate": "adjudicate"},
    )
    graph.add_edge("adjudicate", END)
    return graph.compile()


def run_deliberation(
    query: str,
    evidence: list[EvidenceItem],
    backend: LLMBackend,
    debate_rounds: int | None = None,
) -> DeliberationState:
    rounds = debate_rounds if debate_rounds is not None else get_settings().debate_rounds
    app = build_graph(backend, rounds)
    initial: DeliberationState = {
        "query": query,
        "evidence": evidence,
        "round": 0,
        "critiques": [],
        "transcript": [],
        "backend": backend.name,
    }
    return cast(DeliberationState, app.invoke(initial))
