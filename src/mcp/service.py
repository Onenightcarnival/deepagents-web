"""MCP 服务器：配置 CRUD + 工具加载（langchain-mcp-adapters）。

配置的 MCP 服务器转换为 LangChain 工具后直接传入 create_deep_agent。
工具列表按配置哈希缓存，仅在启用集变化时重新拉取；Python adapter 每次
工具调用新开 MCP 会话，无常驻连接需要关闭。

工具名统一加 `服务器名__工具名` 前缀（与前端及 disabledTools 约定一致）。
"""

import json

import httpx
from langchain_mcp_adapters.client import MultiServerMCPClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.mcp.model import McpServerRecord

# 工具列表缓存，按配置哈希失效；仅原地更新
_cache: dict = {"hash": None, "tools": {}}


# ---------------------------------------------------------------- 配置 CRUD


def list_mcp_servers(db: Session) -> list[dict]:
    rows = db.scalars(select(McpServerRecord).order_by(McpServerRecord.name)).all()
    return [{"name": r.name, "enabled": bool(r.enabled), **json.loads(r.config)} for r in rows]


def upsert_mcp_server(db: Session, name: str, config: dict, enabled: bool = True) -> None:
    db.merge(McpServerRecord(name=name, config=json.dumps(config), enabled=1 if enabled else 0))


def delete_mcp_server(db: Session, name: str) -> None:
    row = db.get(McpServerRecord, name)
    if row:
        db.delete(row)


# ---------------------------------------------------------------- 工具加载


def _httpx_client_factory(headers=None, timeout=None, auth=None) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        headers=headers,
        timeout=timeout,
        auth=auth,
        follow_redirects=True,
        trust_env=False,
        verify=False,
    )


def _to_adapter_config(servers: list[dict]) -> dict:
    connections = {}
    for s in servers:
        # 仅支持 streamable HTTP；跳过停用或遗留 stdio 条目
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
    """Returns (tools, errors)。逐工具停用叠加在缓存之上，开关工具不触发
    重新拉取。"""
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

    disabled = {f"{s['name']}__{t}" for s in servers if s.get("enabled") for t in (s.get("disabledTools") or [])}
    tools = [t for server_tools in _cache["tools"].values() for t in server_tools if t.name not in disabled]
    return tools, errors


async def test_mcp_server(config: dict) -> dict:
    """用一次性客户端测试单个服务器配置，列出其暴露的全部能力：tools、
    prompts、resources（服务器未声明的能力返回空数组）。"""
    name = config.get("name") or "test"
    connections = _to_adapter_config([{**config, "name": name, "enabled": True}])
    client = MultiServerMCPClient(connections=connections)
    try:
        tools = [
            {
                "name": t.name,
                "description": t.description or "",
                # 工具入参的 JSON Schema（adapter 已解引用）
                "schema": t.tool_call_schema
                if isinstance(t.tool_call_schema, dict)
                else (t.args_schema if isinstance(t.args_schema, dict) else None),
            }
            for t in await client.get_tools(server_name=name)
        ]
        prompts: list = []
        resources_list: list = []
        async with client.session(name) as session:
            try:
                res = await session.list_prompts()
                prompts = [
                    {
                        "name": p.name,
                        "description": p.description or "",
                        "arguments": [
                            {"name": a.name, "description": a.description or "", "required": bool(a.required)}
                            for a in (p.arguments or [])
                        ],
                    }
                    for p in (res.prompts or [])
                ]
            except Exception:
                pass
            try:
                res = await session.list_resources()
                resources_list = [
                    {
                        "uri": str(r.uri),
                        "name": r.name or "",
                        "description": r.description or "",
                        "mimeType": r.mimeType or "",
                    }
                    for r in (res.resources or [])
                ]
            except Exception:
                pass
        return {"ok": True, "tools": tools, "prompts": prompts, "resources": resources_list}
    except Exception as e:
        return {"ok": False, "error": str(e)}
