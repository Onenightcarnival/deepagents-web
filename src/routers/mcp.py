"""MCP 服务器：配置增删、连接测试。"""
import re

from fastapi import APIRouter, Request

from ..services.mcp import test_mcp_server
from ..utils.app_config import json_error
from ..utils.resource_loader import resources

router = APIRouter(prefix="/api")


@router.get("/mcp")
async def list_mcp():
    return {"servers": resources.db.list_mcp_servers()}


@router.post("/mcp/test")
async def mcp_test(request: Request):
    config = await request.json()
    if config.get("transport") != "http":
        return json_error("only streamable http transport is supported")
    if not config.get("url"):
        return json_error("http transport requires url")
    return await test_mcp_server(config)


@router.post("/mcp")
async def upsert_mcp(request: Request):
    body = await request.json()
    name = body.pop("name", None)
    enabled = body.pop("enabled", True)
    config = body
    if not name or not re.fullmatch(r"[\w-]+", name):
        return json_error("invalid name")
    if config.get("transport") != "http":
        return json_error("only streamable http transport is supported")
    if not config.get("url"):
        return json_error("http transport requires url")
    if "disabledTools" in config:
        if not isinstance(config["disabledTools"], list):
            return json_error("disabledTools must be an array of tool names")
        config["disabledTools"] = [t for t in config["disabledTools"] if isinstance(t, str)]
        if not config["disabledTools"]:
            del config["disabledTools"]
    resources.db.upsert_mcp_server(name, config, enabled)
    return {"ok": True}


@router.delete("/mcp/{name}")
async def delete_mcp(name: str):
    if not re.fullmatch(r"[\w-]+", name):
        return json_error("invalid name")
    resources.db.delete_mcp_server(name)
    return {"ok": True}
