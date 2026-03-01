"""PageIndex — LLM-reasoned hierarchical tree retrieval for interview content.

Two-phase retrieval replaces keyword-overlap chunk scoring:
  1. build_index()  — LLM builds a theme/claim tree from interview content
  2. retrieve()     — LLM navigates the tree top-down to find relevant sections

Caching strategy (two layers)
------------------------------
- Module-level in-memory dict  _CACHE: sha256(content) → PageIndexTree
- SQLite disk cache via cache_manager.get/store_llm_response(content_hash)
  (survives process restarts)

If the LLM call or parse fails at any step, safe fallbacks are used so
retrieve() always returns a list (possibly from simple keyword scoring).
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import TypedDict

from langchain_core.messages import HumanMessage


# ── Data structures ───────────────────────────────────────────────────────

class PageIndexNode(TypedDict):
    node_id: str
    title: str
    summary: str
    start_char: int
    end_char: int
    level: int           # 0 = root, 1 = theme, 2 = claim
    children: list[str]  # child node_ids


class PageIndexTree(TypedDict):
    interview_id: str
    content_hash: str
    nodes: dict[str, PageIndexNode]
    root_id: str
    built_at: str


class RetrievedSection(TypedDict):
    node_id: str
    title: str
    content: str
    relevance_reasoning: str


# ── Module-level in-memory cache ──────────────────────────────────────────

_CACHE: dict[str, PageIndexTree] = {}  # content_hash → tree


# ── Prompts ───────────────────────────────────────────────────────────────

_BUILD_TREE_PROMPT = """\
You are building a hierarchical content index for a customer interview transcript.

Create a 3-level tree:
- Level 0 (root):   ONE root node summarising the entire interview
- Level 1 (themes): 3-6 major topics / themes discussed
- Level 2 (claims): 2-5 specific, concrete claims or findings per theme

For each node provide approximate character positions (start_char, end_char)
locating that section within the original text.
Total content length: {content_length} characters.

Return ONLY a valid JSON object — no markdown fences, no commentary:
{{
  "root_id": "root",
  "nodes": {{
    "root": {{
      "node_id": "root",
      "title": "Interview Overview",
      "summary": "<2-3 sentence overview of the entire interview>",
      "start_char": 0,
      "end_char": {content_length},
      "level": 0,
      "children": ["t1", "t2"]
    }},
    "t1": {{
      "node_id": "t1",
      "title": "Theme: <descriptive name>",
      "summary": "<what this theme covers and its significance>",
      "start_char": <int>,
      "end_char": <int>,
      "level": 1,
      "children": ["c1_1", "c1_2"]
    }},
    "c1_1": {{
      "node_id": "c1_1",
      "title": "Claim: <specific, concrete assertion>",
      "summary": "<evidence and supporting detail>",
      "start_char": <int>,
      "end_char": <int>,
      "level": 2,
      "children": []
    }}
  }}
}}

Interview content to index:
{content}"""


_PICK_THEMES_PROMPT = """\
Given this interview's theme structure and a search query, pick the most relevant themes.

Search query: {query}

Available themes:
{theme_list}

Return ONLY a JSON array of node_ids (up to 3 most relevant), e.g.:
["t1", "t3"]"""


_PICK_CLAIMS_PROMPT = """\
Given this theme's claims and a search query, pick the most relevant claims to retrieve.

Search query: {query}

Theme: {theme_title}
Claims:
{claim_list}

