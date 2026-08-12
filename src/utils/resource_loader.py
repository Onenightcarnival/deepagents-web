"""配置加载与全局资源池。

- CONFIG：启动时按 --env 选择 src/config/{env}.toml 加载（默认 dev），
  经 pydantic 校验后的只读配置。
- resources：进程级单例资源池。同步资源（SQLAlchemy 引擎/会话工厂、运行
  注册表）在 import 时就绪；异步资源（LangGraph checkpointer 的 aiosqlite
  连接）由 FastAPI lifespan 阶段填充/关闭（见 utils/app_config.py）。
"""

import argparse
import json
import sys
import tomllib

from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import Session, sessionmaker

from src.config.config_template import ROOT_DIR, AppConfig

# ORM 模型需在 create_all 前注册到 Base.metadata
from src.mcp.model import McpServerRecord  # noqa: F401
from src.providers.model import ProviderRecord
from src.sessions.model import SessionRecord  # noqa: F401
from src.settings.model import SettingRecord
from src.utils.database import Base

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
    # WAL 属性随数据库文件持久化，设置一次即可
    with engine.connect() as conn:
        conn.execute(text("PRAGMA journal_mode=WAL"))
    Base.metadata.create_all(engine)
    # 迁移：旧库的 sessions 表补 model 列（create_all 不改已有表）
    with engine.begin() as conn:
        cols = [c["name"] for c in inspect(conn).get_columns("sessions")]
        if "model" not in cols:
            conn.execute(text("ALTER TABLE sessions ADD COLUMN model TEXT"))
    _migrate_providers_from_settings(engine)
    return engine


def _migrate_providers_from_settings(engine) -> None:
    """迁移：服务商列表从 settings 表的 providers 键（JSON 数组）迁到
    providers 表，迁移后删除该键。"""
    with Session(engine) as s:
        kv = s.get(SettingRecord, "providers")
        if kv is None:
            return
        if s.scalars(select(ProviderRecord).limit(1)).first() is None:
            for p in json.loads(kv.value) or []:
                s.add(
                    ProviderRecord(
                        name=p.get("name") or "",
                        enabled=1 if p.get("enabled") else 0,
                        base_url=p.get("baseUrl") or "",
                        api_key=p.get("apiKey"),
                        models=json.dumps(p.get("models") or []),
                        default_model=p.get("defaultModel"),
                        type=p.get("type"),
                    )
                )
        s.delete(kv)
        s.commit()


class Resources:
    """进程级单例资源池。checkpointer 在 lifespan 启动前为 None。"""

    def __init__(self, config: AppConfig):
        self.engine = _init_engine(config)
        self.db_session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.checkpointer = None  # AsyncSqliteSaver，由 lifespan 填充
        # sessionId -> 最近一次运行记录（sessions/service.py），运行与页面连接解耦
        self.runs: dict = {}


resources = Resources(CONFIG)
