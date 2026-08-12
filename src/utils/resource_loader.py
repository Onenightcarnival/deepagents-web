"""配置加载：启动时按 --env 选择 src/config/{env}.toml（默认 dev），
经 pydantic 校验后暴露只读的 CONFIG。

业务库的引擎/会话见 utils/database.py；LangGraph checkpointer 挂在
app.state（lifespan 初始化，见 utils/app_config.py）。
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