Return ONLY a JSON array of claim node_ids (up to 3 most relevant), e.g.:
["c1_1", "c1_3"]"""


# ── JSON extraction helper ─────────────────────────────────────────────────

def _extract_json(text: str):
    """Robustly extract the first JSON value from an LLM response string."""
    text = text.strip()
    # Direct parse
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        pass
    # Markdown code block
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except (json.JSONDecodeError, ValueError):
            pass
    # First JSON object
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        try:
            return json.loads(m.group())
        except (json.JSONDecodeError, ValueError):
            pass
    # First JSON array
    m = re.search(r"\[[\s\S]*\]", text)
    if m:
        try:
            return json.loads(m.group())
        except (json.JSONDecodeError, ValueError):
            pass
    return None


# ── Fallback tree builder (no LLM needed) ────────────────────────────────

def _build_fallback_tree(interview_id: str, content: str, content_hash: str) -> PageIndexTree:
    """Split content into simple chunks as a degenerate 2-level tree."""
    chunk_size = max(1000, len(content) // 6)
    nodes: dict[str, PageIndexNode] = {}
    theme_ids: list[str] = []

    for i in range(0, len(content), chunk_size):
        end = min(len(content), i + chunk_size)
        tid = f"t{len(theme_ids) + 1}"
        snippet = content[i:i + 80].replace("\n", " ")
        nodes[tid] = PageIndexNode(
            node_id=tid,
            title=f"Section {len(theme_ids) + 1}: {snippet}...",
            summary=snippet,
            start_char=i,
            end_char=end,
            level=1,
            children=[],
        )
        theme_ids.append(tid)
        if len(theme_ids) >= 6:
            break

    nodes["root"] = PageIndexNode(
        node_id="root",
        title="Interview Overview",
        summary=content[:200].replace("\n", " "),
        start_char=0,
        end_char=len(content),
        level=0,
        children=theme_ids,
    )

    return PageIndexTree(
        interview_id=interview_id,
        content_hash=content_hash,
        nodes=nodes,
        root_id="root",
        built_at=datetime.now(timezone.utc).isoformat(),
    )


# ── Public API ────────────────────────────────────────────────────────────

def build_index(interview_id: str, content: str, llm) -> PageIndexTree:
    """Build (or return cached) a PageIndexTree for the given interview.

    Two-level cache: module _CACHE (in-memory) + SQLite via cache_manager.
    Falls back to a simple chunk-based tree if the LLM call fails.
    """
    if not content.strip():
        return _build_fallback_tree(interview_id, content, "empty")

    content_hash = hashlib.sha256(content.encode()).hexdigest()

    # 1. In-memory cache hit
    if content_hash in _CACHE:
        return _CACHE[content_hash]

    # 2. Disk cache hit
    from backend.services import cache_manager
    cached_str = cache_manager.get_llm_response(content_hash)
    if cached_str:
        try:
            data = json.loads(cached_str)
            tree = PageIndexTree(**data)
            _CACHE[content_hash] = tree
            return tree
        except Exception:
            pass  # corrupt cache entry — rebuild

    # 3. Build via LLM
    prompt = _BUILD_TREE_PROMPT.format(
        content_length=len(content),
        content=content[:40000],
    )
    try:
        response = llm.invoke([HumanMessage(content=prompt)])
        raw = response.content if isinstance(response.content, str) else str(response.content)
        parsed = _extract_json(raw)

        if parsed and isinstance(parsed, dict) and "nodes" in parsed:
            content_len = len(content)
            nodes: dict[str, PageIndexNode] = {}
            for nid, ndata in parsed.get("nodes", {}).items():
                start = max(0, int(ndata.get("start_char", 0)))
                end = min(content_len, int(ndata.get("end_char", content_len)))
                if end <= start:
                    end = min(content_len, start + 2000)
                nodes[nid] = PageIndexNode(
                    node_id=nid,
                    title=str(ndata.get("title", nid)),
                    summary=str(ndata.get("summary", "")),
                    start_char=start,
                    end_char=end,
                    level=int(ndata.get("level", 1)),
                    children=[str(c) for c in ndata.get("children", [])],
                )

            tree = PageIndexTree(
                interview_id=interview_id,
                content_hash=content_hash,
                nodes=nodes,
                root_id=str(parsed.get("root_id", "root")),
                built_at=datetime.now(timezone.utc).isoformat(),
            )
            _CACHE[content_hash] = tree
            cache_manager.store_llm_response(content_hash, json.dumps(dict(tree)))
            return tree
    except Exception:
        pass  # LLM call failed — use fallback

    # 4. Fallback
    tree = _build_fallback_tree(interview_id, content, content_hash)
    _CACHE[content_hash] = tree
    return tree


def retrieve(
    tree: PageIndexTree,
    query: str,
    content: str,
    llm,
    max_sections: int = 4,
) -> list[RetrievedSection]:
    """Navigate the tree to find sections most relevant to the query.

    Two-phase LLM navigation:
      Phase 1: LLM picks relevant level-1 themes from compact headers.
      Phase 2: For each theme, LLM picks relevant level-2 claims.

    Returns up to max_sections RetrievedSection objects with sliced content.
    Falls back to keyword scoring if the LLM calls fail.
    """
    nodes = tree.get("nodes", {})
    if not nodes:
        return []

    # ── Phase 1: pick relevant themes ────────────────────────────────────
    level1_nodes = [n for n in nodes.values() if n.get("level") == 1]
    if not level1_nodes:
        # Flat tree — return all nodes as sections
        return _nodes_to_sections(level1_nodes or list(nodes.values()), content, query, max_sections)

    theme_list = "\n".join(
        f"- {n['node_id']}: {n['title']} — {n['summary'][:100]}"
        for n in level1_nodes
    )
    chosen_theme_ids: list[str] = []
    try:
        resp = llm.invoke([HumanMessage(content=_PICK_THEMES_PROMPT.format(
            query=query,
            theme_list=theme_list,
        ))])
        raw = resp.content if isinstance(resp.content, str) else str(resp.content)
        parsed = _extract_json(raw)
        if isinstance(parsed, list):
            chosen_theme_ids = [str(x) for x in parsed if str(x) in nodes]
    except Exception:
        pass

    if not chosen_theme_ids:
        # Fallback: keyword-scored themes
        chosen_theme_ids = _keyword_score_nodes(level1_nodes, query)[:3]

    # ── Phase 2: for each theme, pick relevant claims ─────────────────────
    selected_node_ids: list[str] = []
    for tid in chosen_theme_ids[:3]:
        theme_node = nodes.get(tid)
        if not theme_node:
            continue
        child_ids = theme_node.get("children", [])
        child_nodes = [nodes[c] for c in child_ids if c in nodes]

        if not child_nodes:
            # Theme has no children — include the theme itself
            selected_node_ids.append(tid)
            continue

        claim_list = "\n".join(
            f"- {n['node_id']}: {n['title']} — {n['summary'][:100]}"
            for n in child_nodes
        )
        chosen_claims: list[str] = []
        try:
            resp = llm.invoke([HumanMessage(content=_PICK_CLAIMS_PROMPT.format(
                query=query,
                theme_title=theme_node.get("title", tid),
                claim_list=claim_list,
            ))])
            raw = resp.content if isinstance(resp.content, str) else str(resp.content)
            parsed = _extract_json(raw)
            if isinstance(parsed, list):
                chosen_claims = [str(x) for x in parsed if str(x) in nodes]
        except Exception:
            pass

        if chosen_claims:
            selected_node_ids.extend(chosen_claims)
        else:
            # Fallback: keyword-scored claims
            selected_node_ids.extend(_keyword_score_nodes(child_nodes, query)[:2])

    # ── Build RetrievedSection objects ────────────────────────────────────
    seen: set[str] = set()
    results: list[RetrievedSection] = []
    for nid in selected_node_ids:
        if nid in seen or nid not in nodes:
            continue
        seen.add(nid)
        node = nodes[nid]
        start = max(0, node.get("start_char", 0))
        end = min(len(content), node.get("end_char", len(content)))
        if end <= start:
            end = min(len(content), start + 2000)
        results.append(RetrievedSection(
            node_id=nid,
            title=node.get("title", nid),
            content=content[start:end],
            relevance_reasoning=node.get("summary", ""),
        ))
        if len(results) >= max_sections:
            break

    return results


# ── Internal helpers ──────────────────────────────────────────────────────

def _keyword_score_nodes(nodes: list[PageIndexNode], query: str) -> list[str]:
    """Return node_ids sorted by keyword overlap with query."""
    query_words = set(query.lower().split())
    scored: list[tuple[float, str]] = []
    for n in nodes:
        text = f"{n.get('title', '')} {n.get('summary', '')}".lower()
        words = set(text.split())
        overlap = len(query_words & words) / max(len(query_words), 1)
        scored.append((overlap, n["node_id"]))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [nid for _, nid in scored]


def _nodes_to_sections(
    nodes: list[PageIndexNode],
    content: str,
    query: str,
    max_sections: int,
) -> list[RetrievedSection]:
    """Convert a node list directly into RetrievedSection objects."""
    scored_ids = _keyword_score_nodes(nodes, query)
    results: list[RetrievedSection] = []
    for nid in scored_ids[:max_sections]:
        node = next((n for n in nodes if n["node_id"] == nid), None)
        if not node:
            continue
        start = max(0, node.get("start_char", 0))
        end = min(len(content), node.get("end_char", len(content)))
        if end <= start:
            end = min(len(content), start + 2000)
        results.append(RetrievedSection(
            node_id=nid,
            title=node.get("title", nid),
            content=content[start:end],
            relevance_reasoning=node.get("summary", ""),
        ))
    return results
