/**
 * Self-hosted web agent server (Bun).
 *
 *   bun src/server.js          — serves the UI + API on http://127.0.0.1:3080
 *
 * Configuration via .env:
 *   MODEL_BASE_URL / MODEL_API_KEY / MODEL_NAME   (required)
 *   MODEL_TEMPERATURE, MODEL_MAX_RETRIES          (optional)
 *   PORT (default 3080), HOST (default 127.0.0.1)
 *   WORKSPACE_ROOT (default ./workspaces)
 *   AUTH_TOKEN (optional — required for LAN exposure)
 *   SHELL_TIMEOUT (seconds, default 300)
 */
import { mkdirSync, existsSync } from "node:fs";
import { resolve, join } from "node:path";
import { Command } from "@langchain/langgraph";
import { createAppDb } from "./db.js";
import { createCheckpointer } from "./checkpointer.js";
import { buildAgent } from "./agent.js";
import { getProviders, validateProviders, resolveModel, resolveParams, testProvider } from "./providers.js";
import { getSkillDirs, scanSkills, readSkillFile, expandPath } from "./skills.js";
import { testMcpServer } from "./mcp.js";
import {
  serializeHistory,
  serializeInterrupts,
  contentToText,
} from "./serialize.js";

const PORT = Number(process.env.PORT ?? 3080);
const HOST = process.env.HOST ?? "127.0.0.1";
const DATA_DIR = resolve(process.env.DATA_DIR ?? "data");
const WORKSPACE_ROOT = resolve(process.env.WORKSPACE_ROOT ?? "workspaces");
const AUTH_TOKEN = process.env.AUTH_TOKEN || null;
const PUBLIC_DIR = new URL("../public/", import.meta.url).pathname;

mkdirSync(DATA_DIR, { recursive: true });
mkdirSync(WORKSPACE_ROOT, { recursive: true });

const db = createAppDb(join(DATA_DIR, "app.db"));
const checkpointer = createCheckpointer(join(DATA_DIR, "checkpoints.db"));

/** sessionId -> AbortController for the currently active run */
const activeRuns = new Map();

// ---------------------------------------------------------------- helpers

function json(data, status = 200) {
  return Response.json(data, { status });
}

function unauthorized() {
  return json({ error: "unauthorized" }, 401);
}

function checkAuth(req) {
  if (!AUTH_TOKEN) return true;
  const h = req.headers.get("authorization");
  if (h === `Bearer ${AUTH_TOKEN}`) return true;
  const url = new URL(req.url);
  return url.searchParams.get("token") === AUTH_TOKEN;
}

/**
 * Model + params follow the project. A "project" is the session's working
 * directory; sessions in auto-created workspaces share one virtual project.
 */
function projectKeyFor(session) {
  return session.cwd.startsWith(WORKSPACE_ROOT) ? "__standalone__" : session.cwd;
}

async function getSessionAgent(session) {
  const projectKey = projectKeyFor(session);
  return buildAgent({
    cwd: session.cwd,
    checkpointer,
    mcpServers: db.listMcpServers(),
    approvalMode: db.getSetting("approvalMode", "dangerous"),
    model: resolveModel(db, projectKey),
    params: resolveParams(db, projectKey),
    skillDirs: getSkillDirs(db).map(expandPath),
  });
}

/** sessions carry model as a JSON TEXT column — expose it parsed. */
function publicSession(s) {
  if (!s) return s;
  let model = null;
  try { model = s.model ? JSON.parse(s.model) : null; } catch {}
  return { ...s, model };
}

function threadConfig(sessionId) {
  return { configurable: { thread_id: sessionId } };
}

/**
 * Stream one agent run (new message or resume) as SSE.
 */
