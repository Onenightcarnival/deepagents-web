"""MCP 服务器：配置增删、连接测试。"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path
from sqlalchemy.orm import Session

from src.mcp import service
from src.mcp.template import McpTestBody, McpUpsertBody
from src.utils.app_config import api_ok
from src.utils.database import get_db, get_db_with_commit

router = APIRouter(prefix="/mcp")


@router.get("/")
async def list_mcp(db: Session = Depends(get_db)):
    return api_ok({"servers": service.list_mcp_servers(db)})


@router.post("/test")
async def mcp_test(body: McpTestBody):
    return api_ok(await service.test_mcp_server(body.model_dump(by_alias=True, exclude_none=True)))


@router.post("/")
async def upsert_mcp(body: McpUpsertBody, db: Session = Depends(get_db_with_commit)):
    service.upsert_mcp_server(db, body.name, body.to_config(), body.enabled)
    return api_ok()


@router.delete("/{name}")
async def delete_mcp(name: Annotated[str, Path(pattern=r"^[\w-]+$")], db: Session = Depends(get_db_with_commit)):
    service.delete_mcp_server(db, name)
    return api_ok()
