// 全局共享状态（聊天壳层；设置页状态在 frontend/ 的 Vue 应用内自管理）
export const state = {
  sessions: [],
  current: null,
  streaming: false,
  liveAssistant: null,
  streamAbort: null,     // 当前 /stream 订阅的 AbortController
  skipUserEvent: false,  // 发送方页签已本地渲染过自己的用户消息
  config: null,          // GET /settings
  skills: { dirs: [], skills: [] },
  usage: { context: 0, total: 0 },  // 当前会话 token 用量（context=最近一次调用，total=累计）
  collapsed: new Set(JSON.parse(localStorage.getItem("collapsedGroups") || "[]")),
};

export function saveCollapsed() {
  localStorage.setItem("collapsedGroups", JSON.stringify([...state.collapsed]));
}
