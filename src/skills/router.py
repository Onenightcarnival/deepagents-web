"""技能：目录配置、扫描、SKILL.md 查看。"""

from enum import StrEnum
from typing import Annotated

import anyio.to_thread
from fastapi import APIRouter, Depends, Form, UploadFile, status
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
    INVALID_ZIP = "WA-05-03"
    SKILL_EXISTS = "WA-05-04"
    DIR_NOT_CONFIGURED = "WA-05-05"
    DELETE_FAILED = "WA-05-06"


MESSAGES: dict[SkillCode, str] = {
    SkillCode.OK: "成功",
    SkillCode.PATH_REQUIRED: "缺少 path 参数",
    SkillCode.FILE_ERROR: "技能文件读取失败",
    SkillCode.INVALID_ZIP: "技能包不合法",
    SkillCode.SKILL_EXISTS: "技能已存在",
    SkillCode.DIR_NOT_CONFIGURED: "目标目录未在技能目录列表中",
    SkillCode.DELETE_FAILED: "技能删除失败",
}

# 上传的 zip 文件本体大小上限（解压后的限制见 service.MAX_ZIP_TOTAL_BYTES）
MAX_UPLOAD_BYTES = 20 * 1024 * 1024


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


@router.post("/upload")
async def upload_skill(
    file: UploadFile,
    dir: Annotated[str, Form()] = "",
    overwrite: Annotated[bool, Form()] = False,
    db: Session = Depends(get_db),
):
    """上传技能 zip：一包一技能，SKILL.md 须位于 zip 根或唯一顶层目录下，
    frontmatter 的 name 作为落盘目录名。"""
    dirs = service.get_skill_dirs(db)
    target = dir or (dirs[0] if dirs else "")
    if not target or target not in dirs:
        return json_response(
            status.HTTP_400_BAD_REQUEST, SkillCode.DIR_NOT_CONFIGURED, MESSAGES[SkillCode.DIR_NOT_CONFIGURED]
        )
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        return json_response(
            status.HTTP_400_BAD_REQUEST,
            SkillCode.INVALID_ZIP,
            f"{MESSAGES[SkillCode.INVALID_ZIP]}: 文件超过 {MAX_UPLOAD_BYTES // 1024 // 1024}MB",
        )
    try:
        # zipfile 是同步 IO，放线程池执行避免阻塞事件循环
        installed = await anyio.to_thread.run_sync(service.install_skill_zip, target, data, overwrite)
    except service.SkillExistsError as e:
        return json_response(
            status.HTTP_409_CONFLICT, SkillCode.SKILL_EXISTS, f"{MESSAGES[SkillCode.SKILL_EXISTS]}: {e}"
        )
    except ValueError as e:
        return json_response(
            status.HTTP_400_BAD_REQUEST, SkillCode.INVALID_ZIP, f"{MESSAGES[SkillCode.INVALID_ZIP]}: {e}"
        )
    return json_response(status.HTTP_200_OK, SkillCode.OK, MESSAGES[SkillCode.OK], data={"skill": installed})


@router.delete("/")
async def delete_skill(path: str | None = None, db: Session = Depends(get_db)):
    """按 SKILL.md 路径删除技能目录（含目录下所有文件）。"""
    if not path:
        return json_response(status.HTTP_400_BAD_REQUEST, SkillCode.PATH_REQUIRED, MESSAGES[SkillCode.PATH_REQUIRED])
    try:
        name = await anyio.to_thread.run_sync(service.delete_skill, service.get_skill_dirs(db), path)
    except (ValueError, OSError) as e:
        return json_response(
            status.HTTP_400_BAD_REQUEST, SkillCode.DELETE_FAILED, f"{MESSAGES[SkillCode.DELETE_FAILED]}: {e}"
        )
    return json_response(status.HTTP_200_OK, SkillCode.OK, MESSAGES[SkillCode.OK], data={"name": name})


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
