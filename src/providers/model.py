"""providers 表：模型服务商配置，name 为主键。

models 为 JSON TEXT（模型 id 数组）。历史上服务商列表存在 settings 表的
providers 键，迁移逻辑见 utils/resource_loader.py。
"""

from sqlalchemy.orm import Mapped, mapped_column

from src.utils.database import Base


class ProviderRecord(Base):
    __tablename__ = "providers"

    name: Mapped[str] = mapped_column(primary_key=True)
    enabled: Mapped[int] = mapped_column(nullable=False, default=1)
    base_url: Mapped[str] = mapped_column(nullable=False)
    api_key: Mapped[str | None] = mapped_column(nullable=True)
    models: Mapped[str] = mapped_column(nullable=False)  # JSON TEXT
    default_model: Mapped[str | None] = mapped_column(nullable=True)
    type: Mapped[str | None] = mapped_column(nullable=True)
