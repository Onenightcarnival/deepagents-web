// 设置页纵切：模型服务商、MCP 服务器、技能、通用（审批模式）
import { $, esc, shortPath } from "./utils.js";
import { api } from "./api.js";
import { state } from "./state.js";
import { renderModelChip, renderSkillsChip } from "./topbar.js";

export function openSettings() {
  $("settings").classList.add("open");
  loadProvidersPane();
  renderMcpPane();
  loadSkills();
  renderGeneralPane();
}

function closeSettings() {
  if (state.providersDirty && !confirm("模型服务有未保存的更改，确定离开？")) return;
  state.providersDirty = false;
  $("settings").classList.remove("open");
}

// ------------------------------------------------------------ providers
async function loadProvidersPane() {
  const { providers } = await api("/providers/");
  state.providers = structuredClone(providers);
  state.providers.forEach((p) => { p._orig = p.name; }); // 服务端主键，重命名时定位记录
  state.providersDirty = false;
  state.selectedProvider = Math.min(state.selectedProvider, Math.max(0, state.providers.length - 1));
  renderProviders();
}

function markDirty() {
  state.providersDirty = true;
  renderProviderDetail(); // refresh save bar
}

function renderProviders() {
  const list = $("prov-list");
  list.innerHTML = "";
  state.providers.forEach((p, i) => {
    const item = document.createElement("div");
    item.className = "prov-item" + (i === state.selectedProvider ? " active" : "");
    item.innerHTML = `<span class="p-logo">${esc(p.name.slice(0, 2).toUpperCase())}</span>
      <span class="p-name">${esc(p.name)}</span>
      <span class="toggle ${p.enabled ? "on" : ""}"></span>`;
    item.onclick = () => { state.selectedProvider = i; renderProviders(); };
    item.querySelector(".toggle").onclick = async (e) => {
      e.stopPropagation();
      p.enabled = !p.enabled;
      if (p._orig) {
        // 已保存的服务商：开关即保存
        try {
          await saveProvider(p);
          state.config = await api("/settings/");
          renderModelChip();
        } catch (err) {
          p.enabled = !p.enabled;
          alert("保存失败: " + err.message);
        }
      } else {
        state.providersDirty = true;
      }
      renderProviders();
    };
    list.appendChild(item);
  });
  const add = document.createElement("button");
  add.textContent = "＋ 添加服务商";
  add.style.marginTop = "auto";
  add.onclick = () => {
    state.providers.push({ name: `服务商${state.providers.length + 1}`, enabled: true, baseUrl: "", apiKey: "", models: [], defaultModel: null });
    state.selectedProvider = state.providers.length - 1;
    state.providersDirty = true;
    renderProviders();
  };
  list.appendChild(add);
  renderProviderDetail();
}

