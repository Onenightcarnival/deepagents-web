"""应用设置：全局配置、审批模式、项目级模型与生成参数。"""

import contextlib

from fastapi import APIRouter

from src.providers.service import model_exists, resolve_model
from src.settings import service
from src.settings.template import ProjectConfigBody, ProjectParams, SettingsBody
from src.utils.app_config import api_ok, json_error
from src.utils.database import DB
from src.utils.resource_loader import CONFIG

router = APIRouter(prefix="/api")


@router.get("/config")
async def get_config(db: DB):
    default_model = None
    with contextlib.suppress(RuntimeError):
        m = resolve_model(db, None)
        default_model = {"provider": m["provider"], "model": m["model"]}
    return api_ok(
        {
            "approvalMode": service.get_setting(db, "approvalMode", "dangerous"),
            "workspaceRoot": str(CONFIG.paths.workspace_root),
            "defaultModel": default_model,
            "projectConfig": service.get_setting(db, "projectConfig", {}),
        }
    )


@router.post("/settings")
async def post_settings(body: SettingsBody, db: DB):
    if body.approval_mode:
        service.set_setting(db, "approvalMode", body.approval_mode)
    if "default_model" in body.model_fields_set:
        service.set_setting(
            db,
            "defaultModel",
            body.default_model.model_dump() if body.default_model else None,
        )
    return api_ok()


@router.post("/project-config")
async def post_project_config(body: ProjectConfigBody, db: DB):
    has_model = "model" in body.model_fields_set
    if has_model and body.model and not model_exists(db, body.model.provider, body.model.model):
        return json_error("unknown provider/model")
    model = body.model.model_dump() if has_model and body.model else None

    # params 传 null 时按空参数处理（与旧行为一致：entry.params = {}）
    has_params = "params" in body.model_fields_set
    params = (body.params or ProjectParams()).normalized() if has_params else None

    entry = service.update_project_config(db, body.key, model, params, has_model, has_params)
    return api_ok({"key": body.key, "config": entry})
