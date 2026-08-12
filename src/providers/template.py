"""服务商模块的出入参 pydantic 模型。"""

from pydantic import ConfigDict, Field, field_validator

from src.utils.template import ApiModel, NonBlankStr


class ProviderEntry(ApiModel):
    """服务商条目。无论是否启用，都必须有 API 地址和至少一个模型。"""

    model_config = ConfigDict(extra="allow")

    name: NonBlankStr
    enabled: bool = False
    base_url: NonBlankStr
    api_key: str | None = None
    models: list[str] = Field(min_length=1)
    default_model: str | None = None


class SaveProvidersBody(ApiModel):
    providers: list[ProviderEntry]

    @field_validator("providers")
    @classmethod
    def _check_unique_names(cls, v):
        seen = set()
        for p in v:
            if p.name in seen:
                raise ValueError(f"服务商名称重复: {p.name}")
            seen.add(p.name)
        return v


class TestProviderBody(ApiModel):
    base_url: str
    api_key: str
    model: str
