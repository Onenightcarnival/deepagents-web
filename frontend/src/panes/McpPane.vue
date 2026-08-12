<script setup>
import { NButton, NCollapse, NCollapseItem, NInput, NPopconfirm, NSwitch, NTabPane, NTabs, useMessage } from "naive-ui";
import { onMounted, ref } from "vue";

import { api, notifySettingsChanged } from "../api.js";

const message = useMessage();

const servers = ref([]);
const selected = ref(null);   // 服务器名
const draft = ref(null);      // 未保存的新服务器
const tab = ref("general");
const inspect = ref({});      // 各服务器能力缓存，来自 /mcp/test
const formStatus = ref(null); // { ok, text }

// 通用表单的编辑副本（切换服务器时重建）
const form = ref({ name: "", url: "", headersText: "" });

onMounted(load);

async function load() {
  const { servers: list } = await api("/mcp/");
  servers.value = list;
  if (!draft.value && !list.find((s) => s.name === selected.value)) {
    selected.value = list[0]?.name ?? null;
  }
  syncForm();
}

function current() {
  return draft.value ?? servers.value.find((s) => s.name === selected.value) ?? null;
}

function syncForm() {
  const s = current();
  formStatus.value = null;
  form.value = s
    ? {
        name: s.name,
        url: s.url ?? "",
        headersText: s.headers ? Object.entries(s.headers).map(([k, v]) => `${k}: ${v}`).join("\n") : "",
      }
    : { name: "", url: "", headersText: "" };
}

function selectServer(s) {
  draft.value = null;
  selected.value = s.name;
  tab.value = "general";
  syncForm();
}

function startDraft() {
  draft.value = { name: "", transport: "http", url: "" };
  tab.value = "general";
  syncForm();
}

function buildConfig() {
  const s = current();
  const headers = {};
  for (const line of form.value.headersText.split("\n")) {
    const m = line.match(/^\s*([\w.-]+)\s*:\s*(.+)$/);
    if (m) headers[m[1]] = m[2].trim();
  }
  return {
    name: draft.value ? form.value.name.trim() : s.name,
    transport: "http",
    url: form.value.url.trim(),
    ...(Object.keys(headers).length ? { headers } : {}),
    ...(s?.disabledTools?.length ? { disabledTools: s.disabledTools } : {}),
  };
}

async function toggleEnabled(s) {
  const { name, enabled, ...config } = s;
  try {
    await api("/mcp/", { method: "POST", body: { name, enabled: !enabled, ...config } });
    notifySettingsChanged();
    await load();
  } catch (e) { message.error(e.message); }
}

async function testConnection() {
  formStatus.value = { ok: null, text: "连接中…" };
  try {
    const res = await api("/mcp/test", { method: "POST", body: buildConfig() });
    formStatus.value = res.ok
      ? { ok: true, text: `✓ ${res.tools.length} 个工具 · ${res.prompts.length} 个提示词 · ${res.resources.length} 个资源` }
      : { ok: false, text: `✗ ${res.error.slice(0, 160)}` };
  } catch (e) { formStatus.value = { ok: false, text: `✗ ${e.message}` }; }
}

async function save() {
  const c = buildConfig();
  if (!c.name || !/^[\w-]+$/.test(c.name)) { message.error("名称只能包含字母、数字、- 和 _"); return; }
  if (!c.url) { message.error("URL 不能为空"); return; }
  try {
    await api("/mcp/", { method: "POST", body: { ...c, enabled: draft.value ? true : current().enabled } });
    delete inspect.value[c.name];
    draft.value = null;
    selected.value = c.name;
    notifySettingsChanged();
    await load();
    message.success("已保存");
  } catch (e) { message.error(e.message); }
}

async function removeServer() {
  const s = current();
  try {
    await api(`/mcp/${s.name}`, { method: "DELETE" });
  } catch (e) { message.error(e.message); return; }
  delete inspect.value[s.name];
  selected.value = null;
  notifySettingsChanged();
  await load();
}

async function ensureInspect(force = false) {
  const s = current();
  if (!s || draft.value) return;
  if (force) delete inspect.value[s.name];
  if (inspect.value[s.name]) return;
  inspect.value[s.name] = { loading: true };
  let res;
  try { res = await api("/mcp/test", { method: "POST", body: s }); }
  catch (e) { res = { ok: false, error: e.message }; }
  inspect.value[s.name] = res;
}

function onTabChange(v) {
  tab.value = v;
  if (v !== "general") ensureInspect();
}

async function toggleTool(toolName) {
  const s = current();
  const set = new Set(s.disabledTools ?? []);
  if (set.has(toolName)) set.delete(toolName); else set.add(toolName);
  s.disabledTools = [...set];
  const { name, enabled, ...config } = s;
  try {
    await api("/mcp/", { method: "POST", body: { name, enabled, ...config } });
    notifySettingsChanged();
  } catch (e) { message.error(e.message); }
}