function renderProviderDetail() {
  const box = $("prov-detail");
  const p = state.providers[state.selectedProvider];
  if (!p) { box.innerHTML = '<div class="hint" style="color:var(--text-dim)">尚未配置任何服务商</div>'; return; }
  const pvType = p.type ?? (/deepseek/i.test(p.baseUrl ?? "") ? "deepseek" : "openai");
  box.innerHTML = `
    <div class="field"><label>名称</label><input type="text" id="pv-name" value="${esc(p.name)}"></div>
    <div class="field"><label>类型（决定支持哪些参数，如思考开关）</label>
      <select id="pv-type">
        <option value="openai" ${pvType === "openai" ? "selected" : ""}>OpenAI 兼容（通用）</option>
        <option value="deepseek" ${pvType === "deepseek" ? "selected" : ""}>DeepSeek</option>
      </select>
    </div>
    <div class="field"><label>API 地址</label><input type="text" id="pv-url" class="mono" value="${esc(p.baseUrl)}" placeholder="https://api.deepseek.com"></div>
    <div class="field"><label>API 密钥</label>
      <div class="row2">
        <input type="password" id="pv-key" class="mono" value="${esc(p.apiKey)}" style="flex:1">
        <button class="small" id="pv-show">显示</button>
        <button class="small" id="pv-test">检测</button>
      </div>
      <div id="pv-test-result" style="font-size:12px;margin-top:4px"></div>
    </div>
    <div class="sect-label" style="display:flex;align-items:center;gap:10px">模型
      <span style="flex:1"></span>
      <input type="text" id="pv-new-model" class="mono" placeholder="model-id" style="width:200px">
      <button class="small" id="pv-add-model">＋ 添加</button>
    </div>
    <div id="pv-models"></div>
    <div class="hint" style="color:var(--text-dim);font-size:12px;margin-top:6px">修改保存后立即生效，无需重启。</div>
    <div style="margin-top:18px"><button class="small danger" id="pv-del">删除此服务商</button></div>
    <div id="save-bar" class="${state.providersDirty ? "dirty" : ""}">
      <span style="font-size:12px;color:var(--yellow)">有未保存的更改</span>
      <button class="primary" id="pv-save">保存更改</button>
    </div>`;
  const models = box.querySelector("#pv-models");
  p.models.forEach((m, mi) => {
    const row = document.createElement("div");
    row.className = "model-row";
    const isDef = (p.defaultModel ?? p.models[0]) === m;
    row.innerHTML = `<span>${esc(m)}</span>${isDef ? '<span class="tag">默认</span>' : ""}
      ${!isDef ? '<button class="small ghost setdef">设为默认</button>' : '<span class="setdef"></span>'}
      <button class="ghost small rm" style="margin-left:${isDef ? "auto" : "0"}">✕</button>`;
    row.querySelector(".setdef")?.addEventListener?.("click", () => {
      if (row.querySelector("button.setdef")) { p.defaultModel = m; markDirty(); renderProviderDetail(); }
    });
    row.querySelector(".rm").onclick = () => {
      p.models.splice(mi, 1);
      if (p.defaultModel === m) p.defaultModel = p.models[0] ?? null;
      markDirty(); renderProviderDetail();
    };
    models.appendChild(row);
  });
  box.querySelector("#pv-type").onchange = (e) => { p.type = e.target.value; state.providersDirty = true; $("save-bar").classList.add("dirty"); };
  box.querySelector("#pv-name").oninput = (e) => { p.name = e.target.value; state.providersDirty = true; $("save-bar").classList.add("dirty"); };
  box.querySelector("#pv-name").onchange = () => renderProviders();
  box.querySelector("#pv-url").oninput = (e) => { p.baseUrl = e.target.value.trim(); state.providersDirty = true; $("save-bar").classList.add("dirty"); };
  box.querySelector("#pv-key").oninput = (e) => { p.apiKey = e.target.value.trim(); state.providersDirty = true; $("save-bar").classList.add("dirty"); };
  box.querySelector("#pv-show").onclick = () => {
    const inp = box.querySelector("#pv-key");
    const isPw = inp.type === "password";
    inp.type = isPw ? "text" : "password";
    box.querySelector("#pv-show").textContent = isPw ? "隐藏" : "显示";
  };
  box.querySelector("#pv-test").onclick = async () => {
    const r = box.querySelector("#pv-test-result");
    const model = p.defaultModel ?? p.models[0];
    if (!p.baseUrl || !p.apiKey || !model) { r.style.color = "var(--red)"; r.textContent = "需要 API 地址、密钥和至少一个模型"; return; }
    r.style.color = "var(--text-dim)"; r.textContent = "检测中…";
    try {
      const res = await api("/providers/test", { method: "POST", body: { baseUrl: p.baseUrl, apiKey: p.apiKey, model } });
      if (res.ok) { r.style.color = "var(--green)"; r.textContent = `✓ 连接正常（${model}，${res.latencyMs}ms）`; }
      else { r.style.color = "var(--red)"; r.textContent = `✗ ${res.error}`; }
    } catch (e) { r.style.color = "var(--red)"; r.textContent = `✗ ${e.message}`; }
  };
  box.querySelector("#pv-add-model").onclick = () => {
    const inp = box.querySelector("#pv-new-model");
    const v = inp.value.trim();
    if (!v || p.models.includes(v)) return;
    p.models.push(v);
    if (!p.defaultModel) p.defaultModel = v;
    markDirty(); renderProviderDetail();
  };
  box.querySelector("#pv-new-model").onkeydown = (e) => {
    if (e.key === "Enter") box.querySelector("#pv-add-model").click();
  };
  box.querySelector("#pv-del").onclick = async () => {
    if (!confirm(`删除服务商「${p.name}」？`)) return;
    if (p._orig) {
      try { await api(`/providers/${encodeURIComponent(p._orig)}`, { method: "DELETE" }); }
      catch (e) { alert("删除失败: " + e.message); return; }
    }
    state.providers.splice(state.selectedProvider, 1);
    state.selectedProvider = 0;
    state.providersDirty = false;
    state.config = await api("/settings/");
    renderModelChip();
    renderProviders();
  };
  box.querySelector("#pv-save").onclick = async () => {
    try {
      await saveProvider(p);
      state.providersDirty = false;
      state.config = await api("/settings/");
      renderModelChip();
      renderProviders();
    } catch (e) { alert("保存失败: " + e.message); }
  };
}

