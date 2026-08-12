"""服务主程序：lifespan、router、middleware、exception handler、健康检查。

  uv run python main.py [--env dev]   — 默认 http://127.0.0.1:3080

启动配置见 src/config/{env}.toml（结构定义在 src/config/config_template.py）；
模型服务商、MCP、技能目录在网页设置页配置。
"""

import uvicorn
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import IntegrityError

from src.mcp.router import router as mcp_router
from src.providers.router import router as providers_router
from src.sessions.router import router as sessions_router
from src.settings.router import router as settings_router
from src.skills.router import router as skills_router
from src.utils.app_config import (
    auth_middleware,
    lifespan,
    on_error,
    on_integrity_error,
    on_validation_error,
    setup_logging,
)
from src.utils.resource_loader import CONFIG, PUBLIC_DIR

app = FastAPI(lifespan=lifespan)

app.middleware("http")(auth_middleware)
app.exception_handler(Exception)(on_error)
app.exception_handler(RequestValidationError)(on_validation_error)
app.exception_handler(IntegrityError)(on_integrity_error)

# 各模块 router 前缀与模块名一致，统一拼在上下文根之后（默认不配置）
for module_router in (sessions_router, providers_router, settings_router, mcp_router, skills_router):
    app.include_router(module_router, prefix=CONFIG.server.context_root)


@app.get("/healthz")
async def healthz():
    return {"ok": True}


# 静态前端（放在 API 路由之后挂载，/api/* 优先匹配）
app.mount("/", StaticFiles(directory=str(PUBLIC_DIR), html=True), name="static")


def main() -> None:
    setup_logging()
    uvicorn.run(
        app,
        host=CONFIG.server.host,
        port=CONFIG.server.port,
        timeout_keep_alive=0,
        log_level="warning",
    )


if __name__ == "__main__":
    main()
