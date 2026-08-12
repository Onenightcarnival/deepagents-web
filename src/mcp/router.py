"""MCP 服务器：配置增删、连接测试。"""

from enum import StrEnum
from typing import Annotated

from fastapi import APIRouter, Depends, Path, status
from sqlalchemy.orm import Session

from src.mcp import service
from src.mcp.template import McpTestBody, McpUpsertBody
from src.utils.app_config import json_response
from src.utils.database import get_db, get_db_with_commit

router = APIRouter(prefix="/mcp")


class McpCode(StrEnum):
    """mcp 模块业务状态码（三段式规则见 utils/app_config.py）。"""

    OK = "WA-04-00"


MESSAGES: dict[McpCode, str] = {
    McpCode.OK: "成功",
}


@router.get("/")
async def list_mcp(db: Session = Depends(get_db)):
    return json_response(
        status.HTTP_200_OK, McpCode.OK, MESSAGES[McpCode.OK], data={"servers": service.list_mcp_servers(db)}
    )


@router.post("/test")
async def mcp_test(body: McpTestBody):
    return json_response(
        status.HTTP_200_OK,
        McpCode.OK,
        MESSAGES[McpCode.OK],
        data=await service.test_mcp_server(body.model_dump(by_alias=True, exclude_none=True)),
    )


@router.post("/")
async def upsert_mcp(body: McpUpsertBody, db: Session = Depends(get_db_with_commit)):
    service.upsert_mcp_server(db, body.name, body.to_config(), body.enabled)
    return json_response(status.HTTP_200_OK, McpCode.OK, MESSAGES[McpCode.OK])


@router.delete("/{name}")
async def delete_mcp(name: Annotated[str, Path(pattern=r"^[\w-]+$")], db: Session = Depends(get_db_with_commit)):
    service.delete_mcp_server(db, name)
    return json_response(status.HTTP_200_OK, McpCode.OK, MESSAGES[McpCode.OK])
