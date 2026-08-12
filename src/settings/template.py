"""设置模块的出入参 pydantic 模型。"""

from typing import Literal

from pydantic import Field

from src.utils.template import ApiModel, NonBlankStr


class ModelRef(ApiModel):
    provider: str
    model: str


class SettingsBody(ApiModel):
    approval_mode: Literal["off", "dangerous", "dangerous+mcp", "all"] | None = None
    # None 表示清除默认模型；缺省表示不修改（见 router 中的 model_fields_set）
    default_model: ModelRef | None = None


class ProjectParams(ApiModel):
    thinking: Literal["on", "off"] | None = None
    thinking_effort: Literal["low", "high", "max"] | None = None
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, gt=0)

    def normalized(self) -> dict:
        """只保留被设置的字段，形状与前端约定一致（camelCase）。"""
        return self.model_dump(by_alias=True, exclude_none=True)


class ProjectConfigBody(ApiModel):
    key: NonBlankStr
    model: ModelRef | None = None
    params: ProjectParams | None = None
