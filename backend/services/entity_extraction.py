"""Entity extraction and linking service.

Extracts named entities (people, products, features, segments, companies, concepts)
from feedback chunks and links them across documents to build the knowledge graph.

Pipeline:
  1. For each chunk, use the fast LLM to extract entities with types
  2. Match extracted entities against existing canonical entries (fuzzy + semantic)
  3. Create new entity records or update mention counts on existing ones
  4. Store entity_mentions linking entities ↔ chunks ↔ sources
"""

import json

from langchain_core.messages import HumanMessage, SystemMessage

from backend.db.supabase_client import get_supabase
from backend.services.embeddings import create_embedding, to_pgvector_literal
from backend.services.llm import get_fast_llm
from backend.services.synthesis import _parse_json_response


_ENTITY_EXTRACTION_PROMPT = """\
You are an expert at extracting named entities from product feedback and user research.

Given a chunk of text, extract all meaningful entities. For each entity:
- canonical_name: the normalized, standard name
- entity_type: one of: person, product, feature, segment, company, concept
- mention_text: the exact text span in the source
- confidence: 0.0 to 1.0

Output ONLY valid JSON:
{
  "entities": [
    {
      "canonical_name": "string",
      "entity_type": "person|product|feature|segment|company|concept",
      "mention_text": "exact text from source",
      "confidence": 0.85
    }
  ]
}

Rules:
- Do not extract generic words like "user" or "customer" unless they name a specific segment
- Features should be specific (e.g. "dark mode", "CSV export"), not vague ("the feature")
- Concepts are abstract themes or patterns (e.g. "onboarding friction", "data portability")
- Merge slight variations: "CSV export" and "csv exporting" → "CSV Export"
- If no entities are found, return {"entities": []}"""


def _match_existing_entity(
    project_id: str,
    canonical_name: str,
    entity_type: str,
) -> dict | None:
    """Find an existing entity by exact canonical name match or alias match."""
    db = get_supabase()

    # Exact canonical name match
    resp = (
        db.table("entities")
        .select("id, canonical_name, aliases, mention_count")
        .eq("project_id", project_id)
        .eq("entity_type", entity_type)
        .ilike("canonical_name", canonical_name)
        .limit(1)
        .execute()
    )
    if resp.data:
        return resp.data[0]

    # Check aliases — use containedBy for array overlap
    resp = (
        db.table("entities")
        .select("id, canonical_name, aliases, mention_count")
        .eq("project_id", project_id)
        .eq("entity_type", entity_type)
        .contains("aliases", [canonical_name.lower()])
        .limit(1)
        .execute()
    )
    if resp.data:
        return resp.data[0]

    return None


def extract_entities_from_chunk(
    project_id: str,
    chunk_id: str,
    source_id: str,
    content: str,
) -> list[dict]:
    """Extract entities from a single chunk and persist them to the graph.

    Returns list of entity_mention records created.
    """
    if not content.strip():
        return []

    llm = get_fast_llm()
    response = llm.invoke([
        SystemMessage(content=_ENTITY_EXTRACTION_PROMPT),
        HumanMessage(content=f"Extract entities from this text:\n\n{content}"),
    ])
    parsed = _parse_json_response(response.content)
    raw_entities = parsed.get("entities", [])

    if not raw_entities:
        return []

    db = get_supabase()
    mentions_created = []

    for raw in raw_entities:
        canonical_name = raw.get("canonical_name", "").strip()
        entity_type = raw.get("entity_type", "concept")
        mention_text = raw.get("mention_text", "")
        confidence = float(raw.get("confidence", 0.8))

        if not canonical_name or entity_type not in (
            "person", "product", "feature", "segment", "company", "concept"
        ):
            continue

        # Try to match existing entity
        existing = _match_existing_entity(project_id, canonical_name, entity_type)

        if existing:
            entity_id = existing["id"]
            # Update mention count and last_seen
            db.table("entities").update({
                "mention_count": existing["mention_count"] + 1,
                "last_seen_at": "now()",
            }).eq("id", entity_id).execute()

            # Add alias if this is a new variation
            if canonical_name.lower() not in [
                a.lower() for a in (existing.get("aliases") or [])
            ] and canonical_name.lower() != existing["canonical_name"].lower():
                new_aliases = list(existing.get("aliases") or []) + [canonical_name.lower()]
                db.table("entities").update({
                    "aliases": new_aliases,
                }).eq("id", entity_id).execute()
        else:
            # Create new entity
            embedding = create_embedding(canonical_name)
            entity_resp = db.table("entities").insert({
                "project_id": project_id,
                "entity_type": entity_type,
                "canonical_name": canonical_name,
                "aliases": [canonical_name.lower()],
                "mention_count": 1,
                "embedding": to_pgvector_literal(embedding),
                "metadata": {},
            }).execute()
            entity_id = entity_resp.data[0]["id"]

        # Create mention record
        mention_resp = db.table("entity_mentions").insert({
            "entity_id": entity_id,
            "chunk_id": chunk_id,
            "source_id": source_id,
            "mention_text": mention_text[:500],
            "confidence": confidence,
        }).execute()
        if mention_resp.data:
            mentions_created.append(mention_resp.data[0])

    return mentions_created


