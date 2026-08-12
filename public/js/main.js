// 入口：模块事件挂载 + 初始化加载
import { $ } from "./utils.js";
import { api } from "./api.js";
import { state } from "./state.js";
import { initChat, showEmptyHint, addWarnBanner } from "./chat.js";
import { initTopbar, setTopbar } from "./topbar.js";
import { initSessions, loadSessions, selectSession } from "./sessions.js";
import { initSettings, loadSkills } from "./settings.js";

initChat();
initTopbar();
initSessions();
initSettings();

// 点击遮罩关闭弹窗
for (const bid of ["new-session-backdrop", "rename-backdrop", "skillmd-backdrop"]) {
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
