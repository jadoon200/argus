import json
from pathlib import Path

from argus.finetune.dataset import generate_examples, gold_items, to_chat_example, write_jsonl


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


def test_write_jsonl_splits_and_writes(tmp_path: Path) -> None:
    examples = [to_chat_example(f"q{i}", "[E1] e", "body") for i in range(5)]
    stats = write_jsonl(examples, tmp_path, valid_frac=0.2)
    assert stats["train"] + stats["valid"] == 5
    assert stats["valid"] >= 1
    assert (tmp_path / "train.jsonl").exists() and (tmp_path / "valid.jsonl").exists()
    first = json.loads((tmp_path / "valid.jsonl").read_text().splitlines()[0])
    assert first["messages"][0]["role"] == "system"
