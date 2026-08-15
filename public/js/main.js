// 入口：模块事件挂载 + 初始化加载。
// 设置页是独立的 Vue 应用（frontend/ 源码，assets/ 产物），通过两个自定义
// 事件桥接：settings:open（宿主 → 设置应用）、settings:changed（设置应用 → 宿主）。
import { api } from "./api.js";
import { addWarnBanner, initChat, showEmptyHint } from "./chat.js";
import { initFileTree } from "./filetree.js";
import { initSessions, loadSessions, selectSession } from "./sessions.js";
import { state } from "./state.js";
import { initTopbar, loadSkills, renderModelChip, setTopbar } from "./topbar.js";
import { $ } from "./utils.js";

initChat();
initTopbar();
initSessions();
initFileTree();

$("btn-settings").onclick = () => document.dispatchEvent(new CustomEvent("settings:open"));
document.addEventListener("settings:changed", async () => {
  state.config = await api("/settings/").catch(() => state.config);
  renderModelChip();
  loadSkills();
});

// 点击遮罩关闭弹窗
for (const bid of ["new-session-backdrop", "rename-backdrop", "file-view-backdrop"]) {
  $(bid).onclick = (e) => { if (e.target === $(bid)) $(bid).classList.remove("visible"); };
}

(async function init() {
  try {
    state.config = await api("/settings/");
    await Promise.all([loadSessions(), loadSkills()]);
    setTopbar();
    if (state.sessions.length) selectSession(state.sessions[0]);
    else showEmptyHint();
  } catch (e) {
    addWarnBanner("初始化失败: " + e.message);
  }
})();
