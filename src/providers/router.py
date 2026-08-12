"""模型服务商：列表、单条增改删、连通性检测。"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src.providers import service
from src.providers.template import ProviderBody, TestProviderBody
from src.settings.service import get_setting
from src.utils.app_config import api_ok, json_error
from src.utils.database import get_db, get_db_with_commit

router = APIRouter(prefix="/api")


@router.get("/providers")
async def list_providers(db: Session = Depends(get_db)):
    return api_ok({"providers": service.get_providers(db), "defaultModel": get_setting(db, "defaultModel")})


@router.post("/providers")
async def create_provider(body: ProviderBody, db: Session = Depends(get_db_with_commit)):
    service.create_provider(db, body)  # 重名由主键约束触发 409（全局 handler）
    return api_ok()


@router.put("/providers/{name}")
async def update_provider(name: str, body: ProviderBody, db: Session = Depends(get_db_with_commit)):
    if not service.update_provider(db, name, body):
        return json_error("provider not found", 404)
    return api_ok()


@router.delete("/providers/{name}")
async def delete_provider(name: str, db: Session = Depends(get_db_with_commit)):
    service.delete_provider(db, name)
    return api_ok()


@router.post("/providers/test")
async def providers_test(body: TestProviderBody):
    return api_ok(await service.test_provider(body.base_url, body.api_key, body.model))
