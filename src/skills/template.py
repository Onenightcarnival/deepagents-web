"""技能模块的出入参 pydantic 模型。"""

from src.utils.template import ApiModel, NonBlankStr


class SkillDirsBody(ApiModel):
    dirs: list[NonBlankStr]
