"""FastAPI 主程序的横切配置：logging、lifespan、exception handler、
统一响应格式。只定义函数，由 main.py 统一挂载。

响应最外层统一为三个字段：
  { statusCode: 三段式业务状态码, message: 消息说明, data: dict | list | null }

业务状态码为三段式字符串 xx-yy-zz：
  xx  服务名缩写，本服务为 WA（web-agent）；
  yy  功能模块，00 为服务级（健康检查、全局 exception handler），
      业务模块从 01 起递增（与 main.py 的 router 挂载顺序一致）；
  zz  状态序号，00 表示成功；99 表示 500 未知错误（仅服务级有），
      其余错误从 01 起递增。

服务级状态码与文案映射表定义在本文件（ServiceCode / MESSAGES），
模块级的在各模块 router.py 中同样成对定义。每个状态码都有对应文案；
需要携带动态细节的调用点在文案后追加冒号说明（如具体目录、校验失败原因）。
"""

import contextlib
import logging
from enum import StrEnum

import aiosqlite
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

# ORM 模型导入即注册到 Base.metadata，lifespan 建表依赖于此
from src.mcp.model import McpServerRecord  # noqa: F401
from src.providers.model import ProviderRecord  # noqa: F401
from src.providers.service import resolve_model
from src.sessions.model import SessionRecord  # noqa: F401
from src.settings.model import SettingRecord  # noqa: F401
from src.utils.database import Base, SessionLocal, engine
from src.utils.resource_loader import CONFIG, ENV

logger = logging.getLogger("deepagent-web")


def setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


class ServiceCode(StrEnum):
    """服务级业务状态码（WA-00-zz）；模块级的见各模块 router.py。"""

    OK = "WA-00-00"
    VALIDATION_ERROR = "WA-00-01"
    CONFLICT = "WA-00-02"
    UNKNOWN_ERROR = "WA-00-99"


MESSAGES: dict[ServiceCode, str] = {
    ServiceCode.OK: "成功",
    ServiceCode.VALIDATION_ERROR: "请求参数校验失败",
    ServiceCode.CONFLICT: "记录已存在（唯一约束冲突）",
    ServiceCode.UNKNOWN_ERROR: "服务器内部错误",
}


def json_response(http_code: int, status_code: str, message: str, data=None) -> JSONResponse:
    """统一 JSON 响应出口：body 为 {statusCode, message, data}。

    http_code 传 fastapi.status 常量；status_code 是三段式业务码；
    message 必填，常规场景取对应 MESSAGES 表，需要细节时在其后追加。"""
    return JSONResponse({"statusCode": status_code, "message": message, "data": data}, status_code=http_code)


def validation_error_message(e) -> str:
    """取校验错误的第一条，转成对前端友好的单行文案。

    兼容 pydantic ValidationError 与 FastAPI RequestValidationError
    （后者的 loc 以 body/path/query 等来源开头，展示时去掉）。"""
    first = e.errors()[0]
    if first.get("type") == "json_invalid":
        return "invalid JSON body"
    msg = (first.get("msg") or "invalid request").removeprefix("Value error, ")
    if first.get("type") == "value_error":
        return msg  # 自定义校验消息，本身已可读
    parts = [str(p) for p in first.get("loc") or ()]
    if parts and parts[0] in ("body", "path", "query", "header"):
        parts = parts[1:]
    loc = ".".join(parts)
    return f"{loc}: {msg}" if loc else msg


async def on_validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
    """请求校验失败的全局出口：router 内不再逐个 try/except。"""
    code = ServiceCode.VALIDATION_ERROR
    return json_response(
        status.HTTP_422_UNPROCESSABLE_CONTENT, code, f"{MESSAGES[code]}: {validation_error_message(exc)}"
    )


async def on_integrity_error(_request: Request, exc: IntegrityError) -> JSONResponse:
    """数据库唯一/完整性约束冲突的全局出口（如主键重名）。"""
    return json_response(status.HTTP_409_CONFLICT, ServiceCode.CONFLICT, MESSAGES[ServiceCode.CONFLICT])


async def on_error(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("API error: %s %s", request.method, request.url.path)
    code = ServiceCode.UNKNOWN_ERROR
    return json_response(status.HTTP_500_INTERNAL_SERVER_ERROR, code, f"{MESSAGES[code]}: {exc}")


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    # 业务库：建表（无迁移逻辑，表结构变更直接删除 data 目录重建）+ WAL
    Base.metadata.create_all(engine)
    with engine.connect() as conn:
        conn.execute(text("PRAGMA journal_mode=WAL"))

    # checkpoint 库：LangGraph 对话状态，独立于业务库
    conn = await aiosqlite.connect(str(CONFIG.paths.data_dir / "checkpoints-py.db"))
    app.state.checkpointer = AsyncSqliteSaver(conn)
    await app.state.checkpointer.setup()

    logger.info("env: %s", ENV)
    logger.info("listening on http://%s:%s", CONFIG.server.host, CONFIG.server.port)
    try:
        with SessionLocal() as db:
            m = resolve_model(db, None)
        logger.info("default model: %s @ %s (%s)", m["model"], m["baseUrl"], m["provider"])
    except RuntimeError as e:
        logger.warning("no model configured yet: %s", e)
    logger.info("workspace root: %s", CONFIG.paths.workspace_root)

    yield
    await conn.close()
