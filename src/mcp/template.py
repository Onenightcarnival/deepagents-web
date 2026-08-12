"""MCP 模块的出入参 pydantic 模型。"""

from typing import Literal

from pydantic import ConfigDict, Field

from src.utils.template import ApiModel, NonBlankStr


class McpServerBase(ApiModel):
    """MCP 服务器配置的公共约束：目前只支持 streamable http，且必须带 url。"""

    model_config = ConfigDict(extra="allow")

    transport: Literal["http"]
    url: NonBlankStr
    headers: dict[str, str] | None = None


class McpTestBody(McpServerBase):
    name: str | None = None


class McpUpsertBody(McpServerBase):
    """保存 MCP 服务器。除 name/enabled 外的字段整体作为 config 存库。"""

    name: str = Field(pattern=r"^[\w-]+$")
    enabled: bool = True
    disabled_tools: list[str] | None = None

    def to_config(self) -> dict:
        config = self.model_dump(by_alias=True, exclude={"name", "enabled"}, exclude_none=True)
        if not self.disabled_tools:
            config.pop("disabledTools", None)
        return config
