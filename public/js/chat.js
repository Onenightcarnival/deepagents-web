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

// ------------------------------------------------------------ 流式渲染节流
// 每个增量都全量重渲染 markdown，长回复会明显卡顿；把 120ms 内的增量合并成
// 一次渲染。分段切换（新工具行、新正文段、审批卡片）和运行结束时立即冲刷。
let pendingRender = null; // { turn, timer }

function renderTurnText(turn) {
  turn.textEl.innerHTML = renderMd(turn.text);
  enhanceContent(turn.textEl);
}

export function flushAiRender() {
  if (!pendingRender) return;
  clearTimeout(pendingRender.timer);
  const turn = pendingRender.turn;
  pendingRender = null;
  if (turn.textEl) renderTurnText(turn);
}

function scheduleRender(turn) {
  if (pendingRender && pendingRender.turn !== turn) flushAiRender();
  if (pendingRender) return;
  pendingRender = {
    turn,
    timer: setTimeout(() => {
      pendingRender = null;
      renderTurnText(turn);
      scrollBottom();
    }, 120),
  };
}

// ------------------------------------------------------------ 消息
export function resetChat() {
  if (pendingRender) { clearTimeout(pendingRender.timer); pendingRender = null; }
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

// 消息底部的操作行（悬浮出现）；getText 延迟取值，流式期间文本还在增长
function buildActions(getText, title) {
  const div = document.createElement("div");
  div.className = "msg-actions";
  const btn = document.createElement("button");
  btn.type = "button";
  btn.textContent = "复制";
  btn.title = title;
  btn.onclick = () => copyText(getText(), btn);
  div.appendChild(btn);
  return div;
}

export function addUserMsg(text) {
  const div = document.createElement("div");
  div.className = "msg user";
  div.innerHTML = `<div class="bubble">${esc(text)}</div>`;
  div.appendChild(buildActions(() => text, "复制这条消息"));
  chatEl.appendChild(div);
  scrollBottom();
}

export function newAssistantTurn() {
  const div = document.createElement("div");
  div.className = "msg assistant";
  // 内容都挂在 body 上，操作行固定留在消息末尾，不参与 lastElementChild 的分段判断
  const body = document.createElement("div");
  div.appendChild(body);
  const turn = { root: div, body, textEl: null, think: null, text: "", fullText: "" };
  const actions = buildActions(() => turn.fullText, "复制整条回答（Markdown 源码）");
  actions.style.display = "none"; // 只有产生过正文才显示
  div.appendChild(actions);
  turn.actions = actions;
  chatEl.appendChild(div);
  state.liveAssistant = turn;
  return turn;
}

function liveTurn() { return state.liveAssistant ?? newAssistantTurn(); }

export function appendAiText(text) {
  const turn = liveTurn();
  finalizeThink(turn);
  if (!turn.textEl || turn.textEl !== turn.body.lastElementChild) {
    flushAiRender();
    turn.textEl = document.createElement("div");
    turn.textEl.className = "content";
    turn.text = "";
    turn.body.appendChild(turn.textEl);
  }
  turn.text += text;
  turn.fullText += text;
  turn.actions.style.display = "";
  scheduleRender(turn);
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
    turn.body.appendChild(el);
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
  flushAiRender();
  const turn = liveTurn();
  finalizeThink(turn);
  let group = turn.body.lastElementChild;
  if (!group || !group.classList.contains("tool-group")) {
    group = document.createElement("div");
    group.className = "tool-group";
    turn.body.appendChild(group);
  }
  const row = document.createElement("div");
  // 文件改动的 diff 默认摊开可见（可点头部收起），其余工具保持折叠
  row.className = "trow" + (isDiffTool(call.name) ? " open" : "");
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

// 历史被截断时顶部的「显示更早消息」入口
export function addHistoryGap(count, onClick) {
  const div = document.createElement("div");
  div.className = "history-gap";
  div.innerHTML = `<button type="button">显示更早的 ${count} 条消息</button>`;
  div.querySelector("button").onclick = onClick;
  chatEl.appendChild(div);
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
// 每个操作独立决策（批准/拒绝），execute 的命令可编辑后批准（后端 decision
// type=edit），勾选「总是允许」把命令前缀/工具名加入项目审批白名单。
// handler(decisions, allowAdds)：decisions 与 actions 顺序一一对应。
let approvalHandler = () => {};
export function setApprovalHandler(fn) { approvalHandler = fn; }

function actionDetailHTML(a) {
  if (a.name === "execute") return `<pre>${esc(a.args?.command ?? "")}</pre>`;
  if (isDiffTool(a.name)) return diffBlockHTML(a.name, a.args);
  return `<pre>${esc(JSON.stringify(a.args ?? {}, null, 2))}</pre>`;
}

// 白名单前缀建议：取首段命令的前两个词（第二个词是选项时只取第一个），
// 例如 `git status --short` → `git status`，`ls -la` → `ls`
function suggestPrefix(command) {
  const seg = (command ?? "").split(/&&|\|\||[;|\n]/)[0].trim();
  const tokens = seg.split(/\s+/).filter(Boolean);
  if (!tokens.length) return "";
  return tokens[1] && !tokens[1].startsWith("-") ? `${tokens[0]} ${tokens[1]}` : tokens[0];
}

function buildApprovalRow(a, canEdit) {
  const isExec = a.name === "execute";
  const row = document.createElement("div");
  row.className = "ap-action";
  const allowTarget = isExec ? suggestPrefix(a.args?.command) : a.name;
  row.innerHTML = `
    <div class="ap-head">
      <span class="t-ico">${TOOL_ICONS[a.name] ?? "🔧"}</span>
      <span class="t-name">${esc(a.name)}</span>
      <span class="ap-seg">
        <button type="button" data-v="approve" class="on">批准</button>
        <button type="button" data-v="reject">拒绝</button>
      </span>
    </div>
    <div class="ap-detail"></div>
    <label class="ap-always">
      <input type="checkbox">
      <span>本项目总是允许 <code class="ap-allow-target"></code>，不再询问</span>
    </label>`;
  row.querySelector(".ap-allow-target").textContent = allowTarget;
  const detail = row.querySelector(".ap-detail");
  if (isExec && canEdit) {
    const ta = document.createElement("textarea");
    ta.className = "ap-cmd mono";
    ta.value = a.args?.command ?? "";
    ta.rows = Math.min(6, ta.value.split("\n").length + 1);
    // 编辑命令后，白名单建议前缀跟着最终要执行的命令走
    ta.oninput = () => { row.querySelector(".ap-allow-target").textContent = suggestPrefix(ta.value); };
    detail.appendChild(ta);
    row._cmd = ta;
  } else {
    detail.innerHTML = actionDetailHTML(a);
  }
  row._decision = "approve";
  for (const btn of row.querySelectorAll(".ap-seg button")) {
    btn.onclick = () => {
      row._decision = btn.dataset.v;
      for (const b of row.querySelectorAll(".ap-seg button")) b.classList.toggle("on", b === btn);
      row.classList.toggle("rejected", row._decision === "reject");
      row._onChange?.();
    };
  }
  return row;
}

export function showApproval(interrupts) {
  flushAiRender();
  const actions = interrupts.flatMap(i => i.actionRequests);
  if (actions.length === 0) return;
  // reviewConfigs 里是各工具允许的决策类型；缺省按全允许处理
  const allowedDecisions = new Map();
  for (const i of interrupts) {
    for (const rc of i.reviewConfigs ?? []) allowedDecisions.set(rc.actionName, rc.allowedDecisions ?? []);
  }
  const canEdit = (name) => (allowedDecisions.get(name) ?? ["approve", "edit", "reject"]).includes("edit");

  const div = document.createElement("div");
  div.className = "approval";
  div.innerHTML = `<h4>⚠ Agent 请求执行以下操作（${actions.length} 项）</h4>`;
  const rows = actions.map(a => buildApprovalRow(a, canEdit(a.name)));
  for (const row of rows) div.appendChild(row);
  const foot = document.createElement("div");
  foot.innerHTML = `
    <div class="field">
      <input type="text" class="ap-reason" placeholder="拒绝理由（可选，反馈给模型）">
    </div>
    <div class="buttons">
      <button class="primary ap-submit">批准执行</button>
    </div>`;
  div.appendChild(foot);

  const submitBtn = foot.querySelector(".ap-submit");
  const updateSubmit = () => {
    const ds = rows.map(r => r._decision);
    submitBtn.textContent = ds.every(d => d === "approve") ? "批准执行"
      : ds.every(d => d === "reject") ? "全部拒绝" : "提交决定";
    submitBtn.classList.toggle("danger", ds.every(d => d === "reject"));
    submitBtn.classList.toggle("primary", !ds.every(d => d === "reject"));
  };
  for (const row of rows) row._onChange = updateSubmit;

  submitBtn.onclick = () => {
    const reason = foot.querySelector(".ap-reason").value.trim();
    const decisions = actions.map((a, i) => {
      const row = rows[i];
      if (row._decision === "reject") return { type: "reject", message: reason || "用户拒绝了该操作" };
      // 命令被改过 → edit 决策（键名走 langchain 的 snake_case 约定）
      if (row._cmd && row._cmd.value !== (a.args?.command ?? "")) {
        return { type: "edit", edited_action: { name: a.name, args: { ...a.args, command: row._cmd.value } } };
      }
      return { type: "approve" };
    });
    const allowAdds = [];
    rows.forEach((row, i) => {
      if (row._decision !== "approve" || !row.querySelector(".ap-always input").checked) return;
      const a = actions[i];
      if (a.name === "execute") {
        const prefix = suggestPrefix(row._cmd ? row._cmd.value : a.args?.command);
        if (prefix) allowAdds.push({ tool: "execute", prefix });
      } else {
        allowAdds.push({ tool: a.name });
      }
    });
    div.remove();
    approvalHandler(decisions, allowAdds);
  };
  chatEl.appendChild(div);
  scrollBottom();
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
