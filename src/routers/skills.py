"""技能：目录配置、扫描、SKILL.md 查看。"""
from fastapi import APIRouter, Request

from ..services.skills import get_skill_dirs, read_skill_file, scan_skills
from ..utils.app_config import json_error
from ..utils.resource_loader import resources

router = APIRouter(prefix="/api")


@router.get("/skills")
async def list_skills():
    dirs = get_skill_dirs(resources.db)
    result = scan_skills(dirs)
    return {"dirs": dirs, "skills": result["skills"], "errors": result["errors"]}


@router.post("/skills/dirs")
async def save_skill_dirs(request: Request):
    body = await request.json()
    dirs = body.get("dirs")
    if not isinstance(dirs, list) or any(not isinstance(d, str) or not d.strip() for d in dirs):
        return json_error("dirs must be a string array")
    resources.db.set_setting("skillDirs", [d.strip() for d in dirs])
    return {"ok": True}


@router.get("/skills/file")
async def get_skill_file(path: str | None = None):
    if not path:
        return json_error("path required")
    try:
        return {"path": path, "content": read_skill_file(get_skill_dirs(resources.db), path)}
    except ValueError as e:
        return json_error(str(e))
