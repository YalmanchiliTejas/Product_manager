"""Document parser tool for the interview agent.

Reads a folder of customer interview files (.txt, .md, .csv, .pdf, .json)
and returns structured interview data ready for the orchestrator.

Also supports parsing individual files and extracting structured metadata
(speaker turns, timestamps, sentiment cues) from interview transcripts.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from backend.services.file_processing import extract_text, chunk_text


# ── Supported extensions ─────────────────────────────────────────────────

_SUPPORTED_EXTENSIONS = {".txt", ".md", ".csv", ".pdf", ".json"}


def _is_supported(path: Path) -> bool:
    return path.suffix.lower() in _SUPPORTED_EXTENSIONS


# ── Single-file parsing ──────────────────────────────────────────────────

def parse_interview_file(file_path: str) -> dict:
    """Parse a single interview / feedback file into structured data.

    Returns:
        {
            "filename": str,
            "file_path": str,
            "content": str,             # full extracted text
            "chunks": [str, ...],       # chunked for embedding/search
            "metadata": {
                "word_count": int,
                "speaker_count": int,    # detected speakers (if transcript)
                "speakers": [str, ...],
                "has_timestamps": bool,
            },
        }
    """
    p = Path(file_path)

    if p.suffix.lower() == ".json":
        content = _parse_json_file(p)
    else:
        content = extract_text(file_path=str(p))

    speakers = _detect_speakers(content)
    chunks = chunk_text(content, chunk_size=1200, overlap=150)

    return {
        "filename": p.name,
        "file_path": str(p.resolve()),
        "content": content,
        "chunks": chunks,
        "metadata": {
            "word_count": len(content.split()),
            "speaker_count": len(speakers),
            "speakers": speakers,
            "has_timestamps": _has_timestamps(content),
        },
    }


def _parse_json_file(path: Path) -> str:
    """Parse JSON interview files — handles arrays of objects or single objects."""
    raw = path.read_text(encoding="utf-8")
    data = json.loads(raw)

    if isinstance(data, list):
        parts = []
        for item in data:
            if isinstance(item, dict):
                parts.append(_dict_to_text(item))
            else:
                parts.append(str(item))
        return "\n\n---\n\n".join(parts)

    if isinstance(data, dict):
        return _dict_to_text(data)

    return str(data)


def _dict_to_text(d: dict) -> str:
    """Flatten a dict into readable text, preserving key structure."""
    lines = []
    for key, value in d.items():
        if isinstance(value, list):
            value = "\n  ".join(str(v) for v in value)
        lines.append(f"{key}: {value}")
    return "\n".join(lines)


def _detect_speakers(text: str) -> list[str]:
    """Detect speaker labels in transcript-style text.

    Recognises patterns like:
      - "Speaker A:" or "Interviewer:" (colon-delimited)
      - "[John]" (bracketed)
      - "Q:" / "A:" (Q&A format)
    """
    patterns = [
        r"^([A-Z][a-zA-Z\s]{0,30}):\s",          # Name: text
        r"^\[([A-Za-z\s]+)\]\s",                   # [Name] text
        r"^(Q|A|Interviewer|Interviewee|PM|User|Customer):",  # Common roles
    ]
    speakers: set[str] = set()
    for line in text.splitlines():
        line = line.strip()
        for pattern in patterns:
            m = re.match(pattern, line)
            if m:
                speakers.add(m.group(1).strip())
                break
    return sorted(speakers)


def _has_timestamps(text: str) -> bool:
    """Check if the text contains timestamp markers."""
    # HH:MM:SS or MM:SS or [00:00] style
    return bool(re.search(r"\b\d{1,2}:\d{2}(?::\d{2})?\b", text))


# ── Folder ingestion ─────────────────────────────────────────────────────

def parse_interview_folder(folder_path: str) -> list[dict]:
    """Recursively parse all supported files in a folder.

    Returns a list of parsed interview dicts (same shape as parse_interview_file).
    Skips hidden files and unsupported extensions.
    """
    folder = Path(folder_path)
    if not folder.is_dir():
        raise FileNotFoundError(f"Folder not found: {folder_path}")

    results: list[dict] = []
    files = sorted(f for f in folder.rglob("*") if f.is_file() and _is_supported(f))

    if not files:
        raise ValueError(
            f"No supported files found in {folder_path}. "
            f"Supported: {', '.join(sorted(_SUPPORTED_EXTENSIONS))}"
        )

    for file_path in files:
        # Skip hidden files
        if any(part.startswith(".") for part in file_path.parts):
            continue
        try:
            parsed = parse_interview_file(str(file_path))
            results.append(parsed)
        except Exception as e:
            # Log but don't fail the whole batch
            results.append({
                "filename": file_path.name,
                "file_path": str(file_path.resolve()),
                "content": "",
                "chunks": [],
                "metadata": {"error": str(e)},
            })

    return results


def summarize_parsed_interviews(interviews: list[dict]) -> str:
    """Build a human-readable summary of parsed interviews for display."""
    lines = [f"Parsed {len(interviews)} interview file(s):\n"]
    total_words = 0
    total_chunks = 0
    for i, doc in enumerate(interviews, 1):
        meta = doc.get("metadata", {})
        wc = meta.get("word_count", 0)
        sc = meta.get("speaker_count", 0)
        nc = len(doc.get("chunks", []))
        total_words += wc
        total_chunks += nc
        err = meta.get("error")
        if err:
            lines.append(f"  {i}. {doc['filename']} — ERROR: {err}")
        else:
            speaker_info = f", {sc} speaker(s)" if sc > 0 else ""
            lines.append(f"  {i}. {doc['filename']} — {wc:,} words, {nc} chunks{speaker_info}")

    lines.append(f"\nTotal: {total_words:,} words, {total_chunks} chunks")
    return "\n".join(lines)
