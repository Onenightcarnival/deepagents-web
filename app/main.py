"""Self-hosted web agent server (FastAPI).

  uv run python -m app.main      — serves the UI + API on http://127.0.0.1:3080

Configuration via .env:
  MODEL_BASE_URL / MODEL_API_KEY / MODEL_NAME   (required)
  MODEL_TEMPERATURE, MODEL_MAX_RETRIES          (optional)
  PORT (default 3080), HOST (default 127.0.0.1)
  WORKSPACE_ROOT (default ./workspaces)
  AUTH_TOKEN (optional — required for LAN exposure)
  SHELL_TIMEOUT (seconds, default 300)
"""
import asyncio
import contextlib
import json
import os
import re
import uuid
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

import aiosqlite
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command

from .agent import build_agent
from .db import AppDb
from .mcp import test_mcp_server
from .providers import (
    get_providers,
    resolve_model,
    resolve_params,
    test_provider,
    validate_providers,
)
from .serialize import (
    content_to_text,
    serialize_history,
    serialize_interrupt_values,
    serialize_task_interrupts,
)
from .skills import expand_path, get_skill_dirs, read_skill_file, scan_skills

PORT = int(os.environ.get("PORT") or 3080)
HOST = os.environ.get("HOST") or "127.0.0.1"
DATA_DIR = Path(os.environ.get("DATA_DIR") or "data").resolve()
WORKSPACE_ROOT = str(Path(os.environ.get("WORKSPACE_ROOT") or "workspaces").resolve())
AUTH_TOKEN = os.environ.get("AUTH_TOKEN") or None
PUBLIC_DIR = Path(__file__).resolve().parent.parent / "public"

DATA_DIR.mkdir(parents=True, exist_ok=True)
Path(WORKSPACE_ROOT).mkdir(parents=True, exist_ok=True)

db = AppDb(str(DATA_DIR / "app.db"))
checkpointer: AsyncSqliteSaver | None = None

# sessionId -> most recent run record. Runs execute detached from any HTTP
# connection: closing the page only drops the subscriber, never the run.
# Finished runs are kept (until replaced) so a late reattach can still see
# how the run ended. Lost on server restart — runs do not survive it.
runs: dict[str, "Run"] = {}


class Run:
    def __init__(self):
        self.events: list[dict] = []        # buffered for (re)attach replay
        self.subscribers: set[asyncio.Queue] = set()
        self.task: asyncio.Task | None = None
        self.done = False
        self.status = "running"             # running | done | error | aborted
        self.error: str | None = None
        self.cutoff = 0                     # serialized-history length when the run started

    def push(self, obj: dict):
        last = self.events[-1] if self.events else None
        if (
            last is not None
            and last.get("type") == obj.get("type")
            and obj.get("type") in ("ai_delta", "reasoning_delta")
        ):
            last["text"] += obj["text"]  # coalesce deltas so the buffer stays message-sized
        else:
            self.events.append(obj)
        for q in list(self.subscribers):
            q.put_nowait(obj)

    def abort(self):
        if self.task and not self.done:
            self.task.cancel()


def active_run(session_id: str) -> Run | None:
    run = runs.get(session_id)
    return run if run and not run.done else None


# ---------------------------------------------------------------- helpers


