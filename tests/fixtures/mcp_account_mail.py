"""A tiny stdio MCP server for tests: a mail app whose tools have the same names whichever account it is, as two
connections of one service do. MAIL_ACCOUNT (from the server's env in mcp.json) says which account answers."""
import os

from mcp.server.mcpserver import MCPServer

ACCOUNT = os.environ.get("MAIL_ACCOUNT", "unknown")
s = MCPServer("mail")


@s.tool()
def send_email(text: str) -> str:
    """Send an email."""
    return f"sent from the {ACCOUNT} account: {text}"


@s.tool()
def find_email(query: str) -> str:
    """Find emails."""
    return f"found in the {ACCOUNT} account: {query}"


if __name__ == "__main__":
    s.run()
