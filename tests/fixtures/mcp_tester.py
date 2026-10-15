"""A tiny stdio MCP server for tests: one read-only tool, one that writes."""
from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

s = MCPServer("tester")


@s.tool(annotations=ToolAnnotations(readOnlyHint=True))
def echo(text: str) -> str:
    """Echo the text back."""
    return text


@s.tool()
def write_note(text: str) -> str:
    """Pretend to save a note."""
    return "saved"


if __name__ == "__main__":
    s.run()
