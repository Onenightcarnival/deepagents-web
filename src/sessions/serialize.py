"""Convert LangChain message objects / stream events into plain JSON shapes
the web UI understands (same wire format as the previous JS backend).
"""

import json
import time


def content_to_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for b in content:
            if isinstance(b, str):
                parts.append(b)
            elif isinstance(b, dict) and b.get("type") in ("text", "text_delta"):
                parts.append(b.get("text") or "")
        return "".join(parts)
    return ""


def serialize_message(msg) -> dict | None:
    t = getattr(msg, "type", None)
    if t == "human":
        return {"role": "user", "text": content_to_text(msg.content)}
    if t == "ai":
        return {
            "role": "assistant",
            "text": content_to_text(msg.content),
            "reasoning": (msg.additional_kwargs or {}).get("reasoning_content"),
            "tool_calls": [
                {"id": c.get("id"), "name": c.get("name"), "args": c.get("args")}
                for c in (getattr(msg, "tool_calls", None) or [])
            ],
        }
    if t == "tool":
        return {
            "role": "tool",
            "tool_call_id": msg.tool_call_id,
            "name": msg.name,
            "text": content_to_text(msg.content),
            "status": getattr(msg, "status", None) or "success",
        }
    return None  # system/other messages are not shown


def serialize_history(messages) -> list[dict]:
    out = []
    for m in messages or []:
        s = serialize_message(m)
        if s:
            out.append(s)
    return out


def serialize_interrupt_values(interrupts) -> list[dict]:
    """Interrupt objects (HITLRequest payloads) -> the camelCase shape the UI
    expects, matching the JS backend."""
    out = []
    for intr in interrupts or []:
        v = getattr(intr, "value", None) or {}
        out.append(
            {
                "actionRequests": [
                    {"name": a.get("name"), "args": a.get("args"), "description": a.get("description")}
                    for a in (v.get("action_requests") or [])
                ],
                "reviewConfigs": [
                    {"actionName": r.get("action_name"), "allowedDecisions": r.get("allowed_decisions")}
                    for r in (v.get("review_configs") or [])
                ],
            }
        )
    return out


def serialize_task_interrupts(tasks) -> list[dict]:
    out = []
    for task in tasks or []:
        out.extend(serialize_interrupt_values(getattr(task, "interrupts", None)))
    return out


# ---------------------------------------------------------------- Markdown 导出

_EXPORT_RESULT_LIMIT = 4000


def _tool_call_markdown(call: dict, results: dict[str, dict]) -> list[str]:
    args = json.dumps(call.get("args") or {}, ensure_ascii=False, indent=2)
    lines = [f"<details><summary>🔧 {call.get('name')}</summary>", "", "```json", args, "```"]
    result = results.get(call.get("id"))
    if result:
        mark = "✗" if result.get("status") == "error" else "✓"
        text = (result.get("text") or "").strip() or "(空)"
        if len(text) > _EXPORT_RESULT_LIMIT:
            text = text[:_EXPORT_RESULT_LIMIT] + "\n…（已截断）"
        lines += ["", f"结果 {mark}:", "", "```", text, "```"]
    lines += ["</details>", ""]
    return lines


def history_to_markdown(session: dict, messages: list[dict]) -> str:
    """serialize_history 的结果 -> 可读的 Markdown 文档。工具结果按
    tool_call_id 归并进所属的助手回合。"""
    results = {m["tool_call_id"]: m for m in messages if m["role"] == "tool"}
    lines = [
        f"# {session['title']}",
        "",
        f"- 工作目录：`{session['cwd']}`",
        f"- 导出时间：{time.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
    ]
    for m in messages:
        if m["role"] == "user":
            lines += ["## 🧑 用户", "", m["text"], ""]
        elif m["role"] == "assistant":
            lines += ["## 🤖 助手", ""]
            if m.get("reasoning"):
                lines += ["<details><summary>思考过程</summary>", "", m["reasoning"], "</details>", ""]
            for call in m["tool_calls"]:
                lines += _tool_call_markdown(call, results)
            if m["text"]:
                lines += [m["text"], ""]
    return "\n".join(lines)
