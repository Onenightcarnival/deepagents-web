"""模型服务商：列表、单条增改删、连通性检测。"""

from fastapi import APIRouter
from sqlalchemy.exc import IntegrityError

from src.providers import service
from src.providers.template import ProviderBody, TestProviderBody
from src.settings.service import get_setting
from src.utils.app_config import json_error

router = APIRouter(prefix="/api")


@router.get("/providers")
async def list_providers():
    return {"providers": service.get_providers(), "defaultModel": get_setting("defaultModel")}


@router.post("/providers")
async def create_provider(body: ProviderBody):
    try:
        service.create_provider(body)
    except IntegrityError:
        return json_error(f"服务商已存在: {body.name}", 409)
    return {"ok": True}


@router.put("/providers/{name}")
async def update_provider(name: str, body: ProviderBody):
    try:
        if not service.update_provider(name, body):
            return json_error("provider not found", 404)
    except IntegrityError:
        return json_error(f"服务商已存在: {body.name}", 409)
    return {"ok": True}


@router.delete("/providers/{name}")
async def delete_provider(name: str):
    service.delete_provider(name)
    return {"ok": True}


@router.post("/providers/test")
async def providers_test(body: TestProviderBody):
    return await service.test_provider(body.base_url, body.api_key, body.model)
