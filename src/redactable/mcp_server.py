"""Redactable MCP server — drop-in PII scrubbing for any MCP-aware agent.

Exposes three tools over stdio:
  • scrub(text, policy, reversible)  -> redacted text + a session id (to restore later)
  • restore(text, session)           -> originals put back into a scrubbed text
  • detect(text, policy)             -> what PII is present, without modifying anything

Add it (Claude Code, Cursor, etc.):
    claude mcp add redactable -- redactable-mcp
or in .mcp.json:
    { "mcpServers": { "redactable": { "command": "redactable-mcp" } } }

Needs the optional extra:  pip install "redactable[mcp]"
"""

from __future__ import annotations

from redactable.service import RedactionService


def build():
    """Construct the FastMCP server with the redaction tools registered."""
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:  # pragma: no cover - only without the extra
        raise SystemExit(
            "the Redactable MCP server needs the [mcp] extra: pip install 'redactable[mcp]'"
        ) from exc

    service = RedactionService()
    mcp = FastMCP("redactable")

    @mcp.tool()
    def scrub(text: str, policy: str = "pii-structured", reversible: bool = True) -> dict:
        """Remove PII from text BEFORE sending it to an LLM. Returns the redacted text, a
        summary of what was found, and (when reversible) a session id to restore originals."""
        return service.scrub(text, policy=policy, reversible=reversible)

    @mcp.tool()
    def restore(text: str, session: str) -> str:
        """Restore original values into text that was scrubbed reversibly, using its session id."""
        return service.restore(text, session)

    @mcp.tool()
    def detect(text: str, policy: str = "pii-structured") -> dict:
        """Report what PII is present in text WITHOUT modifying it (a safety preview)."""
        return service.detect(text, policy=policy)

    return mcp


def main() -> None:
    build().run()


if __name__ == "__main__":
    main()
