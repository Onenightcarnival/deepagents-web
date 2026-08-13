// API 上下文根：后端返回 index.html 时注入 window.__CTX__（server.context_root），
// 未注入时（如 Vite dev server）回退 /api，与 Vite proxy 约定一致
export const CTX = window.__CTX__ ?? "/api";

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

// multipart 上传：不能设 Content-Type，让浏览器自己带 boundary
export async function apiUpload(path, formData) {
  const res = await fetch(CTX + path, { method: "POST", body: formData });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.message || `HTTP ${res.status}`);
  return body.data;
}

// 通知宿主页面（public/ 下的 vanilla 部分）配置有变，刷新模型 chip / 技能 chip
export function notifySettingsChanged() {
  document.dispatchEvent(new CustomEvent("settings:changed"));
}
