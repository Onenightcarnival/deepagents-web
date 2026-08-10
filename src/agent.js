/**
 * Deep agent construction: custom OpenAI-compatible model + local shell
 * backend + human-in-the-loop approvals + MCP tools + SQLite checkpointer.
 */
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

export function buildModel(env = process.env) {
  const baseURL = env.MODEL_BASE_URL;
  const apiKey = env.MODEL_API_KEY;
  const model = env.MODEL_NAME;
  if (!baseURL || !apiKey || !model) {
    throw new Error(
      "Missing model configuration: set MODEL_BASE_URL, MODEL_API_KEY, MODEL_NAME in .env"
    );
  }
  // NOTE: do not set `streaming: true` here — under Bun, ChatOpenAI's
  // invoke() path with forced streaming can stall. LangGraph still streams
  // tokens automatically when the agent itself is streamed.
  const opts = {
    model,
    apiKey,
    configuration: { baseURL },
    maxRetries: Number(env.MODEL_MAX_RETRIES ?? 2),
  };
  if (env.MODEL_TEMPERATURE !== undefined && env.MODEL_TEMPERATURE !== "") {
    opts.temperature = Number(env.MODEL_TEMPERATURE);
  }
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
 */
export async function buildAgent({ cwd, checkpointer, mcpServers, approvalMode }) {
  const { tools: mcpTools, errors: mcpErrors } = await getMcpTools(mcpServers ?? []);

  const backend = new LocalShellBackend({
    rootDir: cwd,
    inheritEnv: true,
    timeout: Number(process.env.SHELL_TIMEOUT ?? 300),
    maxOutputBytes: 200_000,
  });

  const agent = createDeepAgent({
    model: buildModel(),
    backend,
    tools: mcpTools,
    systemPrompt: SYSTEM_PROMPT,
    checkpointer,
    interruptOn: buildInterruptOn(
      approvalMode ?? "dangerous",
      mcpTools.map((t) => t.name)
    ),
  });

  return { agent, mcpErrors };
}
