"""模型服务商（Cherry-Studio 式配置）。

服务商列表存在 settings 表的 providers 键（JSON 数组）：
  [{ name, enabled, baseUrl, apiKey, models: [str], defaultModel }]

模型选择与生成参数都跟随「项目」（项目=工作目录；自动创建的 workspace
里的会话共享虚拟项目 __standalone__），存 settings.projectConfig：
  { [projectKey]: { model: {provider, model} | null,
                    params: { thinking?, thinkingEffort?, temperature?, maxTokens? } } }

会话所用模型的解析顺序：
  projectConfig[key].model -> settings.defaultModel -> 第一个启用服务商的默认模型
"""

import re
import time

import httpx

from src.settings.service import get_setting


def get_providers() -> list[dict]:
    return get_setting("providers") or []


def model_exists(provider: str, model: str) -> bool:
    """启用的服务商下是否存在该模型。"""
    p = next((x for x in get_providers() if x.get("enabled") and x["name"] == provider), None)
    return bool(p and model in (p.get("models") or []))


def provider_type_of(p: dict | None) -> str:
    """服务商 API 方言。显式 type 优先，否则按 base URL 推断；目前只有
    deepseek 有特殊处理（思考模式），其余按 openai 兼容处理。"""
    if p and p.get("type"):
        return p["type"]
    return "deepseek" if re.search(r"deepseek", p.get("baseUrl") or "", re.I) else "openai"


def resolve_model(project_key: str | None = None) -> dict:
    """解析一个项目（工作目录）应使用的具体模型。

    Returns {provider, model, baseUrl, apiKey, type}.
    """
    providers = [p for p in get_providers() if p.get("enabled")]

    def by_name(name):
        return next((p for p in providers if p["name"] == name), None)

    candidates = []
    if project_key:
        pc = get_setting("projectConfig", {})
        entry = pc.get(project_key) or {}
        if entry.get("model"):
            candidates.append(entry["model"])
    default = get_setting("defaultModel")
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


def resolve_params(project_key: str | None) -> dict:
    """解析项目的生成参数。None 字段表示未覆盖——跟随模型/服务商默认值。"""
    pc = get_setting("projectConfig", {})
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
