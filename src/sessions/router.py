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
from pydantic import ValidationError

from ..utils.app_config import json_error, validation_error_message
from ..utils.resource_loader import CONFIG, resources
from . import service
from .serialize import serialize_history, serialize_task_interrupts
from .service import Run, active_run, public_session, thread_config
from .template import CreateSessionBody, MessageBody, PatchSessionBody, ResumeBody

router = APIRouter(prefix="/api")


@router.get("/dirs/recent")
async def recent_dirs():
    workspace_root = str(CONFIG.paths.workspace_root)
    seen = set()
    dirs = []
    for s in service.list_sessions():
        if s["cwd"].startswith(workspace_root):
            continue  # 自动创建的 workspace 是噪音
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
            for s in service.list_sessions()
        ]
    }


@router.post("/sessions")
async def create_session(request: Request):
    try:
        body = CreateSessionBody.model_validate(await request.json())
    except (ValidationError, ValueError):
        body = CreateSessionBody()
    id = str(uuid.uuid4())
    cwd = (body.cwd or "").strip()
    if cwd:
        cwd = str(Path(cwd).expanduser().resolve())
        if not Path(cwd).exists():
            return json_error(f"directory not found: {cwd}")
    else:
        cwd = str(CONFIG.paths.workspace_root / id[:8])
        Path(cwd).mkdir(parents=True, exist_ok=True)
    session = service.create_session(id, (body.title or "").strip() or "New session", cwd)
    return {"session": public_session(session)}


def _get_session(session_id: str) -> dict | None:
    if not re.fullmatch(r"[0-9a-f-]{36}", session_id):
        return None
    return service.get_session(session_id)


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    session = _get_session(session_id)
    if not session:
        return json_error("session not found", 404)
    run = active_run(session["id"])
    if run:
        run.abort()
    resources.runs.pop(session["id"], None)
    service.delete_session(session["id"])
    with contextlib.suppress(Exception):
        await resources.checkpointer.adelete_thread(session["id"])
    return {"ok": True}


@router.patch("/sessions/{session_id}")
async def patch_session(session_id: str, request: Request):
    session = _get_session(session_id)
    if not session:
        return json_error("session not found", 404)
    try:
        body = PatchSessionBody.model_validate(await request.json())
    except ValidationError as e:
        return json_error(validation_error_message(e))
    return {"session": public_session(service.update_session(session["id"], title=body.title))}


@router.get("/sessions/{session_id}/history")
async def session_history(session_id: str):
    session = _get_session(session_id)
    if not session:
        return json_error("session not found", 404)
    agent, _mcp_errors = await service.get_session_agent(session)
    state = await agent.aget_state(thread_config(session["id"]))
    run = resources.runs.get(session["id"])
    busy = bool(run and not run.done)
    return {
        "session": public_session(session),
        "busy": busy,
        # 运行中回合在 messages 里的起点——客户端渲染到此为止，其余由
        # /stream 回放重建
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
    try:
        body = MessageBody.model_validate(await request.json())
    except ValidationError as e:
        return json_error(validation_error_message(e))
    content = body.content
    if session["title"] == "New session":
        service.touch_session(session["id"], content[:40])
        session["title"] = content[:40]
    await service.start_run(session, {"messages": [{"role": "user", "content": content}]}, content)
    return {"ok": True}


@router.post("/sessions/{session_id}/resume")
async def post_resume(session_id: str, request: Request):
    session = _get_session(session_id)
    if not session:
        return json_error("session not found", 404)
    if active_run(session["id"]):
        return json_error("session busy", 409)
    try:
        body = ResumeBody.model_validate(await request.json())
    except ValidationError:
        return json_error("decisions required")
    await service.start_run(session, Command(resume={"decisions": body.decisions}))
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
            # 无运行记录——客户端应依赖 /history
            yield sse({"type": "done", "idle": True})
            return
        if run.done:
            for ev in run.events:
                yield sse(ev)
            return
        # 先订阅再回放：push() 只发生在本事件循环上，订阅与快照之间没有
        # await，不会漏事件
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
