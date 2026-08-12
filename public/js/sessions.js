// 会话纵切：侧栏分组列表、历史加载、SSE 订阅、运行生命周期、新建/重命名弹窗。
// 运行在服务端后台执行；这里只是订阅 GET /stream 的事件流。关掉页面不会
// 中止运行，重新打开后 selectSession 会重挂到进行中的运行上。
import { $, esc, relTime, baseName, shortPath } from "./utils.js";
import { api, CTX } from "./api.js";
import { state, saveCollapsed } from "./state.js";
import { setTopbar, projectKeyOf, projectLabel, saveAllowlist } from "./topbar.js";
import { requestNotifyPermission, notifyApproval, notifyRunEnd } from "./notify.js";
import {
  resetChat, removeEmptyHint, showEmptyHint, addUserMsg, newAssistantTurn,
  appendAiText, appendReasoning, finalizeThink, addHistoryThink, addToolCard,
  setToolResult, hasToolRow, addWarnBanner, renderTodos, showApproval,
  setApprovalHandler, toolArgSummary, scrollBottom, flushAiRender, addHistoryGap,
} from "./chat.js";

// ------------------------------------------------------------ streaming
function setStreaming(on, statusText) {
  state.streaming = on;
  $("btn-send").style.display = on ? "none" : "";
  $("btn-stop").style.display = on ? "" : "none";
  $("status-line").innerHTML = on
    ? `<span class="spinner"></span> ${esc(statusText ?? "运行中…")}`
    : "";
}

async function consumeSSE(response) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let idx;
    while ((idx = buf.indexOf("\n\n")) >= 0) {
      const raw = buf.slice(0, idx); buf = buf.slice(idx + 2);
      const line = raw.split("\n").find(l => l.startsWith("data: "));
      if (!line) continue;
      handleEvent(JSON.parse(line.slice(6)));
    }
  }
}

function handleEvent(ev) {
  switch (ev.type) {
    case "user":
      // 发送方页签已本地渲染过这条消息，跳过回放里的第一条
      if (state.skipUserEvent) { state.skipUserEvent = false; break; }
      removeEmptyHint();
      addUserMsg(ev.text);
      state.liveAssistant = null;
      break;
    case "ai_delta": appendAiText(ev.text); break;
    case "reasoning_delta": appendReasoning(ev.text); break;
    case "tool_calls":
      for (const c of ev.calls) {
        if (!hasToolRow(c.id)) addToolCard(c);
      }
      break;
    case "tool_result": setToolResult(ev.id, ev.name, ev.text, ev.status); break;
    case "todos": renderTodos(ev.todos); break;
    case "interrupt": {
      finalizeThink(state.liveAssistant);
      showApproval(ev.interrupts);
      const first = ev.interrupts.flatMap(i => i.actionRequests)[0];
      if (first) notifyApproval(`${first.name}: ${toolArgSummary(first.name, first.args)}`.slice(0, 120));
      break;
    }
    case "warning": addWarnBanner(ev.message); break;
    case "error": flushAiRender(); addWarnBanner("错误: " + ev.message); break;
    case "done": flushAiRender(); finalizeThink(state.liveAssistant); break;
  }
}

function detachStream() {
  state.streamAbort?.abort();
  state.streamAbort = null;
}

async function attachStream({ skipUser = false, statusText } = {}) {
  detachStream();
  const ctrl = new AbortController();
  state.streamAbort = ctrl;
  const sess = state.current;
  setStreaming(true, statusText);
  state.liveAssistant = null;
  state.skipUserEvent = skipUser;
  try {
    const res = await fetch(`${CTX}/sessions/${sess.id}/stream`, { signal: ctrl.signal });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    await consumeSSE(res);
    if (state.streamAbort === ctrl) {
      state.streamAbort = null;
      setStreaming(false);
      notifyRunEnd(sess.title);
      loadSessions();
    }
  } catch (e) {
    if (ctrl.signal.aborted) return; // 主动切换/替换了订阅，忽略
    // 连接中途断开（休眠、网络抖动）——重新从历史同步并重挂
    if (state.current?.id === sess.id) selectSession(state.current);
  }
}

async function startRunRequest(url, body, opts) {
  setStreaming(true, opts?.statusText);
  try {
    await api(url, { method: "POST", body });
  } catch (e) {
    addWarnBanner("请求失败: " + e.message);
    setStreaming(false);
    loadSessions();
    return;
  }
  attachStream(opts);
}

export function sendMessage() {
  const text = $("input").value.trim();
  if (!text || state.streaming) return;
  if (!state.current) { openNewSessionModal(); return; }
  requestNotifyPermission();
  $("input").value = "";
  autoGrow();
  removeEmptyHint();
  addUserMsg(text);
  scrollBottom(true);
  startRunRequest(`/sessions/${state.current.id}/messages`, { content: text }, { skipUser: true });
}

