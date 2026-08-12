"""MCP 服务器：配置增删、连接测试。"""

import re

from fastapi import APIRouter, Request
from pydantic import ValidationError

from src.mcp import service
from src.mcp.template import McpTestBody, McpUpsertBody
from src.utils.app_config import json_error, validation_error_message

router = APIRouter(prefix="/api")


@router.get("/mcp")
async def list_mcp():
    return {"servers": service.list_mcp_servers()}


@router.post("/mcp/test")
async def mcp_test(request: Request):
    try:
        body = McpTestBody.model_validate(await request.json())
    except ValidationError as e:
        return json_error(validation_error_message(e))
    if body.transport != "http":
        return json_error("only streamable http transport is supported")
    if not body.url:
        return json_error("http transport requires url")
    return await service.test_mcp_server(body.model_dump(exclude_none=True))


@router.post("/mcp")
async def upsert_mcp(request: Request):
    try:
        body = McpUpsertBody.model_validate(await request.json())
    except ValidationError as e:
        return json_error(validation_error_message(e))
    if body.transport != "http":
        return json_error("only streamable http transport is supported")
    if not body.url:
        return json_error("http transport requires url")
    service.upsert_mcp_server(body.name, body.to_config(), body.enabled)
    return {"ok": True}


@router.delete("/mcp/{name}")
async def delete_mcp(name: str):
    if not re.fullmatch(r"[\w-]+", name):
        return json_error("invalid name")
    service.delete_mcp_server(name)
    return {"ok": True}
