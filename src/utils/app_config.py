"""FastAPI 主程序的横切配置：logging、lifespan、middleware、exception handler、
统一响应格式。只定义函数，由 main.py 统一挂载。

响应最外层统一为三个字段（http 状态码与 statusCode 一致）：
  { statusCode: 业务状态码, message: 消息说明, data: dict | list | null }
"""

import contextlib
import logging

import aiosqlite
from fastapi import FastAPI, Request
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


def api_ok(data=None, message: str = "ok") -> JSONResponse:
    """统一成功响应。"""
    return JSONResponse({"statusCode": 200, "message": message, "data": data})


def json_error(message: str, status: int = 400) -> JSONResponse:
    """统一错误响应。"""
    return JSONResponse({"statusCode": status, "message": message, "data": None}, status_code=status)


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
    return json_error(validation_error_message(exc), 422)


async def on_integrity_error(_request: Request, exc: IntegrityError) -> JSONResponse:
    """数据库唯一/完整性约束冲突的全局出口（如主键重名）。"""
    return json_error("记录已存在（唯一约束冲突）", 409)


async def on_error(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("API error: %s %s", request.method, request.url.path)
    return json_error(str(exc), 500)


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
    if not CONFIG.server.auth_token and CONFIG.server.host not in ("127.0.0.1", "localhost"):
        logger.warning("server exposed beyond localhost without auth_token")

    yield
    await conn.close()


async def auth_middleware(request: Request, call_next):
    token = CONFIG.server.auth_token
    if token and request.url.path.startswith("/api/"):
        ok = request.headers.get("authorization") == f"Bearer {token}" or request.query_params.get("token") == token
        if not ok:
            return json_error("unauthorized", 401)
    return await call_next(request)
