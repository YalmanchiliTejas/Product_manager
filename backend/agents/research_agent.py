"""Research sub-agent.

Performs deep research to quantify and validate claims from customer
interviews.  Searches internal project data and synthesises findings
into structured research results that feed the PRD generator.
"""

from __future__ import annotations

import json
import re

from langchain_core.messages import HumanMessage, SystemMessage

from backend.agents.state import InterviewState
from backend.services.llm import get_fast_llm, get_strong_llm


# ── Prompts ──────────────────────────────────────────────────────────────

_CLAIM_EXTRACTION_PROMPT = """\
You are a research analyst for a product management team.

Given customer interview data and a PM question, extract the key CLAIMS
that need validation.  A claim is any assertion about user needs, pain
points, market size, frequency, willingness-to-pay, or behaviour.

Return a JSON array of objects:
[
  {
    "claim": "Users want X",
    "source": "filename or interview reference",
    "confidence": "high|medium|low",
    "validation_query": "search query to validate this claim"
  }
]

Be exhaustive — extract every testable claim you can find."""


_SYNTHESIS_PROMPT = """\
You are a senior product research analyst.  Synthesise the following
research findings into a structured report.

Rules:
- Every finding must cite its source (interview filename or chunk reference).
- Quantify where possible (counts, percentages, frequency).
- Flag contradictions explicitly.
- Identify gaps where more data is needed.

Return a JSON object:
{
  "validated_claims": [
    {"claim": "...", "evidence": "...", "confidence": "high|medium|low", "source": "..."}
  ],
  "contradictions": [
    {"claim_a": "...", "claim_b": "...", "sources": ["..."]}
  ],
  "quantified_metrics": [
    {"metric": "...", "value": "...", "source": "...", "notes": "..."}
  ],
  "gaps": ["..."],
  "key_themes": ["..."],
  "summary": "2-3 paragraph executive summary"
}"""


def _extract_claims(question: str, interview_text: str) -> list[dict]:
    """Use fast LLM to extract testable claims from interviews."""
    llm = get_fast_llm()
    response = llm.invoke([
        SystemMessage(content=_CLAIM_EXTRACTION_PROMPT),
        HumanMessage(content=(
            f"PM Question: {question}\n\n"
            f"Interview Data:\n{interview_text[:12000]}"
        )),
    ])

    try:
        return json.loads(response.content)
    except (json.JSONDecodeError, TypeError):
        # Try to extract JSON from markdown code block
        match = re.search(r"```(?:json)?\s*([\s\S]*?)```", response.content)
        if match:
            try:
                return json.loads(match.group(1))
            except (json.JSONDecodeError, TypeError):
                pass
        return [{"claim": question, "source": "user", "confidence": "low",
                 "validation_query": question}]


def _search_internal_evidence(
    interview_data: list[dict],
    claims: list[dict],
) -> list[dict]:
    """Search loaded interview data for evidence supporting/contradicting claims."""
    findings: list[dict] = []

    for claim in claims:
        claim_words = set(claim.get("claim", "").lower().split())
        query_words = set(claim.get("validation_query", "").lower().split())
        search_words = claim_words | query_words

        supporting: list[dict] = []
        for doc in interview_data:
            for chunk in doc.get("chunks", []):
                chunk_words = set(chunk.lower().split())
                overlap = len(search_words & chunk_words) / max(len(search_words), 1)
                if overlap > 0.15:
                    supporting.append({
                        "source": doc.get("filename", "unknown"),
                        "content": chunk[:500],
                        "relevance": round(overlap, 3),
                    })

        supporting.sort(key=lambda x: x["relevance"], reverse=True)
        findings.append({
            "claim": claim.get("claim", ""),
            "original_source": claim.get("source", ""),
            "original_confidence": claim.get("confidence", "low"),
            "supporting_evidence": supporting[:5],
            "evidence_count": len(supporting),
        })

    return findings


