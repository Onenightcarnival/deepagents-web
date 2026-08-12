"""会话业务逻辑：元数据 CRUD（SQLAlchemy）+ 运行管理。

一次运行（新消息或审批恢复）以 asyncio.Task 形式执行，与任何 HTTP 连接
解耦：关闭页面只是取消订阅，绝不中断运行（中断走 stop）。已结束的运行
保留在注册表中（直到被下一次运行替换），晚到的重连仍能看到结束状态。
运行不跨服务重启存活。
"""

import asyncio
import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.mcp.service import list_mcp_servers
from src.providers.service import resolve_model, resolve_params
from src.sessions.agent import build_agent
from src.sessions.model import SessionRecord
from src.sessions.serialize import content_to_text, serialize_history, serialize_interrupt_values
from src.settings.service import get_setting
from src.skills.service import expand_path, get_skill_dirs
from src.utils.database import SessionLocal
from src.utils.resource_loader import CONFIG


def _now_ms() -> int:
    return int(time.time() * 1000)


# ---------------------------------------------------------------- 元数据 CRUD


def create_session(db: Session, id: str, title: str, cwd: str) -> dict:
    now = _now_ms()
    db.add(SessionRecord(id=id, title=title, cwd=cwd, created_at=now, updated_at=now))
    return get_session(db, id)


def get_session(db: Session, id: str) -> dict | None:
    row = db.get(SessionRecord, id)
    return row.to_dict() if row else None


def list_sessions(db: Session) -> list[dict]:
    rows = db.scalars(select(SessionRecord).order_by(SessionRecord.updated_at.desc())).all()
    return [r.to_dict() for r in rows]


def touch_session(db: Session, id: str, title: str | None = None) -> None:
    row = db.get(SessionRecord, id)
    if not row:
        return
    row.updated_at = _now_ms()
    if title is not None:
        row.title = title


def delete_session(db: Session, id: str) -> None:
    row = db.get(SessionRecord, id)
    if row:
        db.delete(row)


def update_session(db: Session, id: str, title: str | None = None) -> dict | None:
    row = db.get(SessionRecord, id)
    if row and title is not None:
        row.title = title
    return get_session(db, id)


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
        self.pending: list[str] = []  # 运行中追加的用户消息，待注入对话

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


# sessionId -> 最近一次运行记录（保留到被下一次运行替换），运行与页面连接解耦
runs: dict[str, Run] = {}


def active_run(session_id: str) -> Run | None:
    run = runs.get(session_id)
    return run if run and not run.done else None


def enqueue_message(run: Run, text: str) -> None:
    """运行中追加用户消息：入队并立即广播（SteeringMiddleware 在下一次模型
    调用前注入；运行结束仍未注入的由 loop 作为新一轮输入续发）。"""
    run.pending.append(text)
    run.push({"type": "user", "text": text})


def project_key_for(session: dict) -> str:
    """模型与参数跟随项目。「项目」即会话的工作目录；自动创建的 workspace
    里的会话共享虚拟项目 __standalone__。"""
    if session["cwd"].startswith(str(CONFIG.paths.workspace_root)):
        return "__standalone__"
    return session["cwd"]


def thread_config(session_id: str) -> dict:
    return {"configurable": {"thread_id": session_id}}


async def get_session_agent(db: Session, checkpointer, session: dict, steering_queue: list[str] | None = None):
    project_key = project_key_for(session)
    return await build_agent(
        cwd=session["cwd"],
        checkpointer=checkpointer,
        mcp_servers=list_mcp_servers(db),
        approval_mode=get_setting(db, "approvalMode", "dangerous"),
        model=resolve_model(db, project_key),
        params=resolve_params(db, project_key),
        skill_dirs=[expand_path(d) for d in get_skill_dirs(db)],
        allow=(get_setting(db, "approvalAllowlist", {}) or {}).get(project_key),
        steering_queue=steering_queue,
    )


async def start_run(db: Session, checkpointer, session: dict, input, user_text: str | None = None) -> Run:
    """启动一次运行。agent 构建完成后即返回（构建失败表现为普通 HTTP
    错误），流式循环在后台继续。`user_text` 是触发运行的用户消息（审批
    恢复时为 None），进入缓冲区供重连客户端重建完整运行。"""
    run = Run()

    # Reserve the busy slot before the (slow) agent build so concurrent
    # POSTs can't start a second run for the same session.
    prev = runs.get(session["id"])
    # 上一次运行因审批中断而结束时，排队的消息尚未注入——接力给本次运行
    if prev:
        run.pending = prev.pending
    runs[session["id"]] = run
    try:
        agent, mcp_errors = await get_session_agent(db, checkpointer, session, steering_queue=run.pending)
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

    async def stream_pass(current_input) -> bool:
        """跑一遍 astream，返回是否以审批中断收尾。"""
        interrupted = False
        async for mode, data in agent.astream(
            current_input,
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
                # 每次模型调用的最后一个 chunk 带累计 usage（含子代理的调用）
                usage = getattr(msg, "usage_metadata", None)
                if usage:
                    run.push(
                        {
                            "type": "usage",
                            "inputTokens": usage.get("input_tokens", 0),
                            "outputTokens": usage.get("output_tokens", 0),
                            "totalTokens": usage.get("total_tokens", 0),
                        }
                    )
            elif mode == "updates":
                if "__interrupt__" in data:
                    interrupted = True
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
        return interrupted

    async def loop():
        try:
            current_input = input
            while True:
                interrupted = await stream_pass(current_input)
                # 中断（等审批）时排队消息留在 pending，接力给 resume 的运行；
                # 正常收尾且还有排队消息 → 作为新一轮输入继续跑
                if interrupted or not run.pending:
                    break
                texts = list(run.pending)
                run.pending.clear()
                current_input = {"messages": [{"role": "user", "content": t} for t in texts]}
            # 运行在请求结束后仍在后台继续，不能复用请求作用域的会话
            with SessionLocal() as bg_db:
                touch_session(bg_db, session["id"])
                bg_db.commit()
            run.status = "done"
            run.push({"type": "done"})
        except asyncio.CancelledError:
            run.status = "aborted"
            run.pending.clear()  # 停止即放弃尚未注入的排队消息
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
