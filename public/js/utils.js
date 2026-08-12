// 纯工具函数，不依赖任何模块
export const $ = (id) => document.getElementById(id);

export function esc(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

export function relTime(ts) {
  const d = Date.now() - ts;
  if (d < 60_000) return "刚刚";
  if (d < 3600_000) return `${Math.floor(d / 60_000)} 分钟前`;
  if (d < 86400_000) return `${Math.floor(d / 3600_000)} 小时前`;
  return `${Math.floor(d / 86400_000)} 天前`;
}

export function baseName(p) { return p.replace(/\/+$/, "").split("/").pop() || p; }

export function shortPath(p) { return p.replace(/^\/(Users|home)\/[^/]+/, "~"); }
