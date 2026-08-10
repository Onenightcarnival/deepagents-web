/**
 * Model provider configuration (Cherry-Studio style).
 *
 * Providers live in the settings table as a JSON array:
 *   [{ name, enabled, baseUrl, apiKey, models: [string], defaultModel }]
 *
 * Resolution order for the model used by a session:
 *   session.model ({provider, model}) -> settings.defaultModel -> first
 *   enabled provider's default model -> .env (MODEL_BASE_URL/KEY/NAME).
 */

/** Provider list derived from .env, used to seed first run / as fallback. */
export function envProvider(env = process.env) {
  if (!env.MODEL_BASE_URL || !env.MODEL_API_KEY || !env.MODEL_NAME) return null;
  return {
    name: "默认服务商",
    enabled: true,
    baseUrl: env.MODEL_BASE_URL,
    apiKey: env.MODEL_API_KEY,
    models: [env.MODEL_NAME],
    defaultModel: env.MODEL_NAME,
  };
}

/** Read providers from the db, seeding from .env on first use. */
export function getProviders(db) {
  let providers = db.getSetting("providers");
  if (!providers) {
    const seed = envProvider();
    providers = seed ? [seed] : [];
    if (seed) db.setSetting("providers", providers);
  }
  return providers;
}

export function validateProviders(providers) {
  if (!Array.isArray(providers)) return "providers must be an array";
  const seen = new Set();
  for (const p of providers) {
    if (!p.name?.trim()) return "每个服务商都需要名称";
    if (seen.has(p.name)) return `服务商名称重复: ${p.name}`;
    seen.add(p.name);
    if (p.enabled) {
      if (!p.baseUrl?.trim()) return `${p.name}: 缺少 API 地址`;
      if (!Array.isArray(p.models) || p.models.length === 0)
        return `${p.name}: 至少需要一个模型`;
    }
  }
  return null;
}

/**
 * Resolve which concrete model a session should use.
 * @returns {{provider: string, model: string, baseUrl: string, apiKey: string}}
 */
export function resolveModel(db, session) {
  const providers = getProviders(db).filter((p) => p.enabled);
  const byName = (name) => providers.find((p) => p.name === name);

  const candidates = [];
  if (session?.model) {
    try { candidates.push(JSON.parse(session.model)); } catch {}
  }
  const def = db.getSetting("defaultModel");
  if (def) candidates.push(def);
  if (providers[0]) {
    candidates.push({
      provider: providers[0].name,
      model: providers[0].defaultModel ?? providers[0].models[0],
    });
  }

  for (const c of candidates) {
    const p = c?.provider && byName(c.provider);
    if (p && c.model && p.models.includes(c.model)) {
      return { provider: p.name, model: c.model, baseUrl: p.baseUrl, apiKey: p.apiKey };
    }
  }

  const env = envProvider();
  if (env) {
    return { provider: env.name, model: env.models[0], baseUrl: env.baseUrl, apiKey: env.apiKey };
  }
  throw new Error("没有可用的模型：请在设置 → 模型服务中配置服务商，或在 .env 中配置 MODEL_*");
}

/** Quick connectivity + basic-completion test against an OpenAI-compatible API. */
export async function testProvider({ baseUrl, apiKey, model }) {
  const started = Date.now();
  try {
    const res = await fetch(`${baseUrl.replace(/\/+$/, "")}/chat/completions`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${apiKey}`,
      },
      body: JSON.stringify({
        model,
        messages: [{ role: "user", content: "ping — reply with pong only" }],
        max_tokens: 8,
      }),
      signal: AbortSignal.timeout(20_000),
    });
    const latencyMs = Date.now() - started;
    if (!res.ok) {
      const body = await res.text().catch(() => "");
      return { ok: false, latencyMs, error: `HTTP ${res.status}: ${body.slice(0, 300)}` };
    }
    const data = await res.json();
    const reply = data?.choices?.[0]?.message?.content ?? "";
    return { ok: true, latencyMs, reply: String(reply).slice(0, 100) };
  } catch (e) {
    return { ok: false, latencyMs: Date.now() - started, error: String(e?.message ?? e) };
  }
}
