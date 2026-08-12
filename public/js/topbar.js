// 顶栏：会话标题、cwd chip、模型 chip（含项目级模型/参数/审批白名单弹层）、
// 技能 chip、导出按钮
import { $, esc, baseName, shortPath } from "./utils.js";
import { api, CTX } from "./api.js";
import { state } from "./state.js";

// 会话归属的项目 key：workspaces/ 下的自动目录归入虚拟项目「独立会话」
export function projectKeyOf(cwd) {
  const ws = state.config?.workspaceRoot;
  return ws && cwd?.startsWith(ws) ? "__standalone__" : cwd;
}

export function projectLabel(key) {
  return key === "__standalone__" ? "独立会话" : baseName(key);
}

function currentProjectKey() {
  return state.current ? projectKeyOf(state.current.cwd) : null;
}

function projectEntry(key) {
  return (key && state.config?.projectConfig?.[key]) || {};
}

function effectiveModel(key) {
  return projectEntry(key).model || state.config?.defaultModel || null;
}

export function setTopbar() {
  const s = state.current;
  $("session-title").textContent = s ? s.title : "—";
  $("cwd-chip").textContent = s ? shortPath(s.cwd) : "";
  $("cwd-chip").style.display = s ? "" : "none";
  $("btn-export").style.display = s ? "" : "none";
  renderModelChip();
}

export function renderModelChip() {
  const chip = $("model-chip");
  const key = currentProjectKey();
  const m = effectiveModel(key);
  const parts = [m ? m.model : "未配置模型"];
  const p = projectEntry(key).params ?? {};
  if (p.thinking === "on") parts.push("思考开");
  if (p.thinking === "off") parts.push("思考关");
  if (p.temperature != null) parts.push("T " + p.temperature);
  chip.childNodes[0].textContent = parts.join(" · ") + " ▾";
}

// ------------------------------------------------------------ 审批白名单
async function postAllowlist(key, execute, tools) {
  const res = await api("/settings/allowlist", { method: "POST", body: { key, execute, tools } });
  state.config.approvalAllowlist ??= {};
  if (res.allowlist.execute.length || res.allowlist.tools.length) {
    state.config.approvalAllowlist[key] = res.allowlist;
  } else {
    delete state.config.approvalAllowlist[key];
  }
}

// 审批卡片勾选「总是允许」后调用：adds = [{tool, prefix?}]，追加进当前项目的白名单
export async function saveAllowlist(adds) {
  const key = currentProjectKey();
  if (!key || !adds.length) return;
  const cur = state.config?.approvalAllowlist?.[key] ?? {};
  const execute = [...(cur.execute ?? [])];
  const tools = [...(cur.tools ?? [])];
  for (const a of adds) {
    if (a.tool === "execute") {
      if (a.prefix && !execute.includes(a.prefix)) execute.push(a.prefix);
    } else if (!tools.includes(a.tool)) {
      tools.push(a.tool);
    }
  }
  await postAllowlist(key, execute, tools);
}

async function saveProjectConfig(patch) {
  const key = currentProjectKey();
  if (!key) return;
  try {
    const res = await api("/settings/project-config", { method: "POST", body: { key, ...patch } });
    state.config.projectConfig ??= {};
    state.config.projectConfig[key] = res.config;
  } catch (e) { alert("保存失败: " + e.message); }
  renderModelChip();
  await renderModelMenu();
}

