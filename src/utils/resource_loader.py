"""配置加载与全局资源池。

- CONFIG：启动时按 --env 选择 src/config/{env}.toml 加载（默认 dev），
  经 pydantic 校验后的只读配置。
- resources：进程级单例资源池。同步资源（SQLAlchemy 引擎/会话工厂、运行
  注册表）在 import 时就绪；异步资源（LangGraph checkpointer 的 aiosqlite
  连接）由 FastAPI lifespan 阶段填充/关闭（见 utils/app_config.py）。
"""
import argparse
import sys
import tomllib
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from ..config.config_template import ROOT_DIR, AppConfig
from .database import Base

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


def _init_engine(config: AppConfig):
    config.paths.data_dir.mkdir(parents=True, exist_ok=True)
    config.paths.workspace_root.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        f"sqlite:///{config.paths.data_dir / 'app.db'}",
        connect_args={"check_same_thread": False},
    )
    # 注册所有 ORM 模型后建表（WAL 属性随数据库文件持久化，设置一次即可）
    from ..mcp.model import McpServerRecord  # noqa: F401
    from ..sessions.model import SessionRecord  # noqa: F401
    from ..settings.model import SettingRecord  # noqa: F401

    with engine.connect() as conn:
        conn.execute(text("PRAGMA journal_mode=WAL"))
    Base.metadata.create_all(engine)
    # 迁移：旧库的 sessions 表补 model 列（create_all 不改已有表）
    with engine.begin() as conn:
        cols = [c["name"] for c in inspect(conn).get_columns("sessions")]
        if "model" not in cols:
            conn.execute(text("ALTER TABLE sessions ADD COLUMN model TEXT"))
    return engine


class Resources:
    """进程级单例资源池。checkpointer 在 lifespan 启动前为 None。"""

    def __init__(self, config: AppConfig):
        self.engine = _init_engine(config)
        self.db_session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.checkpointer = None  # AsyncSqliteSaver，由 lifespan 填充
        # sessionId -> 最近一次运行记录（sessions/service.py），运行与页面连接解耦
        self.runs: dict = {}


resources = Resources(CONFIG)
