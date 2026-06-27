from argus.nlp.extract import entity_id, extract_entities


def test_heuristic_extracts_capitalized_spans() -> None:
    ents = extract_entities("Alpha Command attacked Beta Province today.", backend="heuristic")
    names = [name for name, _ in ents]
    assert any("Alpha Command" in n for n in names)
    assert any("Beta Province" in n for n in names)


def test_heuristic_skips_sentence_initial_stopword() -> None:
    ents = extract_entities("The market fell sharply.", backend="heuristic")
    assert all(not n.startswith("The") for n, _ in ents)


def test_entity_id_is_normalized_and_type_sensitive() -> None:
    assert entity_id("Reuters", "ORG") == entity_id("  reuters ", "ORG")
    assert entity_id("Reuters", "ORG") != entity_id("Reuters", "GPE")


def test_empty_text_returns_no_entities() -> None:
    assert extract_entities("   ") == []
