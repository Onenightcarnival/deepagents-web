"""Deep agent construction: custom OpenAI-compatible model + local shell
backend + human-in-the-loop approvals + MCP tools + SQLite checkpointer.
"""

import re

import anyio
import httpx
from deepagents import create_deep_agent
from deepagents.backends import LocalShellBackend
from langchain.agents.middleware import AgentMiddleware, TodoListMiddleware
from langchain_core.messages import HumanMessage
from langchain_deepseek import ChatDeepSeek
from langchain_openai import ChatOpenAI

from src.mcp.service import get_mcp_tools
from src.utils.resource_loader import CONFIG

SYSTEM_PROMPT = """You are a capable coding and general-purpose agent running on the user's machine,
similar to Codex or Claude Code.

Rules:
- The working directory is the user's project directory. Prefer relative paths inside it.
- Use the filesystem tools (ls, read_file, write_file, edit_file, glob, grep) to inspect and modify files,
  and `execute` to run shell commands.
- For multi-step work, maintain a todo list with write_todos and keep it updated as you progress.
- Before destructive operations (deleting files, force-pushing, overwriting uncommitted work),
  explain what you are about to do.
- Reply in the same language the user writes in.
- Keep final answers concise; the user can see tool outputs in the UI."""

# 项目记忆文件：按优先级取第一个存在的注入 system prompt（只取一个，
# CLAUDE.md 通常引用 AGENTS.md，两个都注入会重复）
_MEMORY_FILES = ("AGENTS.md", "CLAUDE.md")
_MEMORY_MAX_CHARS = 24_000


async def load_project_memory(cwd: str) -> str:
    """读取项目目录下优先级最高的记忆文件，拼成 system prompt 附加段；
    没有则返回空串。"""
    for name in _MEMORY_FILES:
        path = anyio.Path(cwd) / name
        if not await path.exists():
            continue
        text = (await path.read_text(encoding="utf-8", errors="replace")).strip()
        if len(text) > _MEMORY_MAX_CHARS:
            text = text[:_MEMORY_MAX_CHARS] + "\n…(truncated)"
        if text:
            return f"## Project instructions (from {name} in the working directory)\n\n{text}"
    return ""


class SteeringMiddleware(AgentMiddleware):
    """运行中追加的用户消息在下一次模型调用前注入对话（queue 由本次运行的
    Run 对象持有，路由层运行中收到新消息时入队）。注入的消息随 checkpoint
    落库，成为正式对话历史。"""

    def __init__(self, queue: list[str]):
        super().__init__()
        self.queue = queue

    def before_model(self, state, runtime):
        if not self.queue:
            return None
        texts = []
        while self.queue:
            texts.append(self.queue.pop(0))
        return {"messages": [HumanMessage(t) for t in texts]}


def build_model(resolved: dict, params: dict | None = None):
    """`resolved` is the concrete model config from providers.resolve_model;
    `params` the project-level generation params from providers.resolve_params.
    None fields are not sent, so the provider default applies."""
    params = params or {}
    base_url, api_key, model = resolved.get("baseUrl"), resolved.get("apiKey"), resolved.get("model")
    if not (base_url and api_key and model):
        raise RuntimeError("模型配置不完整：请在设置 → 模型服务中配置")

    kwargs: dict = {
        "model": model,
        "api_key": api_key,
        "max_retries": CONFIG.agent.model_max_retries,
        # 自定义 httpx 客户端：屏蔽系统代理（trust_env）并跳过证书校验
        "http_client": httpx.Client(trust_env=False, verify=False),
        "http_async_client": httpx.AsyncClient(trust_env=False, verify=False),
        # 自定义 base_url 时 langchain-openai 不会自动开启流式 usage 上报，
        # 必须显式打开，否则拿不到 token 用量
        "stream_usage": True,
    }
    if params.get("temperature") is not None:
        kwargs["temperature"] = float(params["temperature"])
    if params.get("maxTokens") is not None:
        kwargs["max_tokens"] = int(params["maxTokens"])

    if resolved.get("type") == "deepseek":
        # DeepSeek (V4 API): body-level `thinking: {type}` + `reasoning_effort`
        # (low/high/max, default high). In thinking mode DeepSeek ignores
        # temperature/top_p — no error, just no effect.
        extra_body: dict = {}
        if params.get("thinking") == "on":
            extra_body["thinking"] = {"type": "enabled"}
            effort = params.get("thinkingEffort") or "high"
            extra_body["reasoning_effort"] = "high" if effort == "medium" else effort
        elif params.get("thinking") == "off":
            extra_body["thinking"] = {"type": "disabled"}
        if extra_body:
            kwargs["extra_body"] = extra_body
        return ChatDeepSeek(api_base=base_url, **kwargs)

    return ChatOpenAI(base_url=base_url, **kwargs)


