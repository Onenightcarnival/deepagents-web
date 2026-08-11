/**
 * Deep agent construction: custom OpenAI-compatible model + local shell
 * backend + human-in-the-loop approvals + MCP tools + SQLite checkpointer.
 */
import { existsSync } from "node:fs";
import { createDeepAgent, LocalShellBackend } from "deepagents";
import { ChatOpenAI } from "@langchain/openai";
import { getMcpTools } from "./mcp.js";

const SYSTEM_PROMPT = `You are a capable coding and general-purpose agent running on the user's machine, similar to Codex or Claude Code.

Rules:
- The working directory is the user's project directory. Prefer relative paths inside it.
- Use the filesystem tools (ls, read_file, write_file, edit_file, glob, grep) to inspect and modify files, and \`execute\` to run shell commands.
- For multi-step work, maintain a todo list with write_todos and keep it updated as you progress.
- Before destructive operations (deleting files, force-pushing, overwriting uncommitted work), explain what you are about to do.
- Reply in the same language the user writes in.
- Keep final answers concise; the user can see tool outputs in the UI.`;

/**
 * @param {{baseUrl: string, apiKey: string, model: string}} resolved
 *   Concrete model config (see providers.js resolveModel).
 * @param {{thinking?: null|"on"|"off", thinkingEffort?: string,
 *          temperature?: number|null, maxTokens?: number|null}} [params]
 *   Project-level generation params (see providers.js resolveParams).
 *   null fields are not sent, so the provider default applies.
 */
export function buildModel(resolved, params = {}) {
  const { baseUrl, apiKey, model } = resolved;
  if (!baseUrl || !apiKey || !model) {
    throw new Error("模型配置不完整：请在设置 → 模型服务中配置，或在 .env 中配置 MODEL_*");
  }
  // NOTE: do not set `streaming: true` here — under Bun, ChatOpenAI's
  // invoke() path with forced streaming can stall. LangGraph still streams
  // tokens automatically when the agent itself is streamed.
  const opts = {
    model,
    apiKey,
    configuration: { baseURL: baseUrl },
    maxRetries: Number(process.env.MODEL_MAX_RETRIES ?? 2),
  };
  if (params.temperature != null) {
    opts.temperature = Number(params.temperature);
  } else if (process.env.MODEL_TEMPERATURE !== undefined && process.env.MODEL_TEMPERATURE !== "") {
    opts.temperature = Number(process.env.MODEL_TEMPERATURE);
  }
  if (params.maxTokens != null) opts.maxTokens = Number(params.maxTokens);
  // Thinking control is provider-specific; only sent when explicitly overridden.
  // DeepSeek (V4 API): body-level `thinking: {type}` + `reasoning_effort`
  // (low/high/max, default high). In thinking mode DeepSeek ignores
  // temperature/top_p — no error, just no effect.
  const modelKwargs = {};
  if (resolved.type === "deepseek") {
    if (params.thinking === "on") {
      modelKwargs.thinking = { type: "enabled" };
      const effort = params.thinkingEffort === "medium" ? "high" : params.thinkingEffort;
      modelKwargs.reasoning_effort = effort ?? "high";
    } else if (params.thinking === "off") {
      modelKwargs.thinking = { type: "disabled" };
    }
  }
  if (Object.keys(modelKwargs).length) opts.modelKwargs = modelKwargs;
  return new ChatOpenAI(opts);
}

function buildInterruptOn(approvalMode, mcpToolNames) {
  if (approvalMode === "off") return undefined;
  const gated = {
    execute: true,
    write_file: true,
    edit_file: true,
  };
  if (approvalMode === "all") {
    for (const name of ["ls", "read_file", "glob", "grep"]) gated[name] = true;
    for (const name of mcpToolNames) gated[name] = true;
  } else if (approvalMode === "dangerous+mcp") {
    for (const name of mcpToolNames) gated[name] = true;
  }
  return gated;
}

/**
 * Build a deep agent for one session.
 * @param {object} opts
 * @param {string} opts.cwd            session working directory
 * @param {object} opts.checkpointer   shared SqliteSaver
 * @param {Array}  opts.mcpServers     MCP server configs from the app db
 * @param {string} opts.approvalMode   "off" | "dangerous" | "dangerous+mcp" | "all"
 * @param {object} opts.model          resolved model config {baseUrl, apiKey, model}
 * @param {object} [opts.params]       project-level generation params
 * @param {string[]} [opts.skillDirs]  absolute skill source directories
 */
export async function buildAgent({ cwd, checkpointer, mcpServers, approvalMode, model, params, skillDirs }) {
  const { tools: mcpTools, errors: mcpErrors } = await getMcpTools(mcpServers ?? []);

  const backend = new LocalShellBackend({
    rootDir: cwd,
    inheritEnv: true,
    timeout: Number(process.env.SHELL_TIMEOUT ?? 300),
    maxOutputBytes: 200_000,
  });

  // only pass skill dirs that exist — SkillsMiddleware errors on missing paths
  const skills = (skillDirs ?? []).filter((d) => existsSync(d)).map((d) => (d.endsWith("/") ? d : d + "/"));

  const agent = createDeepAgent({
    model: buildModel(model, params),
    backend,
    tools: mcpTools,
    systemPrompt: SYSTEM_PROMPT,
    checkpointer,
    ...(skills.length ? { skills } : {}),
    interruptOn: buildInterruptOn(
      approvalMode ?? "dangerous",
      mcpTools.map((t) => t.name)
    ),
  });

  return { agent, mcpErrors };
}
