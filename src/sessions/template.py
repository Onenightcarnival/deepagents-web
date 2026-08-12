"""会话模块的出入参 pydantic 模型。"""
from pydantic import BaseModel, field_validator


class CreateSessionBody(BaseModel):
    cwd: str | None = None
    title: str | None = None


class PatchSessionBody(BaseModel):
    title: str | None = None

    @field_validator("title")
    @classmethod
    def _check_title(cls, v):
        if v is not None:
            v = v.strip()
            if not v:
                raise ValueError("title cannot be empty")
            v = v[:80]
        return v


class MessageBody(BaseModel):
    content: str

    @field_validator("content")
    @classmethod
    def _check_content(cls, v):
        v = (v or "").strip()
        if not v:
            raise ValueError("empty message")
        return v


class ResumeBody(BaseModel):
    decisions: list[dict]

    @field_validator("decisions")
    @classmethod
    def _check_decisions(cls, v):
        if not v:
            raise ValueError("decisions required")
        return v