function streamRun(session, input) {
  const encoder = new TextEncoder();
  const abort = new AbortController();
  activeRuns.set(session.id, abort);

  const stream = new ReadableStream({
    async start(controller) {
      const send = (obj) => {
        try {
          controller.enqueue(encoder.encode(`data: ${JSON.stringify(obj)}\n\n`));
        } catch {}
      };
      try {
        const { agent, mcpErrors } = await getSessionAgent(session);
        for (const err of mcpErrors) send({ type: "warning", message: `MCP: ${err}` });

        const runStream = await agent.stream(input, {
          ...threadConfig(session.id),
          streamMode: ["messages", "updates"],
          signal: abort.signal,
        });

        for await (const [mode, data] of runStream) {
          if (mode === "messages") {
            const [msg] = data;
            const cls = msg?.constructor?.name ?? "";
            if (cls === "AIMessageChunk" || cls === "ChatMessageChunk") {
              const text = contentToText(msg.content);
              if (text) send({ type: "ai_delta", text });
              const reasoning = msg.additional_kwargs?.reasoning_content;
              if (reasoning) send({ type: "reasoning_delta", text: reasoning });
            } else if (cls === "ToolMessage") {
              send({
                type: "tool_result",
                id: msg.tool_call_id,
                name: msg.name,
                text: contentToText(msg.content).slice(0, 20000),
                status: msg.status ?? "success",
              });
            }
          } else if (mode === "updates") {
            if (data.__interrupt__) {
              send({
                type: "interrupt",
                interrupts: serializeInterrupts([
                  { interrupts: data.__interrupt__ },
                ]),
              });
              continue;
            }
            for (const update of Object.values(data)) {
              if (!update || typeof update !== "object") continue;
              // surface completed AI messages (for tool_calls) and todos
              if (Array.isArray(update.todos)) {
                send({ type: "todos", todos: update.todos });
              }
              if (Array.isArray(update.messages)) {
                for (const m of update.messages) {
                  const t = m?.type ?? m?._getType?.();
                  if (t === "ai" && m.tool_calls?.length) {
                    send({
                      type: "tool_calls",
                      calls: m.tool_calls.map((c) => ({
                        id: c.id,
                        name: c.name,
                        args: c.args,
                      })),
                    });
                  }
                }
              }
            }
          }
        }
        db.touchSession(session.id);
        send({ type: "done" });
      } catch (e) {
        const message = String(e?.message ?? e);
        if (!abort.signal.aborted) send({ type: "error", message });
        else send({ type: "done", aborted: true });
      } finally {
        activeRuns.delete(session.id);
        try {
          controller.close();
        } catch {}
      }
    },
    cancel() {
      abort.abort();
      activeRuns.delete(session.id);
    },
  });

  return new Response(stream, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
    },
  });
}

// ---------------------------------------------------------------- routes

