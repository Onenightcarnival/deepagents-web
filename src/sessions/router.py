"""会话：增删改查、消息发送、审批恢复、SSE 附着、停止、最近目录。"""

import asyncio
import contextlib
import json
import re
import uuid
from enum import StrEnum
from urllib.parse import quote

import anyio
from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import Response, StreamingResponse
from langgraph.types import Command
from sqlalchemy.orm import Session

from src.sessions import service
from src.sessions.serialize import history_to_markdown, serialize_history, serialize_task_interrupts
from src.sessions.service import Run, active_run, thread_config
from src.sessions.template import CreateSessionBody, MessageBody, PatchSessionBody, ResumeBody
from src.utils.app_config import json_response
from src.utils.database import get_db, get_db_with_commit
from src.utils.resource_loader import CONFIG

router = APIRouter(prefix="/sessions")


class SessionCode(StrEnum):
    """sessions 模块业务状态码（三段式规则见 utils/app_config.py）。"""

    OK = "WA-01-00"
    NOT_FOUND = "WA-01-01"
    BUSY = "WA-01-02"
    DIR_NOT_FOUND = "WA-01-03"
    DIR_FORBIDDEN = "WA-01-04"


MESSAGES: dict[SessionCode, str] = {
    SessionCode.OK: "成功",
    SessionCode.NOT_FOUND: "会话不存在",
    SessionCode.BUSY: "会话正在运行中",
    SessionCode.DIR_NOT_FOUND: "目录不存在",
    SessionCode.DIR_FORBIDDEN: "目录无权限访问",
}


@router.get("/dirs/recent")
async def recent_dirs(db: Session = Depends(get_db)):
    workspace_root = str(CONFIG.paths.workspace_root)
    seen = set()
    dirs = []
    for s in service.list_sessions(db):
        if s["cwd"].startswith(workspace_root):
            continue  # 自动创建的 workspace 是噪音
        if s["cwd"] in seen:
            continue
        seen.add(s["cwd"])
        dirs.append(s["cwd"])
        if len(dirs) >= 8:
            break
    return json_response(status.HTTP_200_OK, SessionCode.OK, MESSAGES[SessionCode.OK], data={"dirs": dirs})


@router.get("/dirs/browse")
async def browse_dirs(path: str = ""):
    """列出服务器上某目录的子目录，供前端目录浏览器下钻。浏览器出于安全
    拿不到本机绝对路径，且服务可能部署在远程 Linux，只能由后端代为浏览。"""
    target = await (await anyio.Path(path or "~").expanduser()).resolve()
    if not await target.is_dir():
        return json_response(
            status.HTTP_400_BAD_REQUEST,
            SessionCode.DIR_NOT_FOUND,
            f"{MESSAGES[SessionCode.DIR_NOT_FOUND]}: {target}",
        )
    dirs = []
    try:
        async for child in target.iterdir():
            if child.name.startswith("."):
                continue
            # 个别子项 stat 失败（权限、坏软链）跳过即可，不该拖垮整个列表
            with contextlib.suppress(OSError):
                if await child.is_dir():
                    dirs.append({"name": child.name, "path": str(child)})
    except PermissionError:
        return json_response(
            status.HTTP_400_BAD_REQUEST,
            SessionCode.DIR_FORBIDDEN,
            f"{MESSAGES[SessionCode.DIR_FORBIDDEN]}: {target}",
        )
    dirs.sort(key=lambda d: d["name"].lower())
    parent = str(target.parent) if str(target.parent) != str(target) else None
    return json_response(
        status.HTTP_200_OK,
        SessionCode.OK,
        MESSAGES[SessionCode.OK],
        data={"path": str(target), "parent": parent, "dirs": dirs},
    )


@router.get("/")
async def list_sessions(db: Session = Depends(get_db)):
    return json_response(
        status.HTTP_200_OK,
        SessionCode.OK,
        MESSAGES[SessionCode.OK],
        data={"sessions": [{**s, "busy": bool(active_run(s["id"]))} for s in service.list_sessions(db)]},
    )


@router.post("/")
async def create_session(body: CreateSessionBody | None = None, db: Session = Depends(get_db_with_commit)):
    body = body or CreateSessionBody()
    id = str(uuid.uuid4())
    cwd = (body.cwd or "").strip()
    if cwd:
        cwd = str(await (await anyio.Path(cwd).expanduser()).resolve())
        if not await anyio.Path(cwd).exists():
            return json_response(
                status.HTTP_400_BAD_REQUEST,
                SessionCode.DIR_NOT_FOUND,
                f"{MESSAGES[SessionCode.DIR_NOT_FOUND]}: {cwd}",
            )
    else:
        cwd = str(CONFIG.paths.workspace_root / id[:8])
        await anyio.Path(cwd).mkdir(parents=True, exist_ok=True)
    session = service.create_session(db, id, (body.title or "").strip() or "New session", cwd)
    return json_response(status.HTTP_200_OK, SessionCode.OK, MESSAGES[SessionCode.OK], data={"session": session})


def _get_session(db: Session, session_id: str) -> dict | None:
    if not re.fullmatch(r"[0-9a-f-]{36}", session_id):
        return None
    return service.get_session(db, session_id)


@router.delete("/{session_id}")
async def delete_session(session_id: str, request: Request, db: Session = Depends(get_db_with_commit)):
    session = _get_session(db, session_id)
    if not session:
        return json_response(status.HTTP_404_NOT_FOUND, SessionCode.NOT_FOUND, MESSAGES[SessionCode.NOT_FOUND])
    run = active_run(session["id"])
    if run:
        run.abort()
    service.runs.pop(session["id"], None)
    service.delete_session(db, session["id"])
    with contextlib.suppress(Exception):
        await request.app.state.checkpointer.adelete_thread(session["id"])
    return json_response(status.HTTP_200_OK, SessionCode.OK, MESSAGES[SessionCode.OK])