// 单条保存：新建 POST（重名 409），已有 PUT（按服务端主键 _orig 定位，改名即重命名）
async function saveProvider(p) {
  const { _orig, ...body } = p;
  if (_orig) await api(`/providers/${encodeURIComponent(_orig)}`, { method: "PUT", body });
  else await api("/providers/", { method: "POST", body });
  p._orig = p.name;
}

// ------------------------------------------------------------ MCP
const MCP_TABS = [["general", "通用"], ["tools", "工具"], ["prompts", "提示词"], ["resources", "资源"]];

async function renderMcpPane() {
  state.mcpInspect ??= {};   // per-server {ok, tools, prompts, resources} cache
  const { servers } = await api("/mcp/");
  state.mcpServers = servers;
  state.mcpTab ??= "general";
  if (!state.mcpDraft && !servers.find((s) => s.name === state.selectedMcp))
    state.selectedMcp = servers[0]?.name ?? null;
  const list = $("mcp-srv-list");
  list.innerHTML = "";
  for (const s of servers) {
    const item = document.createElement("div");
    item.className = "prov-item" + (!state.mcpDraft && s.name === state.selectedMcp ? " active" : "");
    item.innerHTML = `<span class="p-logo">${esc(s.name.slice(0, 2).toUpperCase())}</span>
      <span class="p-name">${esc(s.name)}</span>
      <span class="toggle ${s.enabled ? "on" : ""}"></span>`;
    item.onclick = () => {
      state.mcpDraft = null; state.selectedMcp = s.name; state.mcpTab = "general";
      renderMcpPane();
    };
    item.querySelector(".toggle").onclick = async (e) => {
      e.stopPropagation();
      const { name, enabled, ...config } = s;
      await api("/mcp/", { method: "POST", body: { name, enabled: !enabled, ...config } });
      renderMcpPane();
    };
    list.appendChild(item);
  }
  const add = document.createElement("button");
  add.textContent = "＋ 添加服务器";
  add.style.marginTop = "auto";
  add.onclick = () => {
    state.mcpDraft = { name: "", transport: "http", url: "" };
    state.mcpTab = "general";
    renderMcpPane();
  };
  list.appendChild(add);
  renderMcpDetail();
}

