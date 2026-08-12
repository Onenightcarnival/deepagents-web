"""应用设置：全局配置、审批模式、项目级模型与生成参数。"""

import contextlib
from enum import StrEnum

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from src.providers.service import model_exists, resolve_model
from src.settings import service
from src.settings.template import AllowlistBody, ProjectConfigBody, ProjectParams, SettingsBody
from src.utils.app_config import json_response
from src.utils.database import get_db, get_db_with_commit
from src.utils.resource_loader import CONFIG

router = APIRouter(prefix="/settings")


class SettingsCode(StrEnum):
    """settings 模块业务状态码（三段式规则见 utils/app_config.py）。"""

    OK = "WA-03-00"
    UNKNOWN_MODEL = "WA-03-01"


MESSAGES: dict[SettingsCode, str] = {
    SettingsCode.OK: "成功",
    SettingsCode.UNKNOWN_MODEL: "未知的服务商或模型",
}


@router.get("/")
async def get_config(db: Session = Depends(get_db)):
    default_model = None
    with contextlib.suppress(RuntimeError):
        m = resolve_model(db, None)
        default_model = {"provider": m["provider"], "model": m["model"]}
    return json_response(
        status.HTTP_200_OK,
        SettingsCode.OK,
        MESSAGES[SettingsCode.OK],
        data={
            "approvalMode": service.get_setting(db, "approvalMode", "dangerous"),
            "workspaceRoot": str(CONFIG.paths.workspace_root),
            "defaultModel": default_model,
            "projectConfig": service.get_setting(db, "projectConfig", {}),
            "approvalAllowlist": service.get_setting(db, "approvalAllowlist", {}),
        },
    )


@router.post("/")
async def post_settings(body: SettingsBody, db: Session = Depends(get_db_with_commit)):
    if body.approval_mode:
        service.set_setting(db, "approvalMode", body.approval_mode)
    if "default_model" in body.model_fields_set:
        service.set_setting(
            db,
            "defaultModel",
            body.default_model.model_dump() if body.default_model else None,
        )
    return json_response(status.HTTP_200_OK, SettingsCode.OK, MESSAGES[SettingsCode.OK])


@router.post("/project-config")
async def post_project_config(body: ProjectConfigBody, db: Session = Depends(get_db_with_commit)):
    has_model = "model" in body.model_fields_set
    if has_model and body.model and not model_exists(db, body.model.provider, body.model.model):
        return json_response(
            status.HTTP_400_BAD_REQUEST, SettingsCode.UNKNOWN_MODEL, MESSAGES[SettingsCode.UNKNOWN_MODEL]
        )
    model = body.model.model_dump() if has_model and body.model else None

    # params 传 null 时按空参数处理（与旧行为一致：entry.params = {}）
    has_params = "params" in body.model_fields_set
    params = (body.params or ProjectParams()).normalized() if has_params else None

    entry = service.update_project_config(db, body.key, model, params, has_model, has_params)
    return json_response(
        status.HTTP_200_OK, SettingsCode.OK, MESSAGES[SettingsCode.OK], data={"key": body.key, "config": entry}
    )


@router.post("/allowlist")
async def post_allowlist(body: AllowlistBody, db: Session = Depends(get_db_with_commit)):
    entry = service.update_allowlist(db, body.key, body.execute, body.tools)
    return json_response(
        status.HTTP_200_OK, SettingsCode.OK, MESSAGES[SettingsCode.OK], data={"key": body.key, "allowlist": entry}
    )
