"""模型服务商:列表、保存、连通性检测。"""

from fastapi import APIRouter

from src.providers import service
from src.providers.template import SaveProvidersBody, TestProviderBody
from src.settings.service import get_setting, set_setting

router = APIRouter(prefix="/api")


@router.get("/providers")
async def list_providers():
    return {"providers": service.get_providers(), "defaultModel": get_setting("defaultModel")}


@router.post("/providers")
async def save_providers(body: SaveProvidersBody):
    set_setting("providers", [p.model_dump(by_alias=True, exclude_none=True) for p in body.providers])
    return {"ok": True}


@router.post("/providers/test")
async def providers_test(body: TestProviderBody):
    return await service.test_provider(body.base_url, body.api_key, body.model)
