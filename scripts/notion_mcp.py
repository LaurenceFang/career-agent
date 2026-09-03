#!/usr/bin/env python3
"""Direct, profile-scoped client for the already-authorized official Notion MCP."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
# Locate the Hermes runtime via environment; the Notion lane is only usable
# where Hermes is installed. Defaults match a standard Windows install.
_HERMES_BASE = Path(os.environ.get("HERMES_BASE", Path.home() / "AppData" / "Local" / "hermes"))
HERMES_ROOT = Path(os.environ.get("HERMES_ROOT", _HERMES_BASE / "hermes-agent"))
HERMES_HOME = Path(os.environ.get("HERMES_HOME_PROFILE", _HERMES_BASE / "profiles" / "careeragent"))
if not HERMES_ROOT.exists():
    raise SystemExit(f"Hermes runtime not found at {HERMES_ROOT}; set HERMES_ROOT or HERMES_BASE.")
sys.path.insert(0, str(HERMES_ROOT))
os.environ["HERMES_HOME"] = str(HERMES_HOME)

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from tools.mcp_oauth_manager import get_manager

URL = "https://mcp.notion.com/mcp"


async def with_session(operation):
    auth = get_manager().get_or_build_provider("notion", URL, None)
    if auth is None:
        raise SystemExit("Notion OAuth provider unavailable; run Hermes MCP login first.")
    async with streamablehttp_client(URL, auth=auth, timeout=30.0) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await operation(session)


async def list_tools(_args):
    async def operation(session):
        result = await session.list_tools()
        return [{"name": tool.name, "description": tool.description, "inputSchema": tool.inputSchema} for tool in result.tools]
    print(json.dumps(await with_session(operation), ensure_ascii=False, indent=2))


async def describe(args):
    async def operation(session):
        result = await session.list_tools()
        tool = next((item for item in result.tools if item.name == args.name), None)
        if tool is None: raise SystemExit(f"Tool not found: {args.name}")
        return {"name": tool.name, "description": tool.description, "inputSchema": tool.inputSchema}
    print(json.dumps(await with_session(operation), ensure_ascii=False, indent=2))


async def call_tool(args):
    raw_arguments = Path(args.arguments_file).read_text(encoding="utf-8") if args.arguments_file else args.arguments
    if not raw_arguments:
        raise SystemExit("Provide arguments JSON or --arguments-file.")
    arguments = json.loads(raw_arguments)
    async def operation(session):
        result = await session.call_tool(args.name, arguments=arguments)
        blocks = []
        for block in result.content or []:
            text = getattr(block, "text", None)
            if text: blocks.append(text)
        return {"is_error": bool(result.isError), "content": blocks}
    print(json.dumps(await with_session(operation), ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list-tools").set_defaults(func=list_tools)
    p = sub.add_parser("describe"); p.add_argument("name"); p.set_defaults(func=describe)
    p = sub.add_parser("call"); p.add_argument("name"); p.add_argument("arguments", nargs="?", help="JSON object for the official MCP tool"); p.add_argument("--arguments-file", help="UTF-8 JSON file; avoids shell escaping"); p.set_defaults(func=call_tool)
    args = parser.parse_args()
    asyncio.run(args.func(args))


if __name__ == "__main__":
    main()
