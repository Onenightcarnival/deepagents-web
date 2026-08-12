"""技能：目录配置、扫描、SKILL.md 查看。"""

from enum import StrEnum

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from src.settings.service import set_setting
from src.skills import service
from src.skills.template import SkillDirsBody
from src.utils.app_config import json_response
from src.utils.database import get_db, get_db_with_commit

router = APIRouter(prefix="/skills")


class SkillCode(StrEnum):
    """skills 模块业务状态码（三段式规则见 utils/app_config.py）。"""

    OK = "WA-05-00"
    PATH_REQUIRED = "WA-05-01"
    FILE_ERROR = "WA-05-02"


MESSAGES: dict[SkillCode, str] = {
    SkillCode.OK: "成功",
    SkillCode.PATH_REQUIRED: "缺少 path 参数",
    SkillCode.FILE_ERROR: "技能文件读取失败",
}


@router.get("/")
async def list_skills(db: Session = Depends(get_db)):
    dirs = service.get_skill_dirs(db)
    result = service.scan_skills(dirs)
    return json_response(
        status.HTTP_200_OK,
        SkillCode.OK,
        MESSAGES[SkillCode.OK],
        data={"dirs": dirs, "skills": result["skills"], "errors": result["errors"]},
    )


@router.post("/dirs")
async def save_skill_dirs(body: SkillDirsBody, db: Session = Depends(get_db_with_commit)):
    set_setting(db, "skillDirs", body.dirs)
    return json_response(status.HTTP_200_OK, SkillCode.OK, MESSAGES[SkillCode.OK])


@router.get("/file")
async def get_skill_file(path: str | None = None, db: Session = Depends(get_db)):
    if not path:
        return json_response(status.HTTP_400_BAD_REQUEST, SkillCode.PATH_REQUIRED, MESSAGES[SkillCode.PATH_REQUIRED])
    try:
        return json_response(
            status.HTTP_200_OK,
            SkillCode.OK,
            MESSAGES[SkillCode.OK],
            data={"path": path, "content": service.read_skill_file(service.get_skill_dirs(db), path)},
        )
    except ValueError as e:
        return json_response(
            status.HTTP_400_BAD_REQUEST, SkillCode.FILE_ERROR, f"{MESSAGES[SkillCode.FILE_ERROR]}: {e}"
        )
