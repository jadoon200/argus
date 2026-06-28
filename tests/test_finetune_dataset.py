import json
from pathlib import Path

from sqlalchemy.orm import Session

from argus.db.models import Document, Source
from argus.eval.goldset import QUERIES
from argus.finetune.dataset import (
    corpus_items,
    generate_examples,
    gold_items,
    to_chat_example,
    write_jsonl,
)


def test_to_chat_example_structure() -> None:
    ex = to_chat_example("the question", "[E1] some evidence", "THE BRIEF BODY")
    roles = [m["role"] for m in ex["messages"]]
    assert roles == ["system", "user", "assistant"]
    assert "the question" in ex["messages"][1]["content"]
    assert "[E1] some evidence" in ex["messages"][1]["content"]
    assert ex["messages"][2]["content"] == "THE BRIEF BODY"


def test_generate_examples_keeps_cited_drops_uncited() -> None:
    # Template backend over the gold evidence yields a cited digest -> kept.
    kept = generate_examples(gold_items()[:1], backend=None)
    assert len(kept) == 1
    assert kept[0]["messages"][0]["role"] == "system"
    # No evidence -> no citations -> dropped (quality gate).
    assert generate_examples([("empty", [])], backend=None) == []


def test_gold_items_use_retrieved_relevant_evidence() -> None:
    items = gold_items(k=3)
    assert len(items) == len(QUERIES)
    # Mirrors inference: at most k retrieved items per query, not the whole corpus.
    assert all(0 < len(ev) <= 3 for _, ev in items)
    # The central-bank query retrieves the central-bank document (relevance, not dump).
    central_bank = next(ev for q, ev in items if "central bank" in q.lower())
    assert any("central bank" in e.title.lower() for e in central_bank)


def test_corpus_items_harvest_from_session(session: Session) -> None:
    session.add(Source(label="reuters.com", reliability="B"))
    session.add(
        Document(
            doc_id="reuters.com:1",
            source="reuters.com",
            title="South China Sea standoff escalates near disputed reef",
            summary="Coast guard vessels clashed near the reef.",
            credibility=3,
        )
    )
    session.flush()

    items = corpus_items(session, queries=["South China Sea tensions"], k=4)
    assert len(items) == 1
    query, evidence = items[0]
    assert query == "South China Sea tensions"
    assert evidence and evidence[0].doc_id == "reuters.com:1"
    assert evidence[0].reliability == "B"  # joined from Source


def test_corpus_items_skips_when_corpus_empty(session: Session) -> None:
    assert corpus_items(session, queries=["anything at all"]) == []


def test_write_jsonl_splits_and_writes(tmp_path: Path) -> None:
    examples = [to_chat_example(f"q{i}", "[E1] e", "body") for i in range(5)]
    stats = write_jsonl(examples, tmp_path, valid_frac=0.2)
    assert stats["train"] + stats["valid"] == 5
    assert stats["valid"] >= 1
    assert (tmp_path / "train.jsonl").exists() and (tmp_path / "valid.jsonl").exists()
    first = json.loads((tmp_path / "valid.jsonl").read_text().splitlines()[0])
    assert first["messages"][0]["role"] == "system"
