/**
 * Convert LangChain message objects / stream events into plain JSON shapes
 * the web UI understands.
 */

export function contentToText(content) {
  if (typeof content === "string") return content;
  if (Array.isArray(content)) {
    return content
      .map((b) => {
        if (typeof b === "string") return b;
        if (b?.type === "text" || b?.type === "text_delta") return b.text ?? "";
        return "";
      })
      .join("");
  }
  return "";
}

export function serializeMessage(msg) {
  const type = msg.type ?? msg._getType?.();
  if (type === "human") {
    return { role: "user", text: contentToText(msg.content) };
  }
  if (type === "ai") {
    return {
      role: "assistant",
      text: contentToText(msg.content),
      reasoning: msg.additional_kwargs?.reasoning_content ?? null,
      tool_calls: (msg.tool_calls ?? []).map((t) => ({
        id: t.id,
        name: t.name,
        args: t.args,
      })),
    };
  }
  if (type === "tool") {
    return {
      role: "tool",
      tool_call_id: msg.tool_call_id,
      name: msg.name,
      text: contentToText(msg.content),
      status: msg.status ?? "success",
    };
  }
  return null; // system/other messages are not shown
}

export function serializeHistory(messages) {
  return (messages ?? []).map(serializeMessage).filter(Boolean);
}

export function serializeInterrupts(tasks) {
  const out = [];
  for (const task of tasks ?? []) {
    for (const intr of task.interrupts ?? []) {
      const v = intr.value ?? {};
      out.push({
        actionRequests: (v.actionRequests ?? []).map((a) => ({
          name: a.name,
          args: a.args,
          description: a.description,
        })),
        reviewConfigs: (v.reviewConfigs ?? []).map((r) => ({
          actionName: r.actionName,
          allowedDecisions: r.allowedDecisions,
        })),
      });
    }
  }
  return out;
}
