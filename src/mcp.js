/**
 * MCP server integration via @langchain/mcp-adapters.
 *
 * Converts the user's configured MCP servers into LangChain tools that get
 * passed straight into createDeepAgent. The client is cached and only
 * rebuilt when the enabled server set changes (config hash).
 */
import { MultiServerMCPClient } from "@langchain/mcp-adapters";

let cached = null; // { hash, client, tools }

function toAdapterConfig(servers) {
  const mcpServers = {};
  for (const s of servers) {
    if (!s.enabled) continue;
    if (s.transport === "stdio") {
      mcpServers[s.name] = {
        transport: "stdio",
        command: s.command,
        args: s.args ?? [],
        env: s.env ?? undefined,
      };
    } else {
      // streamable HTTP (falls back to SSE automatically inside the adapter)
      mcpServers[s.name] = {
        transport: "http",
        url: s.url,
        headers: s.headers ?? undefined,
      };
    }
  }
  return mcpServers;
}

export async function getMcpTools(servers) {
  const config = toAdapterConfig(servers);
  const names = Object.keys(config);
  if (names.length === 0) {
    if (cached?.client) await cached.client.close().catch(() => {});
    cached = null;
    return { tools: [], errors: [] };
  }

  const hash = JSON.stringify(config);
  if (cached && cached.hash === hash) {
    return { tools: cached.tools, errors: [] };
  }
  if (cached?.client) await cached.client.close().catch(() => {});
  cached = null;

  const errors = [];
  const client = new MultiServerMCPClient({
    mcpServers: config,
    throwOnLoadError: false,
    prefixToolNameWithServerName: true,
  });
  let tools = [];
  try {
    tools = await client.getTools();
  } catch (e) {
    errors.push(String(e?.message ?? e));
  }
  cached = { hash, client, tools };
  return { tools, errors };
}

export async function closeMcp() {
  if (cached?.client) await cached.client.close().catch(() => {});
  cached = null;
}
