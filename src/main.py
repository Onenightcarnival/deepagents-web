"""服务主程序：lifespan、router、middleware、exception handler、健康检查。

  uv run python -m src.main [--env dev]   — 默认 http://127.0.0.1:3080

启动配置见 src/config/{env}.toml（结构定义在 src/config/config_template.py）；
模型服务商、MCP、技能目录在网页设置页配置。
"""
import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .routers import mcp, providers, sessions, settings, skills
from .utils.app_config import auth_middleware, lifespan, on_error, setup_logging
from .utils.resource_loader import CONFIG, PUBLIC_DIR

app = FastAPI(lifespan=lifespan)

app.middleware("http")(auth_middleware)
app.exception_handler(Exception)(on_error)

app.include_router(sessions.router)
app.include_router(providers.router)
app.include_router(settings.router)
app.include_router(mcp.router)
app.include_router(skills.router)


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