def _search_db_evidence(project_id: str, claims: list[dict]) -> list[dict]:
    """Search database for additional evidence (gracefully degrades)."""
    db_findings: list[dict] = []
    try:
        from backend.services.hybrid_search import hybrid_search_chunks
        for claim in claims[:8]:
            query = claim.get("validation_query", claim.get("claim", ""))
            chunks = hybrid_search_chunks(
                project_id=project_id, query=query, match_count=4,
            )
            if chunks:
                db_findings.append({
                    "claim": claim.get("claim", ""),
                    "db_evidence": [
                        {
                            "chunk_id": c.get("chunk_id"),
                            "source_id": c.get("source_id"),
                            "content": c.get("content", "")[:400],
                            "score": c.get("combined_score", 0),
                        }
                        for c in chunks[:3]
                    ],
                })
    except Exception:
        pass  # DB not available in CLI-only mode

    return db_findings


def _synthesise_findings(
    question: str,
    claims: list[dict],
    internal_findings: list[dict],
    db_findings: list[dict],
) -> dict:
    """Use strong LLM to synthesise all research into structured output."""
    llm = get_strong_llm()

    # Build evidence text
    evidence_parts: list[str] = []
    for f in internal_findings:
        evidence_parts.append(
            f"Claim: {f['claim']}\n"
            f"Original source: {f['original_source']}\n"
            f"Evidence pieces: {f['evidence_count']}\n"
            f"Top evidence:\n" +
            "\n".join(
                f"  - [{e['source']}] (relevance {e['relevance']}): {e['content'][:200]}"
                for e in f.get("supporting_evidence", [])[:3]
            )
        )

    for f in db_findings:
        evidence_parts.append(
            f"Claim: {f['claim']}\n"
            f"Database evidence:\n" +
            "\n".join(
                f"  - [chunk {e.get('chunk_id', '?')[:8]}] (score {e.get('score', 0):.2f}): "
                f"{e.get('content', '')[:200]}"
                for e in f.get("db_evidence", [])
            )
        )

    response = llm.invoke([
        SystemMessage(content=_SYNTHESIS_PROMPT),
        HumanMessage(content=(
            f"PM Question: {question}\n\n"
            f"Research Findings:\n\n" +
            "\n\n---\n\n".join(evidence_parts)
        )),
    ])

    try:
        return json.loads(response.content)
    except (json.JSONDecodeError, TypeError):
        match = re.search(r"```(?:json)?\s*([\s\S]*?)```", response.content)
        if match:
            try:
                return json.loads(match.group(1))
            except (json.JSONDecodeError, TypeError):
                pass
        return {
            "validated_claims": [],
            "contradictions": [],
            "quantified_metrics": [],
            "gaps": ["Could not parse structured research output"],
            "key_themes": [],
            "summary": response.content,
        }


def run_research_agent(state: InterviewState) -> dict:
    """Entry point called by the orchestrator.

    Pipeline: extract claims → search internal → search DB → synthesise.

    Returns structured research results dict.
    """
    question = state["current_question"]
    interview_data = state.get("interview_data", [])
    project_id = state.get("project_id", "")

    # Build combined interview text for claim extraction
    interview_texts: list[str] = []
    for doc in interview_data:
        header = f"--- {doc.get('filename', 'unknown')} ---"
        interview_texts.append(f"{header}\n{doc.get('content', '')[:3000]}")
    combined_text = "\n\n".join(interview_texts)

    # 1. Extract claims
    claims = _extract_claims(question, combined_text)

    # 2. Search loaded interviews for evidence
    internal_findings = _search_internal_evidence(interview_data, claims)

    # 3. Search DB for additional evidence
    db_findings: list[dict] = []
    if project_id:
        db_findings = _search_db_evidence(project_id, claims)

    # 4. Synthesise everything
    research = _synthesise_findings(question, claims, internal_findings, db_findings)

    # Attach raw claims for traceability
    research["raw_claims"] = claims
    research["claim_count"] = len(claims)
    research["internal_evidence_count"] = sum(
        f["evidence_count"] for f in internal_findings
    )

    return research
