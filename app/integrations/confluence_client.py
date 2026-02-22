from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx


@dataclass
class ConfluencePage:
    """A Confluence page with its content."""

    page_id: str
    title: str
    space_key: str
    body_text: str
    version: int = 1
    labels: list[str] = field(default_factory=list)
    ancestors: list[str] = field(default_factory=list)

    def to_text(self) -> str:
        """Convert page to readable text for agent consumption."""
        lines = [
            f"# {self.title}",
            f"Space: {self.space_key} | Version: {self.version}",
        ]
        if self.labels:
            lines.append(f"Labels: {', '.join(self.labels)}")
        lines.append(f"\n{self.body_text}")
        return "\n".join(lines)


class ConfluenceClient:
    """Client for pulling context from Confluence Cloud.

    Supports:
    - Fetching page content (with HTML-to-text conversion)
    - Searching pages via CQL
    - Fetching pages by space and label
    - Creating/updating pages (for PRD distribution)
    """

    def __init__(
        self,
        base_url: str | None = None,
        email: str | None = None,
        api_token: str | None = None,
    ) -> None:
        self._base_url = (
            base_url or os.environ.get("CONFLUENCE_BASE_URL", "")
        ).rstrip("/")
        self._email = email or os.environ.get("CONFLUENCE_EMAIL", "")
        self._token = api_token or os.environ.get("CONFLUENCE_API_TOKEN", "")
        self._http = httpx.Client(
            base_url=f"{self._base_url}/wiki/api/v2" if self._base_url else "",
            auth=(self._email, self._token) if self._email and self._token else None,
            timeout=30.0,
        )
        # V1 API client for operations that need it
        self._http_v1 = httpx.Client(
            base_url=f"{self._base_url}/wiki/rest/api" if self._base_url else "",
            auth=(self._email, self._token) if self._email and self._token else None,
            timeout=30.0,
        )

    def fetch_page(self, page_id: str) -> ConfluencePage:
        """Fetch a single page by ID with its body content."""
        resp = self._http.get(
            f"/pages/{page_id}",
            params={"body-format": "storage"},
        )
        resp.raise_for_status()
        data = resp.json()
        return self._parse_page(data)

    def search_pages(self, query: str, space_key: str | None = None, limit: int = 10) -> list[ConfluencePage]:
        """Search Confluence using CQL."""
        cql = f'text ~ "{query}"'
        if space_key:
            cql += f' AND space = "{space_key}"'

        resp = self._http_v1.get(
            "/content/search",
            params={
                "cql": cql,
                "limit": limit,
                "expand": "body.storage,version,metadata.labels",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return [self._parse_page_v1(r) for r in data.get("results", [])]

    def fetch_space_pages(
        self,
        space_key: str,
        limit: int = 25,
        label: str | None = None,
    ) -> list[ConfluencePage]:
        """Fetch pages from a space, optionally filtered by label."""
        cql = f'space = "{space_key}" AND type = "page"'
        if label:
            cql += f' AND label = "{label}"'
        cql += " ORDER BY lastModified DESC"

        resp = self._http_v1.get(
            "/content/search",
            params={
                "cql": cql,
                "limit": limit,
                "expand": "body.storage,version,metadata.labels",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return [self._parse_page_v1(r) for r in data.get("results", [])]

    def fetch_context_for_agent(
        self,
        *,
        page_ids: list[str] | None = None,
        search_queries: list[str] | None = None,
        space_keys: list[str] | None = None,
        labels: list[str] | None = None,
        limit_per_source: int = 10,
    ) -> list[str]:
        """High-level method: gather text context from multiple Confluence sources.

        Returns a list of text documents suitable for agent consumption.
        """
        documents: list[str] = []

        if page_ids:
            for pid in page_ids:
                try:
                    page = self.fetch_page(pid)
                    documents.append(page.to_text())
                except Exception as e:
                    documents.append(f"[Error fetching page {pid}: {e}]")

        if search_queries:
            for query in search_queries:
                try:
                    pages = self.search_pages(query, limit=limit_per_source)
                    for page in pages:
                        documents.append(page.to_text())
                except Exception as e:
                    documents.append(f"[Error searching '{query}': {e}]")

        if space_keys:
            for space in space_keys:
                try:
                    label = labels[0] if labels else None
                    pages = self.fetch_space_pages(space, limit=limit_per_source, label=label)
                    for page in pages:
                        documents.append(page.to_text())
                except Exception as e:
                    documents.append(f"[Error fetching space {space}: {e}]")

        return documents

    def create_page(
        self,
        space_key: str,
        title: str,
        body_html: str,
        parent_id: str | None = None,
    ) -> ConfluencePage:
        """Create a new Confluence page (for PRD distribution)."""
        payload: dict[str, Any] = {
            "type": "page",
            "title": title,
            "space": {"key": space_key},
            "body": {
                "storage": {
                    "value": body_html,
                    "representation": "storage",
                }
            },
        }
        if parent_id:
            payload["ancestors"] = [{"id": parent_id}]

        resp = self._http_v1.post("/content", json=payload)
        resp.raise_for_status()
        return self._parse_page_v1(resp.json())

    def _parse_page(self, data: dict[str, Any]) -> ConfluencePage:
        """Parse V2 API page response."""
        body_raw = data.get("body", {}).get("storage", {}).get("value", "")
        body_text = self._html_to_text(body_raw)
        labels_data = data.get("labels", {}).get("results", [])
        labels = [l.get("name", "") for l in labels_data] if isinstance(labels_data, list) else []

        return ConfluencePage(
            page_id=str(data.get("id", "")),
            title=data.get("title", ""),
            space_key=data.get("spaceId", ""),
            body_text=body_text,
            version=data.get("version", {}).get("number", 1) if isinstance(data.get("version"), dict) else 1,
            labels=labels,
        )

    def _parse_page_v1(self, data: dict[str, Any]) -> ConfluencePage:
        """Parse V1 API page response."""
        body_raw = data.get("body", {}).get("storage", {}).get("value", "")
        body_text = self._html_to_text(body_raw)
        labels_meta = data.get("metadata", {}).get("labels", {}).get("results", [])
        labels = [l.get("name", "") for l in labels_meta] if isinstance(labels_meta, list) else []

        return ConfluencePage(
            page_id=str(data.get("id", "")),
            title=data.get("title", ""),
            space_key=data.get("space", {}).get("key", "") if isinstance(data.get("space"), dict) else "",
            body_text=body_text,
            version=data.get("version", {}).get("number", 1) if isinstance(data.get("version"), dict) else 1,
            labels=labels,
        )

    @staticmethod
    def _html_to_text(html: str) -> str:
        """Simple HTML to plain text conversion for Confluence storage format."""
        if not html:
            return ""
        # Replace common block elements with newlines
        text = re.sub(r"<br\s*/?>", "\n", html)
        text = re.sub(r"</?(p|div|h[1-6]|li|tr|blockquote)[^>]*>", "\n", text)
        text = re.sub(r"</?ul[^>]*>", "\n", text)
        text = re.sub(r"</?ol[^>]*>", "\n", text)
        # Extract link text
        text = re.sub(r'<a[^>]*>([^<]*)</a>', r'\1', text)
        # Strip remaining tags
        text = re.sub(r"<[^>]+>", "", text)
        # Clean up whitespace
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def close(self) -> None:
        self._http.close()
        self._http_v1.close()
