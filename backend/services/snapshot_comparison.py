"""Snapshot comparison engine.

Compares two memory snapshots (weekly point-in-time captures) to detect:
  - New items that appeared since the baseline
  - Removed items no longer active
  - Changed items (same title/type but different content)

Produces a structured diff stored in snapshot_comparisons table.
"""

import json
from datetime import datetime, timezone

from backend.db.supabase_client import get_supabase


def _parse_snapshot_items(snapshot_content: str) -> list[dict]:
    """Extract the items list from a snapshot's JSON content."""
    try:
        body = json.loads(snapshot_content)
        return body.get("items", [])
    except (json.JSONDecodeError, TypeError):
        return []


def _parse_snapshot_counts(snapshot_content: str) -> dict:
    """Extract the counts dict from a snapshot's JSON content."""
    try:
        body = json.loads(snapshot_content)
        return body.get("counts", {})
    except (json.JSONDecodeError, TypeError):
        return {}


def compare_snapshots(
    project_id: str,
    baseline_snapshot_id: str,
    current_snapshot_id: str,
) -> dict:
    """Compare two memory snapshots and store the diff.

    Args:
        project_id: Project UUID.
        baseline_snapshot_id: The older snapshot (memory_items.id where type='snapshot').
        current_snapshot_id: The newer snapshot.

    Returns:
        The snapshot_comparisons record with new/removed/changed items and summary.
    """
    db = get_supabase()

    # Fetch both snapshots
    baseline_resp = (
        db.table("memory_items")
        .select("id, title, content, effective_from")
        .eq("id", baseline_snapshot_id)
        .single()
        .execute()
    )
    current_resp = (
        db.table("memory_items")
        .select("id, title, content, effective_from")
        .eq("id", current_snapshot_id)
        .single()
        .execute()
    )

    baseline = baseline_resp.data
    current = current_resp.data

    if not baseline or not current:
        raise ValueError("One or both snapshots not found.")

    baseline_items = _parse_snapshot_items(baseline["content"])
    current_items = _parse_snapshot_items(current["content"])
    baseline_counts = _parse_snapshot_counts(baseline["content"])
    current_counts = _parse_snapshot_counts(current["content"])

    # Index by (type, title) for matching
    baseline_index = {(i["type"], i["title"]): i for i in baseline_items}
    current_index = {(i["type"], i["title"]): i for i in current_items}

    baseline_keys = set(baseline_index.keys())
    current_keys = set(current_index.keys())

    new_items = [
        {"type": k[0], "title": k[1], "id": current_index[k].get("id")}
        for k in (current_keys - baseline_keys)
    ]
    removed_items = [
        {"type": k[0], "title": k[1], "id": baseline_index[k].get("id")}
        for k in (baseline_keys - current_keys)
    ]

    # For items in both, check if they changed (different id = superseded)
    changed_items = []
    for k in (baseline_keys & current_keys):
        b_item = baseline_index[k]
        c_item = current_index[k]
        if b_item.get("id") != c_item.get("id"):
            changed_items.append({
                "type": k[0],
                "title": k[1],
                "baseline_id": b_item.get("id"),
                "current_id": c_item.get("id"),
            })

    # Build summary
    count_changes = []
    all_types = set(list(baseline_counts.keys()) + list(current_counts.keys()))
    for t in sorted(all_types):
        b_count = baseline_counts.get(t, 0)
        c_count = current_counts.get(t, 0)
        if b_count != c_count:
            delta = c_count - b_count
            sign = "+" if delta > 0 else ""
            count_changes.append(f"{t}: {b_count} → {c_count} ({sign}{delta})")

    summary_parts = []
    if new_items:
        summary_parts.append(f"{len(new_items)} new items appeared")
    if removed_items:
        summary_parts.append(f"{len(removed_items)} items removed")
    if changed_items:
        summary_parts.append(f"{len(changed_items)} items changed")
    if count_changes:
        summary_parts.append("Count changes: " + "; ".join(count_changes))
    if not summary_parts:
        summary_parts.append("No changes detected between snapshots")

    summary = ". ".join(summary_parts) + "."

    # Persist comparison
    comp_resp = db.table("snapshot_comparisons").insert({
        "project_id": project_id,
        "baseline_snapshot_id": baseline_snapshot_id,
        "current_snapshot_id": current_snapshot_id,
        "new_items": new_items,
        "removed_items": removed_items,
        "changed_items": changed_items,
        "summary": summary,
    }).execute()

    return comp_resp.data[0] if comp_resp.data else {
        "new_items": new_items,
        "removed_items": removed_items,
        "changed_items": changed_items,
        "summary": summary,
    }


def get_latest_snapshots(project_id: str, limit: int = 10) -> list[dict]:
    """Get the most recent memory snapshots for a project."""
    db = get_supabase()
    resp = (
        db.table("memory_items")
        .select("id, title, content, effective_from, created_at")
        .eq("project_id", project_id)
        .eq("type", "snapshot")
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    snapshots = []
    for row in (resp.data or []):
        counts = _parse_snapshot_counts(row["content"])
        snapshots.append({
            "id": row["id"],
            "title": row["title"],
            "created_at": row["created_at"],
            "counts": counts,
        })
    return snapshots


def compare_latest_snapshots(project_id: str) -> dict | None:
    """Compare the two most recent snapshots automatically.

    Returns the comparison result or None if fewer than 2 snapshots exist.
    """
    snapshots = get_latest_snapshots(project_id, limit=2)
    if len(snapshots) < 2:
        return None

    current = snapshots[0]
    baseline = snapshots[1]

    return compare_snapshots(
        project_id=project_id,
        baseline_snapshot_id=baseline["id"],
        current_snapshot_id=current["id"],
    )
