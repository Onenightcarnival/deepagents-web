<script setup>
import { NButton, NInput, NPopconfirm, NSelect, NSwitch, useMessage } from "naive-ui";
import { onMounted, ref } from "vue";

import { api, notifySettingsChanged } from "../api.js";
import { store } from "../store.js";

const message = useMessage();

const providers = ref([]);
const selected = ref(0);
const testResult = ref(null); // { ok, text }
const newModel = ref("");

onMounted(load);

async function load() {
  const { providers: list } = await api("/providers/");
  // _orig 是服务端主键，重命名时用它定位记录
  providers.value = list.map((p) => ({ ...p, _orig: p.name }));
  store.providersDirty = false;
  selected.value = Math.min(selected.value, Math.max(0, list.length - 1));
}

function cur() { return providers.value[selected.value]; }

function markDirty() { store.providersDirty = true; }

async function refreshConfig() {
  store.config = await api("/settings/");
  notifySettingsChanged();
}

// 单条保存：新建 POST（重名 409），已有 PUT（改名即重命名）
async function saveProvider(p) {
  const { _orig, ...body } = p;
  if (_orig) await api(`/providers/${encodeURIComponent(_orig)}`, { method: "PUT", body });
  else await api("/providers/", { method: "POST", body });
  p._orig = p.name;
}

async function save() {
  try {
    await saveProvider(cur());
    store.providersDirty = false;
    await refreshConfig();
    message.success("已保存");
  } catch (e) { message.error("保存失败: " + e.message); }
}

async function toggleEnabled(p) {
  p.enabled = !p.enabled;
  if (!p._orig) { markDirty(); return; }
  try {
    await saveProvider(p);
    await refreshConfig();
  } catch (e) {
    p.enabled = !p.enabled;
    message.error("保存失败: " + e.message);
  }
}

function addProvider() {
  providers.value.push({
    name: `服务商${providers.value.length + 1}`,
    enabled: true, baseUrl: "", apiKey: "", models: [], defaultModel: null,
  });
  selected.value = providers.value.length - 1;
  markDirty();
}

async function removeProvider() {
  const p = cur();
  if (p._orig) {
    try { await api(`/providers/${encodeURIComponent(p._orig)}`, { method: "DELETE" }); }
    catch (e) { message.error("删除失败: " + e.message); return; }
  }
  providers.value.splice(selected.value, 1);
  selected.value = 0;
  store.providersDirty = false;
  await refreshConfig();
}

async function testConnection() {
  const p = cur();
  const model = p.defaultModel ?? p.models[0];
  if (!p.baseUrl || !p.apiKey || !model) {
    testResult.value = { ok: false, text: "需要 API 地址、密钥和至少一个模型" };
    return;
  }
  testResult.value = { ok: null, text: "检测中…" };
  try {
    const res = await api("/providers/test", { method: "POST", body: { baseUrl: p.baseUrl, apiKey: p.apiKey, model } });
    testResult.value = res.ok
      ? { ok: true, text: `✓ 连接正常（${model}，${res.latencyMs}ms）` }
      : { ok: false, text: `✗ ${res.error}` };
  } catch (e) { testResult.value = { ok: false, text: `✗ ${e.message}` }; }
}

function addModel() {
  const p = cur();
  const v = newModel.value.trim();
  if (!v || p.models.includes(v)) return;
  p.models.push(v);
  if (!p.defaultModel) p.defaultModel = v;
  newModel.value = "";
  markDirty();
}

function removeModel(mi) {
  const p = cur();
  const m = p.models[mi];
  p.models.splice(mi, 1);
  if (p.defaultModel === m) p.defaultModel = p.models[0] ?? null;
  markDirty();
}

function setDefault(m) {
  cur().defaultModel = m;
  markDirty();
}

function providerType(p) {
  return p.type ?? (/deepseek/i.test(p.baseUrl ?? "") ? "deepseek" : "openai");
}

const TYPE_OPTIONS = [
  { label: "OpenAI 兼容（通用）", value: "openai" },
  { label: "DeepSeek", value: "deepseek" },
];
const showKey = ref(false);
</script>

