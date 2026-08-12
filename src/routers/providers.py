"""模型服务商：列表、保存、连通性检测。"""
from fastapi import APIRouter, Request

from ..services.providers import get_providers, test_provider, validate_providers
from ..utils.app_config import json_error
from ..utils.resource_loader import resources

router = APIRouter(prefix="/api")


@router.get("/providers")
async def list_providers():
    db = resources.db
    return {"providers": get_providers(db), "defaultModel": db.get_setting("defaultModel")}


@router.post("/providers")
async def save_providers(request: Request):
    body = await request.json()
    err = validate_providers(body.get("providers"))
    if err:
        return json_error(err)
    resources.db.set_setting("providers", body["providers"])
    return {"ok": True}


@router.post("/providers/test")
async def providers_test(request: Request):
    body = await request.json()
    base_url, api_key, model = body.get("baseUrl"), body.get("apiKey"), body.get("model")
    if not (base_url and api_key and model):
        return json_error("baseUrl / apiKey / model required")
    return await test_provider(base_url, api_key, model)
