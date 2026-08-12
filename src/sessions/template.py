"""会话模块的出入参 pydantic 模型。"""

from typing import Annotated

from pydantic import Field, StringConstraints

from src.utils.template import ApiModel, NonBlankStr


class CreateSessionBody(ApiModel):
    cwd: str | None = None
    title: str | None = None


class PatchSessionBody(ApiModel):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)] | None = None


class MessageBody(ApiModel):
    content: NonBlankStr


class ResumeBody(ApiModel):
    decisions: list[dict] = Field(min_length=1)
