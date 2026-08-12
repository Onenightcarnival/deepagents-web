"""SQLAlchemy 声明基类。

业务表（sessions / mcp_servers / settings）的 ORM 模型定义在各业务模块的
model.py 中，统一继承这里的 Base；引擎与会话工厂见 resource_loader.py。
LangGraph checkpoint 数据（checkpoints-py.db）由 langgraph 自行管理，不走
SQLAlchemy。
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