// ---- JSON Schema 摘要（工具参数文档） ----
function schemaType(p) {
  if (!p || typeof p !== "object") return "";
  if (Array.isArray(p.type)) return p.type.join(" | ");
  if (p.type) return p.type === "array" && p.items ? `${schemaType(p.items) || "any"}[]` : p.type;
  const union = p.anyOf ?? p.oneOf;
  if (union) return [...new Set(union.map(schemaType).filter((t) => t && t !== "null"))].join(" | ");
  return p.enum ? "enum" : "";
}

function schemaParams(schema) {
  if (!schema?.properties) return [];
  const req = new Set(schema.required ?? []);
  return Object.entries(schema.properties).map(([key, p]) => ({
    name: key,
    type: schemaType(p),
    required: req.has(key),
    desc: [
      p?.description,
      p?.enum ? `可选值：${p.enum.join("、")}` : "",
      p?.default !== undefined && p?.default !== null ? `默认：${JSON.stringify(p.default)}` : "",
    ].filter(Boolean).join("　"),
  }));
}

function promptParams(p) {
  return (p.arguments ?? []).map((a) => ({
    name: a.name, type: "", required: a.required, desc: a.description ?? "",
  }));
}

function disabledSet() {
  return new Set(current()?.disabledTools ?? []);
}
</script>

<template>
  <div class="layout">
    <div class="list">
      <div
        v-for="s in servers" :key="s.name"
        class="prov-item" :class="{ active: !draft && s.name === selected }"
        @click="selectServer(s)"
      >
        <span class="logo">{{ s.name.slice(0, 2).toUpperCase() }}</span>
        <span class="name">{{ s.name }}</span>
        <NSwitch size="small" :value="s.enabled" @click.stop @update:value="toggleEnabled(s)" />
      </div>
      <NButton class="add-btn" size="small" @click="startDraft">＋ 添加服务器</NButton>
    </div>

    <div v-if="current()" class="detail">
      <NTabs :value="tab" size="small" @update:value="onTabChange">
        <NTabPane name="general" tab="通用">
          <div class="field">
            <label>名称（字母数字-_）</label>
            <NInput v-model:value="form.name" size="small" :disabled="!draft" placeholder="my-server" />
          </div>
          <div class="field">
            <label>URL（Streamable HTTP）</label>
            <NInput v-model:value="form.url" size="small" class="mono" placeholder="http://localhost:8000/mcp" />
          </div>
          <div class="field">
            <label>请求头（每行一个 KEY: VALUE，可留空）</label>
            <NInput
              v-model:value="form.headersText" size="small" class="mono" type="textarea"
              :rows="3" placeholder="Authorization: Bearer xxx"
            />
          </div>
          <div class="btn-row">
            <NButton size="small" @click="testConnection">测试连接</NButton>
            <NButton size="small" type="primary" @click="save">保存</NButton>
            <NButton v-if="draft" size="small" @click="draft = null; syncForm()">取消</NButton>
            <NPopconfirm v-else positive-text="删除" negative-text="取消" @positive-click="removeServer">
              <template #trigger>
                <NButton size="small" type="error" ghost>删除此服务器</NButton>
              </template>
              删除 MCP 服务器「{{ current().name }}」？
            </NPopconfirm>
            <span v-if="formStatus" class="status" :class="{ ok: formStatus.ok, err: formStatus.ok === false }">
              {{ formStatus.text }}
            </span>
          </div>
          <div class="hint">保存后即时生效，作用于之后的对话轮次；工具名会以「服务器名__工具名」前缀注入。</div>
        </NTabPane>

        <NTabPane v-for="cap in ['tools', 'prompts', 'resources']" :key="cap" :name="cap" :disabled="!!draft"
          :tab="cap === 'tools' ? '工具' : cap === 'prompts' ? '提示词' : '资源'"
        >
          <div v-if="!inspect[current().name] || inspect[current().name].loading" class="hint">连接中…</div>
          <div v-else-if="!inspect[current().name].ok" class="status err" style="word-break:break-all">
            ✗ {{ inspect[current().name].error }}
          </div>
          <template v-else>
            <div class="cap-head">
              <span class="hint" style="margin:0">
                {{ inspect[current().name][cap].length }} 个{{ cap === "tools" ? "工具" : cap === "prompts" ? "提示词" : "资源" }}
                <template v-if="cap === 'tools'">
                  · 已启用 {{ inspect[current().name].tools.filter(t => !disabledSet().has(t.name)).length }}
                </template>
              </span>
              <NButton size="tiny" @click="ensureInspect(true)">刷新</NButton>
            </div>

            <NCollapse v-if="cap !== 'resources'">
              <NCollapseItem v-for="t in inspect[current().name][cap]" :key="t.name" :name="t.name">
                <template #header>
                  <span class="td-name" :class="{ off: cap === 'tools' && disabledSet().has(t.name) }">{{ t.name }}</span>
                  <span class="td-brief" :class="{ off: cap === 'tools' && disabledSet().has(t.name) }">
                    {{ t.description || "（无描述）" }}
                  </span>
                </template>
                <template v-if="cap === 'tools'" #header-extra>
                  <NSwitch size="small" :value="!disabledSet().has(t.name)" @click.stop @update:value="toggleTool(t.name)" />
                </template>
                <div v-if="t.description" class="td-desc">{{ t.description }}</div>
                <div class="td-params-label">参数</div>
                <template v-if="(cap === 'tools' ? schemaParams(t.schema) : promptParams(t)).length">
                  <div v-for="p in (cap === 'tools' ? schemaParams(t.schema) : promptParams(t))" :key="p.name" class="td-param">
                    <code>{{ p.name }}</code>
                    <span v-if="p.type" class="pt">{{ p.type }}</span>
                    <span v-if="p.required" class="preq">必填</span>
                    <span v-if="p.desc" class="pd">{{ p.desc }}</span>
                  </div>
                </template>
                <div v-else class="td-param hint" style="margin:0">无参数</div>
              </NCollapseItem>
            </NCollapse>

            <NCollapse v-else>
              <NCollapseItem v-for="r in inspect[current().name].resources" :key="r.uri" :name="r.uri">
                <template #header>
                  <span class="td-name">{{ r.name || r.uri }}</span>
                  <span class="td-brief">{{ r.description || r.uri }}</span>
                </template>
                <div class="td-param"><code>URI</code><span class="pd" style="flex-basis:auto">{{ r.uri }}</span></div>
                <div v-if="r.mimeType" class="td-param"><code>类型</code><span class="pd" style="flex-basis:auto">{{ r.mimeType }}</span></div>
                <div v-if="r.description" class="td-desc" style="margin-top:8px">{{ r.description }}</div>
              </NCollapseItem>
            </NCollapse>
          </template>
        </NTabPane>
      </NTabs>
    </div>
    <div v-else class="detail hint">
      尚未配置任何 MCP 服务器（仅支持 Streamable HTTP），点击左下角「＋ 添加服务器」。
    </div>
  </div>
