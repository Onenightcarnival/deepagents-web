"""settings 表：应用设置 KV 存储（value 为 JSON TEXT）。

存放内容：providers（服务商列表）、defaultModel、approvalMode、
projectConfig（项目级模型与参数）、skillDirs。
"""

from sqlalchemy.orm import Mapped, mapped_column

from src.utils.database import Base


class SettingRecord(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(primary_key=True)
    value: Mapped[str] = mapped_column(nullable=False)  # JSON TEXT
