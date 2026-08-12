"""API 出入参模型基类。

字段名按 Python 规范用蛇形；对外（请求体、存库 JSON、前端响应）契约是
camelCase，由 to_camel 别名生成器自动映射。跨边界序列化时用
`model_dump(by_alias=True)`。
"""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints
from pydantic.alias_generators import to_camel

NonBlankStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
