"""Text extraction and chunking utilities.

Supported input formats:
  - Plain text / markdown  (.txt, .md)
  - CSV                    (.csv)
  - PDF                    (.pdf) — requires pypdf or pdfminer.six

Extraction priority:
  1. raw_content  (string already in memory)
  2. file_bytes   (bytes uploaded via HTTP, with filename hint)
  3. file_path    (path on disk)
"""

import csv
import io
import re


# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------

def _extract_from_bytes(file_bytes: bytes, filename: str) -> str:
    """Decode bytes into plain text based on file extension."""
    name = filename.lower()

    if name.endswith((".txt", ".md")):
        return file_bytes.decode("utf-8", errors="replace")

    if name.endswith(".csv"):
        reader = csv.reader(io.StringIO(file_bytes.decode("utf-8", errors="replace")))
        rows = [" ".join(row) for row in reader]
        return "\n".join(rows)

    if name.endswith(".pdf"):
        return _extract_pdf(file_bytes)

    raise ValueError(
        f"Unsupported file type '{filename}'. "
        "Supported: .txt, .md, .csv, .pdf — or provide raw_content directly."
    )


def _extract_pdf(pdf_bytes: bytes) -> str:
    """Extract text from PDF bytes. Tries pypdf first, then pdfminer."""
    # --- pypdf (lightweight, usually pre-installed) ---
    try:
        import pypdf  # type: ignore

        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        parts = [page.extract_text() or "" for page in reader.pages]
        text = "\n".join(parts).strip()
        if text:
            return text
    except ImportError:
        pass

    # --- pdfminer.six (more accurate, heavier) ---
    try:
        from pdfminer.high_level import extract_text_to_fp  # type: ignore
        from pdfminer.layout import LAParams  # type: ignore

        output = io.StringIO()
        extract_text_to_fp(io.BytesIO(pdf_bytes), output, laparams=LAParams())
        text = output.getvalue().strip()
        if text:
            return text
    except ImportError:
        pass

    raise RuntimeError(
        "PDF extraction requires pypdf or pdfminer.six. "
        "Install with: pip install pypdf  OR  pip install pdfminer.six"
    )


def extract_text(
    raw_content: str | None = None,
    file_path: str | None = None,
    file_bytes: bytes | None = None,
    filename: str | None = None,
) -> str:
    """Return plain text from the first available source.

    Priority: raw_content → (file_bytes + filename) → file_path (disk read).

    Raises ValueError if no usable source is provided.
    """
    # 1. In-memory string content
    if raw_content and raw_content.strip():
        return raw_content

    # 2. Uploaded bytes with a filename hint
    if file_bytes and filename:
        return _extract_from_bytes(file_bytes, filename)

    # 3. Path on disk
    if file_path and file_path.strip():
        path = file_path.strip()
        with open(path, "rb") as fh:
            data = fh.read()
        hint = filename or path
        return _extract_from_bytes(data, hint)

    raise ValueError(
        "No extractable content found. "
        "Provide raw_content, (file_bytes + filename), or file_path."
    )


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

def chunk_text(
    text: str,
    chunk_size: int = 1200,
    overlap: int = 150,
) -> list[str]:
    """Split text into overlapping fixed-size character chunks.

    Mirrors the TypeScript implementation in app/src/app/lib/sourcePipeline.ts.
    """
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return []

    chunks: list[str] = []
    cursor = 0

    while cursor < len(normalized):
        end = min(cursor + chunk_size, len(normalized))
        chunks.append(normalized[cursor:end])

        if end >= len(normalized):
            break

        cursor = max(end - overlap, cursor + 1)

    return chunks
