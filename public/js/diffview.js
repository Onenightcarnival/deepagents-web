// edit_file / write_file 的行级 diff 视图（jsdiff 由 vendor UMD 提供全局 Diff）
import { esc } from "./utils.js";

export function isDiffTool(name) {
  return name === "edit_file" || name === "write_file";
}

// 生成「文件路径 + 增删统计 + diff 块」的 HTML，用于工具行展开体和审批卡片
export function diffBlockHTML(name, args) {
  const a = args ?? {};
  if (name === "edit_file") {
    return build(a.file_path, a.old_string, a.new_string, a.replace_all ? "替换全部匹配" : "");
  }
  // write_file 拿不到旧内容，整体按新增展示
  return build(a.file_path, "", a.content, "整文件写入");
}

function build(path, oldStr, newStr, note) {
  const parts = Diff.diffLines(String(oldStr ?? ""), String(newStr ?? ""));
  let added = 0, removed = 0, rows = "";
  for (const p of parts) {
    const cls = p.added ? "add" : p.removed ? "del" : "ctx";
    for (const line of p.value.replace(/\n$/, "").split("\n")) {
      rows += `<div class="dl ${cls}">${esc(line)}\n</div>`;
      if (p.added) added++;
      else if (p.removed) removed++;
    }
  }
  return `
    <div class="diff-file">
      <code>${esc(path ?? "")}</code>
      ${note ? `<span>${esc(note)}</span>` : ""}
      <span class="da">+${added}</span><span class="dd">−${removed}</span>
    </div>
    <div class="diff-box">${rows}</div>`;
}
