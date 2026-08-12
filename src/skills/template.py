"""技能模块的出入参 pydantic 模型。"""
from pydantic import BaseModel, field_validator


class SkillDirsBody(BaseModel):
    dirs: list[str]

    @field_validator("dirs")
    @classmethod
    def _check_dirs(cls, v):
        if any(not d.strip() for d in v):
            raise ValueError("dirs must be a string array")
        return [d.strip() for d in v]