async function resumeRun(decisions, allowAdds = []) {
  // 先落白名单再恢复运行：resume 会重建 agent，本轮后续同类调用即可自动放行
  if (allowAdds.length) {
    try {
      await saveAllowlist(allowAdds);
    } catch (e) {
      addWarnBanner("保存审批白名单失败: " + e.message);
    }
  }
  startRunRequest(`/sessions/${state.current.id}/resume`, { decisions }, { statusText: "执行已审批的操作…" });
}
setApprovalHandler(resumeRun);

// ------------------------------------------------------------ sidebar: grouped sessions
export async function loadSessions() {
  const { sessions } = await api("/sessions/");
  state.sessions = sessions;
  renderSessions();
}

function renderSessions() {
  const groups = new Map(); // projectKey -> sessions[]
  for (const s of state.sessions) {
    const key = projectKeyOf(s.cwd);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(s);
  }
  const entries = [...groups.entries()].sort(
    (a, b) => Math.max(...b[1].map(s => s.updated_at)) - Math.max(...a[1].map(s => s.updated_at))
  );
  // 项目组按最近使用排序，「独立会话」组固定最后
  const ordered = [
    ...entries.filter(([k]) => k !== "__standalone__"),
    ...entries.filter(([k]) => k === "__standalone__"),
  ];
  const el = $("sessions");
  el.innerHTML = "";
  for (const [key, list] of ordered) el.appendChild(renderGroup(key, list));
}

function renderGroup(key, list) {
  const standalone = key === "__standalone__";
  const g = document.createElement("div");
  g.className = "group" + (state.collapsed.has(key) ? " collapsed" : "");
  const head = document.createElement("div");
  head.className = "group-head";
  head.innerHTML = `<span class="chev">▼</span><span class="gicon">${standalone ? "🗂" : "📁"}</span>
    <span class="gname">${esc(projectLabel(key))}</span>
    <span class="gpath">${esc(standalone ? "workspaces/*" : shortPath(key))}</span>
    <span class="gcount">${list.length}</span>`;
  head.onclick = () => {
    g.classList.toggle("collapsed");
    if (g.classList.contains("collapsed")) state.collapsed.add(key);
    else state.collapsed.delete(key);
    saveCollapsed();
  };
  g.appendChild(head);
  const body = document.createElement("div");
  body.className = "group-body";
  for (const s of list) body.appendChild(renderSessionItem(s));
  const add = document.createElement("div");
  add.className = "session-item new-in";
  add.innerHTML = `<span>＋</span><div class="s-main"><div class="s-title" style="color:inherit">${
    standalone ? "新建独立会话" : "在此项目新建会话"}</div></div>`;
  add.onclick = async () => {
    try {
      const { session } = await api("/sessions/", {
        method: "POST", body: { cwd: standalone ? "" : key },
      });
      await loadSessions();
      selectSession(session);
    } catch (e) { alert(e.message); }
  };
  body.appendChild(add);
  g.appendChild(body);
  return g;
}

function renderSessionItem(s) {
  const item = document.createElement("div");
  item.className = "session-item" + (state.current?.id === s.id ? " active" : "");
  item.innerHTML = `
    <span class="dot ${s.busy ? "busy" : ""}"></span>
    <div class="s-main">
      <div class="s-title">${esc(s.title)}</div>
      <div class="s-meta">${s.busy
        ? '<span class="busy-label">运行中</span><span class="spinner"></span>'
        : `<span>空闲</span><span>${relTime(s.updated_at)}</span>`}</div>
    </div>
    <span class="acts">
      <button title="重命名">✎</button>
      <button title="删除">✕</button>
    </span>`;
  item.onclick = () => selectSession(s);
  const [rnBtn, delBtn] = item.querySelectorAll(".acts button");
  rnBtn.onclick = (e) => { e.stopPropagation(); openRename(s); };
  // two-step inline confirm: native confirm() is silently suppressed in
  // embedded browser panes, which made deletion appear broken
  delBtn.onclick = async (e) => {
    e.stopPropagation();
    if (!delBtn.dataset.armed) {
      delBtn.dataset.armed = "1";
      delBtn.textContent = "确认删除";
      delBtn.style.color = "var(--red)";
      setTimeout(() => {
        delBtn.dataset.armed = "";
        delBtn.textContent = "✕";
        delBtn.style.color = "";
      }, 3000);
      return;
    }
    try {
      await api(`/sessions/${s.id}`, { method: "DELETE" });
    } catch (err) {
      addWarnBanner("删除会话失败: " + err.message);
      return;
    }
    fullHistory.delete(s.id);
    if (state.current?.id === s.id) { state.current = null; resetChat(); setTopbar(); }
    loadSessions();
  };
  return item;
}

// 用户点过「显示更早消息」的会话——重进时直接渲染全量历史
const fullHistory = new Set();
const HISTORY_LIMIT = 80;