function renderMcpDetail() {
  const box = $("mcp-detail");
  const isNew = !!state.mcpDraft;
  const server = state.mcpDraft ?? state.mcpServers.find((s) => s.name === state.selectedMcp);
  if (!server) {
    box.innerHTML = '<div class="hint" style="color:var(--text-dim)">尚未配置任何 MCP 服务器（仅支持 Streamable HTTP），点击左下角「＋ 添加服务器」。</div>';
    return;
  }
  box.innerHTML = `
    <div class="tabs">
      ${MCP_TABS.map(([k, label]) =>
        `<button data-tab="${k}" class="${state.mcpTab === k ? "on" : ""}" ${isNew && k !== "general" ? "disabled" : ""}>${label}</button>`).join("")}
      <span style="flex:1"></span>
      ${!isNew && state.mcpTab !== "general" ? '<button class="small" id="mcp-refresh">刷新</button>' : ""}
    </div>
    <div id="mcp-tab-body"></div>`;
  box.querySelectorAll("[data-tab]").forEach((b) => {
    b.onclick = () => { state.mcpTab = b.dataset.tab; renderMcpDetail(); };
  });
  const refresh = box.querySelector("#mcp-refresh");
  if (refresh) refresh.onclick = () => { delete state.mcpInspect[server.name]; renderMcpDetail(); };
  const body = box.querySelector("#mcp-tab-body");
  if (state.mcpTab === "general") renderMcpGeneral(body, server, isNew);
  else renderMcpCapability(body, server, state.mcpTab);
}

function renderMcpGeneral(body, server, isNew) {
  const headerText = server.headers
    ? Object.entries(server.headers).map(([k, v]) => `${k}: ${v}`).join("\n") : "";
  body.innerHTML = `
    <div class="field"><label>名称（字母数字-_）</label>
      <input type="text" id="mcp-name" ${isNew ? "" : "disabled"} value="${esc(server.name)}" placeholder="my-server"></div>
    <div class="field"><label>URL（Streamable HTTP）</label>
      <input type="text" id="mcp-url" class="mono" value="${esc(server.url ?? "")}" placeholder="http://localhost:8000/mcp"></div>
    <div class="field"><label>请求头（每行一个 KEY: VALUE，可留空）</label>
      <textarea id="mcp-headers" rows="3" class="mono" placeholder="Authorization: Bearer xxx">${esc(headerText)}</textarea></div>
    <div style="display:flex;gap:8px;align-items:center;margin-top:6px;flex-wrap:wrap">
      <button id="btn-mcp-test" style="flex:none;white-space:nowrap">测试连接</button>
      <button class="primary" id="btn-mcp-save" style="flex:none;white-space:nowrap">保存</button>
      ${isNew ? '<button id="btn-mcp-cancel" style="flex:none;white-space:nowrap">取消</button>'
        : '<button class="small danger" id="btn-mcp-del" style="flex:none;white-space:nowrap">删除此服务器</button>'}
      <span id="mcp-form-status" style="font-size:12px;color:var(--text-dim)"></span>
    </div>
    <div class="hint" style="color:var(--text-dim);font-size:12px;margin-top:10px">保存后即时生效，作用于之后的对话轮次；工具名会以「服务器名__工具名」前缀注入。</div>`;
  const cfg = () => {
    const headers = {};
    for (const line of body.querySelector("#mcp-headers").value.split("\n")) {
      const m = line.match(/^\s*([\w.-]+)\s*:\s*(.+)$/);
      if (m) headers[m[1]] = m[2].trim();
    }
    return {
      name: isNew ? body.querySelector("#mcp-name").value.trim() : server.name,
      transport: "http", url: body.querySelector("#mcp-url").value.trim(),
      ...(Object.keys(headers).length ? { headers } : {}),
      ...(server.disabledTools?.length ? { disabledTools: server.disabledTools } : {}),
    };
  };
  const status = body.querySelector("#mcp-form-status");
  body.querySelector("#btn-mcp-test").onclick = async () => {
    status.style.color = "var(--text-dim)"; status.textContent = "连接中…";
    try {
      const res = await api("/mcp/test", { method: "POST", body: cfg() });
      if (res.ok) {
        status.style.color = "var(--green)";
        status.textContent = `✓ ${res.tools.length} 个工具 · ${res.prompts.length} 个提示词 · ${res.resources.length} 个资源`;
      } else { status.style.color = "var(--red)"; status.textContent = `✗ ${res.error.slice(0, 160)}`; }
    } catch (e) { status.style.color = "var(--red)"; status.textContent = `✗ ${e.message}`; }
  };
  body.querySelector("#btn-mcp-save").onclick = async () => {
    const c = cfg();
    if (!c.name || !/^[\w-]+$/.test(c.name)) { alert("名称只能包含字母、数字、- 和 _"); return; }
    if (!c.url) { alert("URL 不能为空"); return; }
    try {
      await api("/mcp/", { method: "POST", body: { ...c, enabled: isNew ? true : server.enabled } });
      delete state.mcpInspect[c.name];
      state.mcpDraft = null; state.selectedMcp = c.name;
      renderMcpPane();
    } catch (e) { alert(e.message); }
  };
  if (isNew) {
    body.querySelector("#btn-mcp-cancel").onclick = () => { state.mcpDraft = null; renderMcpPane(); };
  } else {
    body.querySelector("#btn-mcp-del").onclick = async () => {
      if (!confirm(`删除 MCP 服务器「${server.name}」？`)) return;
      await api(`/mcp/${server.name}`, { method: "DELETE" });
      delete state.mcpInspect[server.name];
      state.selectedMcp = null;
      renderMcpPane();
    };
  }
}

