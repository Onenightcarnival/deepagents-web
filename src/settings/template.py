"""设置模块的出入参 pydantic 模型。"""

from pydantic import BaseModel, field_validator

APPROVAL_MODES = ("off", "dangerous", "dangerous+mcp", "all")
THINKING_EFFORTS = ("low", "high", "max")


class ModelRef(BaseModel):
    provider: str
    model: str


class SettingsBody(BaseModel):
    approvalMode: str | None = None
    # None 表示清除默认模型；缺省表示不修改（见 router 中的 model_fields_set）
    defaultModel: ModelRef | None = None

    @field_validator("approvalMode")
    @classmethod
    def _check_mode(cls, v):
        if v is not None and v not in APPROVAL_MODES:
            raise ValueError("invalid approvalMode")
        return v


class ProjectParams(BaseModel):
    thinking: str | None = None
    thinkingEffort: str | None = None
    temperature: float | None = None
    maxTokens: int | None = None

    @field_validator("temperature")
    @classmethod
    def _check_temperature(cls, v):
        if v is not None and not (0 <= v <= 2):
            raise ValueError("temperature must be 0-2")
        return v

    @field_validator("maxTokens")
    @classmethod
    def _check_max_tokens(cls, v):
        if v is not None and v <= 0:
            raise ValueError("maxTokens must be a positive integer")
        return v

    def normalized(self) -> dict:
        """只保留合法且被设置的字段，形状与前端约定一致。"""
        out: dict = {}
        if self.thinking in ("on", "off"):
            out["thinking"] = self.thinking
        if self.thinkingEffort in THINKING_EFFORTS:
            out["thinkingEffort"] = self.thinkingEffort
        if self.temperature is not None:
            out["temperature"] = self.temperature
        if self.maxTokens is not None:
            out["maxTokens"] = self.maxTokens
        return out


class ProjectConfigBody(BaseModel):
    key: str
    model: ModelRef | None = None
    params: ProjectParams | None = None
