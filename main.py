"""服务主程序：lifespan、router、exception handler、健康检查。

  uv run python main.py [--env dev]   — 默认 http://127.0.0.1:3080

启动配置见 src/config/{env}.toml（结构定义在 src/config/config_template.py）；
模型服务商、MCP、技能目录在网页设置页配置。
"""

import uvicorn
from fastapi import FastAPI, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import IntegrityError

from src.mcp.router import router as mcp_router
from src.providers.router import router as providers_router
from src.sessions.router import router as sessions_router
from src.settings.router import router as settings_router
from src.skills.router import router as skills_router
from src.utils.app_config import (
    MESSAGES,
    ServiceCode,
    json_response,
    lifespan,
    on_error,
    on_integrity_error,
    on_validation_error,
    setup_logging,
)
from src.utils.resource_loader import CONFIG, PUBLIC_DIR

app = FastAPI(lifespan=lifespan)

app.exception_handler(Exception)(on_error)
app.exception_handler(RequestValidationError)(on_validation_error)
app.exception_handler(IntegrityError)(on_integrity_error)

# 上下文根：整个应用（API + 静态前端 + 主页）统一收在该前缀下，默认 "" 即挂根路径
CONTEXT_ROOT = CONFIG.server.context_root

# 各模块 router 前缀与模块名一致，统一拼在上下文根之后
for module_router in (sessions_router, providers_router, settings_router, mcp_router, skills_router):
    app.include_router(module_router, prefix=CONTEXT_ROOT)


# 健康检查留在根路径，供探针直连进程，不随上下文根移动
@app.get("/healthz")
async def healthz():
    return json_response(status.HTTP_200_OK, ServiceCode.OK, MESSAGES[ServiceCode.OK])


# 首页注入 context_root，前端 api.js 读 window.__CTX__，静态产物无需按部署环境重新构建
@app.get(f"{CONTEXT_ROOT}/", include_in_schema=False)
async def index() -> HTMLResponse:
    html = (PUBLIC_DIR / "index.html").read_text(encoding="utf-8")
    inject = f'<script>window.__CTX__ = "{CONTEXT_ROOT}";</script>\n</head>'
    return HTMLResponse(html.replace("</head>", inject, 1), headers={"Cache-Control": "no-cache"})


if CONTEXT_ROOT:
    # 不带尾斜杠访问上下文根时重定向到主页，保证 index.html 里的相对路径按目录解析
    @app.get(CONTEXT_ROOT, include_in_schema=False)
    async def index_redirect() -> RedirectResponse:
        return RedirectResponse(f"{CONTEXT_ROOT}/")


# 静态前端（放在 API 路由之后挂载，API 路由优先匹配）。
# no-cache 要求浏览器每次协商缓存（ETag/304），避免 JS 模块改动后被启发式缓存拖住不更新
class NoCacheStaticFiles(StaticFiles):
    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


app.mount(CONTEXT_ROOT or "/", NoCacheStaticFiles(directory=str(PUBLIC_DIR), html=True), name="static")


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
