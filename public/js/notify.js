// 页面不可见时的提醒：标签页标题徽标 + 系统通知
const BASE_TITLE = document.title;

function setBadge(badge) {
  document.title = badge + BASE_TITLE;
}

document.addEventListener("visibilitychange", () => {
  if (!document.hidden) setBadge("");
});

function sysNotify(title, body) {
  if ("Notification" in window && Notification.permission === "granted") {
    new Notification(title, { body, tag: "deepagent" }); // 同 tag 覆盖旧通知，避免堆积
  }
}

// 在用户手势（首次发送消息）里请求授权，此时浏览器才不会静默拒绝
export function requestNotifyPermission() {
  if ("Notification" in window && Notification.permission === "default") {
    Notification.requestPermission();
  }
}

export function notifyApproval(summary) {
  if (!document.hidden) return;
  setBadge("⏸ ");
  sysNotify("Agent 等待审批", summary);
}

export function notifyRunEnd(sessionTitle) {
  if (!document.hidden) return;
  setBadge("✅ ");
  sysNotify("任务运行结束", sessionTitle);
}
