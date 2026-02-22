from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx


@dataclass
class SlackMessage:
    """A single Slack message."""

    user: str
    text: str
    ts: str
    thread_ts: str | None = None
    reactions: list[str] = field(default_factory=list)


@dataclass
class SlackThread:
    """A Slack thread with all its messages."""

    channel: str
    messages: list[SlackMessage] = field(default_factory=list)

    def to_text(self) -> str:
        """Flatten thread into readable text for agent consumption."""
        lines = [f"# Slack Thread in #{self.channel}\n"]
        for msg in self.messages:
            prefix = f"**{msg.user}**"
            lines.append(f"{prefix}: {msg.text}")
            if msg.reactions:
                lines.append(f"  Reactions: {', '.join(msg.reactions)}")
        return "\n".join(lines)


class SlackClient:
    """Client for pulling context from Slack.

    Supports:
    - Fetching channel history
    - Fetching thread replies
    - Searching messages
    """

    BASE_URL = "https://slack.com/api"

    def __init__(self, token: str | None = None) -> None:
        self._token = token or os.environ.get("SLACK_BOT_TOKEN", "")
        self._http = httpx.Client(
            base_url=self.BASE_URL,
            headers={"Authorization": f"Bearer {self._token}"},
            timeout=30.0,
        )

    def _get(self, endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        resp = self._http.get(endpoint, params=params or {})
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"Slack API error: {data.get('error', 'unknown')}")
        return data

    def fetch_channel_history(
        self,
        channel_id: str,
        limit: int = 100,
        oldest: str | None = None,
    ) -> list[SlackMessage]:
        """Fetch recent messages from a channel."""
        params: dict[str, Any] = {"channel": channel_id, "limit": limit}
        if oldest:
            params["oldest"] = oldest

        data = self._get("/conversations.history", params)
        return [self._parse_message(m) for m in data.get("messages", [])]

    def fetch_thread(self, channel_id: str, thread_ts: str) -> SlackThread:
        """Fetch all replies in a thread."""
        data = self._get(
            "/conversations.replies",
            {"channel": channel_id, "ts": thread_ts, "limit": 200},
        )
        messages = [self._parse_message(m) for m in data.get("messages", [])]
        return SlackThread(channel=channel_id, messages=messages)

    def search_messages(
        self,
        query: str,
        count: int = 20,
    ) -> list[SlackMessage]:
        """Search for messages matching a query."""
        data = self._get("/search.messages", {"query": query, "count": count})
        matches = data.get("messages", {}).get("matches", [])
        return [self._parse_message(m) for m in matches]

    def fetch_context_for_agent(
        self,
        *,
        channel_ids: list[str] | None = None,
        thread_refs: list[dict[str, str]] | None = None,
        search_queries: list[str] | None = None,
        limit_per_source: int = 50,
    ) -> list[str]:
        """High-level method: gather text context from multiple Slack sources.

        Returns a list of text documents suitable for agent consumption.
        """
        documents: list[str] = []

        if channel_ids:
            for ch_id in channel_ids:
                try:
                    msgs = self.fetch_channel_history(ch_id, limit=limit_per_source)
                    thread = SlackThread(channel=ch_id, messages=msgs)
                    documents.append(thread.to_text())
                except Exception as e:
                    documents.append(f"[Error fetching channel {ch_id}: {e}]")

        if thread_refs:
            for ref in thread_refs:
                try:
                    thread = self.fetch_thread(ref["channel"], ref["thread_ts"])
                    documents.append(thread.to_text())
                except Exception as e:
                    documents.append(f"[Error fetching thread: {e}]")

        if search_queries:
            for query in search_queries:
                try:
                    msgs = self.search_messages(query, count=limit_per_source)
                    thread = SlackThread(channel="search", messages=msgs)
                    documents.append(thread.to_text())
                except Exception as e:
                    documents.append(f"[Error searching '{query}': {e}]")

        return documents

    def post_message(self, channel_id: str, text: str, thread_ts: str | None = None) -> dict[str, Any]:
        """Post a message to a channel (for distributing PRD summaries)."""
        payload: dict[str, Any] = {"channel": channel_id, "text": text}
        if thread_ts:
            payload["thread_ts"] = thread_ts

        resp = self._http.post("/chat.postMessage", json=payload)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"Slack API error: {data.get('error', 'unknown')}")
        return data

    def _parse_message(self, raw: dict[str, Any]) -> SlackMessage:
        reactions = [r["name"] for r in raw.get("reactions", [])]
        return SlackMessage(
            user=raw.get("user") or raw.get("username", "unknown"),
            text=raw.get("text", ""),
            ts=raw.get("ts", ""),
            thread_ts=raw.get("thread_ts"),
            reactions=reactions,
        )

    def close(self) -> None:
        self._http.close()
