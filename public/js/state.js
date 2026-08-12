// 全局共享状态（单页应用内的唯一可变状态入口）
export const state = {
  sessions: [],
  current: null,
  streaming: false,
  liveAssistant: null,
  streamAbort: null,     // 当前 /stream 订阅的 AbortController
  skipUserEvent: false,  // 发送方页签已本地渲染过自己的用户消息
  config: null,          // GET /settings
  providers: [],         // 设置页里的工作副本
  providersDirty: false,
  selectedProvider: 0,
  skills: { dirs: [], skills: [] },
  mcpServers: [],
  selectedMcp: null,     // 详情面板当前展示的服务器名
  mcpDraft: null,        // 未保存的新服务器配置，或 null
  mcpTab: "general",     // general | tools | prompts | resources
  mcpInspect: {},        // 各服务器能力缓存，来自 /mcp/test
  collapsed: new Set(JSON.parse(localStorage.getItem("collapsedGroups") || "[]")),
};

export function saveCollapsed() {
  localStorage.setItem("collapsedGroups", JSON.stringify([...state.collapsed]));
}
