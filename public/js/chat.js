// 聊天区渲染：消息、思考过程、工具行、审批卡片、todos、滚动管理。
// 只负责 DOM，不发网络请求；审批决定通过 setApprovalHandler 注入。
import { $, esc } from "./utils.js";
import { state } from "./state.js";
import { renderMd, enhanceContent, copyText } from "./markdown.js";
import { isDiffTool, diffBlockHTML } from "./diffview.js";

const chatEl = $("chat-inner");

// ------------------------------------------------------------ 滚动管理
// 只有用户本来就停在底部附近时才跟随流式输出；向上翻阅时不再强行拽回，
// 改为显示「回到底部」悬浮按钮。
let stick = true;

function setStick(v) {
  stick = v;
  $("btn-jump-bottom").classList.toggle("visible", !stick);
}

export function scrollBottom(force = false) {
  if (force) setStick(true);
  if (stick) $("chat").scrollTop = $("chat").scrollHeight;
}

function updateStick() {
  const box = $("chat");
  setStick(box.scrollHeight - box.scrollTop - box.clientHeight < 80);
}

// ------------------------------------------------------------ 消息
export function resetChat() {
  chatEl.innerHTML = "";
  state.liveAssistant = null;
}

export function removeEmptyHint() {
  chatEl.querySelector("#empty-hint")?.remove();
}

export function showEmptyHint() {
  const div = document.createElement("div");
  div.id = "empty-hint";
  div.innerHTML = "在下方输入任务开始工作<br><span style='font-size:12px'>Agent 将在此目录下读写文件、执行命令</span>";
  chatEl.appendChild(div);
}

export function addUserMsg(text) {
  const div = document.createElement("div");
  div.className = "msg user";
  div.innerHTML = `<div class="bubble">${esc(text)}</div>`;
  chatEl.appendChild(div);
  scrollBottom();
}

export function newAssistantTurn() {
  const div = document.createElement("div");
  div.className = "msg assistant";
  const turn = { root: div, textEl: null, think: null, text: "", fullText: "" };
  // 复制按钮悬浮定位且始终是第一个子节点，不参与 lastElementChild 的分段判断
  const copyBtn = document.createElement("button");
  copyBtn.type = "button";
  copyBtn.className = "msg-copy";
  copyBtn.textContent = "复制";
  copyBtn.title = "复制整条回答（Markdown 源码）";
  copyBtn.style.display = "none";
  copyBtn.onclick = () => copyText(turn.fullText, copyBtn);
  div.appendChild(copyBtn);
  turn.copyBtn = copyBtn;
  chatEl.appendChild(div);
  state.liveAssistant = turn;
  return turn;
}

function liveTurn() { return state.liveAssistant ?? newAssistantTurn(); }

export function appendAiText(text) {
  const turn = liveTurn();
  finalizeThink(turn);
  if (!turn.textEl || turn.textEl !== turn.root.lastElementChild) {
    turn.textEl = document.createElement("div");
    turn.textEl.className = "content";
    turn.text = "";
    turn.root.appendChild(turn.textEl);
  }
  turn.text += text;
  turn.fullText += text;
  turn.copyBtn.style.display = "";
  turn.textEl.innerHTML = renderMd(turn.text);
  enhanceContent(turn.textEl);
  scrollBottom();
}

// ------------------------------------------------------------ 思考过程
function ensureThink(turn) {
  if (!turn.think) {
    const el = document.createElement("div");
    el.className = "think";
    el.innerHTML = `
      <button class="think-head" type="button">
        <span class="chev">▶</span><span class="tk-ico">✦</span>
        <span class="tk-label"></span>
      </button>
      <div class="think-body"></div>`;
    el.querySelector(".think-head").onclick = () => el.classList.toggle("open");
    turn.root.appendChild(el);
    turn.think = {
      el,
      label: el.querySelector(".tk-label"),
      body: el.querySelector(".think-body"),
      text: "",
      startedAt: Date.now(),
      done: false,
    };
  }
  return turn.think;
}

export function appendReasoning(text) {
  const turn = liveTurn();
  const th = ensureThink(turn);
  th.text += text;
  th.body.textContent = th.text;
  const lastLine = th.text.trim().split("\n").filter(Boolean).pop() ?? "";
  th.label.innerHTML = `<span class="shimmer-text">思考中 · ${esc(lastLine.slice(-60))}</span>`;
  scrollBottom();
}

export function finalizeThink(turn) {
  const th = turn?.think;
  if (!th || th.done) return;
  th.done = true;
  const secs = Math.max(1, Math.round((Date.now() - th.startedAt) / 1000));
  th.label.textContent = `已思考 · ${secs} 秒`;
}

export function addHistoryThink(turn, text) {
  const th = ensureThink(turn);
  th.text = text;
  th.body.textContent = text;
  th.done = true;
  th.label.textContent = "思考过程";
}

// ------------------------------------------------------------ 工具调用行
const TOOL_ICONS = {
  execute: "⌨️", read_file: "📖", write_file: "📝", edit_file: "✏️",
  ls: "📂", glob: "🔍", grep: "🔍", write_todos: "☑️", task: "🤖",
};

export function toolArgSummary(name, args) {
  if (!args || typeof args !== "object") return "";
  if (name === "execute") return args.command ?? "";
  if (args.file_path || args.path) return args.file_path ?? args.path;
  if (name === "glob" || name === "grep") return args.pattern ?? JSON.stringify(args);
  if (name === "write_todos") return `${(args.todos ?? []).length} 项`;
  return JSON.stringify(args);
}

export function hasToolRow(id) {
  return !!chatEl.querySelector(`.trow[data-call-id="${CSS.escape(id ?? "")}"]`);
}

