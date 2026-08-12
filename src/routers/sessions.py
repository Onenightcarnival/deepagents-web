"""会话：增删改查、消息发送、审批恢复、SSE 附着、停止、最近目录。"""
import asyncio
import contextlib
import json
import re
import uuid
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from langgraph.types import Command

from ..services.runs import (
    Run,
    active_run,
    get_session_agent,
    public_session,
    start_run,
    thread_config,
)
from ..services.serialize import serialize_history, serialize_task_interrupts
from ..utils.app_config import json_error
from ..utils.resource_loader import CONFIG, resources

router = APIRouter(prefix="/api")


@router.get("/dirs/recent")
async def recent_dirs():
    workspace_root = str(CONFIG.paths.workspace_root)
    seen = set()
    dirs = []
    for s in resources.db.list_sessions():
        if s["cwd"].startswith(workspace_root):
            continue  # auto-created workspaces are noise
        if s["cwd"] in seen:
            continue
        seen.add(s["cwd"])
        dirs.append(s["cwd"])
        if len(dirs) >= 8:
            break
    return {"dirs": dirs}


@router.get("/sessions")
async def list_sessions():
    return {
        "sessions": [
            {**public_session(s), "busy": bool(active_run(s["id"]))}
            for s in resources.db.list_sessions()
        ]
    }


@router.post("/sessions")
async def create_session(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    id = str(uuid.uuid4())
    cwd = (body.get("cwd") or "").strip()
    if cwd:
        cwd = str(Path(cwd).expanduser().resolve())
        if not Path(cwd).exists():
            return json_error(f"directory not found: {cwd}")
    else:
        cwd = str(CONFIG.paths.workspace_root / id[:8])
        Path(cwd).mkdir(parents=True, exist_ok=True)
    session = resources.db.create_session(
        id, (body.get("title") or "").strip() or "New session", cwd
    )
    return {"session": public_session(session)}


def _get_session(session_id: str) -> dict | None:
    if not re.fullmatch(r"[0-9a-f-]{36}", session_id):
        return None
    return resources.db.get_session(session_id)


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    session = _get_session(session_id)
    if not session:
        return json_error("session not found", 404)
    run = active_run(session["id"])
    if run:
        run.abort()
    resources.runs.pop(session["id"], None)
    resources.db.delete_session(session["id"])
    with contextlib.suppress(Exception):
        await resources.checkpointer.adelete_thread(session["id"])
    return {"ok": True}


@router.patch("/sessions/{session_id}")
async def patch_session(session_id: str, request: Request):
    session = _get_session(session_id)
    if not session:
        return json_error("session not found", 404)
    body = await request.json()
    title = None
    if "title" in body:
        title = str(body["title"]).strip()
        if not title:
            return json_error("title cannot be empty")
        title = title[:80]
    return {"session": public_session(resources.db.update_session(session["id"], title=title))}


@router.get("/sessions/{session_id}/history")
async def session_history(session_id: str):
    session = _get_session(session_id)
    if not session:
        return json_error("session not found", 404)
    agent, _mcp_errors = await get_session_agent(session)
    state = await agent.aget_state(thread_config(session["id"]))
    run = resources.runs.get(session["id"])
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


@router.post("/sessions/{session_id}/messages")
async def post_message(session_id: str, request: Request):
    session = _get_session(session_id)
    if not session:
        return json_error("session not found", 404)
    if active_run(session["id"]):
        return json_error("session busy", 409)
    body = await request.json()
    content = str(body.get("content") or "").strip()
    if not content:
        return json_error("empty message")
    if session["title"] == "New session":
        resources.db.touch_session(session["id"], content[:40])
        session["title"] = content[:40]
    await start_run(session, {"messages": [{"role": "user", "content": content}]}, content)
    return {"ok": True}


@router.post("/sessions/{session_id}/resume")
async def post_resume(session_id: str, request: Request):
    session = _get_session(session_id)
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


@router.get("/sessions/{session_id}/stream")
async def session_stream(session_id: str):
    session = _get_session(session_id)
    if not session:
        return json_error("session not found", 404)
    return _stream_attach_response(resources.runs.get(session["id"]))


@router.post("/sessions/{session_id}/stop")
async def post_stop(session_id: str):
    session = _get_session(session_id)
    if not session:
        return json_error("session not found", 404)
    run = active_run(session["id"])
    if run:
        run.abort()
    return {"ok": True}


def _stream_attach_response(run: Run | None) -> StreamingResponse:
    """附着到会话运行的 SSE 响应：先回放缓冲区，再转发实时事件直到运行
    结束。客户端断开只是取消订阅，绝不中断运行（中断走 POST /stop）。"""

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
