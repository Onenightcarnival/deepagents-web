"""服务商模块的出入参 pydantic 模型。"""

from typing import Literal

from pydantic import Field

from src.utils.template import ApiModel, NonBlankStr


class ProviderBody(ApiModel):
    """单个服务商。无论是否启用，都必须有 API 地址和至少一个模型。"""

    name: NonBlankStr
    enabled: bool = False
    base_url: NonBlankStr
    api_key: str | None = None
    models: list[str] = Field(min_length=1)
    default_model: str | None = None
    type: Literal["openai", "deepseek"] | None = None


class TestProviderBody(ApiModel):
    base_url: str
    api_key: str
    model: str
