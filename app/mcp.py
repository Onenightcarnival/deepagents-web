"""MCP server integration via langchain-mcp-adapters.

Converts the user's configured MCP servers into LangChain tools that get
passed straight into create_deep_agent. Loaded tools are cached and only
refetched when the enabled server set changes (config hash). The Python
adapter opens a fresh MCP session per tool call, so there is no persistent
client to close.

Tool names are prefixed `server__tool` (matching the JS version and the
`disabledTools` convention stored in the app db).
"""
import json

import httpx
from langchain_mcp_adapters.client import MultiServerMCPClient

# 工具列表缓存，按配置哈希失效；仅原地更新，见 get_mcp_tools
_cache: dict = {"hash": None, "tools": {}}


def _httpx_client_factory(headers=None, timeout=None, auth=None) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        headers=headers, timeout=timeout, auth=auth,
        follow_redirects=True, trust_env=False, verify=False,
    )


def _to_adapter_config(servers: list[dict]) -> dict:
    connections = {}
    for s in servers:
        # Only streamable HTTP is supported; skip disabled or legacy stdio entries.
        if not s.get("enabled") or not s.get("url"):
            continue
        connections[s["name"]] = {
            "transport": "streamable_http",
            "url": s["url"],
            "httpx_client_factory": _httpx_client_factory,
            **({"headers": s["headers"]} if s.get("headers") else {}),
        }
    return connections


async def get_mcp_tools(servers: list[dict]) -> tuple[list, list[str]]:
    """Returns (tools, errors). Per-tool disable is applied on top of the
    cached tool list, so toggling a tool never forces a refetch."""
    config = _to_adapter_config(servers)
    if not config:
        _cache.update(hash=None, tools={})
        return [], []

    digest = json.dumps(
        {name: {"url": c["url"], "headers": c.get("headers")} for name, c in config.items()},
        sort_keys=True,
    )
    errors: list[str] = []
    if _cache["hash"] != digest:
        client = MultiServerMCPClient(connections=config)
        by_server: dict[str, list] = {}
        for name in config:
            try:
                tools = await client.get_tools(server_name=name)
            except Exception as e:
                errors.append(f"{name}: {e}")
                continue
            for t in tools:
                t.name = f"{name}__{t.name}"
            by_server[name] = tools
        _cache.update(hash=digest, tools=by_server)

    disabled = {
        f"{s['name']}__{t}"
        for s in servers if s.get("enabled")
        for t in (s.get("disabledTools") or [])
    }
    tools = [
        t
        for server_tools in _cache["tools"].values()
        for t in server_tools
        if t.name not in disabled
    ]
    return tools, errors


async def test_mcp_server(config: dict) -> dict:
    """Test a single server config with a throwaway client and list everything
    it exposes: tools, prompts and resources (empty arrays when the server
    does not advertise the capability)."""
    name = config.get("name") or "test"
    connections = _to_adapter_config([{**config, "name": name, "enabled": True}])
    client = MultiServerMCPClient(connections=connections)
    try:
        tools = [
            {
                "name": t.name,
                "description": t.description or "",
                # JSON Schema of the tool's input (already dereferenced by the adapter)
                "schema": t.tool_call_schema if isinstance(t.tool_call_schema, dict) else (
                    t.args_schema if isinstance(t.args_schema, dict) else None
                ),
            }
            for t in await client.get_tools(server_name=name)
        ]
        prompts: list = []
        resources: list = []
        async with client.session(name) as session:
            try:
                res = await session.list_prompts()
                prompts = [
                    {
                        "name": p.name,
                        "description": p.description or "",
                        "arguments": [
                            {"name": a.name, "description": a.description or "",
                             "required": bool(a.required)}
                            for a in (p.arguments or [])
                        ],
                    }
                    for p in (res.prompts or [])
                ]
            except Exception:
                pass
            try:
                res = await session.list_resources()
                resources = [
                    {"uri": str(r.uri), "name": r.name or "",
                     "description": r.description or "", "mimeType": r.mimeType or ""}
                    for r in (res.resources or [])
                ]
            except Exception:
                pass
        return {"ok": True, "tools": tools, "prompts": prompts, "resources": resources}
    except Exception as e:
        return {"ok": False, "error": str(e)}
