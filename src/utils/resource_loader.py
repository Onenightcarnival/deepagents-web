"""配置加载与全局资源池。

- CONFIG：启动时按 --env 选择 src/config/{env}.toml 加载（默认 dev），
  经 pydantic 校验后的只读配置。
- resources：进程级单例资源池——运行注册表（sessions/service.py）与
  LangGraph checkpointer（lifespan 阶段填充/关闭，见 utils/app_config.py）。
  业务库的引擎/会话见 utils/database.py。
"""

import argparse
import sys
import tomllib

from src.config.config_template import ROOT_DIR, AppConfig

PUBLIC_DIR = ROOT_DIR / "public"
CONFIG_DIR = ROOT_DIR / "src" / "config"


def _select_env(argv: list[str]) -> str:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--env", default="dev")
    args, _ = parser.parse_known_args(argv)
    return args.env


def load_config(env: str) -> AppConfig:
    path = CONFIG_DIR / f"{env}.toml"
    if not path.exists():
        if env == "dev":
            return AppConfig().resolve_paths()
        raise FileNotFoundError(f"配置文件不存在: {path}")
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    return AppConfig.model_validate(raw).resolve_paths()


ENV = _select_env(sys.argv[1:])
CONFIG = load_config(ENV)
CONFIG.paths.data_dir.mkdir(parents=True, exist_ok=True)
CONFIG.paths.workspace_root.mkdir(parents=True, exist_ok=True)


class Resources:
    """进程级单例资源池。checkpointer 在 lifespan 启动前为 None。"""

    def __init__(self):
        self.checkpointer = None  # AsyncSqliteSaver，由 lifespan 填充
        # sessionId -> 最近一次运行记录（sessions/service.py），运行与页面连接解耦
        self.runs: dict = {}


resources = Resources()
