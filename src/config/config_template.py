"""配置模板：{环境}.toml 的结构定义（pydantic）。

配置文件放在本目录下，按环境命名（dev.toml / prod.toml / test.toml），
启动时用 --env 选择（默认 dev），由 utils/resource_loader.py 加载。
所有键都可省略，缺省值见各字段定义。dev.toml 随仓库提交（不含密钥），
其他环境的 toml 已加入 .gitignore。
"""
from pathlib import Path

from pydantic import BaseModel

# 项目根目录（src/config/ 的上两级）
ROOT_DIR = Path(__file__).resolve().parent.parent.parent


class ServerConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 3080
    # 局域网访问时务必设置；请求需带 ?token= 或 Authorization: Bearer
    auth_token: str | None = None


class PathsConfig(BaseModel):
    data_dir: Path = ROOT_DIR / "data"
    workspace_root: Path = ROOT_DIR / "workspaces"


class AgentConfig(BaseModel):
    # execute 工具的单条命令超时（秒）
    shell_timeout: int = 300
    # 模型请求失败重试次数
    model_max_retries: int = 2


class AppConfig(BaseModel):
    server: ServerConfig = ServerConfig()
    paths: PathsConfig = PathsConfig()
    agent: AgentConfig = AgentConfig()

    def resolve_paths(self) -> "AppConfig":
        """相对路径一律相对项目根目录解析。"""
        paths = PathsConfig(
            data_dir=(ROOT_DIR / self.paths.data_dir.expanduser()).resolve(),
            workspace_root=(ROOT_DIR / self.paths.workspace_root.expanduser()).resolve(),
        )
        return self.model_copy(update={"paths": paths})
