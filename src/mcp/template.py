"""MCP 模块的出入参 pydantic 模型。"""
import re

from pydantic import BaseModel, ConfigDict, field_validator


class McpTestBody(BaseModel):
    model_config = ConfigDict(extra="allow")

    transport: str
    url: str | None = None
    name: str | None = None
    headers: dict[str, str] | None = None


class McpUpsertBody(BaseModel):
    """保存 MCP 服务器。除 name/enabled 外的字段整体作为 config 存库。"""

    model_config = ConfigDict(extra="allow")

    name: str
    enabled: bool = True
    transport: str
    url: str | None = None
    headers: dict[str, str] | None = None
    disabledTools: list | None = None

    @field_validator("name")
    @classmethod
    def _check_name(cls, v):
        if not re.fullmatch(r"[\w-]+", v or ""):
            raise ValueError("invalid name")
        return v

    def to_config(self) -> dict:
        config = self.model_dump(exclude={"name", "enabled"}, exclude_none=True)
        tools = [t for t in (self.disabledTools or []) if isinstance(t, str)]
        config.pop("disabledTools", None)
        if tools:
            config["disabledTools"] = tools
        return config
