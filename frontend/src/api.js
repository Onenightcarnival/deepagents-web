// API 上下文根，与 src/config/{env}.toml 的 server.context_root 保持一致
export const CTX = "/api";

export async function api(path, opts = {}) {
  const res = await fetch(CTX + path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  // 响应统一封装 { statusCode, message, data }，这里解包只返回 data
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.message || `HTTP ${res.status}`);
  return body.data;
}

// 通知宿主页面（public/ 下的 vanilla 部分）配置有变，刷新模型 chip / 技能 chip
export function notifySettingsChanged() {
  document.dispatchEvent(new CustomEvent("settings:changed"));
}
