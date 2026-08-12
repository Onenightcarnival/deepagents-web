<script setup>
import { useMessage } from "naive-ui";

import { api, notifySettingsChanged } from "../api.js";
import { store } from "../store.js";

const message = useMessage();

const APPROVAL_MODES = [
  { v: "off", t: "off — 全自动", d: "所有工具直接执行，不需要审批（信任模式，慎用）" },
  { v: "dangerous", t: "dangerous — 审批危险操作", d: "shell 命令、写文件、改文件需要审批（推荐）" },
  { v: "dangerous+mcp", t: "dangerous+mcp", d: "在 dangerous 基础上，MCP 工具调用也需要审批" },
  { v: "all", t: "all — 全部审批", d: "所有工具（包括只读）都需要审批" },
];

async function setMode(v) {
  try {
    await api("/settings/", { method: "POST", body: { approvalMode: v } });
    store.config = { ...store.config, approvalMode: v };
    notifySettingsChanged();
  } catch (e) { message.error(e.message); }
}

function shortPath(p) { return (p ?? "").replace(/^\/(Users|home)\/[^/]+/, "~"); }

const host = location.host;
</script>

<template>
  <div class="pane-inner">
    <h2>通用</h2>
    <div class="sub">审批模式即时生效。</div>

    <div class="sect-label">审批模式</div>
    <div
      v-for="m in APPROVAL_MODES" :key="m.v"
      class="radio-card" :class="{ on: (store.config?.approvalMode ?? 'dangerous') === m.v }"
      @click="setMode(m.v)"
    >
      <span class="r-dot"></span>
      <div>
        <div class="r-title">{{ m.t }}</div>
        <div class="r-desc">{{ m.d }}</div>
      </div>
    </div>

    <div class="sect-label" style="margin-top:22px">服务信息</div>
    <div class="kv"><span class="k">工作区根目录</span><span class="v">{{ shortPath(store.config?.workspaceRoot) }}</span></div>
    <div class="kv"><span class="k">监听地址</span><span class="v">{{ host }}</span></div>
    <div class="hint" style="margin-top:10px">
      局域网访问需在配置 toml 中把 server.host 改为 0.0.0.0 并重启服务。
    </div>
  </div>
</template>

<style scoped>
.pane-inner { max-width: 760px; margin: 0 auto; padding: 24px; }
.pane-inner h2 { font-size: 17px; margin: 0 0 4px; }
.sub { color: #8b949e; font-size: 13px; margin-bottom: 18px; }
.sect-label { color: #8b949e; font-size: 12px; margin: 16px 0 6px; }
.radio-card {
  display: flex; gap: 10px; align-items: flex-start; background: #161b22;
  border: 1px solid #30363d; border-radius: 10px; padding: 10px 14px;
  margin-bottom: 8px; cursor: pointer;
}
.radio-card.on { border-color: #58a6ff; }
.r-title { font-weight: 600; font-size: 13px; }
.r-desc { color: #8b949e; font-size: 12px; margin-top: 2px; }
.r-dot {
  width: 14px; height: 14px; border-radius: 50%; border: 2px solid #30363d;
  margin-top: 2px; flex: none;
}
.radio-card.on .r-dot { border-color: #58a6ff; background: #58a6ff; }
.kv { display: flex; gap: 10px; font-size: 13px; padding: 4px 0; }
.kv .k { color: #8b949e; width: 110px; flex: none; }
.kv .v { font-family: ui-monospace, monospace; word-break: break-all; }
.hint { color: #8b949e; font-size: 12px; }
</style>
