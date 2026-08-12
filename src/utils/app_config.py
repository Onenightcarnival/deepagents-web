"""FastAPI 主程序的横切配置：logging、lifespan、middleware、exception handler。

只定义函数，由 main.py 统一挂载。
"""
import contextlib
import logging

import aiosqlite
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from ..services.providers import resolve_model
from .resource_loader import CONFIG, ENV, resources

logger = logging.getLogger("deepagent-web")


def setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


def json_error(message: str, status: int = 400) -> JSONResponse:
    """统一错误响应形状（前端读取 error 字段）。"""
    return JSONResponse({"error": message}, status_code=status)


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI):
    conn = await aiosqlite.connect(str(CONFIG.paths.data_dir / "checkpoints-py.db"))
    resources.checkpointer = AsyncSqliteSaver(conn)
    await resources.checkpointer.setup()

    logger.info("env: %s", ENV)
    logger.info("listening on http://%s:%s", CONFIG.server.host, CONFIG.server.port)
    try:
        m = resolve_model(resources.db, None)
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
        ok = (
            request.headers.get("authorization") == f"Bearer {token}"
            or request.query_params.get("token") == token
        )
        if not ok:
            return json_error("unauthorized", 401)
    return await call_next(request)


async def on_error(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("API error: %s %s", request.method, request.url.path)
    return json_error(str(exc), 500)