def json_error(message: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


def project_key_for(session: dict) -> str:
    """Model + params follow the project. A "project" is the session's working
    directory; sessions in auto-created workspaces share one virtual project."""
    return "__standalone__" if session["cwd"].startswith(WORKSPACE_ROOT) else session["cwd"]


async def get_session_agent(session: dict):
    project_key = project_key_for(session)
    return await build_agent(
        cwd=session["cwd"],
        checkpointer=checkpointer,
        mcp_servers=db.list_mcp_servers(),
        approval_mode=db.get_setting("approvalMode", "dangerous"),
        model=resolve_model(db, project_key),
        params=resolve_params(db, project_key),
        skill_dirs=[expand_path(d) for d in get_skill_dirs(db)],
    )


def public_session(s: dict | None) -> dict | None:
    """sessions carry model as a JSON TEXT column — expose it parsed."""
    if not s:
        return s
    model = None
    if s.get("model"):
        with contextlib.suppress(Exception):
            model = json.loads(s["model"])
    return {**s, "model": model}


def thread_config(session_id: str) -> dict:
    return {"configurable": {"thread_id": session_id}}


async def start_run(session: dict, input, user_text: str | None = None) -> Run:
    """Start one agent run (new message or resume) detached from any HTTP
    connection. Events are buffered on the run record for replay, and fanned
    out live to subscribers (see the /stream endpoint). Returns after the
    agent is built — build failures surface as a normal HTTP error — while
    the streaming loop continues in the background.

    `user_text` is the triggering user message (None for resume runs); it goes
    into the buffer so a reattaching client can reconstruct the full run.
    """
    run = Run()

    # Reserve the busy slot before the (slow) agent build so concurrent
    # POSTs can't start a second run for the same session.
    prev = runs.get(session["id"])
    runs[session["id"]] = run
    try:
        agent, mcp_errors = await get_session_agent(session)
        state = await agent.aget_state(thread_config(session["id"]))
        run.cutoff = len(serialize_history((state.values or {}).get("messages")))
        if user_text is not None:
            run.push({"type": "user", "text": user_text})
        for err in mcp_errors:
            run.push({"type": "warning", "message": f"MCP: {err}"})
    except BaseException:
        if prev:
            runs[session["id"]] = prev
        else:
            runs.pop(session["id"], None)
        raise

    async def loop():
        try:
            async for mode, data in agent.astream(
                input,
                config=thread_config(session["id"]),
                stream_mode=["messages", "updates"],
            ):
                if mode == "messages":
                    msg, _meta = data
                    if type(msg).__name__ in ("AIMessageChunk", "ChatMessageChunk"):
                        text = content_to_text(msg.content)
                        if text:
                            run.push({"type": "ai_delta", "text": text})
                        reasoning = (msg.additional_kwargs or {}).get("reasoning_content")
                        if reasoning:
                            run.push({"type": "reasoning_delta", "text": reasoning})
                elif mode == "updates":
                    if "__interrupt__" in data:
                        run.push({
                            "type": "interrupt",
                            "interrupts": serialize_interrupt_values(data["__interrupt__"]),
                        })
                        continue
                    for update in data.values():
                        if not isinstance(update, dict):
                            continue
                        # surface completed AI messages (for tool_calls), tool
                        # results and todos
                        if isinstance(update.get("todos"), list):
                            run.push({"type": "todos", "todos": update["todos"]})
                        for m in update.get("messages") or []:
                            t = getattr(m, "type", None)
                            if t == "ai" and getattr(m, "tool_calls", None):
                                run.push({
                                    "type": "tool_calls",
                                    "calls": [
                                        {"id": c.get("id"), "name": c.get("name"),
                                         "args": c.get("args")}
                                        for c in m.tool_calls
                                    ],
                                })
                            elif t == "tool":
                                run.push({
                                    "type": "tool_result",
                                    "id": m.tool_call_id,
                                    "name": m.name,
                                    "text": content_to_text(m.content)[:20000],
                                    "status": getattr(m, "status", None) or "success",
                                })
            db.touch_session(session["id"])
            run.status = "done"
            run.push({"type": "done"})
        except asyncio.CancelledError:
            run.status = "aborted"
            run.push({"type": "done", "aborted": True})
        except Exception as e:
            run.status = "error"
            run.error = str(e)
            run.push({"type": "error", "message": str(e)})
            run.push({"type": "done"})
        finally:
            run.done = True
            run.subscribers.clear()

    run.task = asyncio.create_task(loop())
    return run


def stream_attach_response(run: Run | None) -> StreamingResponse:
    """SSE response attached to a session's run: replays the buffer, then
    relays live events until the run finishes. Client disconnect only
    unsubscribes — it never aborts the run (that is what POST /stop is for)."""

    def sse(obj: dict) -> str:
        return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"

    async def gen():
        if run is None:
            # no run on record — client should rely on /history
            yield sse({"type": "done", "idle": True})
            return
        if run.done:
            for ev in run.events:
                yield sse(ev)
            return
        # Subscribe before replaying: push() only happens on this event loop,
        # so nothing can slip between subscribing and snapshotting the buffer.
        q: asyncio.Queue = asyncio.Queue()
        run.subscribers.add(q)
        snapshot = list(run.events)
        try:
            for ev in snapshot:
                yield sse(ev)
            while True:
                ev = await q.get()
                yield sse(ev)
                if ev.get("type") == "done":
                    return
        finally:
            run.subscribers.discard(q)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


# ---------------------------------------------------------------- app


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI):
    global checkpointer
    conn = await aiosqlite.connect(str(DATA_DIR / "checkpoints-py.db"))
    checkpointer = AsyncSqliteSaver(conn)
    await checkpointer.setup()
    print(f"deepagent-web listening on http://{HOST}:{PORT}")
    try:
        m = resolve_model(db, None)
        print(f"default model: {m['model']} @ {m['baseUrl']} ({m['provider']})")
    except Exception as e:
        print(f"no model configured yet: {e}")
    print(f"workspace root: {WORKSPACE_ROOT}")
    if not AUTH_TOKEN and HOST not in ("127.0.0.1", "localhost"):
        print("WARNING: server exposed beyond localhost without AUTH_TOKEN")
    yield
    await conn.close()


