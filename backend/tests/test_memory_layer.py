from backend.services.memory_validations import (
    decision_consistency_from_rows,
    estimate_pack_tokens,
    evidence_integrity_from_rows,
    prd_has_required_sections,
)


def test_evidence_integrity_gate():
    memory_rows = [{"id": "m1", "evidence_chunk_ids": ["c1", "c2"]}]
    chunk_rows = [{"id": "c1"}, {"id": "c2"}, {"id": "c3"}]
    assert evidence_integrity_from_rows(memory_rows, chunk_rows)
    assert not evidence_integrity_from_rows(memory_rows, [{"id": "c1"}])


def test_decision_consistency_gate():
    consistent = [
        {"type": "decision", "title": "Pricing model", "content": "Use seat-based pricing", "supersedes_id": None},
        {"type": "constraint", "title": "Data retention", "content": "Retain for 30 days", "supersedes_id": None},
    ]
    conflict = [
        {"type": "decision", "title": "Pricing model", "content": "Use seat-based pricing", "supersedes_id": None},
        {"type": "decision", "title": "Pricing model", "content": "Use usage-based pricing", "supersedes_id": None},
    ]
    assert decision_consistency_from_rows(consistent)
    assert not decision_consistency_from_rows(conflict)


def test_context_pack_budget_estimator():
    pack = {
        "index": "short index",
        "memory_items": [{"id": "m1", "content": "x" * 120}],
        "evidence_chunks": [{"chunk_id": "c1", "content": "y" * 400}],
        "citations": {"memory_item_ids": ["m1"], "chunk_ids": ["c1"]},
    }
    assert estimate_pack_tokens(pack) > 0
    assert estimate_pack_tokens(pack) <= 2500


def test_prd_regression_required_sections_and_citations():
    prd_text = """
    # PRD
    ## Constraints
    Must support additive migrations only.

    ## Success Metrics
    Retrieval latency under 500ms.

    ## Risks
    Memory drift across quarters.
    """
    assert prd_has_required_sections(prd_text, ["chunk-1"])
    assert not prd_has_required_sections("missing sections", ["chunk-1"])
    assert not prd_has_required_sections(prd_text, [])
