"""sessions 表：会话元数据。

对话内容本身存 LangGraph checkpointer 库（checkpoints-py.db，thread_id=会话
id），由 langgraph 自行管理。模型与参数配置在项目上（settings 的
projectConfig），会话不单独持有。
"""

from sqlalchemy.orm import Mapped, mapped_column

from src.utils.database import Base


class SessionRecord(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(nullable=False, default="New session")
    cwd: Mapped[str] = mapped_column(nullable=False)
    created_at: Mapped[int] = mapped_column(nullable=False)
    updated_at: Mapped[int] = mapped_column(nullable=False)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "cwd": self.cwd,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