async function handleApi(req, url) {
  const { pathname } = url;
  const method = req.method;

  // ---- config / settings ----
  if (pathname === "/api/config" && method === "GET") {
    let defaultModel = null;
    try { defaultModel = resolveModel(db, null); } catch {}
    return json({
      approvalMode: db.getSetting("approvalMode", "dangerous"),
      workspaceRoot: WORKSPACE_ROOT,
      defaultModel: defaultModel
        ? { provider: defaultModel.provider, model: defaultModel.model }
        : null,
      projectConfig: db.getSetting("projectConfig", {}),
    });
  }
  if (pathname === "/api/settings" && method === "POST") {
    const body = await req.json();
    if (body.approvalMode) {
      if (!["off", "dangerous", "dangerous+mcp", "all"].includes(body.approvalMode)) {
        return json({ error: "invalid approvalMode" }, 400);
      }
      db.setSetting("approvalMode", body.approvalMode);
    }
    if (body.defaultModel !== undefined) {
      db.setSetting("defaultModel", body.defaultModel); // {provider, model} | null
    }
    return json({ ok: true });
  }

  // ---- project-level model + params ----
  if (pathname === "/api/project-config" && method === "POST") {
    const body = await req.json();
    const key = String(body.key ?? "").trim();
    if (!key) return json({ error: "key required" }, 400);
    const cfg = db.getSetting("projectConfig", {});
    const entry = cfg[key] ?? {};
    if (body.model !== undefined) {
      if (body.model === null) {
        entry.model = null;
      } else {
        const p = getProviders(db).find(
          (x) => x.enabled && x.name === body.model.provider
        );
        if (!p || !p.models.includes(body.model.model))
          return json({ error: "unknown provider/model" }, 400);
        entry.model = { provider: body.model.provider, model: body.model.model };
      }
    }
    if (body.params !== undefined) {
      const src = body.params ?? {};
      const params = {};
      if (src.thinking === "on" || src.thinking === "off") params.thinking = src.thinking;
      if (["low", "high", "max"].includes(src.thinkingEffort))
        params.thinkingEffort = src.thinkingEffort;
      if (src.temperature != null) {
        const t = Number(src.temperature);
        if (!(t >= 0 && t <= 2)) return json({ error: "temperature must be 0-2" }, 400);
        params.temperature = t;
      }
      if (src.maxTokens != null) {
        const n = Math.floor(Number(src.maxTokens));
        if (!(n > 0)) return json({ error: "maxTokens must be a positive integer" }, 400);
        params.maxTokens = n;
      }
      entry.params = params;
    }
    cfg[key] = entry;
    db.setSetting("projectConfig", cfg);
    return json({ ok: true, key, config: entry });
  }

  // ---- model providers ----
  if (pathname === "/api/providers" && method === "GET") {
    return json({
      providers: getProviders(db),
      defaultModel: db.getSetting("defaultModel"),
    });
  }
  if (pathname === "/api/providers" && method === "POST") {
    const body = await req.json();
    const err = validateProviders(body.providers);
    if (err) return json({ error: err }, 400);
    db.setSetting("providers", body.providers);
    return json({ ok: true });
  }
  if (pathname === "/api/providers/test" && method === "POST") {
    const { baseUrl, apiKey, model } = await req.json();
    if (!baseUrl || !apiKey || !model)
      return json({ error: "baseUrl / apiKey / model required" }, 400);
    return json(await testProvider({ baseUrl, apiKey, model }));
  }

  // ---- skills ----
  if (pathname === "/api/skills" && method === "GET") {
    const dirs = getSkillDirs(db);
    const { skills, errors } = scanSkills(dirs);
    return json({ dirs, skills, errors });
  }
  if (pathname === "/api/skills/dirs" && method === "POST") {
    const body = await req.json();
    if (!Array.isArray(body.dirs) || body.dirs.some((d) => typeof d !== "string" || !d.trim()))
      return json({ error: "dirs must be a string array" }, 400);
    db.setSetting("skillDirs", body.dirs.map((d) => d.trim()));
    return json({ ok: true });
  }
  if (pathname === "/api/skills/file" && method === "GET") {
    const path = url.searchParams.get("path");
    if (!path) return json({ error: "path required" }, 400);
    try {
      return json({ path, content: readSkillFile(getSkillDirs(db), path) });
    } catch (e) {
      return json({ error: String(e?.message ?? e) }, 400);
    }
  }

  // ---- recent working directories ----
  if (pathname === "/api/dirs/recent" && method === "GET") {
    const seen = new Set();
    const dirs = [];
    for (const s of db.listSessions()) {
      if (s.cwd.startsWith(WORKSPACE_ROOT)) continue; // auto-created workspaces are noise
      if (seen.has(s.cwd)) continue;
      seen.add(s.cwd);
      dirs.push(s.cwd);
      if (dirs.length >= 8) break;
    }
    return json({ dirs });
  }

  // ---- MCP servers ----
  if (pathname === "/api/mcp" && method === "GET") {
    return json({ servers: db.listMcpServers() });
  }
  if (pathname === "/api/mcp/test" && method === "POST") {
    const config = await req.json();
    if (config.transport !== "http")
      return json({ error: "only streamable http transport is supported" }, 400);
    if (!config.url) return json({ error: "http transport requires url" }, 400);
    return json(await testMcpServer(config));
  }
  if (pathname === "/api/mcp" && method === "POST") {
    const body = await req.json();
    const { name, enabled = true, ...config } = body;
    if (!name || !/^[\w-]+$/.test(name)) return json({ error: "invalid name" }, 400);
    if (config.transport !== "http")
      return json({ error: "only streamable http transport is supported" }, 400);
    if (!config.url) return json({ error: "http transport requires url" }, 400);
    if (config.disabledTools !== undefined) {
      if (!Array.isArray(config.disabledTools))
        return json({ error: "disabledTools must be an array of tool names" }, 400);
      config.disabledTools = config.disabledTools.filter((t) => typeof t === "string");
      if (config.disabledTools.length === 0) delete config.disabledTools;
    }
    db.upsertMcpServer(name, config, enabled);
    return json({ ok: true });
  }
  {
    const m = pathname.match(/^\/api\/mcp\/([\w-]+)$/);
    if (m && method === "DELETE") {
      db.deleteMcpServer(m[1]);
      return json({ ok: true });
    }
  }

  // ---- sessions ----
  if (pathname === "/api/sessions" && method === "GET") {
    return json({
      sessions: db.listSessions().map((s) => ({
        ...publicSession(s),
        busy: activeRuns.has(s.id),
      })),
    });
  }
  if (pathname === "/api/sessions" && method === "POST") {
    const body = await req.json().catch(() => ({}));
    const id = crypto.randomUUID();
    let cwd = body.cwd?.trim();
    if (cwd) {
      cwd = resolve(cwd);
      if (!existsSync(cwd)) return json({ error: `directory not found: ${cwd}` }, 400);
    } else {
      cwd = join(WORKSPACE_ROOT, id.slice(0, 8));
      mkdirSync(cwd, { recursive: true });
    }
    const session = db.createSession({
      id,
      title: body.title?.trim() || "New session",
      cwd,
    });
    return json({ session: publicSession(session) });
  }

  const sm = pathname.match(
    /^\/api\/sessions\/([0-9a-f-]{36})(\/(history|messages|resume|stop))?$/
  );
  if (sm) {
    const session = db.getSession(sm[1]);
    if (!session) return json({ error: "session not found" }, 404);
    const sub = sm[3];

    if (!sub && method === "DELETE") {
      activeRuns.get(session.id)?.abort();
      db.deleteSession(session.id);
      await checkpointer.deleteThread?.(session.id).catch?.(() => {});
      return json({ ok: true });
    }

    if (!sub && method === "PATCH") {
      const body = await req.json();
      const patch = {};
      if (body.title !== undefined) {
        const title = String(body.title).trim();
        if (!title) return json({ error: "title cannot be empty" }, 400);
        patch.title = title.slice(0, 80);
      }
      return json({ session: publicSession(db.updateSession(session.id, patch)) });
    }

    if (sub === "history" && method === "GET") {
      const { agent } = await getSessionAgent(session);
      const state = await agent.getState(threadConfig(session.id));
      return json({
        session: publicSession(session),
        busy: activeRuns.has(session.id),
        messages: serializeHistory(state?.values?.messages),
        todos: state?.values?.todos ?? [],
        interrupts: serializeInterrupts(state?.tasks),
      });
    }

    if (sub === "messages" && method === "POST") {
      if (activeRuns.has(session.id)) return json({ error: "session busy" }, 409);
      const body = await req.json();
      const content = String(body.content ?? "").trim();
      if (!content) return json({ error: "empty message" }, 400);
      if (session.title === "New session") {
        db.touchSession(session.id, content.slice(0, 40));
        session.title = content.slice(0, 40);
      }
      return streamRun(session, { messages: [{ role: "user", content }] });
    }

    if (sub === "resume" && method === "POST") {
      if (activeRuns.has(session.id)) return json({ error: "session busy" }, 409);
      const body = await req.json();
      if (!Array.isArray(body.decisions) || body.decisions.length === 0) {
        return json({ error: "decisions required" }, 400);
      }
      return streamRun(session, new Command({ resume: { decisions: body.decisions } }));
    }

    if (sub === "stop" && method === "POST") {
      activeRuns.get(session.id)?.abort();
      return json({ ok: true });
    }
  }

  return json({ error: "not found" }, 404);
}

