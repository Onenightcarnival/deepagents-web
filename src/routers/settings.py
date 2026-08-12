"""应用设置：全局配置、审批模式、项目级模型与生成参数。"""
import contextlib

from fastapi import APIRouter, Request

from ..services.providers import get_providers, resolve_model
from ..utils.app_config import json_error
from ..utils.resource_loader import CONFIG, resources

router = APIRouter(prefix="/api")


@router.get("/config")
async def get_config():
    db = resources.db
    default_model = None
    with contextlib.suppress(RuntimeError):
        m = resolve_model(db, None)
        default_model = {"provider": m["provider"], "model": m["model"]}
    return {
        "approvalMode": db.get_setting("approvalMode", "dangerous"),
        "workspaceRoot": str(CONFIG.paths.workspace_root),
        "defaultModel": default_model,
        "projectConfig": db.get_setting("projectConfig", {}),
    }


@router.post("/settings")
async def post_settings(request: Request):
    db = resources.db
    body = await request.json()
    if body.get("approvalMode"):
        if body["approvalMode"] not in ("off", "dangerous", "dangerous+mcp", "all"):
            return json_error("invalid approvalMode")
        db.set_setting("approvalMode", body["approvalMode"])
    if "defaultModel" in body:
        db.set_setting("defaultModel", body["defaultModel"])  # {provider, model} | None
    return {"ok": True}


@router.post("/project-config")
async def post_project_config(request: Request):
    db = resources.db
    body = await request.json()
    key = str(body.get("key") or "").strip()
    if not key:
        return json_error("key required")
    cfg = db.get_setting("projectConfig", {})
    entry = cfg.get(key) or {}
    if "model" in body:
        if body["model"] is None:
            entry["model"] = None
        else:
            p = next(
                (x for x in get_providers(db)
                 if x.get("enabled") and x["name"] == body["model"].get("provider")),
                None,
            )
            if not p or body["model"].get("model") not in (p.get("models") or []):
                return json_error("unknown provider/model")
            entry["model"] = {"provider": body["model"]["provider"], "model": body["model"]["model"]}
    if "params" in body:
        src = body.get("params") or {}
        params: dict = {}
        if src.get("thinking") in ("on", "off"):
            params["thinking"] = src["thinking"]
        if src.get("thinkingEffort") in ("low", "high", "max"):
            params["thinkingEffort"] = src["thinkingEffort"]
        if src.get("temperature") is not None:
            try:
                t = float(src["temperature"])
            except (TypeError, ValueError):
                t = -1
            if not (0 <= t <= 2):
                return json_error("temperature must be 0-2")
            params["temperature"] = t
        if src.get("maxTokens") is not None:
            try:
                n = int(float(src["maxTokens"]))
            except (TypeError, ValueError):
                n = 0
            if n <= 0:
                return json_error("maxTokens must be a positive integer")
            params["maxTokens"] = n
        entry["params"] = params
    cfg[key] = entry
    db.set_setting("projectConfig", cfg)
    return {"ok": True, "key": key, "config": entry}