async function renderMcpCapability(body, server, tab) {
  const cached = state.mcpInspect[server.name];
  if (!cached) {
    body.innerHTML = '<div class="hint" style="color:var(--text-dim)">连接中…</div>';
    let res;
    try { res = await api("/mcp/test", { method: "POST", body: server }); }
    catch (e) { res = { ok: false, error: e.message }; }
    state.mcpInspect[server.name] = res;
    // re-render only if the user is still on this server (any capability tab reads the same cache)
    if (state.selectedMcp === server.name && !state.mcpDraft && state.mcpTab !== "general") renderMcpDetail();
    return;
  }
  if (!cached.ok) {
    body.innerHTML = `<div class="hint" style="color:var(--red);word-break:break-all">✗ ${esc(cached.error)}</div>`;
    return;
  }
  if (tab === "tools") renderToolDocs(body, cached.tools, server);
  else if (tab === "prompts") renderPromptDocs(body, cached.prompts);
  else renderResourceDocs(body, cached.resources);
}

function renderPromptDocs(box, prompts) {
  if (!prompts.length) {
    box.innerHTML = '<div class="hint" style="color:var(--text-dim)">该服务器未提供提示词</div>';
    return;
  }
  box.innerHTML = `<span style="font-size:12px;color:var(--text-dim)">${prompts.length} 个提示词</span>`;
  for (const p of prompts) {
    const d = document.createElement("div");
    d.className = "tool-doc";
    d.innerHTML = `
      <div class="td-head">
        <span class="td-name">${esc(p.name)}</span>
        <span class="td-brief">${esc(p.description || "（无描述）")}</span>
        <span class="td-arrow">▸</span>
      </div>
      <div class="td-body">
        ${p.description ? `<div class="td-desc">${esc(p.description)}</div>` : ""}
        <div class="td-params-label">参数</div>
        ${p.arguments.length ? p.arguments.map((a) => `
          <div class="td-param">
            <code>${esc(a.name)}</code>
            ${a.required ? '<span class="preq">必填</span>' : ""}
            ${a.description ? `<span class="pd">${esc(a.description)}</span>` : ""}
          </div>`).join("")
        : '<div class="td-param" style="color:var(--text-dim)">无参数</div>'}
      </div>`;
    d.querySelector(".td-head").onclick = () => d.classList.toggle("open");
    box.appendChild(d);
  }
}

