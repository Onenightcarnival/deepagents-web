<script setup>
import { NButton, NInput, NModal, NSelect, useDialog, useMessage } from "naive-ui";
import { computed, onMounted, ref } from "vue";

import { api, apiUpload, notifySettingsChanged } from "../api.js";

const message = useMessage();
const dialog = useDialog();

const skills = ref({ dirs: [], skills: [], errors: [] });
const adding = ref(false);
const newDir = ref("");
const viewer = ref(null); // { title, content }
const fileInput = ref(null);
const uploadDir = ref(null); // 为空时后端落到第一个目录
const uploading = ref(false);
const dirOptions = computed(() => skills.value.dirs.map((d) => ({ label: d, value: d })));

onMounted(load);

async function load() {
  try { skills.value = await api("/skills/"); }
  catch { skills.value = { dirs: [], skills: [], errors: [] }; }
}

async function saveDirs(dirs) {
  try {
    await api("/skills/dirs", { method: "POST", body: { dirs } });
    notifySettingsChanged();
    await load();
  } catch (e) { message.error(e.message); }
}

function addDir() {
  const v = newDir.value.trim();
  if (!v) return;
  adding.value = false;
  newDir.value = "";
  saveDirs([...skills.value.dirs, v]);
}

function shortPath(p) { return p.replace(/^\/(Users|home)\/[^/]+/, "~"); }

function onZipPicked(ev) {
  const file = ev.target.files?.[0];
  ev.target.value = ""; // 清掉选择，允许连续上传同一文件
  if (file) uploadZip(file, false);
}

async function uploadZip(file, overwrite) {
  const fd = new FormData();
  fd.append("file", file);
  fd.append("dir", uploadDir.value || "");
  fd.append("overwrite", overwrite ? "true" : "false");
  uploading.value = true;
  try {
    const { skill } = await apiUpload("/skills/upload", fd);
    message.success(`已安装技能 ${skill.name}`);
    notifySettingsChanged();
    await load();
  } catch (e) {
    if (!overwrite && e.message.startsWith("技能已存在")) {
      dialog.warning({
        title: "技能已存在",
        content: `${e.message}，覆盖安装？原目录会被整体替换。`,
        positiveText: "覆盖",
        negativeText: "取消",
        onPositiveClick: () => uploadZip(file, true),
      });
    } else {
      message.error(e.message);
    }
  } finally {
    uploading.value = false;
  }
}

function confirmDelete(sk) {
  dialog.warning({
    title: "删除技能",
    content: `将删除 ${sk.name} 的整个目录（含其中所有文件），且不可恢复。确认？`,
    positiveText: "删除",
    negativeText: "取消",
    onPositiveClick: async () => {
      try {
        await api(`/skills/?path=${encodeURIComponent(sk.path)}`, { method: "DELETE" });
        message.success(`已删除技能 ${sk.name}`);
        notifySettingsChanged();
        await load();
      } catch (e) { message.error(e.message); }
    },
  });
}

async function viewSkill(sk) {
  try {
    const { content } = await api(`/skills/file?path=${encodeURIComponent(sk.path)}`);
    viewer.value = { title: shortPath(sk.path), content };
  } catch (e) { message.error(e.message); }
}
</script>

