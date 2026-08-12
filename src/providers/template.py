"""服务商模块的出入参 pydantic 模型。

服务商条目本身的结构校验带用户可读的中文提示（重名、缺地址等），
留在 service.validate_providers；这里只约束请求外层形状。
"""

from pydantic import BaseModel


class SaveProvidersBody(BaseModel):
    providers: list[dict]


class TestProviderBody(BaseModel):
    baseUrl: str
    apiKey: str
    model: str