</template>

<style scoped>
.layout { display: flex; height: 100%; }
.list {
  width: 230px; border-right: 1px solid #30363d; padding: 12px 8px;
  display: flex; flex-direction: column; gap: 2px; overflow-y: auto; flex: none;
}
.prov-item {
  display: flex; align-items: center; gap: 8px; padding: 8px 10px;
  border-radius: 8px; cursor: pointer;
}
.prov-item:hover, .prov-item.active { background: #21262d; }
.prov-item.active .name { color: #58a6ff; }
.logo {
  width: 26px; height: 26px; border-radius: 50%; background: #0d1117;
  border: 1px solid #30363d; display: flex; align-items: center; justify-content: center;
  font-size: 11px; color: #58a6ff; flex: none;
}
.name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 13px; }
.add-btn { margin-top: auto; }
.detail { flex: 1; overflow-y: auto; padding: 14px 24px; }
.field { margin-bottom: 10px; }
.field label { display: block; color: #8b949e; font-size: 12px; margin-bottom: 3px; }
.mono { font-family: ui-monospace, "SF Mono", Consolas, monospace; }
.btn-row { display: flex; gap: 8px; align-items: center; margin-top: 6px; flex-wrap: wrap; }
.status { font-size: 12px; color: #8b949e; }
.status.ok { color: #3fb950; }
.status.err { color: #f85149; }
.hint { color: #8b949e; font-size: 12px; margin-top: 10px; }
.cap-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 4px; }
.td-name {
  font-family: ui-monospace, monospace; font-size: 12.5px; font-weight: 600;
  color: #58a6ff; white-space: nowrap; margin-right: 10px;
}
.td-brief {
  font-size: 12px; color: #8b949e;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 340px;
  display: inline-block; vertical-align: bottom;
}
.td-name.off, .td-brief.off { opacity: 0.45; }
.td-desc { font-size: 12.5px; white-space: pre-wrap; margin-bottom: 8px; }
.td-params-label {
  font-size: 11px; color: #8b949e; text-transform: uppercase;
  letter-spacing: 0.5px; margin-bottom: 6px;
}
.td-param {
  display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap;
  padding: 5px 0; border-top: 1px solid #30363d; font-size: 12px;
}
.td-param code { font-family: ui-monospace, monospace; font-weight: 600; }
.pt { color: #8b949e; font-family: ui-monospace, monospace; font-size: 11px; }
.preq {
  font-size: 10px; color: #f85149; border: 1px solid #f85149;
  border-radius: 6px; padding: 0 5px;
}
.pd { flex-basis: 100%; color: #8b949e; white-space: pre-wrap; }
</style>