<template>
  <div class="pane-inner">
    <h2>技能</h2>
    <div class="sub">技能是一个包含 SKILL.md 的目录，Agent 会按需读取并遵循其中的指引。</div>

    <div class="sect-label">技能目录</div>
    <div v-for="(d, i) in skills.dirs" :key="d" class="src-row">
      <span class="src-path mono">{{ d }}</span>
      <NButton text size="tiny" title="移除" @click="saveDirs(skills.dirs.filter((_, j) => j !== i))">✕</NButton>
    </div>
    <div v-if="adding" class="src-row">
      <NInput
        v-model:value="newDir" size="small" class="mono" placeholder="~/my-skills/"
        style="flex:1" @keydown.enter="addDir"
      />
      <NButton size="tiny" type="primary" @click="addDir">确定</NButton>
      <NButton size="tiny" @click="adding = false; newDir = ''">取消</NButton>
    </div>
    <NButton v-else size="small" @click="adding = true">＋ 添加目录</NButton>
    <div class="hint" style="margin: 8px 0 18px">
      目录下每个包含 SKILL.md 的子目录会被加载为技能；多个目录中同名技能，后面的目录覆盖前面的。
    </div>

    <div class="sect-label">已发现的技能 <span style="opacity:0.75">自动加载，无需逐个开关</span></div>
    <div style="display:flex; gap:8px; align-items:center; margin: 6px 0">
      <NButton size="small" :loading="uploading" @click="fileInput?.click()">⬆ 上传技能包 (.zip)</NButton>
      <NSelect
        v-if="skills.dirs.length > 1" v-model:value="uploadDir" size="small" clearable
        :options="dirOptions" placeholder="安装到…（默认第一个目录）" style="max-width: 340px"
      />
      <input ref="fileInput" type="file" accept=".zip,application/zip" style="display:none" @change="onZipPicked">
    </div>
    <div class="hint" style="margin-bottom: 10px">
      一包一技能：zip 内的 SKILL.md 须位于 zip 根或唯一顶层目录下，frontmatter 的 name 作为技能目录名。
    </div>
    <div v-if="!skills.skills.length" class="hint">未发现技能：在技能目录下创建包含 SKILL.md 的子目录即可。</div>
    <div v-for="sk in skills.skills" :key="sk.path" class="skill-card">
      <span class="sk-name mono">{{ sk.name }}</span>
      <span class="sk-desc">{{ sk.description || "（无描述）" }}</span>
      <NButton size="small" @click="viewSkill(sk)">查看 SKILL.md</NButton>
      <NButton size="small" type="error" ghost title="删除技能目录" @click="confirmDelete(sk)">删除</NButton>
    </div>
    <div v-if="skills.errors?.length" class="warn">扫描警告: {{ skills.errors.join("; ") }}</div>

    <NModal
      :show="!!viewer" preset="card" style="width: 640px" :title="viewer?.title"
      @update:show="viewer = null"
    >
      <pre class="skillmd">{{ viewer?.content }}</pre>
      <div class="hint" style="margin-top:8px">只读预览 · 修改请直接编辑文件，或让 Agent 帮你完善</div>
    </NModal>
  </div>
</template>

<style scoped>
.pane-inner { max-width: 760px; margin: 0 auto; padding: 24px; }
.pane-inner h2 { font-size: 17px; margin: 0 0 4px; }
.sub { color: #8b949e; font-size: 13px; margin-bottom: 18px; }
.sect-label { color: #8b949e; font-size: 12px; margin: 16px 0 6px; }
.mono { font-family: ui-monospace, "SF Mono", Consolas, monospace; }
.src-row {
  display: flex; align-items: center; gap: 8px; background: #161b22;
  border: 1px solid #30363d; border-radius: 8px; padding: 8px 12px; margin-bottom: 6px;
}
.src-path { font-size: 13px; flex: 1; }
.skill-card {
  background: #161b22; border: 1px solid #30363d; border-radius: 10px;
  padding: 10px 14px; margin-bottom: 8px; display: flex; align-items: center; gap: 10px;
}
.sk-name { font-weight: 600; }
.sk-desc { color: #8b949e; font-size: 13px; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.hint { color: #8b949e; font-size: 12px; }
.warn {
  background: #f8514911; border: 1px solid #f85149; color: #f85149;
  border-radius: 8px; padding: 8px 12px; margin: 8px 0; font-size: 13px;
}
.skillmd {
  background: #0d1117; border: 1px solid #30363d; border-radius: 8px;
  padding: 12px; white-space: pre-wrap; word-break: break-word;
  font-family: ui-monospace, monospace; font-size: 12px; max-height: 55vh; overflow-y: auto; margin: 0;
}
</style>
