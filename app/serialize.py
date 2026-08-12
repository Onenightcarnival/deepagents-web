"""Convert LangChain message objects / stream events into plain JSON shapes
the web UI understands (same wire format as the previous JS backend).
"""


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
        out.append({
            "actionRequests": [
                {"name": a.get("name"), "args": a.get("args"),
                 "description": a.get("description")}
                for a in (v.get("action_requests") or [])
            ],
            "reviewConfigs": [
                {"actionName": r.get("action_name"),
                 "allowedDecisions": r.get("allowed_decisions")}
                for r in (v.get("review_configs") or [])
            ],
        })
    return out


def serialize_task_interrupts(tasks) -> list[dict]:
    out = []
    for task in tasks or []:
        out.extend(serialize_interrupt_values(getattr(task, "interrupts", None)))
    return out
