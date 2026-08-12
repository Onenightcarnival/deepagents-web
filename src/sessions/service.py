"""会话业务逻辑：元数据 CRUD（SQLAlchemy）+ 运行管理。

一次运行（新消息或审批恢复）以 asyncio.Task 形式执行，与任何 HTTP 连接
解耦：关闭页面只是取消订阅，绝不中断运行（中断走 stop）。已结束的运行
保留在注册表中（直到被下一次运行替换），晚到的重连仍能看到结束状态。
运行不跨服务重启存活。
"""

import asyncio
import contextlib
import json
import time

from sqlalchemy import select

from src.mcp.service import list_mcp_servers
from src.providers.service import resolve_model, resolve_params
from src.sessions.agent import build_agent
from src.sessions.model import SessionRecord
from src.sessions.serialize import content_to_text, serialize_history, serialize_interrupt_values
from src.settings.service import get_setting
from src.skills.service import expand_path, get_skill_dirs
from src.utils.resource_loader import CONFIG, resources


def _now_ms() -> int:
    return int(time.time() * 1000)


# ---------------------------------------------------------------- 元数据 CRUD


def create_session(id: str, title: str, cwd: str) -> dict:
    now = _now_ms()
    with resources.db_session() as s:
        s.add(SessionRecord(id=id, title=title, cwd=cwd, created_at=now, updated_at=now))
        s.commit()
    return get_session(id)


def get_session(id: str) -> dict | None:
    with resources.db_session() as s:
        row = s.get(SessionRecord, id)
        return row.to_dict() if row else None


def list_sessions() -> list[dict]:
    with resources.db_session() as s:
        rows = s.scalars(select(SessionRecord).order_by(SessionRecord.updated_at.desc())).all()
        return [r.to_dict() for r in rows]


def touch_session(id: str, title: str | None = None) -> None:
    with resources.db_session() as s:
        row = s.get(SessionRecord, id)
        if not row:
            return
        row.updated_at = _now_ms()
        if title is not None:
            row.title = title
        s.commit()


def delete_session(id: str) -> None:
    with resources.db_session() as s:
        row = s.get(SessionRecord, id)
        if row:
            s.delete(row)
            s.commit()


def update_session(id: str, title: str | None = None) -> dict | None:
    with resources.db_session() as s:
        row = s.get(SessionRecord, id)
        if row and title is not None:
            row.title = title
            s.commit()
    return get_session(id)


def public_session(s: dict | None) -> dict | None:
    """sessions 的 model 列是 JSON TEXT——对外暴露解析后的对象。"""
    if not s:
        return s
    model = None
    if s.get("model"):
        with contextlib.suppress(Exception):
            model = json.loads(s["model"])
    return {**s, "model": model}


# ---------------------------------------------------------------- 运行管理


class Run:
    def __init__(self):
        self.events: list[dict] = []  # buffered for (re)attach replay
        self.subscribers: set[asyncio.Queue] = set()
        self.task: asyncio.Task | None = None
        self.done = False
        self.status = "running"  # running | done | error | aborted
        self.error: str | None = None
        self.cutoff = 0  # serialized-history length when the run started

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
    run = resources.runs.get(session_id)
    return run if run and not run.done else None


def project_key_for(session: dict) -> str:
    """模型与参数跟随项目。「项目」即会话的工作目录；自动创建的 workspace
    里的会话共享虚拟项目 __standalone__。"""
    if session["cwd"].startswith(str(CONFIG.paths.workspace_root)):
        return "__standalone__"
    return session["cwd"]


def thread_config(session_id: str) -> dict:
    return {"configurable": {"thread_id": session_id}}


async def get_session_agent(session: dict):
    project_key = project_key_for(session)
    return await build_agent(
        cwd=session["cwd"],
        checkpointer=resources.checkpointer,
        mcp_servers=list_mcp_servers(),
        approval_mode=get_setting("approvalMode", "dangerous"),
        model=resolve_model(project_key),
        params=resolve_params(project_key),
        skill_dirs=[expand_path(d) for d in get_skill_dirs()],
    )


async def start_run(session: dict, input, user_text: str | None = None) -> Run:
    """启动一次运行。agent 构建完成后即返回（构建失败表现为普通 HTTP
    错误），流式循环在后台继续。`user_text` 是触发运行的用户消息（审批
    恢复时为 None），进入缓冲区供重连客户端重建完整运行。"""
    run = Run()

    # Reserve the busy slot before the (slow) agent build so concurrent
    # POSTs can't start a second run for the same session.
    prev = resources.runs.get(session["id"])
    resources.runs[session["id"]] = run
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
            resources.runs[session["id"]] = prev
        else:
            resources.runs.pop(session["id"], None)
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
                        run.push(
                            {
                                "type": "interrupt",
                                "interrupts": serialize_interrupt_values(data["__interrupt__"]),
                            }
                        )
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
                                run.push(
                                    {
                                        "type": "tool_calls",
                                        "calls": [
                                            {"id": c.get("id"), "name": c.get("name"), "args": c.get("args")}
                                            for c in m.tool_calls
                                        ],
                                    }
                                )
                            elif t == "tool":
                                run.push(
                                    {
                                        "type": "tool_result",
                                        "id": m.tool_call_id,
                                        "name": m.name,
                                        "text": content_to_text(m.content)[:20000],
                                        "status": getattr(m, "status", None) or "success",
                                    }
                                )
            touch_session(session["id"])
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