function renderResourceDocs(box, resources) {
  if (!resources.length) {
    box.innerHTML = '<div class="hint" style="color:var(--text-dim)">该服务器未提供资源</div>';
    return;
  }
  box.innerHTML = `<span style="font-size:12px;color:var(--text-dim)">${resources.length} 个资源</span>`;
  for (const r of resources) {
    const d = document.createElement("div");
    d.className = "tool-doc";
    d.innerHTML = `
      <div class="td-head">
        <span class="td-name">${esc(r.name || r.uri)}</span>
        <span class="td-brief">${esc(r.description || r.uri)}</span>
        <span class="td-arrow">▸</span>
      </div>
      <div class="td-body">
        <div class="td-param"><code>URI</code><span class="pd" style="flex-basis:auto">${esc(r.uri)}</span></div>
        ${r.mimeType ? `<div class="td-param"><code>类型</code><span class="pd" style="flex-basis:auto">${esc(r.mimeType)}</span></div>` : ""}
        ${r.description ? `<div class="td-desc" style="margin-top:8px">${esc(r.description)}</div>` : ""}
      </div>`;
    d.querySelector(".td-head").onclick = () => d.classList.toggle("open");
    box.appendChild(d);
  }
}

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

function renderToolDocs(box, tools, server) {
  if (!tools.length) {
    box.innerHTML = '<div class="hint" style="color:var(--text-dim)">该服务器未提供工具</div>';
    return;
  }
  const disabledSet = new Set(server?.disabledTools ?? []);
  const enabledCount = tools.filter((t) => !disabledSet.has(t.name)).length;
  box.innerHTML = `<span style="font-size:12px;color:var(--text-dim)">${tools.length} 个工具${
    server ? ` · 已启用 ${enabledCount}` : ""}</span>`;
  for (const t of tools) {
    const params = schemaParams(t.schema);
    const off = disabledSet.has(t.name);
    const d = document.createElement("div");
    d.className = "tool-doc" + (off ? " off" : "");
    d.innerHTML = `
      <div class="td-head">
        <span class="td-name">${esc(t.name)}</span>
        <span class="td-brief">${esc(t.description || "（无描述）")}</span>
        ${server ? `<span class="toggle ${off ? "" : "on"}" title="启用/停用该工具" style="align-self:center"></span>` : ""}
        <span class="td-arrow">▸</span>
      </div>
      <div class="td-body">
        ${t.description ? `<div class="td-desc">${esc(t.description)}</div>` : ""}
        <div class="td-params-label">参数</div>
        ${params.length ? params.map((p) => `
          <div class="td-param">
            <code>${esc(p.name)}</code>
            <span class="pt">${esc(p.type)}</span>
            ${p.required ? '<span class="preq">必填</span>' : ""}
            ${p.desc ? `<span class="pd">${esc(p.desc)}</span>` : ""}
          </div>`).join("")
        : '<div class="td-param" style="color:var(--text-dim)">无参数</div>'}
      </div>`;
    d.querySelector(".td-head").onclick = () => d.classList.toggle("open");
    const toggle = d.querySelector(".toggle");
    if (toggle) toggle.onclick = async (e) => {
      e.stopPropagation();
      const set = new Set(server.disabledTools ?? []);
      set.has(t.name) ? set.delete(t.name) : set.add(t.name);
      server.disabledTools = [...set];
      const { name, enabled, ...config } = server;
      try {
        await api("/mcp/", { method: "POST", body: { name, enabled, ...config } });
      } catch (err) { alert(err.message); }
      renderMcpDetail();
    };
    box.appendChild(d);
  }
}

// ------------------------------------------------------------ skills
export async function loadSkills() {
  try {
    state.skills = await api("/skills/");
  } catch { state.skills = { dirs: [], skills: [] }; }
  renderSkillsChip();
  renderSkillsPane();
}