app = FastAPI(lifespan=lifespan)


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    if AUTH_TOKEN and request.url.path.startswith("/api/"):
        ok = (
            request.headers.get("authorization") == f"Bearer {AUTH_TOKEN}"
            or request.query_params.get("token") == AUTH_TOKEN
        )
        if not ok:
            return json_error("unauthorized", 401)
    return await call_next(request)


@app.exception_handler(Exception)
async def on_error(request: Request, exc: Exception):
    return json_error(str(exc), 500)


# ---- config / settings ----


@app.get("/api/config")
async def get_config():
    default_model = None
    with contextlib.suppress(Exception):
        m = resolve_model(db, None)
        default_model = {"provider": m["provider"], "model": m["model"]}
    return {
        "approvalMode": db.get_setting("approvalMode", "dangerous"),
        "workspaceRoot": WORKSPACE_ROOT,
        "defaultModel": default_model,
        "projectConfig": db.get_setting("projectConfig", {}),
    }


@app.post("/api/settings")
async def post_settings(request: Request):
    body = await request.json()
    if body.get("approvalMode"):
        if body["approvalMode"] not in ("off", "dangerous", "dangerous+mcp", "all"):
            return json_error("invalid approvalMode")
        db.set_setting("approvalMode", body["approvalMode"])
    if "defaultModel" in body:
        db.set_setting("defaultModel", body["defaultModel"])  # {provider, model} | None
    return {"ok": True}


# ---- project-level model + params ----


@app.post("/api/project-config")
async def post_project_config(request: Request):
    body = await request.json()
    key = str(body.get("key") or "").strip()
    if not key:
        return json_error("key required")
    cfg = db.get_setting("projectConfig", {})
    entry = cfg.get(key) or {}
    if "model" in body:
        if body["model"] is None:
            entry["model"] = None
        else:
            p = next(
                (x for x in get_providers(db)
                 if x.get("enabled") and x["name"] == body["model"].get("provider")),
                None,
            )
            if not p or body["model"].get("model") not in (p.get("models") or []):
                return json_error("unknown provider/model")
            entry["model"] = {"provider": body["model"]["provider"], "model": body["model"]["model"]}
    if "params" in body:
        src = body.get("params") or {}
        params: dict = {}
        if src.get("thinking") in ("on", "off"):
            params["thinking"] = src["thinking"]
        if src.get("thinkingEffort") in ("low", "high", "max"):
            params["thinkingEffort"] = src["thinkingEffort"]
        if src.get("temperature") is not None:
            try:
                t = float(src["temperature"])
            except (TypeError, ValueError):
                t = -1
            if not (0 <= t <= 2):
                return json_error("temperature must be 0-2")
            params["temperature"] = t
        if src.get("maxTokens") is not None:
            try:
                n = int(float(src["maxTokens"]))
            except (TypeError, ValueError):
                n = 0
            if n <= 0:
                return json_error("maxTokens must be a positive integer")
            params["maxTokens"] = n
        entry["params"] = params
    cfg[key] = entry
    db.set_setting("projectConfig", cfg)
    return {"ok": True, "key": key, "config": entry}


