// 文件树面板：以会话 cwd 为根懒加载目录，手动刷新（刷新=重拉并恢复展开）。
// 点文件在左侧查看器栏只读预览（带行号）；hljs 由 vendor UMD 提供全局。
import { api } from "./api.js";
import { state } from "./state.js";
import { $, esc } from "./utils.js";

// sessionId → Set<已展开的相对路径>，切会话来回时保留各自的展开状态
const expandedBySession = new Map();

function expandedSet() {
  const id = state.current?.id;
  if (!expandedBySession.has(id)) expandedBySession.set(id, new Set());
  return expandedBySession.get(id);
}

function panelWanted() { return localStorage.getItem("filePanelOpen") === "1"; }

let openRel = null; // 查看器当前打开的文件相对路径（刷新重建树时据此恢复高亮）

// 拉取 rel 目录并渲染进 box；已展开的子目录递归恢复
async function loadInto(rel, box, depth) {
  const sid = state.current?.id;
  if (!sid) return;
  let data;
  try {
    data = await api(`/files/${sid}?path=${encodeURIComponent(rel)}`);
  } catch (e) {
    if (state.current?.id !== sid) return; // 加载期间切走了
    box.innerHTML = `<div class="ft-err" style="padding-left:${10 + depth * 14}px">${esc(e.message)}</div>`;
    expandedSet().delete(rel); // 目录没了就别在刷新时反复重试
    return;
  }
  if (state.current?.id !== sid) return;
  box.innerHTML = "";
  if (!data.entries.length) {
    box.innerHTML = `<div class="ft-empty" style="padding-left:${10 + depth * 14}px">空目录</div>`;
    return;
  }
  for (const en of data.entries) box.appendChild(entryNode(rel, en, depth));
}

function entryNode(parentRel, en, depth) {
  const rel = parentRel ? `${parentRel}/${en.name}` : en.name;
  const wrap = document.createElement("div");
  const row = document.createElement("div");
  row.className = `ft-row ${en.type}`;
  row.style.paddingLeft = `${6 + depth * 14}px`;
  row.innerHTML = `<span class="ft-arrow">${en.type === "dir" ? "▸" : ""}</span><span class="ft-name">${esc(en.name)}</span>`;
  row.title = rel;
  wrap.appendChild(row);
  if (en.type === "dir") {
    const kids = document.createElement("div");
    wrap.appendChild(kids);
    const arrow = row.querySelector(".ft-arrow");
    const open = () => {
      expandedSet().add(rel);
      arrow.textContent = "▾";
      loadInto(rel, kids, depth + 1);
    };
    row.onclick = () => {
      if (expandedSet().has(rel)) {
        expandedSet().delete(rel);
        arrow.textContent = "▸";
        kids.innerHTML = "";
      } else open();
    };
    if (expandedSet().has(rel)) open(); // 刷新 / 切回会话时恢复展开
  } else {
    row.onclick = () => openFile(rel, row);
    if (rel === openRel) row.classList.add("active");
  }
  return wrap;
}

function refresh() {
  if (!state.current) return;
  loadInto("", $("filetree"), 0);
}

function fmtSize(n) {
  if (n >= 1024 * 1024) return (n / 1024 / 1024).toFixed(1) + " MB";
  if (n >= 1024) return (n / 1024).toFixed(1) + " KB";
  return n + " B";
}

async function openFile(rel, row) {
  openRel = rel;
  for (const r of document.querySelectorAll(".ft-row.active")) r.classList.remove("active");
  row?.classList.add("active");
  const code = document.querySelector("#fileview .fv-code code");
  const ln = document.querySelector("#fileview .fv-ln");
  $("fileview-path").textContent = rel;
  $("fileview-path").title = rel;
  $("fileview-meta").textContent = "";
  code.className = "hljs";
  code.textContent = "加载中…";
  ln.textContent = "";
  $("fileview").classList.add("visible");
  let data;
  try {
    data = await api(`/files/${state.current.id}/content?path=${encodeURIComponent(rel)}`);
  } catch (e) {
    if (openRel !== rel) return; // 等待期间切换了文件
    code.textContent = e.message; // 过大 / 二进制 / 已删除，直接把后端文案摆出来
    return;
  }
  if (openRel !== rel) return;
  const lines = data.content.split("\n");
  if (lines.length > 1 && lines.at(-1) === "") lines.pop(); // 末尾换行不算一行
  ln.textContent = lines.map((_, i) => i + 1).join("\n");
  $("fileview-meta").textContent = `${lines.length} 行 · ${fmtSize(data.size)}`;
  const ext = rel.split(".").pop().toLowerCase();
  // 超大文本不做高亮直出，避免卡住页面
  if (hljs.getLanguage(ext) && data.content.length < 200_000) {
    code.innerHTML = hljs.highlight(data.content, { language: ext }).value;
  } else {
    code.textContent = data.content;
  }
}

function closeViewer() {
  openRel = null;
  $("fileview").classList.remove("visible");
  for (const r of document.querySelectorAll(".ft-row.active")) r.classList.remove("active");
}

function setPanelVisible(on) {
  localStorage.setItem("filePanelOpen", on ? "1" : "0");
  $("filepanel").classList.toggle("visible", on && !!state.current);
  if (on && state.current) refresh();
  else closeViewer(); // 树关了，查看器留着没有意义
}

// 会话切换钩子：sessions.js 的 selectSession 里调用
export function fileTreeSessionChanged() {
  closeViewer(); // 查看器内容属于上个会话
  $("files-chip").style.display = state.current ? "" : "none";
  if (!state.current) {
    $("filepanel").classList.remove("visible");
    return;
  }
  $("filepanel").classList.toggle("visible", panelWanted());
  if (panelWanted()) refresh();
}

export function initFileTree() {
  $("files-chip").onclick = () => setPanelVisible(!panelWanted());
  $("btn-tree-close").onclick = () => setPanelVisible(false);
  $("btn-tree-refresh").onclick = refresh;
  $("btn-fv-close").onclick = closeViewer;
}
