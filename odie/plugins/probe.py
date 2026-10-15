"""Lists one MCP server's tools in a throwaway process (spec as JSON on stdin; prints [{name, read_only, destructive}]).
Odie runs this with a hard timeout and kills the whole process group if the server hangs, so a stuck server
can never leave a process or task behind in Odie itself."""
import asyncio
import json
import os
import sys

from odie.plugins.mcp import is_destructive, is_read_only, toolset_for


async def _main() -> None:
    ts = toolset_for("probe", json.loads(sys.stdin.read()))
    tools = await ts.get_tools()
    print(json.dumps([{"name": t.name, "read_only": is_read_only(t), "destructive": is_destructive(t)} for t in tools]), flush=True)


if __name__ == "__main__":
    asyncio.run(_main())
    os._exit(0)  # skip slow MCP teardown; the parent only needs the list
