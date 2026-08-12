"""Deep agent construction: custom OpenAI-compatible model + local shell
backend + human-in-the-loop approvals + MCP tools + SQLite checkpointer.
"""
from pathlib import Path

import httpx
from deepagents import create_deep_agent
from deepagents.backends import LocalShellBackend
from langchain.agents.middleware import TodoListMiddleware
from langchain_deepseek import ChatDeepSeek
from langchain_openai import ChatOpenAI

from .config import CONFIG
from .mcp import get_mcp_tools

SYSTEM_PROMPT = """You are a capable coding and general-purpose agent running on the user's machine, similar to Codex or Claude Code.

Rules:
- The working directory is the user's project directory. Prefer relative paths inside it.
- Use the filesystem tools (ls, read_file, write_file, edit_file, glob, grep) to inspect and modify files, and `execute` to run shell commands.
- For multi-step work, maintain a todo list with write_todos and keep it updated as you progress.
- Before destructive operations (deleting files, force-pushing, overwriting uncommitted work), explain what you are about to do.
- Reply in the same language the user writes in.
- Keep final answers concise; the user can see tool outputs in the UI."""


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
        "max_retries": CONFIG.model_max_retries,
        # 自定义 httpx 客户端：屏蔽系统代理（trust_env）并跳过证书校验
        "http_client": httpx.Client(trust_env=False, verify=False),
        "http_async_client": httpx.AsyncClient(trust_env=False, verify=False),
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


def build_interrupt_on(approval_mode: str, mcp_tool_names: list[str]) -> dict | None:
    if approval_mode == "off":
        return None
    gated: dict = {
        "execute": True,
        "write_file": True,
        "edit_file": True,
        "delete": True,
    }
    if approval_mode == "all":
        for name in ("ls", "read_file", "glob", "grep"):
            gated[name] = True
        for name in mcp_tool_names:
            gated[name] = True
    elif approval_mode == "dangerous+mcp":
        for name in mcp_tool_names:
            gated[name] = True
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
):
    """Build a deep agent for one session. Returns (agent, mcp_errors)."""
    mcp_tools, mcp_errors = await get_mcp_tools(mcp_servers or [])

    backend = LocalShellBackend(
        root_dir=cwd,
        virtual_mode=False,
        inherit_env=True,
        timeout=CONFIG.shell_timeout,
        max_output_bytes=200_000,
    )

    # only pass skill dirs that exist — SkillsMiddleware errors on missing paths
    skills = [
        d if d.endswith("/") else d + "/"
        for d in (skill_dirs or [])
        if Path(d).exists()
    ]

    agent = create_deep_agent(
        model=build_model(model, params),
        backend=backend,
        tools=mcp_tools,
        system_prompt=SYSTEM_PROMPT,
        checkpointer=checkpointer,
        middleware=[TodoListMiddleware()],
        **({"skills": skills} if skills else {}),
        interrupt_on=build_interrupt_on(
            approval_mode or "dangerous",
            [t.name for t in mcp_tools],
        ),
    )
    return agent, mcp_errors
