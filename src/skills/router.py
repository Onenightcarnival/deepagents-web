"""技能：目录配置、扫描、SKILL.md 查看。"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src.settings.service import set_setting
from src.skills import service
from src.skills.template import SkillDirsBody
from src.utils.app_config import api_ok, json_error
from src.utils.database import get_db, get_db_with_commit

router = APIRouter(prefix="/api")


@router.get("/skills")
async def list_skills(db: Session = Depends(get_db)):
    dirs = service.get_skill_dirs(db)
    result = service.scan_skills(dirs)
    return api_ok({"dirs": dirs, "skills": result["skills"], "errors": result["errors"]})


@router.post("/skills/dirs")
async def save_skill_dirs(body: SkillDirsBody, db: Session = Depends(get_db_with_commit)):
    set_setting(db, "skillDirs", body.dirs)
    return api_ok()


@router.get("/skills/file")
async def get_skill_file(path: str | None = None, db: Session = Depends(get_db)):
    if not path:
        return json_error("path required")
    try:
        return api_ok({"path": path, "content": service.read_skill_file(service.get_skill_dirs(db), path)})
    except ValueError as e:
        return json_error(str(e))