# ---- model providers ----


@app.get("/api/providers")
async def get_providers_route():
    return {"providers": get_providers(db), "defaultModel": db.get_setting("defaultModel")}


@app.post("/api/providers")
async def post_providers(request: Request):
    body = await request.json()
    err = validate_providers(body.get("providers"))
    if err:
        return json_error(err)
    db.set_setting("providers", body["providers"])
    return {"ok": True}


@app.post("/api/providers/test")
async def post_providers_test(request: Request):
    body = await request.json()
    base_url, api_key, model = body.get("baseUrl"), body.get("apiKey"), body.get("model")
    if not (base_url and api_key and model):
        return json_error("baseUrl / apiKey / model required")
    return await test_provider(base_url, api_key, model)


# ---- skills ----


@app.get("/api/skills")
async def get_skills():
    dirs = get_skill_dirs(db)
    result = scan_skills(dirs)
    return {"dirs": dirs, "skills": result["skills"], "errors": result["errors"]}


@app.post("/api/skills/dirs")
async def post_skill_dirs(request: Request):
    body = await request.json()
    dirs = body.get("dirs")
    if not isinstance(dirs, list) or any(not isinstance(d, str) or not d.strip() for d in dirs):
        return json_error("dirs must be a string array")
    db.set_setting("skillDirs", [d.strip() for d in dirs])
    return {"ok": True}


@app.get("/api/skills/file")
async def get_skill_file(path: str | None = None):
    if not path:
        return json_error("path required")
    try:
        return {"path": path, "content": read_skill_file(get_skill_dirs(db), path)}
    except Exception as e:
        return json_error(str(e))


# ---- recent working directories ----


@app.get("/api/dirs/recent")
async def get_recent_dirs():
    seen = set()
    dirs = []
    for s in db.list_sessions():
        if s["cwd"].startswith(WORKSPACE_ROOT):
            continue  # auto-created workspaces are noise
        if s["cwd"] in seen:
            continue
        seen.add(s["cwd"])
        dirs.append(s["cwd"])
        if len(dirs) >= 8:
            break
    return {"dirs": dirs}


# ---- MCP servers ----


@app.get("/api/mcp")
async def get_mcp():
    return {"servers": db.list_mcp_servers()}


@app.post("/api/mcp/test")
async def post_mcp_test(request: Request):
    config = await request.json()
    if config.get("transport") != "http":
        return json_error("only streamable http transport is supported")
    if not config.get("url"):
        return json_error("http transport requires url")
    return await test_mcp_server(config)


@app.post("/api/mcp")
async def post_mcp(request: Request):
    body = await request.json()
    name = body.pop("name", None)
    enabled = body.pop("enabled", True)
    config = body
    if not name or not re.fullmatch(r"[\w-]+", name):
        return json_error("invalid name")
    if config.get("transport") != "http":
        return json_error("only streamable http transport is supported")
    if not config.get("url"):
        return json_error("http transport requires url")
    if "disabledTools" in config:
        if not isinstance(config["disabledTools"], list):
            return json_error("disabledTools must be an array of tool names")
        config["disabledTools"] = [t for t in config["disabledTools"] if isinstance(t, str)]
        if not config["disabledTools"]:
            del config["disabledTools"]
    db.upsert_mcp_server(name, config, enabled)
    return {"ok": True}


@app.delete("/api/mcp/{name}")
async def delete_mcp(name: str):
    if not re.fullmatch(r"[\w-]+", name):
        return json_error("invalid name")
    db.delete_mcp_server(name)
    return {"ok": True}


# ---- sessions ----


@app.get("/api/sessions")
async def list_sessions():
    return {
        "sessions": [
            {**public_session(s), "busy": bool(active_run(s["id"]))}
            for s in db.list_sessions()
        ]
    }