export function addToolCard(call) {
  const turn = liveTurn();
  finalizeThink(turn);
  let group = turn.root.lastElementChild;
  if (!group || !group.classList.contains("tool-group")) {
    group = document.createElement("div");
    group.className = "tool-group";
    turn.root.appendChild(group);
  }
  const row = document.createElement("div");
  row.className = "trow";
  row.dataset.callId = call.id ?? "";
  // 写文件/改文件展示行级 diff，其余工具展示原始参数
  const argsHTML = isDiffTool(call.name)
    ? `<div class="io-label">改动</div>${diffBlockHTML(call.name, call.args)}`
    : `<div class="io-label">参数</div><pre>${esc(JSON.stringify(call.args ?? {}, null, 2))}</pre>`;
  row.innerHTML = `
    <button class="trow-head" type="button">
      <span class="chev">▶</span>
      <span class="t-ico">${TOOL_ICONS[call.name] ?? "🔧"}</span>
      <span class="t-name">${esc(call.name)}</span>
      <span class="t-arg">${esc(toolArgSummary(call.name, call.args))}</span>
      <span class="t-meta"></span>
      <span class="t-st"><span class="spinner"></span></span>
    </button>
    <div class="trow-body">
      ${argsHTML}
      <div class="result-slot"></div>
    </div>`;
  row.querySelector(".trow-head").onclick = () => row.classList.toggle("open");
  group.appendChild(row);
  turn.textEl = null;
  scrollBottom();
  return row;
}

export function setToolResult(id, name, text, status) {
  let row = chatEl.querySelector(`.trow[data-call-id="${CSS.escape(id ?? "")}"]`);
  if (!row) row = addToolCard({ id, name, args: {} });
  const ok = status !== "error";
  const st = row.querySelector(".t-st");
  st.textContent = ok ? "✓" : "✗";
  st.className = "t-st " + (ok ? "ok" : "err");
  const lines = (text ?? "").split("\n").length;
  row.querySelector(".t-meta").textContent = ok
    ? (text && lines > 1 ? `${lines} 行` : "")
    : "出错";
  row.querySelector(".result-slot").innerHTML =
    `<div class="io-label">结果</div><pre>${esc(text || "(空)")}</pre>`;
  scrollBottom();
}

export function addWarnBanner(text) {
  const div = document.createElement("div");
  div.className = "warn-banner";
  div.textContent = text;
  chatEl.appendChild(div);
  scrollBottom();
}

export function renderTodos(todos) {
  const el = $("todos");
  if (!todos || todos.length === 0) { el.classList.remove("visible"); return; }
  el.classList.add("visible");
  el.innerHTML = todos.map(t => {
    const icon = t.status === "completed" ? "☑" : t.status === "in_progress" ? "◉" : "☐";
    return `<div class="todo ${t.status}">${icon} ${esc(t.content)}</div>`;
  }).join("");
}

// ------------------------------------------------------------ 审批卡片
let approvalHandler = () => {};
export function setApprovalHandler(fn) { approvalHandler = fn; }

function actionDetailHTML(a) {
  if (a.name === "execute") return `<pre>${esc(a.args?.command ?? "")}</pre>`;
  if (isDiffTool(a.name)) return diffBlockHTML(a.name, a.args);
  return `<pre>${esc(JSON.stringify(a.args ?? {}, null, 2))}</pre>`;
}

export function showApproval(interrupts) {
  const actions = interrupts.flatMap(i => i.actionRequests);
  if (actions.length === 0) return;
  const div = document.createElement("div");
  div.className = "approval";
  div.innerHTML = `
    <h4>⚠ Agent 请求执行以下操作（${actions.length} 项）</h4>
    ${actions.map(a => `
      <div><strong style="font-family:monospace">${esc(a.name)}</strong></div>
      ${actionDetailHTML(a)}
    `).join("")}
    <div class="field">
      <input type="text" id="reject-reason" placeholder="拒绝理由（可选，拒绝时反馈给模型）">
    </div>
    <div class="buttons">
      <button class="primary" id="btn-approve">批准执行</button>
      <button class="danger" id="btn-reject">拒绝</button>
    </div>`;
  chatEl.appendChild(div);
  scrollBottom();
  const finish = () => div.remove();
  div.querySelector("#btn-approve").onclick = () => {
    finish();
    approvalHandler(actions.map(() => ({ type: "approve" })));
  };
  div.querySelector("#btn-reject").onclick = () => {
    const reason = div.querySelector("#reject-reason").value.trim();
    finish();
    approvalHandler(actions.map(() => ({ type: "reject", message: reason || "用户拒绝了该操作" })));
  };
}

// ------------------------------------------------------------ 事件挂载
export function initChat() {
  $("chat").addEventListener("scroll", updateStick);
  // 部分内嵌浏览器环境 scroll 事件不可靠，wheel 兜底：
  // 向上滚意味着用户要翻阅历史，立即解除跟随；向下滚延时按位置重新判定
  $("chat").addEventListener("wheel", (e) => {
    if (e.deltaY < 0) setStick(false);
    else setTimeout(updateStick, 50);
  }, { passive: true });
  // 注意：内嵌浏览器面板会静默忽略 scrollTo({behavior:"smooth"})，必须直接赋值
  $("btn-jump-bottom").onclick = () => {
    setStick(true);
    $("chat").scrollTop = $("chat").scrollHeight;
  };
  // 代码块复制按钮走事件委托：流式重渲染会反复销毁重建按钮，不能挂实例监听
  $("chat").addEventListener("click", (e) => {
    const btn = e.target.closest(".code-copy");
    if (btn) copyText(btn.parentElement.querySelector("code")?.innerText ?? "", btn);
  });
}
