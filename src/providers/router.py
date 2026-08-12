"""模型服务商:列表、保存、连通性检测。"""

from fastapi import APIRouter, Request
from pydantic import ValidationError

from src.providers import service
from src.providers.template import SaveProvidersBody, TestProviderBody
from src.settings.service import get_setting, set_setting
from src.utils.app_config import json_error

router = APIRouter(prefix="/api")


@router.get("/providers")
async def list_providers():
    return {"providers": service.get_providers(), "defaultModel": get_setting("defaultModel")}


@router.post("/providers")
async def save_providers(request: Request):
    try:
        body = SaveProvidersBody.model_validate(await request.json())
    except ValidationError:
        return json_error("providers must be an array")
    err = service.validate_providers(body.providers)
    if err:
        return json_error(err)
    set_setting("providers", body.providers)
    return {"ok": True}


@router.post("/providers/test")
async def providers_test(request: Request):
    try:
        body = TestProviderBody.model_validate(await request.json())
    except ValidationError:
        return json_error("baseUrl / apiKey / model required")
    return await service.test_provider(body.baseUrl, body.apiKey, body.model)
