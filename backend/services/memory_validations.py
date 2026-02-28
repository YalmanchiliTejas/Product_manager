"""Validation gates for memory/context pack regressions."""

from backend.db.supabase_client import get_supabase


def evidence_integrity_from_rows(memory_rows: list[dict], chunk_rows: list[dict]) -> bool:
    chunk_ids = {row["id"] for row in chunk_rows}
    for row in memory_rows:
        for cid in row.get("evidence_chunk_ids") or []:
            if cid not in chunk_ids:
                return False
    return True


def validate_evidence_integrity(project_id: str) -> bool:
    db = get_supabase()
    memory_rows = (
        db.table("memory_items")
        .select("id, evidence_chunk_ids")
        .eq("project_id", project_id)
        .execute()
        .data
        or []
    )
    chunk_rows = db.table("chunks").select("id").execute().data or []
    return evidence_integrity_from_rows(memory_rows, chunk_rows)


def decision_consistency_from_rows(rows: list[dict]) -> bool:
    seen: dict[tuple[str, str], dict] = {}
    for row in rows:
        key = (row["type"], row["title"].strip().lower())
        if key not in seen:
            seen[key] = row
            continue
        if row["content"].strip() != seen[key]["content"].strip() and not row.get("supersedes_id") and not seen[key].get("supersedes_id"):
            return False
    return True


def validate_decision_consistency(project_id: str) -> bool:
    db = get_supabase()
    rows = (
        db.table("memory_items")
        .select("id, type, title, content, supersedes_id")
        .eq("project_id", project_id)
        .is_("effective_to", "null")
        .in_("type", ["decision", "constraint"])
        .execute()
        .data
        or []
    )
    return decision_consistency_from_rows(rows)


def estimate_pack_tokens(pack: dict) -> int:
    return max(1, len(str(pack)) // 4)


def prd_has_required_sections(prd_text: str, cited_chunk_ids: list[str]) -> bool:
    required = ["constraints", "success metrics", "risks"]
    lower = prd_text.lower()
    return all(r in lower for r in required) and len(cited_chunk_ids) > 0