function renderSkillsPane() {
  const dirList = $("skill-dir-list");
  dirList.innerHTML = "";
  state.skills.dirs.forEach((d, i) => {
    const row = document.createElement("div");
    row.className = "skill-src-row";
    row.innerHTML = `<span class="src-path">${esc(d)}</span>
      <button class="ghost small" title="移除">✕</button>`;
    row.querySelector("button").onclick = async () => {
      const dirs = state.skills.dirs.filter((_, j) => j !== i);
      await api("/skills/dirs", { method: "POST", body: { dirs } });
      loadSkills();
    };
    dirList.appendChild(row);
  });
  const list = $("skill-list");
  list.innerHTML = state.skills.skills.length ? "" :
    '<div class="hint" style="color:var(--text-dim)">未发现技能：在技能目录下创建包含 SKILL.md 的子目录即可。</div>';
  for (const sk of state.skills.skills) {
    const card = document.createElement("div");
    card.className = "skill-card";
    card.innerHTML = `<span class="sk-name">${esc(sk.name)}</span>
      <span class="sk-desc">${esc(sk.description || "（无描述）")}</span>
      <button class="small">查看 SKILL.md</button>`;
    card.querySelector("button").onclick = async () => {
      try {
        const { content } = await api(`/skills/file?path=${encodeURIComponent(sk.path)}`);
        $("skillmd-title").textContent = shortPath(sk.path);
        $("skillmd-view").textContent = content;
        $("skillmd-backdrop").classList.add("visible");
      } catch (e) { alert(e.message); }
    };
    list.appendChild(card);
  }
  if (state.skills.errors?.length) {
    const warn = document.createElement("div");
    warn.className = "warn-banner";
    warn.textContent = "扫描警告: " + state.skills.errors.join("; ");
    list.appendChild(warn);
  }
}

// ------------------------------------------------------------ general
const APPROVAL_MODES = [
  { v: "off", t: "off — 全自动", d: "所有工具直接执行，不需要审批（信任模式，慎用）" },
  { v: "dangerous", t: "dangerous — 审批危险操作", d: "shell 命令、写文件、改文件需要审批（推荐）" },
  { v: "dangerous+mcp", t: "dangerous+mcp", d: "在 dangerous 基础上，MCP 工具调用也需要审批" },
  { v: "all", t: "all — 全部审批", d: "所有工具（包括只读）都需要审批" },
];

function renderGeneralPane() {
  const cur = state.config?.approvalMode ?? "dangerous";
  const box = $("approval-cards");
  box.innerHTML = "";
  for (const m of APPROVAL_MODES) {
    const card = document.createElement("div");
    card.className = "radio-card" + (cur === m.v ? " on" : "");
    card.innerHTML = `<span class="r-dot"></span>
      <div><div class="r-title">${esc(m.t)}</div><div class="r-desc">${esc(m.d)}</div></div>`;
    card.onclick = async () => {
      await api("/settings/", { method: "POST", body: { approvalMode: m.v } });
      state.config.approvalMode = m.v;
      renderGeneralPane();
    };
    box.appendChild(card);
  }
  $("info-workspace").textContent = shortPath(state.config?.workspaceRoot ?? "");
  $("info-host").textContent = location.host;
}

// ------------------------------------------------------------ wiring
export function initSettings() {
  $("btn-settings").onclick = openSettings;
  $("btn-settings-back").onclick = closeSettings;
  for (const nav of document.querySelectorAll(".nav-item")) {
    nav.onclick = () => {
      document.querySelectorAll(".nav-item").forEach(n => n.classList.remove("active"));
      document.querySelectorAll(".settings-pane").forEach(p => p.classList.remove("active"));
      nav.classList.add("active");
      $("pane-" + nav.dataset.pane).classList.add("active");
    };
  }
  $("btn-skillmd-close").onclick = () => $("skillmd-backdrop").classList.remove("visible");
  $("btn-add-dir").onclick = () => {
    $("btn-add-dir").style.display = "none";
    $("dir-add-row").style.display = "flex";
    $("dir-input").focus();
  };
  $("btn-dir-cancel").onclick = () => {
    $("dir-add-row").style.display = "none";
    $("btn-add-dir").style.display = "";
    $("dir-input").value = "";
  };
  $("btn-dir-ok").onclick = async () => {
    const v = $("dir-input").value.trim();
    if (!v) { $("dir-input").focus(); return; }
    await api("/skills/dirs", { method: "POST", body: { dirs: [...state.skills.dirs, v] } });
    $("btn-dir-cancel").onclick();
    loadSkills();
  };
  $("dir-input").addEventListener("keydown", (e) => { if (e.key === "Enter") $("btn-dir-ok").onclick(); });
}
