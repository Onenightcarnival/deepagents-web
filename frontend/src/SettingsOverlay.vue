<script setup>
import { useDialog } from "naive-ui";
import { ref } from "vue";

import GeneralPane from "./panes/GeneralPane.vue";
import McpPane from "./panes/McpPane.vue";
import ProvidersPane from "./panes/ProvidersPane.vue";
import SkillsPane from "./panes/SkillsPane.vue";
import { store } from "./store.js";

const emit = defineEmits(["close"]);
const dialog = useDialog();

const NAV = [
  { key: "providers", icon: "🧩", label: "模型服务", comp: ProvidersPane },
  { key: "mcp", icon: "🛠", label: "MCP 服务器", comp: McpPane },
  { key: "skills", icon: "⚡", label: "技能", comp: SkillsPane },
  { key: "general", icon: "⚙", label: "通用", comp: GeneralPane },
];
const active = ref("providers");

function close() {
  if (store.providersDirty) {
    dialog.warning({
      title: "未保存的更改",
      content: "模型服务有未保存的更改，确定离开？",
      positiveText: "离开",
      negativeText: "留下",
      onPositiveClick: () => {
        store.providersDirty = false;
        emit("close");
      },
    });
    return;
  }
  emit("close");
}
</script>

<template>
  <div class="overlay">
    <div class="top">
      <button class="back" @click="close">← 返回</button>
      <h2>设置</h2>
    </div>
    <div class="body">
      <div class="nav">
        <div
          v-for="n in NAV" :key="n.key"
          class="nav-item" :class="{ active: active === n.key }"
          @click="active = n.key"
        >
          <span>{{ n.icon }}</span><span>{{ n.label }}</span>
        </div>
      </div>
      <div class="pane">
        <template v-for="n in NAV" :key="n.key">
          <component :is="n.comp" v-show="active === n.key" />
        </template>
      </div>
    </div>
  </div>
</template>

<style scoped>
.overlay {
  position: fixed; inset: 0; background: #0d1117; z-index: 20;
  display: flex; flex-direction: column;
  color: #e6edf3; font-size: 14px;
}
.top {
  padding: 12px 20px; border-bottom: 1px solid #30363d;
  display: flex; align-items: center; gap: 14px;
}
.top h2 { font-size: 15px; margin: 0; }
.back {
  background: none; border: none; color: #8b949e; cursor: pointer; font-size: 13px; padding: 6px 8px;
}
.back:hover { color: #e6edf3; }
.body { flex: 1; display: flex; min-height: 0; }
.nav {
  width: 190px; border-right: 1px solid #30363d; padding: 12px 8px; background: #161b22;
}
.nav-item {
  display: flex; gap: 8px; align-items: center; padding: 8px 10px;
  border-radius: 6px; cursor: pointer; color: #8b949e; margin-bottom: 2px;
}
.nav-item:hover { background: #21262d; }
.nav-item.active { background: #21262d; color: #58a6ff; }
.pane { flex: 1; overflow-y: auto; min-height: 0; }
</style>
