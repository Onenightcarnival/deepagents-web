"""sessions 表：会话元数据。

对话内容本身存 LangGraph checkpointer 库（checkpoints-py.db，thread_id=会话
id），由 langgraph 自行管理。model 列是会话级模型覆盖（JSON {provider,
model} 或 NULL）。
"""
from sqlalchemy.orm import Mapped, mapped_column

from ..utils.database import Base


class SessionRecord(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(nullable=False, default="New session")
    cwd: Mapped[str] = mapped_column(nullable=False)
    created_at: Mapped[int] = mapped_column(nullable=False)
    updated_at: Mapped[int] = mapped_column(nullable=False)
    model: Mapped[str | None] = mapped_column(nullable=True)  # JSON TEXT

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "cwd": self.cwd,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "model": self.model,
        }
