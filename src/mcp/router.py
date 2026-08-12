"""MCP 服务器：配置增删、连接测试。"""

from typing import Annotated

from fastapi import APIRouter, Path

from src.mcp import service
from src.mcp.template import McpTestBody, McpUpsertBody

router = APIRouter(prefix="/api")


@router.get("/mcp")
async def list_mcp():
    return {"servers": service.list_mcp_servers()}


@router.post("/mcp/test")
async def mcp_test(body: McpTestBody):
    return await service.test_mcp_server(body.model_dump(by_alias=True, exclude_none=True))


@router.post("/mcp")
async def upsert_mcp(body: McpUpsertBody):
    service.upsert_mcp_server(body.name, body.to_config(), body.enabled)
    return {"ok": True}


@router.delete("/mcp/{name}")
async def delete_mcp(name: Annotated[str, Path(pattern=r"^[\w-]+$")]):
    service.delete_mcp_server(name)
    return {"ok": True}