@app.post("/api/sessions")
async def create_session(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    id = str(uuid.uuid4())
    cwd = (body.get("cwd") or "").strip()
    if cwd:
        cwd = str(Path(cwd).resolve())
        if not Path(cwd).exists():
            return json_error(f"directory not found: {cwd}")
    else:
        cwd = str(Path(WORKSPACE_ROOT) / id[:8])
        Path(cwd).mkdir(parents=True, exist_ok=True)
    session = db.create_session(id, (body.get("title") or "").strip() or "New session", cwd)
    return {"session": public_session(session)}


def _get_session_or_none(session_id: str) -> dict | None:
    if not re.fullmatch(r"[0-9a-f-]{36}", session_id):
        return None
    return db.get_session(session_id)


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    session = _get_session_or_none(session_id)
    if not session:
        return json_error("session not found", 404)
    run = active_run(session["id"])
    if run:
        run.abort()
    runs.pop(session["id"], None)
    db.delete_session(session["id"])
    with contextlib.suppress(Exception):
        await checkpointer.adelete_thread(session["id"])
    return {"ok": True}


@app.patch("/api/sessions/{session_id}")
async def patch_session(session_id: str, request: Request):
    session = _get_session_or_none(session_id)
    if not session:
        return json_error("session not found", 404)
    body = await request.json()
    title = None
    if "title" in body:
        title = str(body["title"]).strip()
        if not title:
            return json_error("title cannot be empty")
        title = title[:80]
    return {"session": public_session(db.update_session(session["id"], title=title))}


@app.get("/api/sessions/{session_id}/history")
async def session_history(session_id: str):
    session = _get_session_or_none(session_id)
    if not session:
        return json_error("session not found", 404)
    agent, _mcp_errors = await get_session_agent(session)
    state = await agent.aget_state(thread_config(session["id"]))
    run = runs.get(session["id"])
    busy = bool(run and not run.done)
    return {
        "session": public_session(session),
        "busy": busy,
        # where the running turn starts in `messages` — the client renders
        # history up to here and reconstructs the rest from /stream replay
        "runCutoff": run.cutoff if busy else None,
        "lastRun": {"status": run.status, "error": run.error} if run and run.done else None,
        "messages": serialize_history((state.values or {}).get("messages")),
        "todos": (state.values or {}).get("todos") or [],
        "interrupts": serialize_task_interrupts(state.tasks),
    }


@app.post("/api/sessions/{session_id}/messages")
async def post_message(session_id: str, request: Request):
    session = _get_session_or_none(session_id)
    if not session:
        return json_error("session not found", 404)
    if active_run(session["id"]):
        return json_error("session busy", 409)
    body = await request.json()
    content = str(body.get("content") or "").strip()
    if not content:
        return json_error("empty message")
    if session["title"] == "New session":
        db.touch_session(session["id"], content[:40])
        session["title"] = content[:40]
    await start_run(session, {"messages": [{"role": "user", "content": content}]}, content)
    return {"ok": True}


@app.post("/api/sessions/{session_id}/resume")
async def post_resume(session_id: str, request: Request):
    session = _get_session_or_none(session_id)
    if not session:
        return json_error("session not found", 404)
    if active_run(session["id"]):
        return json_error("session busy", 409)
    body = await request.json()
    decisions = body.get("decisions")
    if not isinstance(decisions, list) or not decisions:
        return json_error("decisions required")
    await start_run(session, Command(resume={"decisions": decisions}))
    return {"ok": True}


@app.get("/api/sessions/{session_id}/stream")
async def session_stream(session_id: str):
    session = _get_session_or_none(session_id)
    if not session:
        return json_error("session not found", 404)
    return stream_attach_response(runs.get(session["id"]))


@app.post("/api/sessions/{session_id}/stop")
async def post_stop(session_id: str):
    session = _get_session_or_none(session_id)
    if not session:
        return json_error("session not found", 404)
    run = active_run(session["id"])
    if run:
        run.abort()
    return {"ok": True}


# static files (after API routes so /api/* wins)
app.mount("/", StaticFiles(directory=str(PUBLIC_DIR), html=True), name="static")


def main():
    uvicorn.run(app, host=HOST, port=PORT, timeout_keep_alive=0)


if __name__ == "__main__":
    main()
