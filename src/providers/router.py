"""模型服务商：列表、单条增改删、连通性检测。"""

from enum import StrEnum

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from src.providers import service
from src.providers.template import ProviderBody, TestProviderBody
from src.settings.service import get_setting
from src.utils.app_config import json_response
from src.utils.database import get_db, get_db_with_commit

router = APIRouter(prefix="/providers")


class ProviderCode(StrEnum):
    """providers 模块业务状态码（三段式规则见 utils/app_config.py）。"""

    OK = "WA-02-00"
    NOT_FOUND = "WA-02-01"


MESSAGES: dict[ProviderCode, str] = {
    ProviderCode.OK: "成功",
    ProviderCode.NOT_FOUND: "服务商不存在",
}


@router.get("/")
async def list_providers(db: Session = Depends(get_db)):
    return json_response(
        status.HTTP_200_OK,
        ProviderCode.OK,
        MESSAGES[ProviderCode.OK],
        data={"providers": service.get_providers(db), "defaultModel": get_setting(db, "defaultModel")},
    )


@router.post("/")
async def create_provider(body: ProviderBody, db: Session = Depends(get_db_with_commit)):
    service.create_provider(db, body)  # 重名由主键约束触发 409（全局 handler）
    return json_response(status.HTTP_200_OK, ProviderCode.OK, MESSAGES[ProviderCode.OK])


@router.put("/{name}")
async def update_provider(name: str, body: ProviderBody, db: Session = Depends(get_db_with_commit)):
    if not service.update_provider(db, name, body):
        return json_response(status.HTTP_404_NOT_FOUND, ProviderCode.NOT_FOUND, MESSAGES[ProviderCode.NOT_FOUND])
    return json_response(status.HTTP_200_OK, ProviderCode.OK, MESSAGES[ProviderCode.OK])


@router.delete("/{name}")
async def delete_provider(name: str, db: Session = Depends(get_db_with_commit)):
    service.delete_provider(db, name)
    return json_response(status.HTTP_200_OK, ProviderCode.OK, MESSAGES[ProviderCode.OK])


@router.post("/test")
async def providers_test(body: TestProviderBody):
    return json_response(
        status.HTTP_200_OK,
        ProviderCode.OK,
        MESSAGES[ProviderCode.OK],
        data=await service.test_provider(body.base_url, body.api_key, body.model),
    )
