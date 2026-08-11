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
    // Only streamable HTTP is supported; skip disabled or legacy stdio entries.
    if (!s.enabled || !s.url) continue;
    // streamable HTTP (falls back to SSE automatically inside the adapter)
    mcpServers[s.name] = {
      transport: "http",
      url: s.url,
      headers: s.headers ?? undefined,
    };
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
  const errors = [];
  if (!cached || cached.hash !== hash) {
    if (cached?.client) await cached.client.close().catch(() => {});
    cached = null;
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
  }

  // Per-tool disable is applied on top of the cached connection, so toggling
  // a tool never forces a reconnect. Adapter tool names are `server__tool`.
  const disabled = new Set(
    servers.filter((s) => s.enabled).flatMap((s) =>
      (s.disabledTools ?? []).map((t) => `${s.name}__${t}`)),
  );
  return { tools: cached.tools.filter((t) => !disabled.has(t.name)), errors };
}

export async function closeMcp() {
  if (cached?.client) await cached.client.close().catch(() => {});
  cached = null;
}

/**
 * Test a single server config with a throwaway client and list everything it
 * exposes: tools, prompts and resources (empty arrays when the server does
 * not advertise the capability).
 * @returns {{ok: boolean, tools?: object[], prompts?: object[], resources?: object[], error?: string}}
 */
export async function testMcpServer(config) {
  const name = config.name || "test";
  const map = toAdapterConfig([{ ...config, name, enabled: true }]);
  const client = new MultiServerMCPClient({
    mcpServers: map,
    throwOnLoadError: true,
    prefixToolNameWithServerName: false,
  });
  try {
    const tools = (await client.getTools()).map((t) => ({
      name: t.name,
      description: t.description ?? "",
      // JSON Schema of the tool's input (already dereferenced by the adapter)
      schema: t.schema && typeof t.schema === "object" ? t.schema : null,
    }));
    const raw = await client.getClient(name);
    const tryList = async (fn) => {
      try { return await fn(); } catch { return []; }
    };
    const prompts = await tryList(async () =>
      ((await raw.listPrompts()).prompts ?? []).map((p) => ({
        name: p.name,
        description: p.description ?? "",
        arguments: (p.arguments ?? []).map((a) => ({
          name: a.name, description: a.description ?? "", required: !!a.required,
        })),
      })));
    const resources = await tryList(async () =>
      ((await raw.listResources()).resources ?? []).map((r) => ({
        uri: r.uri,
        name: r.name ?? "",
        description: r.description ?? "",
        mimeType: r.mimeType ?? "",
      })));
    return { ok: true, tools, prompts, resources };
  } catch (e) {
    return { ok: false, error: String(e?.message ?? e) };
  } finally {
    await client.close().catch(() => {});
  }
}
