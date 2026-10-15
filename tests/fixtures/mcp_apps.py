"""A small MCP server like a connected app's: tools named the way Zapier and Composio name them, mostly without
annotations. Run with "http <port> <path>" to serve over streamable HTTP (a live check); stdio otherwise."""
import sys

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

ITEMS = ["milk", "bread"]
s = MCPServer("apps")


@s.tool()
def list_items() -> list[str]:
    """List the items on the shopping list."""
    return ITEMS


@s.tool()
def create_item(name: str) -> str:
    """Add an item to the shopping list."""
    ITEMS.append(name)
    return f"added {name}"


@s.tool(annotations=ToolAnnotations(destructiveHint=True))
def fetch_report() -> str:
    """Fetch the weekly report (and clear it)."""
    return "report"


@s.tool(annotations=ToolAnnotations(readOnlyHint=True))
def get_status() -> str:
    """The list's status."""
    return "ok"


if __name__ == "__main__":
    if sys.argv[1:2] == ["http"]:
        s.run(transport="streamable-http", port=int(sys.argv[2]), streamable_http_path=sys.argv[3])
    else:
        s.run()
