// Markdown 渲染：marked 解析 + DOMPurify 消毒 + highlight.js 高亮。
// 三个库均由 vendor/ 下的 UMD 脚本提供全局变量（marked / DOMPurify / hljs）。

marked.use({ gfm: true, breaks: true });

// 外链在新标签页打开
DOMPurify.addHook("afterSanitizeAttributes", (node) => {
  if (node.tagName === "A" && node.hasAttribute("href")) {
    node.setAttribute("target", "_blank");
    node.setAttribute("rel", "noopener");
  }
});

export function renderMd(src) {
  return DOMPurify.sanitize(marked.parse(String(src)));
}

// 对渲染产物做增强：代码高亮 + 注入代码块复制按钮。
// 流式期间 innerHTML 会整体重建，因此每次渲染后都要重新调用。
export function enhanceContent(root) {
  for (const code of root.querySelectorAll("pre code")) {
    hljs.highlightElement(code);
    const pre = code.parentElement;
    if (!pre.querySelector(".code-copy")) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "code-copy";
      btn.textContent = "复制";
      pre.appendChild(btn);
    }
  }
}

// 复制文本。clipboard API 在两种情况下不可用：局域网 http 环境（API 不存在）、
// 内嵌面板等文档失焦场景（调用被拒），都退回 execCommand
function copyByExecCommand(text) {
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.style.position = "fixed";
  ta.style.opacity = "0";
  document.body.appendChild(ta);
  ta.select();
  const ok = document.execCommand("copy");
  ta.remove();
  return ok;
}

export async function copyText(text, btn) {
  let ok = false;
  if (navigator.clipboard) {
    ok = await navigator.clipboard.writeText(text).then(() => true, () => false);
  }
  if (!ok) {
    try { ok = copyByExecCommand(text); } catch { ok = false; }
  }
  if (btn) {
    const original = btn.textContent;
    btn.textContent = ok ? "✓ 已复制" : "复制失败";
    setTimeout(() => { btn.textContent = original; }, 1500);
  }
}