export async function selectSession(s) {
  detachStream();
  setStreaming(false);
  state.current = s;
  setTopbar();
  resetChat();
  renderTodos([]);
  renderSessions();
  try {
    const h = await api(`/sessions/${s.id}/history`);
    if (state.current?.id !== s.id) return; // 加载期间切走了
    state.current = { ...s, ...h.session };
    setTopbar();
    state.liveAssistant = null;
    // 运行中：历史只渲染到本轮起点，本轮内容由 /stream 回放重建，避免重复
    let msgs = h.busy && h.runCutoff != null ? h.messages.slice(0, h.runCutoff) : h.messages;
    const total = msgs.length;
    // 长会话只渲染最近一段（截断点退到用户消息边界，保住工具行与结果的配对）
    if (!fullHistory.has(s.id) && msgs.length > HISTORY_LIMIT) {
      let start = msgs.length - HISTORY_LIMIT;
      while (start > 0 && msgs[start].role !== "user") start--;
      if (start > 0) {
        msgs = msgs.slice(start);
        addHistoryGap(start, () => { fullHistory.add(s.id); selectSession(s); });
      }
    }
    for (const m of msgs) {
      if (m.role === "user") addUserMsg(m.text);
      else if (m.role === "assistant") {
        const turn = newAssistantTurn();
        if (m.reasoning) addHistoryThink(turn, m.reasoning);
        if (m.text) appendAiText(m.text);
        for (const c of m.tool_calls) addToolCard(c);
      } else if (m.role === "tool") {
        setToolResult(m.tool_call_id, m.name, m.text, m.status);
      }
    }
    flushAiRender();
    renderTodos(h.todos);
    if (h.interrupts?.length) showApproval(h.interrupts);
    state.liveAssistant = null;
    if (!h.busy && h.lastRun?.status === "error" && h.lastRun.error) {
      addWarnBanner("上次运行出错: " + h.lastRun.error);
    }
    if (total === 0 && !h.busy) showEmptyHint();
    scrollBottom(true);
    if (h.busy) attachStream();
  } catch (e) {
    addWarnBanner("加载历史失败: " + e.message);
  }
}

// ------------------------------------------------------------ new session modal
export async function openNewSessionModal() {
  $("new-cwd").value = "";
  const box = $("recent-dirs");
  box.innerHTML = "";
  try {
    const { dirs } = await api("/sessions/dirs/recent");
    if (dirs.length) {
      const label = document.createElement("div");
      label.className = "hint";
      label.style.marginBottom = "4px";
      label.textContent = "最近使用";
      box.appendChild(label);
      for (const d of dirs) {
        const row = document.createElement("div");
        row.className = "recent-dir";
        row.innerHTML = `<span>📁</span><span class="d-name">${esc(baseName(d))}</span>
          <span class="d-path">${esc(shortPath(d))}</span>`;
        row.onclick = () => { $("new-cwd").value = d; };
        box.appendChild(row);
      }
    }
  } catch {}
  $("new-session-backdrop").classList.add("visible");
  $("new-cwd").focus();
}

async function createSessionFromModal() {
  const cwd = $("new-cwd").value.trim();
  try {
    const { session } = await api("/sessions/", { method: "POST", body: { cwd } });
    $("new-session-backdrop").classList.remove("visible");
    await loadSessions();
    selectSession(session);
  } catch (e) { alert(e.message); }
}

// ------------------------------------------------------------ rename modal
let renameTarget = null;
function openRename(s) {
  renameTarget = s;
  $("rename-input").value = s.title;
  $("rename-backdrop").classList.add("visible");
  $("rename-input").focus();
}

async function doRename() {
  const title = $("rename-input").value.trim();
  if (!title || !renameTarget) return;
  await api(`/sessions/${renameTarget.id}`, { method: "PATCH", body: { title } });
  $("rename-backdrop").classList.remove("visible");
  if (state.current?.id === renameTarget.id) { state.current.title = title; setTopbar(); }
  loadSessions();
}

// ------------------------------------------------------------ composer & wiring
function autoGrow() {
  const el = $("input");
  el.style.height = "auto";
  el.style.height = Math.min(el.scrollHeight, 200) + "px";
}

export function initSessions() {
  $("input").addEventListener("input", autoGrow);
  $("input").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); }
  });
  $("btn-send").onclick = sendMessage;
  $("btn-stop").onclick = () => state.current && api(`/sessions/${state.current.id}/stop`, { method: "POST" });
  $("btn-new").onclick = openNewSessionModal;
  $("btn-ns-cancel").onclick = () => $("new-session-backdrop").classList.remove("visible");
  $("btn-ns-create").onclick = createSessionFromModal;
  $("new-cwd").addEventListener("keydown", (e) => { if (e.key === "Enter") createSessionFromModal(); });
  $("btn-rn-cancel").onclick = () => $("rename-backdrop").classList.remove("visible");
  $("btn-rn-ok").onclick = doRename;
  $("rename-input").addEventListener("keydown", (e) => { if (e.key === "Enter") doRename(); });
}