async function renderModelMenu() {
  const menu = $("model-menu");
  const key = currentProjectKey();
  if (!key) { menu.innerHTML = ""; return; }
  const { providers } = await api("/providers/");
  const entry = projectEntry(key);
  const own = entry.model ?? null;
  const params = entry.params ?? {};
  const def = state.config?.defaultModel;
  const th = params.thinking ?? null;
  const effort = ["low", "high", "max"].includes(params.thinkingEffort)
    ? params.thinkingEffort : "high";
  // 生效模型所属服务商的类型决定展示哪些参数
  const effProvider = providers.find((p) => p.name === (own ?? def)?.provider);
  const provType = effProvider?.type
    ?? (/deepseek/i.test(effProvider?.baseUrl ?? "") ? "deepseek" : "openai");

  let html = `<div class="m-sec">模型 <span class="proj-tag">${esc(projectLabel(key))}</span></div>`;
  html += `<div class="m-item" data-def="1"><span>跟随全局默认（${esc(def?.model ?? "—")}）</span>${
    !own ? '<span class="check">✓</span>' : ""}</div>`;
  for (const p of providers.filter(p => p.enabled)) {
    html += `<div class="m-group">${esc(p.name)}</div>`;
    for (const m of p.models) {
      const on = own && own.provider === p.name && own.model === m;
      html += `<div class="m-item" data-p="${esc(p.name)}" data-m="${esc(m)}">
        <span>${esc(m)}</span>${on ? '<span class="check">✓</span>' : ""}</div>`;
    }
  }
  html += `<hr>
    <div class="m-sec">项目参数</div>`;
  if (provType === "deepseek") {
    html += `
    <div class="param">
      <div class="p-head"><span>思考</span><span class="p-val">DeepSeek 默认开</span></div>
      <div class="seg" id="pp-think">
        <button data-v="" class="${th === null ? "on" : ""}">默认</button>
        <button data-v="on" class="${th === "on" ? "on" : ""}">开</button>
        <button data-v="off" class="${th === "off" ? "on" : ""}">关</button>
      </div>
      ${th === "on" ? `<div class="seg" id="pp-effort" style="margin-top:6px">
        <button data-v="low" class="${effort === "low" ? "on" : ""}">低</button>
        <button data-v="high" class="${effort === "high" ? "on" : ""}">高</button>
        <button data-v="max" class="${effort === "max" ? "on" : ""}">最大</button>
      </div>` : ""}
    </div>`;
  }
  html += `
    <div class="param">
      <div class="p-head"><span>温度</span>
        <span class="p-val" id="pp-temp-val">${params.temperature != null ? params.temperature : "默认"}</span>
        ${params.temperature != null ? '<button class="p-reset" id="pp-temp-reset" type="button">重置</button>' : ""}
      </div>
      <input type="range" id="pp-temp" min="0" max="20"
        value="${params.temperature != null ? Math.round(params.temperature * 10) : 10}">
    </div>
    <div class="param">
      <div class="p-head"><span>最大输出</span>
        <input type="number" id="pp-maxtok" min="1" placeholder="默认" value="${params.maxTokens ?? ""}">
      </div>
    </div>
    <div class="pop-foot">模型与参数保存在项目上，对项目下所有会话生效；「独立会话」视为一个虚拟项目。${
      provType === "deepseek" ? "DeepSeek 思考开启时，温度等采样参数会被忽略。" : ""}</div>`;

  // 审批白名单：命中的操作不再弹审批（在审批卡片勾选「总是允许」加入）
  const al = state.config?.approvalAllowlist?.[key] ?? {};
  const alItems = [
    ...(al.execute ?? []).map(v => ({ kind: "execute", val: v, label: `execute: ${v}` })),
    ...(al.tools ?? []).map(v => ({ kind: "tool", val: v, label: v })),
  ];
  html += `<hr><div class="m-sec">审批白名单</div>`;
  if (alItems.length) {
    html += alItems.map((it, i) =>
      `<div class="al-item"><code>${esc(it.label)}</code><button type="button" class="al-del" data-i="${i}" title="移除">✕</button></div>`
    ).join("");
  } else {
    html += `<div class="pop-foot" style="padding-top:0">空。审批时勾选「总是允许」加入，命中的操作不再询问。</div>`;
  }
  menu.innerHTML = html;

  for (const btn of menu.querySelectorAll(".al-del")) {
    btn.onclick = async (e) => {
      e.stopPropagation();
      const it = alItems[+btn.dataset.i];
      const execute = (al.execute ?? []).filter(v => !(it.kind === "execute" && v === it.val));
      const tools = (al.tools ?? []).filter(v => !(it.kind === "tool" && v === it.val));
      try { await postAllowlist(key, execute, tools); } catch (err) { alert("保存失败: " + err.message); }
      await renderModelMenu();
    };
  }

  const curParams = () => ({ ...params });
  for (const item of menu.querySelectorAll(".m-item")) {
    item.onclick = (e) => {
      e.stopPropagation();
      saveProjectConfig(item.dataset.def
        ? { model: null }
        : { model: { provider: item.dataset.p, model: item.dataset.m } });
    };
  }
  menu.querySelectorAll("#pp-think button").forEach((b) => {
    b.onclick = (e) => {
      e.stopPropagation();
      const p2 = curParams();
      if (b.dataset.v) p2.thinking = b.dataset.v; else delete p2.thinking;
      saveProjectConfig({ params: p2 });
    };
  });
  menu.querySelectorAll("#pp-effort button").forEach((b) => {
    b.onclick = (e) => {
      e.stopPropagation();
      saveProjectConfig({ params: { ...curParams(), thinkingEffort: b.dataset.v } });
    };
  });
  const temp = menu.querySelector("#pp-temp");
  temp.oninput = () => {
    menu.querySelector("#pp-temp-val").textContent = (temp.value / 10).toFixed(1);
  };
  temp.onchange = () => saveProjectConfig({ params: { ...curParams(), temperature: temp.value / 10 } });
  menu.querySelector("#pp-temp-reset")?.addEventListener("click", (e) => {
    e.stopPropagation();
    const p2 = curParams();
    delete p2.temperature;
    saveProjectConfig({ params: p2 });
  });
  const mt = menu.querySelector("#pp-maxtok");
  mt.onclick = (e) => e.stopPropagation();
  mt.onchange = () => {
    const p2 = curParams();
    const v = parseInt(mt.value, 10);
    if (v > 0) p2.maxTokens = v; else delete p2.maxTokens;
    saveProjectConfig({ params: p2 });
  };
}

export async function loadSkills() {
  try {
    state.skills = await api("/skills/");
  } catch { state.skills = { dirs: [], skills: [] }; }
  renderSkillsChip();
}

export function renderSkillsChip() {
  const n = state.skills.skills.length;
  $("skills-chip").childNodes[0].textContent = `⚡ ${n} 技能`;
  $("skills-tip").innerHTML = n
    ? `<div class="tt-title">已加载 ${n} 个技能</div>` +
      state.skills.skills.map(s => `<div class="tt-item">${esc(s.name)}</div>`).join("")
    : `<div class="tt-title">未发现技能</div><div style="font-size:12px;color:var(--text-dim)">在设置 → 技能中配置目录</div>`;
}

export function initTopbar() {
  // 导出：后端返回 Content-Disposition attachment，直接触发下载
  $("btn-export").onclick = () => {
    if (!state.current) return;
    const a = document.createElement("a");
    a.href = `${CTX}/sessions/${state.current.id}/export`;
    a.download = "";
    a.click();
  };
  $("model-chip").onclick = async (e) => {
    if (e.target.closest("#model-menu")) return;
    if (!state.current) return;
    const menu = $("model-menu");
    if (menu.classList.contains("open")) { menu.classList.remove("open"); return; }
    await renderModelMenu();
    menu.classList.add("open");
  };
  document.addEventListener("click", (e) => {
    if (!e.target.closest("#model-chip")) $("model-menu").classList.remove("open");
  });
}