def extract_entities_for_source(project_id: str, source_id: str) -> dict:
    """Extract entities from all chunks of a source.

    Returns: {entities_found: int, mentions_created: int}
    """
    db = get_supabase()
    chunks = (
        db.table("chunks")
        .select("id, source_id, content")
        .eq("source_id", source_id)
        .order("chunk_index")
        .execute()
        .data or []
    )

    total_mentions = 0
    for chunk in chunks:
        mentions = extract_entities_from_chunk(
            project_id=project_id,
            chunk_id=chunk["id"],
            source_id=source_id,
            content=chunk.get("content", ""),
        )
        total_mentions += len(mentions)

    # Count unique entities for this source
    entity_count_resp = (
        db.table("entity_mentions")
        .select("entity_id")
        .eq("source_id", source_id)
        .execute()
    )
    unique_entities = len(set(m["entity_id"] for m in (entity_count_resp.data or [])))

    return {
        "entities_found": unique_entities,
        "mentions_created": total_mentions,
    }


def extract_entities_for_project(project_id: str) -> dict:
    """Extract entities from all sources in a project.

    Returns: {sources_processed: int, entities_found: int, mentions_created: int}
    """
    db = get_supabase()
    sources = (
        db.table("sources")
        .select("id")
        .eq("project_id", project_id)
        .execute()
        .data or []
    )

    total_mentions = 0
    for src in sources:
        result = extract_entities_for_source(project_id, src["id"])
        total_mentions += result["mentions_created"]

    entity_count = (
        db.table("entities")
        .select("id", count="exact")
        .eq("project_id", project_id)
        .execute()
    )

    return {
        "sources_processed": len(sources),
        "entities_found": entity_count.count or 0,
        "mentions_created": total_mentions,
    }


def get_entity_graph(project_id: str, entity_type: str | None = None) -> list[dict]:
    """Fetch all entities for a project, optionally filtered by type."""
    db = get_supabase()
    query = (
        db.table("entities")
        .select("id, entity_type, canonical_name, aliases, description, "
                "first_seen_at, last_seen_at, mention_count, metadata")
        .eq("project_id", project_id)
        .order("mention_count", desc=True)
    )
    if entity_type:
        query = query.eq("entity_type", entity_type)

    return query.execute().data or []


def get_entity_connections(entity_id: str) -> dict:
    """Get all chunks and sources where this entity appears."""
    db = get_supabase()
    mentions = (
        db.table("entity_mentions")
        .select("id, chunk_id, source_id, mention_text, confidence, created_at")
        .eq("entity_id", entity_id)
        .order("created_at", desc=True)
        .execute()
        .data or []
    )

    source_ids = list(set(m["source_id"] for m in mentions))
    chunk_ids = list(set(m["chunk_id"] for m in mentions))

    return {
        "entity_id": entity_id,
        "mentions": mentions,
        "unique_sources": len(source_ids),
        "unique_chunks": len(chunk_ids),
        "source_ids": source_ids,
        "chunk_ids": chunk_ids,
    }