# 命令替换/重定向可以把无害前缀变成任意读写，含这些标记的命令不走白名单
_EXEC_UNSAFE = ("$(", "`", ">", "<")
_EXEC_SPLIT = re.compile(r"&&|\|\||[;|\n]")


def execute_allowlisted(command: str, prefixes: list[str]) -> bool:
    """复合命令按控制符拆段，每一段都命中某个白名单前缀才放行。引号内的
    控制符也会被拆开，导致段落匹配失败——方向是多问而不是漏问，可接受。"""
    if any(tok in command for tok in _EXEC_UNSAFE):
        return False
    segments = [s.strip() for s in _EXEC_SPLIT.split(command) if s.strip()]
    return bool(segments) and all(any(seg == p or seg.startswith(p + " ") for p in prefixes) for seg in segments)


def build_interrupt_on(approval_mode: str, mcp_tool_names: list[str], allow: dict | None = None) -> dict | None:
    """按审批模式生成 interrupt_on 配置。`allow` 是项目审批白名单
    （{"execute": [命令前缀], "tools": [工具名]}）：命中的 execute 调用由
    `when` 谓词自动放行，白名单里的工具名显式关闭审批（False 同时覆盖
    deepagents 对文件系统工具的默认审批配置）。"""
    if approval_mode == "off":
        return None
    allow = allow or {}
    allowed_tools = set(allow.get("tools") or [])
    exec_prefixes = [p.strip() for p in allow.get("execute") or [] if p.strip()]

    def gate(name: str):
        if name in allowed_tools:
            return False
        if name == "execute" and exec_prefixes:
            return {
                "allowed_decisions": ["approve", "edit", "reject"],
                "when": lambda req: (
                    not execute_allowlisted((req.tool_call.get("args") or {}).get("command") or "", exec_prefixes)
                ),
            }
        return True

    gated: dict = {name: gate(name) for name in ("execute", "write_file", "edit_file", "delete")}
    if approval_mode == "all":
        for name in ("ls", "read_file", "glob", "grep", *mcp_tool_names):
            gated[name] = gate(name)
    elif approval_mode == "dangerous+mcp":
        for name in mcp_tool_names:
            gated[name] = gate(name)
    return gated


async def build_agent(
    *,
    cwd: str,
    checkpointer,
    mcp_servers: list[dict],
    approval_mode: str,
    model: dict,
    params: dict | None = None,
    skill_dirs: list[str] | None = None,
    allow: dict | None = None,
    steering_queue: list[str] | None = None,
):
    """Build a deep agent for one session. Returns (agent, mcp_errors)."""
    mcp_tools, mcp_errors = await get_mcp_tools(mcp_servers or [])

    backend = LocalShellBackend(
        root_dir=cwd,
        virtual_mode=False,
        inherit_env=True,
        timeout=CONFIG.agent.shell_timeout,
        max_output_bytes=200_000,
    )

    # only pass skill dirs that exist — SkillsMiddleware errors on missing paths
    skills = []
    for d in skill_dirs or []:
        if await anyio.Path(d).exists():
            skills.append(d if d.endswith("/") else d + "/")

    system_prompt = SYSTEM_PROMPT
    memory = await load_project_memory(cwd)
    if memory:
        system_prompt += "\n\n" + memory

    middleware = [TodoListMiddleware()]
    if steering_queue is not None:
        middleware.append(SteeringMiddleware(steering_queue))

    agent = create_deep_agent(
        model=build_model(model, params),
        backend=backend,
        tools=mcp_tools,
        system_prompt=system_prompt,
        checkpointer=checkpointer,
        middleware=middleware,
        **({"skills": skills} if skills else {}),
        interrupt_on=build_interrupt_on(
            approval_mode or "dangerous",
            [t.name for t in mcp_tools],
            allow,
        ),
    )
    return agent, mcp_errors