@router.patch("/{session_id}")
async def patch_session(session_id: str, body: PatchSessionBody, db: Session = Depends(get_db_with_commit)):
    session = _get_session(db, session_id)
    if not session:
        return json_response(status.HTTP_404_NOT_FOUND, SessionCode.NOT_FOUND, MESSAGES[SessionCode.NOT_FOUND])
    return json_response(
        status.HTTP_200_OK,
        SessionCode.OK,
        MESSAGES[SessionCode.OK],
        data={"session": service.update_session(db, session["id"], title=body.title)},
    )


@router.get("/{session_id}/history")
async def session_history(session_id: str, request: Request, db: Session = Depends(get_db)):
    session = _get_session(db, session_id)
    if not session:
        return json_response(status.HTTP_404_NOT_FOUND, SessionCode.NOT_FOUND, MESSAGES[SessionCode.NOT_FOUND])
    agent, _mcp_errors = await service.get_session_agent(db, request.app.state.checkpointer, session)
    state = await agent.aget_state(thread_config(session["id"]))
    run = service.runs.get(session["id"])
    busy = bool(run and not run.done)
    return json_response(
        status.HTTP_200_OK,
        SessionCode.OK,
        MESSAGES[SessionCode.OK],
        data={
            "session": session,
            "busy": busy,
            # 运行中回合在 messages 里的起点——客户端渲染到此为止，其余由
            # /stream 回放重建
            "runCutoff": run.cutoff if busy else None,
            "lastRun": {"status": run.status, "error": run.error} if run and run.done else None,
            "messages": serialize_history((state.values or {}).get("messages")),
            "todos": (state.values or {}).get("todos") or [],
            "interrupts": serialize_task_interrupts(state.tasks),
        },
    )


@router.get("/{session_id}/export")
async def export_session(session_id: str, request: Request, db: Session = Depends(get_db)):
    """导出会话历史为 Markdown 附件。checkpoint 的 channel 值是增量存储，
    裸读拿不到完整 messages，必须与 /history 一样经 agent 的 aget_state 重建。"""
    session = _get_session(db, session_id)
    if not session:
        return json_response(status.HTTP_404_NOT_FOUND, SessionCode.NOT_FOUND, MESSAGES[SessionCode.NOT_FOUND])
    agent, _mcp_errors = await service.get_session_agent(db, request.app.state.checkpointer, session)
    state = await agent.aget_state(thread_config(session["id"]))
    messages = serialize_history((state.values or {}).get("messages"))
    filename = quote(f"{session['title'][:40]}.md")
    return Response(
        history_to_markdown(session, messages),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )


@router.post("/{session_id}/messages")
async def post_message(session_id: str, body: MessageBody, request: Request, db: Session = Depends(get_db_with_commit)):
    session = _get_session(db, session_id)
    if not session:
        return json_response(status.HTTP_404_NOT_FOUND, SessionCode.NOT_FOUND, MESSAGES[SessionCode.NOT_FOUND])
    content = body.content
    run = active_run(session["id"])
    if run:
        # 运行中追加：入队，SteeringMiddleware 在下一次模型调用前注入
        service.enqueue_message(run, content)
        return json_response(status.HTTP_200_OK, SessionCode.OK, MESSAGES[SessionCode.OK], data={"queued": True})
    if session["title"] == "New session":
        service.touch_session(db, session["id"], content[:40])
        session["title"] = content[:40]
    checkpointer = request.app.state.checkpointer
    await service.start_run(db, checkpointer, session, {"messages": [{"role": "user", "content": content}]}, content)
    return json_response(status.HTTP_200_OK, SessionCode.OK, MESSAGES[SessionCode.OK], data={"queued": False})


@router.post("/{session_id}/resume")
async def post_resume(session_id: str, body: ResumeBody, request: Request, db: Session = Depends(get_db)):
    session = _get_session(db, session_id)
    if not session:
        return json_response(status.HTTP_404_NOT_FOUND, SessionCode.NOT_FOUND, MESSAGES[SessionCode.NOT_FOUND])
    if active_run(session["id"]):
        return json_response(status.HTTP_409_CONFLICT, SessionCode.BUSY, MESSAGES[SessionCode.BUSY])
    checkpointer = request.app.state.checkpointer
    await service.start_run(db, checkpointer, session, Command(resume={"decisions": body.decisions}))
    return json_response(status.HTTP_200_OK, SessionCode.OK, MESSAGES[SessionCode.OK])


@router.get("/{session_id}/stream")
async def session_stream(session_id: str, db: Session = Depends(get_db)):
    session = _get_session(db, session_id)
    if not session:
        return json_response(status.HTTP_404_NOT_FOUND, SessionCode.NOT_FOUND, MESSAGES[SessionCode.NOT_FOUND])
    return _stream_attach_response(service.runs.get(session["id"]))


@router.post("/{session_id}/stop")
async def post_stop(session_id: str, db: Session = Depends(get_db)):
    session = _get_session(db, session_id)
    if not session:
        return json_response(status.HTTP_404_NOT_FOUND, SessionCode.NOT_FOUND, MESSAGES[SessionCode.NOT_FOUND])
    run = active_run(session["id"])
    if run:
        run.abort()
    return json_response(status.HTTP_200_OK, SessionCode.OK, MESSAGES[SessionCode.OK])


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
