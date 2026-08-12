"""技能：目录配置、扫描、SKILL.md 查看。"""

from fastapi import APIRouter, Request
from pydantic import ValidationError

from src.settings.service import set_setting
from src.skills import service
from src.skills.template import SkillDirsBody
from src.utils.app_config import json_error

router = APIRouter(prefix="/api")


@router.get("/skills")
async def list_skills():
    dirs = service.get_skill_dirs()
    result = service.scan_skills(dirs)
    return {"dirs": dirs, "skills": result["skills"], "errors": result["errors"]}


@router.post("/skills/dirs")
async def save_skill_dirs(request: Request):
    try:
        body = SkillDirsBody.model_validate(await request.json())
    except ValidationError:
        return json_error("dirs must be a string array")
    set_setting("skillDirs", body.dirs)
    return {"ok": True}


@router.get("/skills/file")
async def get_skill_file(path: str | None = None):
    if not path:
        return json_error("path required")
    try:
        return {"path": path, "content": service.read_skill_file(service.get_skill_dirs(), path)}
    except ValueError as e:
        return json_error(str(e))
