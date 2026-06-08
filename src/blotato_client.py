"""Thin Blotato MCP client over HTTPS / JSON-RPC.

Blotato exposes its 16 publishing/scheduling/asset-generation tools through
a streaming MCP server at https://mcp.blotato.com/mcp. This module wraps
just the calls AdProof actually uses:

  list_visual_templates   -- which templates are available for create_visual
  create_visual           -- generate an image / carousel / video from a
                             template + variables (used by Pillar E variants)
  get_visual_status       -- poll a generation job for completion
  create_source           -- extract the assets from a competitor URL or
                             landing page (used by Pillar F)
  get_source_status       -- poll an extraction job for completion

The Viral AI Coach is NOT exposed via this MCP (verified live with the
account's API key) — see project memory. Don't try to call it here.

Auth: the API key is read from BLOTATO_API_KEY env var. When the var is
unset, every call returns a structured "feature disabled" error so the
UI can hide the surface entirely without crashing.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any

import requests

__all__ = [
    "BlotatoUnavailable",
    "BlotatoClient",
    "is_enabled",
]


# The owner's MCP URL. Hard-coded because it's the only deployment.
_MCP_URL = "https://mcp.blotato.com/mcp"
_DEFAULT_TIMEOUT = 30


class BlotatoUnavailable(RuntimeError):
    """Raised when BLOTATO_API_KEY is missing or the MCP server is unreachable.
    Distinct exception so the FastAPI handler can return 503 (not 500) and
    the UI can render a clean "feature disabled" state rather than an error
    trace.
    """


def is_enabled() -> bool:
    """Cheap availability check for routes that want to conditionally render."""
    return bool(os.environ.get("BLOTATO_API_KEY"))


@dataclass
class BlotatoClient:
    """Stateless wrapper — one MCP-over-HTTP session per request.

    MCP requires a tiny handshake (initialize + notifications/initialized)
    before any tools/* call. We do it inline per request so the client is
    safe to use from FastAPI's request-scoped handlers; the handshake adds
    ~50ms to the first call, which is dwarfed by Blotato's own latency.
    """
    api_key: str | None = None
    timeout: int = _DEFAULT_TIMEOUT

    def __post_init__(self):
        self.api_key = self.api_key or os.environ.get("BLOTATO_API_KEY")
        if not self.api_key:
            raise BlotatoUnavailable(
                "BLOTATO_API_KEY is not set — Blotato features are disabled. "
                "Add the key to data/.secrets.json (or the Railway env) to "
                "enable variant generation and source extraction.")

    # ------------------------------------------------------------------ private

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "blotato-api-key": self.api_key or "",
        }

    def _post(self, payload: dict) -> dict | None:
        """One JSON-RPC POST. Returns the parsed result, or None for
        notifications (which don't carry a response)."""
        try:
            r = requests.post(_MCP_URL, json=payload,
                              headers=self._headers(), timeout=self.timeout)
        except requests.RequestException as exc:
            raise BlotatoUnavailable(
                f"Blotato MCP unreachable: {exc}") from exc
        # Notifications: 202 with no body.
        if r.status_code == 202 or not r.content:
            return None
        if not r.ok:
            raise BlotatoUnavailable(
                f"Blotato MCP returned HTTP {r.status_code}: {r.text[:200]}")
        try:
            body = r.json()
        except json.JSONDecodeError as exc:
            raise BlotatoUnavailable(
                f"Blotato MCP returned non-JSON: {r.text[:200]}") from exc
        if "error" in body:
            err = body["error"]
            msg = err.get("message", str(err))
            raise BlotatoUnavailable(f"Blotato MCP error: {msg}")
        return body.get("result")

    def _handshake(self) -> None:
        """Initialize + notify — required before any tools/* call."""
        self._post({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "adproof", "version": "1.0"},
            },
        })
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def _call_tool(self, name: str, arguments: dict | None = None) -> Any:
        """Invoke an MCP tool by name; returns the tool's structured result."""
        self._handshake()
        result = self._post({
            "jsonrpc": "2.0", "id": 2,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments or {}},
        })
        # MCP tools/call returns {"content": [{"type": "text", "text": "..."}], ...}
        # where the text is usually a JSON-encoded structured payload.
        if not isinstance(result, dict):
            return result
        content = result.get("content") or []
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text" and item.get("text"):
                text = item["text"]
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    return text
        # Fall through — return the raw result for diagnostic display.
        return result

    # ------------------------------------------------------------------ public

    def list_visual_templates(self) -> list[dict]:
        """List Blotato's available visual templates.

        The MCP response wraps the list under "items"; older docs called it
        "templates", so we check both for forward compat.
        """
        out = self._call_tool("blotato_list_visual_templates", {})
        if isinstance(out, dict):
            for key in ("items", "templates", "data"):
                if key in out and isinstance(out[key], list):
                    return out[key]
        if isinstance(out, list):
            return out
        return []

    def create_visual(self, template_id: str, variables: dict | None = None) -> dict:
        """Kick off a visual-generation job. Returns the job descriptor."""
        return self._call_tool("blotato_create_visual", {
            "templateId": template_id,
            "variables": variables or {},
        })

    def get_visual_status(self, visual_id: str) -> dict:
        return self._call_tool("blotato_get_visual_status",
                                {"visualId": visual_id})

    def wait_for_visual(self, visual_id: str, *,
                         poll_interval: float = 2.0,
                         timeout: float = 90.0) -> dict:
        """Poll get_visual_status until done or timeout. Returns the final
        status payload. Soft cap on total wall-clock so a wedged Blotato
        job can never hang a request indefinitely."""
        deadline = time.time() + timeout
        last: dict = {}
        while time.time() < deadline:
            last = self.get_visual_status(visual_id) or {}
            status = (last.get("status") or "").lower()
            if status in ("succeeded", "completed", "done", "failed", "error"):
                return last
            time.sleep(poll_interval)
        return last or {"status": "timeout"}

    def create_source(self, url: str | None = None,
                       text: str | None = None) -> dict:
        """Kick off a content-extraction job from a URL or raw text. Returns
        the job descriptor for polling with get_source_status."""
        args: dict = {}
        if url:
            args["url"] = url
        if text:
            args["text"] = text
        if not args:
            raise ValueError("create_source needs either url or text.")
        return self._call_tool("blotato_create_source", args)

    def get_source_status(self, source_id: str) -> dict:
        return self._call_tool("blotato_get_source_status",
                                {"sourceId": source_id})

    def wait_for_source(self, source_id: str, *,
                         poll_interval: float = 2.0,
                         timeout: float = 60.0) -> dict:
        deadline = time.time() + timeout
        last: dict = {}
        while time.time() < deadline:
            last = self.get_source_status(source_id) or {}
            status = (last.get("status") or "").lower()
            if status in ("succeeded", "completed", "done", "failed", "error"):
                return last
            time.sleep(poll_interval)
        return last or {"status": "timeout"}
