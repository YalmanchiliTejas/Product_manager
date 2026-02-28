"""Index-memory builder for always-on compact context."""

from backend.db.supabase_client import get_supabase


INDEX_MAX_CHARS = 2200


def rebuild_index_memory(project_id: str) -> str:
    db = get_supabase()
    rows = (
        db.table("memory_items")
        .select("id, type, title, content, tags, effective_from")
        .eq("project_id", project_id)
        .is_("effective_to", "null")
        .in_("type", ["constraint", "decision", "metric", "persona", "snapshot"])
        .order("effective_from", desc=True)
        .limit(50)
        .execute()
        .data
        or []
    )

    grouped: dict[str, list[dict]] = {"constraint": [], "decision": [], "metric": [], "persona": [], "snapshot": []}
    for r in rows:
        grouped.setdefault(r["type"], []).append(r)

    lines = ["PM Memory Index (pointer-style; load topic memory on demand):"]
    for t in ["constraint", "decision", "metric", "persona"]:
        lines.append(f"- {t}s:")
        for item in grouped.get(t, [])[:5]:
            lines.append(f"  - {item['title']} (id={item['id']})")

    if grouped.get("snapshot"):
        snap = grouped["snapshot"][0]
        lines.append(f"- latest_snapshot: {snap['title']} (id={snap['id']})")

    content = "\n".join(lines)[:INDEX_MAX_CHARS]

    current = (
        db.table("memory_items")
        .select("id")
        .eq("project_id", project_id)
        .eq("type", "index")
        .is_("effective_to", "null")
        .limit(1)
        .execute()
        .data
        or []
    )

    if current:
        idx_id = current[0]["id"]
        db.table("memory_items").update({"title": "Always-on Memory Index", "content": content}).eq("id", idx_id).execute()
        return idx_id

    created = (
        db.table("memory_items")
        .insert({
            "project_id": project_id,
            "type": "index",
            "title": "Always-on Memory Index",
            "content": content,
            "authority": 10,
            "metadata": {"style": "pointer"},
        })
        .execute()
    )
    return created.data[0]["id"]
