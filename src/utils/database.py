"""业务库（app.db）：SQLAlchemy 声明基类、引擎、会话工厂与 FastAPI 依赖。

业务表（sessions / mcp_servers / settings / providers）的 ORM 模型定义在各
业务模块的 model.py 中，统一继承这里的 Base；建表在 lifespan 中执行
（见 utils/app_config.py）。表结构变更不做迁移，直接删除 data 目录重建。

LangGraph checkpoint 数据是独立的库（checkpoints-py.db），由 langgraph
自行管理（aiosqlite），在 lifespan 中初始化，不走 SQLAlchemy。
"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from src.utils.resource_loader import CONFIG


class Base(DeclarativeBase):
    pass


engine = create_engine(
    f"sqlite:///{CONFIG.paths.data_dir / 'app.db'}",
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    """FastAPI 依赖：每个请求一个业务库会话（db: Session = Depends(get_db)）。"""
    with SessionLocal() as session:
        yield session
