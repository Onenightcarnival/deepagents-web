"""应用设置：全局配置、审批模式、项目级模型与生成参数。"""

import contextlib

from fastapi import APIRouter, Request
from pydantic import ValidationError

from src.providers.service import get_providers, resolve_model
from src.settings import service
from src.settings.template import ProjectConfigBody, ProjectParams, SettingsBody
from src.utils.app_config import json_error, validation_error_message
from src.utils.resource_loader import CONFIG

router = APIRouter(prefix="/api")


@router.get("/config")
async def get_config():
    default_model = None
    with contextlib.suppress(RuntimeError):
        m = resolve_model(None)
        default_model = {"provider": m["provider"], "model": m["model"]}
    return {
        "approvalMode": service.get_setting("approvalMode", "dangerous"),
        "workspaceRoot": str(CONFIG.paths.workspace_root),
        "defaultModel": default_model,
        "projectConfig": service.get_setting("projectConfig", {}),
    }


@router.post("/settings")
async def post_settings(request: Request):
    try:
        body = SettingsBody.model_validate(await request.json())
    except ValidationError as e:
        return json_error(validation_error_message(e))
    if body.approvalMode:
        service.set_setting("approvalMode", body.approvalMode)
    if "defaultModel" in body.model_fields_set:
        service.set_setting(
            "defaultModel",
            body.defaultModel.model_dump() if body.defaultModel else None,
        )
    return {"ok": True}


@router.post("/project-config")
async def post_project_config(request: Request):
    try:
        body = ProjectConfigBody.model_validate(await request.json())
    except ValidationError as e:
        return json_error(validation_error_message(e))
    key = body.key.strip()
    if not key:
        return json_error("key required")

    has_model = "model" in body.model_fields_set
    model = None
    if has_model and body.model is not None:
        p = next(
            (x for x in get_providers() if x.get("enabled") and x["name"] == body.model.provider),
            None,
        )
        if not p or body.model.model not in (p.get("models") or []):
            return json_error("unknown provider/model")
        model = body.model.model_dump()

    # params 传 null 时按空参数处理（与旧行为一致：entry.params = {}）
    has_params = "params" in body.model_fields_set
    params = (body.params or ProjectParams()).normalized() if has_params else None

    entry = service.update_project_config(key, model, params, has_model, has_params)
    return {"ok": True, "key": key, "config": entry}