<template>
  <div class="layout">
    <div class="list">
      <div
        v-for="(p, i) in providers" :key="p._orig ?? i"
        class="prov-item" :class="{ active: i === selected }"
        @click="selected = i; testResult = null"
      >
        <span class="logo">{{ p.name.slice(0, 2).toUpperCase() }}</span>
        <span class="name">{{ p.name }}</span>
        <NSwitch size="small" :value="p.enabled" @click.stop @update:value="toggleEnabled(p)" />
      </div>
      <NButton class="add-btn" size="small" @click="addProvider">＋ 添加服务商</NButton>
    </div>

    <div v-if="cur()" class="detail">
      <div class="field">
        <label>名称</label>
        <NInput v-model:value="cur().name" size="small" @update:value="markDirty" />
      </div>
      <div class="field">
        <label>类型（决定支持哪些参数，如思考开关）</label>
        <NSelect
          size="small" :options="TYPE_OPTIONS" :value="providerType(cur())"
          @update:value="(v) => { cur().type = v; markDirty(); }"
        />
      </div>
      <div class="field">
        <label>API 地址</label>
        <NInput v-model:value="cur().baseUrl" size="small" class="mono" placeholder="https://api.deepseek.com" @update:value="markDirty" />
      </div>
      <div class="field">
        <label>API 密钥</label>
        <div class="row2">
          <NInput
            v-model:value="cur().apiKey" size="small" class="mono" style="flex:1"
            :type="showKey ? 'text' : 'password'" @update:value="markDirty"
          />
          <NButton size="small" @click="showKey = !showKey">{{ showKey ? "隐藏" : "显示" }}</NButton>
          <NButton size="small" @click="testConnection">检测</NButton>
        </div>
        <div v-if="testResult" class="test-result" :class="{ ok: testResult.ok, err: testResult.ok === false }">
          {{ testResult.text }}
        </div>
      </div>

      <div class="sect-label">
        模型
        <span style="flex:1"></span>
        <NInput v-model:value="newModel" size="small" class="mono" placeholder="model-id" style="width:200px" @keydown.enter="addModel" />
        <NButton size="small" @click="addModel">＋ 添加</NButton>
      </div>
      <div v-for="(m, mi) in cur().models" :key="m" class="model-row">
        <span class="mono">{{ m }}</span>
        <span v-if="(cur().defaultModel ?? cur().models[0]) === m" class="tag">默认</span>
        <NButton v-else text size="tiny" class="setdef" @click="setDefault(m)">设为默认</NButton>
        <NButton text size="tiny" class="rm" @click="removeModel(mi)">✕</NButton>
      </div>
      <div class="hint">修改保存后立即生效，无需重启。</div>

      <div style="margin-top:18px">
        <NPopconfirm positive-text="删除" negative-text="取消" @positive-click="removeProvider">
          <template #trigger>
            <NButton size="small" type="error" ghost>删除此服务商</NButton>
          </template>
          删除服务商「{{ cur().name }}」？
        </NPopconfirm>
      </div>

      <div v-if="store.providersDirty" class="save-bar">
        <span class="dirty-hint">有未保存的更改</span>
        <NButton size="small" type="primary" @click="save">保存更改</NButton>
      </div>
    </div>
    <div v-else class="detail hint">尚未配置任何服务商</div>
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
.detail { flex: 1; overflow-y: auto; padding: 20px 24px; }
.field { margin-bottom: 10px; }
.field label { display: block; color: #8b949e; font-size: 12px; margin-bottom: 3px; }
.row2 { display: flex; gap: 8px; align-items: center; }
.mono { font-family: ui-monospace, "SF Mono", Consolas, monospace; }
.test-result { font-size: 12px; margin-top: 4px; color: #8b949e; }
.test-result.ok { color: #3fb950; }
.test-result.err { color: #f85149; }
.sect-label {
  color: #8b949e; font-size: 12px; margin: 16px 0 6px;
  display: flex; align-items: center; gap: 10px;
}
.model-row {
  display: flex; align-items: center; gap: 8px; background: #161b22;
  border: 1px solid #30363d; border-radius: 8px; padding: 7px 10px; margin-bottom: 6px;
  font-size: 13px;
}
.model-row .tag {
  font-size: 11px; color: #58a6ff; border: 1px solid #58a6ff;
  border-radius: 8px; padding: 0 7px;
}
.model-row .setdef { visibility: hidden; margin-left: auto; }
.model-row:hover .setdef { visibility: visible; }
.model-row .rm { color: #8b949e; margin-left: auto; }
.model-row .setdef + .rm, .model-row .tag ~ .rm { margin-left: 0; }
.model-row .tag { margin-right: auto; }
.model-row .rm:hover { color: #f85149; }
.hint { color: #8b949e; font-size: 12px; margin-top: 6px; }
.save-bar {
  position: sticky; bottom: 0; background: #0d1117; border-top: 1px solid #30363d;
  padding: 10px 0; display: flex; gap: 10px; align-items: center; margin-top: 14px;
}
.dirty-hint { font-size: 12px; color: #d29922; }
</style>
