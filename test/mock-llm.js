/**
 * Minimal OpenAI-compatible mock LLM for end-to-end testing without a real
 * API key. Scripted behavior:
 *   - If the last message is not a tool result: call `execute` with an echo.
 *   - If a tool result is present: stream a short final text answer.
 * Run: bun test/mock-llm.js  (listens on :8901)
 */
const PORT = Number(process.env.MOCK_PORT ?? 8901);
// per-word delay when streaming the final answer; raise it (e.g. 800) to
// keep a run in-flight long enough to exercise detach/reattach flows
const DELAY = Number(process.env.MOCK_DELAY_MS ?? 30);

function sse(obj) {
  return `data: ${JSON.stringify(obj)}\n\n`;
}

// one id per completion, shared by all chunks of that completion
function makeChunkFactory() {
  const id = "chatcmpl-" + Math.random().toString(36).slice(2);
  return function chunk(delta, finish = null) {
    return {
      id,
      object: "chat.completion.chunk",
      created: Math.floor(Date.now() / 1000),
      model: "mock-model",
      choices: [{ index: 0, delta, finish_reason: finish }],
    };
  };
}

Bun.serve({
  port: PORT,
  async fetch(req) {
    const url = new URL(req.url);
    if (!url.pathname.endsWith("/chat/completions")) {
      return new Response("not found", { status: 404 });
    }
    const body = await req.json();
    const messages = body.messages ?? [];
    const hasToolResult = messages.some((m) => m.role === "tool");
    const usage = { prompt_tokens: 10, completion_tokens: 10, total_tokens: 20 };

    if (body.stream === false) {
      const message = hasToolResult
        ? { role: "assistant", content: "命令已执行，见工具结果。" }
        : {
            role: "assistant",
            content: "",
            tool_calls: [
              {
                id: "call_mock_1",
                type: "function",
                function: {
                  name: "execute",
                  arguments: JSON.stringify({ command: "echo hello-from-mock-agent" }),
                },
              },
            ],
          };
      return Response.json({
        id: "chatcmpl-" + Math.random().toString(36).slice(2),
        object: "chat.completion",
        created: Math.floor(Date.now() / 1000),
        model: "mock-model",
        choices: [
          {
            index: 0,
            message,
            finish_reason: hasToolResult ? "stop" : "tool_calls",
          },
        ],
        usage,
      });
    }

    const stream = new ReadableStream({
      async start(controller) {
        const chunk = makeChunkFactory();
        const enc = new TextEncoder();
        const push = (s) => controller.enqueue(enc.encode(s));

        if (!hasToolResult) {
          // stream a tool call to `execute`
          push(sse(chunk({ role: "assistant", content: "" })));
          push(
            sse(
              chunk({
                tool_calls: [
                  {
                    index: 0,
                    id: "call_mock_1",
                    type: "function",
                    function: { name: "execute", arguments: "" },
                  },
                ],
              })
            )
          );
          const args = JSON.stringify({ command: "echo hello-from-mock-agent" });
          for (const piece of [args.slice(0, 12), args.slice(12)]) {
            push(
              sse(
                chunk({
                  tool_calls: [{ index: 0, function: { arguments: piece } }],
                })
              )
            );
          }
          push(sse(chunk({}, "tool_calls")));
        } else {
          push(sse(chunk({ role: "assistant", content: "" })));
          for (const word of ["命令", "已执行", "，输出", "见上方", "工具结果。"]) {
            push(sse(chunk({ content: word })));
            await new Promise((r) => setTimeout(r, DELAY));
          }
          push(sse(chunk({}, "stop")));
        }
        // usage chunk (as sent by OpenAI with stream_options.include_usage)
        push(
          sse({
            id: "chatcmpl-" + Math.random().toString(36).slice(2),
            object: "chat.completion.chunk",
            created: Math.floor(Date.now() / 1000),
            model: "mock-model",
            choices: [],
            usage,
          })
        );
        push("data: [DONE]\n\n");
        controller.close();
      },
    });

    return new Response(stream, {
      headers: {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
      },
    });
  },
});

console.log(`mock LLM listening on http://127.0.0.1:${PORT}/v1`);
