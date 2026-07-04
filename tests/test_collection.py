import json
from typing import Any

from argus.agent.state import BriefResult
from argus.collection.tasking import derive_queries


class TaskingFake:
    name = "task"

    def complete(
        self,
        system: str,
        user: str,
        response_schema: dict[str, Any] | None = None,
        temperature: float | None = None,
    ) -> str:
        return json.dumps(
            {"queries": ["Venezuela earthquake casualties", "US Iran strike response"]}
        )


def test_derive_queries_from_backend() -> None:
    brief = BriefResult(query="q", body="", gaps="intentions unknown", alternatives="")
    assert derive_queries(brief, TaskingFake()) == [
        "Venezuela earthquake casualties",
        "US Iran strike response",
    ]


def test_derive_queries_fallback_extracts_named_entities() -> None:
    brief = BriefResult(
        query="q",
        body="",
        gaps="Unclear whether the Philippine Coast Guard or a China Coast Guard vessel fired.",
        alternatives="",
    )
    queries = derive_queries(brief, None)  # no backend -> deterministic fallback
    assert queries  # extracted capitalised spans
    assert any("Coast Guard" in q for q in queries)


def test_derive_queries_empty_without_gaps() -> None:
    brief = BriefResult(query="q", body="", gaps=None, alternatives=None)
    assert derive_queries(brief, None) == []
    assert derive_queries(brief, TaskingFake()) == []  # short-circuits before the backend