// ---------------------------------------------------------------- server

const server = Bun.serve({
  port: PORT,
  hostname: HOST,
  idleTimeout: 0, // keep SSE connections open
  async fetch(req) {
    const url = new URL(req.url);
    if (url.pathname.startsWith("/api/")) {
      if (!checkAuth(req)) return unauthorized();
      try {
        return await handleApi(req, url);
      } catch (e) {
        console.error("API error:", e);
        return json({ error: String(e?.message ?? e) }, 500);
      }
    }
    // static files
    const path = url.pathname === "/" ? "/index.html" : url.pathname;
    const file = Bun.file(join(PUBLIC_DIR, path.replaceAll("..", "")));
    if (await file.exists()) return new Response(file);
    return new Response("not found", { status: 404 });
  },
});

console.log(`deepagent-web listening on http://${HOST}:${server.port}`);
try {
  const m = resolveModel(db, null);
  console.log(`default model: ${m.model} @ ${m.baseUrl} (${m.provider})`);
} catch (e) {
  console.warn(`no model configured yet: ${e.message}`);
}
console.log(`workspace root: ${WORKSPACE_ROOT}`);
if (!AUTH_TOKEN && HOST !== "127.0.0.1" && HOST !== "localhost") {
  console.warn("WARNING: server exposed beyond localhost without AUTH_TOKEN");
}
