"""服务启动配置：读取项目根目录的 config.toml（不存在则全部用默认值）。

模型服务商、MCP、技能目录等属于用户数据，在设置页配置并存入 SQLite，
不在此文件范围内。参考 config.example.toml。
"""
import tomllib
from dataclasses import dataclass
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
PUBLIC_DIR = ROOT_DIR / "public"


@dataclass(frozen=True)
class Config:
    host: str = "127.0.0.1"
    port: int = 3080
    # 局域网访问时务必设置；请求需带 ?token= 或 Authorization: Bearer
    auth_token: str | None = None
    data_dir: Path = ROOT_DIR / "data"
    workspace_root: Path = ROOT_DIR / "workspaces"
    # execute 工具的单条命令超时（秒）
    shell_timeout: int = 300
    # 模型请求失败重试次数
    model_max_retries: int = 2


def load_config(path: Path | None = None) -> Config:
    path = path or ROOT_DIR / "config.toml"
    if not path.exists():
        return Config()
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    server = raw.get("server") or {}
    paths = raw.get("paths") or {}
    agent = raw.get("agent") or {}

    def as_path(value, default: Path) -> Path:
        return (ROOT_DIR / Path(value).expanduser()).resolve() if value else default

    return Config(
        host=server.get("host") or Config.host,
        port=int(server.get("port") or Config.port),
        auth_token=server.get("auth_token") or None,
        data_dir=as_path(paths.get("data_dir"), Config.data_dir),
        workspace_root=as_path(paths.get("workspace_root"), Config.workspace_root),
        shell_timeout=int(agent.get("shell_timeout") or Config.shell_timeout),
        model_max_retries=int(agent.get("model_max_retries") or Config.model_max_retries),
    )


CONFIG = load_config()
