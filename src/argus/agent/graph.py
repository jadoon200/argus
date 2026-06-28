"""LangGraph deliberation: hypotheses -> ACH score -> analyst <-> red-team -> adjudicate.

The hypothesis-setter seeds competing explanations; an ACH scorer ranks them by least
disconfirming evidence; then the analyst and red team trade `debate_rounds` challenges —
crucially, the analyst ANSWERS each red-team challenge (including the last) before the
neutral adjudicator issues the finding, so the judgment is genuinely argued out rather
than one-shotted. `debate_rounds` is the number of red-team challenges; each is rebutted.
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
    graph.add_node("score", lambda s: nodes.score_hypotheses(s, backend))
    graph.add_node("analyst", lambda s: nodes.analyst(s, backend))
    graph.add_node("red_team", lambda s: nodes.red_team(s, backend))
    graph.add_node("adjudicate", lambda s: nodes.adjudicate(s, backend))

    graph.add_edge(START, "hypotheses")
    graph.add_edge("hypotheses", "score")
    graph.add_edge("score", "analyst")
    # The analyst speaks first (round 0) and after every red-team challenge; it routes on
    # to another challenge while rounds remain, else to adjudication — so the analyst
    # always gets the last word before the adjudicator, and `red_team` runs exactly
    # `debate_rounds` times (the round counter is incremented there).
    graph.add_conditional_edges(
        "analyst",
        lambda s: "red_team" if s.get("round", 0) < debate_rounds else "adjudicate",
        {"red_team": "red_team", "adjudicate": "adjudicate"},
    )
    graph.add_edge("red_team", "analyst")
    graph.add_edge("adjudicate", END)
    return graph.compile()


def run_deliberation(
    query: str,
    evidence: list[EvidenceItem],
    backend: LLMBackend,
    debate_rounds: int | None = None,
    num_hypotheses: int | None = None,
) -> DeliberationState:
    settings = get_settings()
    rounds = debate_rounds if debate_rounds is not None else settings.debate_rounds
    n_hyp = num_hypotheses if num_hypotheses is not None else settings.num_hypotheses
    app = build_graph(backend, rounds)
    initial: DeliberationState = {
        "query": query,
        "evidence": evidence,
        "num_hypotheses": n_hyp,
        "round": 0,
        "critiques": [],
        "critiques_struct": [],
        "transcript": [],
        "backend": backend.name,
    }
    return cast(DeliberationState, app.invoke(initial))
