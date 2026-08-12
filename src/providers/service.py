"""模型服务商（Cherry-Studio 式配置）。

服务商存 providers 表（name 主键），对外形状：
  { name, enabled, baseUrl, apiKey, models: [str], defaultModel, type? }

模型选择与生成参数都跟随「项目」（项目=工作目录；自动创建的 workspace
里的会话共享虚拟项目 __standalone__），存 settings.projectConfig：
  { [projectKey]: { model: {provider, model} | null,
                    params: { thinking?, thinkingEffort?, temperature?, maxTokens? } } }

会话所用模型的解析顺序：
  projectConfig[key].model -> settings.defaultModel -> 第一个启用服务商的默认模型
"""

import json
import re
import time

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.providers.model import ProviderRecord
from src.providers.template import ProviderBody
from src.settings.service import get_setting


def _public(r: ProviderRecord) -> dict:
    p = {
        "name": r.name,
        "enabled": bool(r.enabled),
        "baseUrl": r.base_url,
        "apiKey": r.api_key or "",
        "models": json.loads(r.models),
        "defaultModel": r.default_model,
    }
    if r.type:
        p["type"] = r.type
    return p


def _apply(row: ProviderRecord, body: ProviderBody) -> None:
    row.name = body.name
    row.enabled = 1 if body.enabled else 0
    row.base_url = body.base_url
    row.api_key = body.api_key
    row.models = json.dumps(body.models)
    row.default_model = body.default_model
    row.type = body.type


def get_providers(db: Session) -> list[dict]:
    return [_public(r) for r in db.scalars(select(ProviderRecord)).all()]


def create_provider(db: Session, body: ProviderBody) -> None:
    """新增服务商。重名由主键约束拦截（IntegrityError 走全局 handler）。"""
    row = ProviderRecord(name=body.name)
    _apply(row, body)
    db.add(row)
    db.commit()


def update_provider(db: Session, name: str, body: ProviderBody) -> bool:
    """更新服务商（body.name 与 name 不同即重命名）。不存在返回 False；
    重命名撞到已有名称由主键约束拦截。"""
    row = db.get(ProviderRecord, name)
    if row is None:
        return False
    _apply(row, body)
    db.commit()
    return True


def delete_provider(db: Session, name: str) -> None:
    row = db.get(ProviderRecord, name)
    if row:
        db.delete(row)
        db.commit()


def model_exists(db: Session, provider: str, model: str) -> bool:
    """启用的服务商下是否存在该模型。"""
    p = next((x for x in get_providers(db) if x.get("enabled") and x["name"] == provider), None)
    return bool(p and model in (p.get("models") or []))


def provider_type_of(p: dict | None) -> str:
    """服务商 API 方言。显式 type 优先，否则按 base URL 推断；目前只有
    deepseek 有特殊处理（思考模式），其余按 openai 兼容处理。"""
    if p and p.get("type"):
        return p["type"]
    return "deepseek" if re.search(r"deepseek", p.get("baseUrl") or "", re.I) else "openai"


def resolve_model(db: Session, project_key: str | None = None) -> dict:
    """解析一个项目（工作目录）应使用的具体模型。

    Returns {provider, model, baseUrl, apiKey, type}.
    """
    providers = [p for p in get_providers(db) if p.get("enabled")]

    def by_name(name):
        return next((p for p in providers if p["name"] == name), None)

    candidates = []
    if project_key:
        pc = get_setting(db, "projectConfig", {})
        entry = pc.get(project_key) or {}
        if entry.get("model"):
            candidates.append(entry["model"])
    default = get_setting(db, "defaultModel")
    if default:
        candidates.append(default)
    if providers:
        first = providers[0]
        candidates.append(
            {
                "provider": first["name"],
                "model": first.get("defaultModel") or first["models"][0],
            }
        )

    for c in candidates:
        p = by_name(c.get("provider")) if c and c.get("provider") else None
        if p and c.get("model") and c["model"] in (p.get("models") or []):
            return {
                "provider": p["name"],
                "model": c["model"],
                "baseUrl": p["baseUrl"],
                "apiKey": p.get("apiKey") or "",
                "type": provider_type_of(p),
            }

    raise RuntimeError("没有可用的模型：请在设置 → 模型服务中配置服务商")


def resolve_params(db: Session, project_key: str | None) -> dict:
    """解析项目的生成参数。None 字段表示未覆盖——跟随模型/服务商默认值。"""
    pc = get_setting(db, "projectConfig", {})
    p = (pc.get(project_key) or {}).get("params") or {} if project_key else {}
    return {
        "thinking": p.get("thinking") if p.get("thinking") in ("on", "off") else None,
        # DeepSeek effort levels: low / high / max ("medium" is a legacy value)
        "thinkingEffort": p["thinkingEffort"] if p.get("thinkingEffort") in ("low", "high", "max") else "high",
        "temperature": p.get("temperature"),
        "maxTokens": p.get("maxTokens"),
    }


async def test_provider(base_url: str, api_key: str, model: str) -> dict:
    """对 OpenAI 兼容 API 做连通性 + 基本补全测试。"""
    started = time.monotonic()

    def latency():
        return int((time.monotonic() - started) * 1000)

    try:
        async with httpx.AsyncClient(timeout=20.0, trust_env=False, verify=False) as client:
            res = await client.post(
                base_url.rstrip("/") + "/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": "ping — reply with pong only"}],
                    "max_tokens": 8,
                },
            )
        if res.status_code != 200:
            return {"ok": False, "latencyMs": latency(), "error": f"HTTP {res.status_code}: {res.text[:300]}"}
        data = res.json()
        reply = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        return {"ok": True, "latencyMs": latency(), "reply": str(reply)[:100]}
    except Exception as e:
        return {"ok": False, "latencyMs": latency(), "error": str(e)}
