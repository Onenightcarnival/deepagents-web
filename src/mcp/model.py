"""mcp_servers 表：MCP 服务器配置。

config 为 JSON TEXT：{transport: "http", url, headers?, disabledTools?}。
"""

from sqlalchemy.orm import Mapped, mapped_column

from src.utils.database import Base


class McpServerRecord(Base):
    __tablename__ = "mcp_servers"

    name: Mapped[str] = mapped_column(primary_key=True)
    config: Mapped[str] = mapped_column(nullable=False)  # JSON TEXT
    enabled: Mapped[int] = mapped_column(nullable=False, default=1)
