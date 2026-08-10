/**
 * 模型连通性与 tool calling 自检。
 * 在 .env 配好 MODEL_* 后运行：bun test/check-model.js
 */
import { tool } from "langchain";
import { z } from "zod";
import { buildModel } from "../src/agent.js";

const model = buildModel();
console.log(`模型: ${process.env.MODEL_NAME} @ ${process.env.MODEL_BASE_URL}`);

// 1. 基本对话
process.stdout.write("1) 基本对话 … ");
const r1 = await model.invoke([{ role: "user", content: "回复「ok」两个字母即可" }]);
console.log(`通过（${JSON.stringify(r1.content).slice(0, 60)}）`);

// 2. tool calling
process.stdout.write("2) tool calling … ");
const echoTool = tool(async ({ text }) => text, {
  name: "echo",
  description: "Echo the given text back verbatim.",
  schema: z.object({ text: z.string() }),
});
const bound = model.bindTools([echoTool]);
const r2 = await bound.invoke([
  { role: "user", content: "请调用 echo 工具，参数 text 为 hello" },
]);
if (r2.tool_calls?.length) {
  console.log(`通过（调用了 ${r2.tool_calls[0].name}，args=${JSON.stringify(r2.tool_calls[0].args)}）`);
} else {
  console.log("失败：模型没有返回 tool_calls。该模型可能不支持工具调用，agent 无法正常工作。");
  process.exit(1);
}

// 3. 流式输出
process.stdout.write("3) 流式输出 … ");
let n = 0;
for await (const _ of await model.stream([{ role: "user", content: "从1数到5" }])) n++;
console.log(`通过（${n} 个 chunk）`);

console.log("\n全部通过，可以运行 bun start 启动服务。");
process.exit(0);
