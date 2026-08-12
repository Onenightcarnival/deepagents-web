"""Model provider configuration (Cherry-Studio style).

Providers live in the settings table as a JSON array:
  [{ name, enabled, baseUrl, apiKey, models: [str], defaultModel }]

Model selection and generation params both follow the *project* (a project
is a working directory; sessions in auto-created workspaces share the
virtual project "__standalone__"). Stored in settings.projectConfig:
  { [projectKey]: { model: {provider, model} | null,
                    params: { thinking?, thinkingEffort?, temperature?, maxTokens? } } }

Resolution order for the model used by a session:
  projectConfig[key].model -> settings.defaultModel -> first enabled
  provider's default model -> .env (MODEL_BASE_URL/KEY/NAME).
"""
import os
import re
import time

import httpx


def env_provider() -> dict | None:
    """Provider derived from .env, used to seed first run / as fallback."""
    base_url = os.environ.get("MODEL_BASE_URL")
    api_key = os.environ.get("MODEL_API_KEY")
    model = os.environ.get("MODEL_NAME")
    if not (base_url and api_key and model):
        return None
    return {
        "name": "默认服务商",
        "enabled": True,
        "baseUrl": base_url,
        "apiKey": api_key,
        "models": [model],
        "defaultModel": model,
    }


def get_providers(db) -> list[dict]:
    """Read providers from the db, seeding from .env on first use."""
    providers = db.get_setting("providers")
    if providers is None:
        seed = env_provider()
        providers = [seed] if seed else []
        if seed:
            db.set_setting("providers", providers)
    return providers


def validate_providers(providers) -> str | None:
    if not isinstance(providers, list):
        return "providers must be an array"
    seen = set()
    for p in providers:
        name = (p.get("name") or "").strip()
        if not name:
            return "每个服务商都需要名称"
        if name in seen:
            return f"服务商名称重复: {name}"
        seen.add(name)
        if p.get("enabled"):
            if not (p.get("baseUrl") or "").strip():
                return f"{name}: 缺少 API 地址"
            models = p.get("models")
            if not isinstance(models, list) or len(models) == 0:
                return f"{name}: 至少需要一个模型"
    return None


def provider_type_of(p: dict | None) -> str:
    """Provider API dialect. Explicit `type` wins; otherwise inferred from the
    base URL. Currently only "deepseek" gets special treatment (thinking mode);
    everything else is plain "openai"-compatible."""
    if p and p.get("type"):
        return p["type"]
    return "deepseek" if re.search(r"deepseek", p.get("baseUrl") or "", re.I) else "openai"


def resolve_model(db, project_key: str | None = None) -> dict:
    """Resolve which concrete model a project (working directory) should use.

    Returns {provider, model, baseUrl, apiKey, type}.
    """
    providers = [p for p in get_providers(db) if p.get("enabled")]

    def by_name(name):
        return next((p for p in providers if p["name"] == name), None)

    candidates = []
    if project_key:
        pc = db.get_setting("projectConfig", {})
        entry = pc.get(project_key) or {}
        if entry.get("model"):
            candidates.append(entry["model"])
    default = db.get_setting("defaultModel")
    if default:
        candidates.append(default)
    if providers:
        first = providers[0]
        candidates.append({
            "provider": first["name"],
            "model": first.get("defaultModel") or first["models"][0],
        })

    for c in candidates:
        p = by_name(c.get("provider")) if c and c.get("provider") else None
        if p and c.get("model") and c["model"] in (p.get("models") or []):
            return {
                "provider": p["name"], "model": c["model"],
                "baseUrl": p["baseUrl"], "apiKey": p.get("apiKey") or "",
                "type": provider_type_of(p),
            }

    env = env_provider()
    if env:
        return {
            "provider": env["name"], "model": env["models"][0],
            "baseUrl": env["baseUrl"], "apiKey": env["apiKey"],
            "type": provider_type_of(env),
        }
    raise RuntimeError("没有可用的模型：请在设置 → 模型服务中配置服务商，或在 .env 中配置 MODEL_*")


def resolve_params(db, project_key: str | None) -> dict:
    """Resolve generation params for a project. Fields left None mean
    "not overridden — follow the model/provider default"."""
    pc = db.get_setting("projectConfig", {})
    p = (pc.get(project_key) or {}).get("params") or {} if project_key else {}
    return {
        "thinking": p.get("thinking") if p.get("thinking") in ("on", "off") else None,
        # DeepSeek effort levels: low / high / max ("medium" is a legacy value)
        "thinkingEffort": p["thinkingEffort"]
        if p.get("thinkingEffort") in ("low", "high", "max") else "high",
        "temperature": p.get("temperature"),
        "maxTokens": p.get("maxTokens"),
    }


async def test_provider(base_url: str, api_key: str, model: str) -> dict:
    """Quick connectivity + basic-completion test against an OpenAI-compatible API."""
    started = time.monotonic()

    def latency():
        return int((time.monotonic() - started) * 1000)

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
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
            return {"ok": False, "latencyMs": latency(),
                    "error": f"HTTP {res.status_code}: {res.text[:300]}"}
        data = res.json()
        reply = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        return {"ok": True, "latencyMs": latency(), "reply": str(reply)[:100]}
    except Exception as e:
        return {"ok": False, "latencyMs": latency(), "error": str(e)}
