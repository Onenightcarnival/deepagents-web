# DeepAgent Web

自托管的 Web Agent，形态类似 Codex / Claude Code：网页界面下达任务，agent 在你的机器上读写文件、执行 shell 命令、调用 MCP 工具，危险操作需要你在界面上审批。

技术栈：[deepagents](https://github.com/langchain-ai/deepagents)（agent 内核）+ FastAPI + uv（Python 运行时与包管理）+ SQLite（会话与状态持久化）+ 单文件 vanilla JS 前端。

## 特性

- **多服务商模型管理**：设置页内配置多个 OpenAI 兼容服务商（DeepSeek、vLLM、Ollama、各类中转），支持连通性检测、默认模型和会话级模型切换，改完即时生效。DeepSeek 服务商走 `langchain-deepseek`，支持思考模式开关与力度调节
- **项目化会话管理**：侧栏按项目文件夹分组，新建会话时选择工作目录（最近使用一键选取），会话可重命名
- **本地执行**：agent 直接操作你机器上的文件和 shell（每个会话绑定一个工作目录）
- **审批机制**：`execute` / `write_file` / `edit_file` / `delete` 等危险操作默认中断，界面上批准或拒绝后继续；审批状态落库，刷新页面甚至重启服务后仍在
- **技能（Skills）**：指定技能目录（默认 `~/.deepagent/skills/`），每个含 `SKILL.md` 的子目录自动加载为技能（与 Claude Code 技能格式一致，由 deepagents SkillsMiddleware 渐进式披露）
- **MCP 接入**：设置页添加 Streamable HTTP 的 MCP 服务器，支持启用开关和连接测试，工具自动注入 agent（`langchain-mcp-adapters`）
- **SQLite 持久化**：会话历史、断点状态全部本地存储（`langgraph-checkpoint-sqlite`），无外部依赖
- **规划能力**：deepagents 内置 todo list、子代理、上下文管理

## 快速开始

前置要求：安装 [uv](https://docs.astral.sh/uv/)（`curl -LsSf https://astral.sh/uv/install.sh | sh`）。

```bash
uv sync

# 启动
uv run python -m app.main
# 打开 http://127.0.0.1:3080，在设置 → 模型服务中添加服务商

# 自检：验证默认模型的 API 连通性和 tool calling 能力（agent 能否工作的关键）
uv run python -m test.check_model
```

服务启动配置（端口、监听地址、鉴权令牌、数据目录等）在项目根目录的 `config.toml`，可选；参考 [config.example.toml](config.example.toml)。模型服务商、MCP、技能目录等都在网页设置页配置。

## 使用说明

**会话与工作目录**：每个会话绑定一个工作目录。「新建会话」弹窗里可选择最近使用的目录或填入项目路径（如 `~/my-project`），agent 的文件操作和 shell 命令都在该目录下执行；留空则在 `workspaces/` 下自动创建独立目录。侧栏按项目文件夹分组展示会话。

**模型服务**（设置 → 模型服务）：Cherry Studio 式配置。每个服务商有启用开关、API 地址、API 密钥（带「检测」按钮）和模型列表；顶栏模型 chip 可为单个会话切换模型，不选则用默认。

**审批模式**（设置 → 通用）：

| 模式 | 行为 |
|------|------|
| `off` | 全自动，不审批（信任模式，慎用） |
| `dangerous`（默认） | shell 命令、写文件、改文件、删文件需审批 |
| `dangerous+mcp` | 上述基础上，MCP 工具调用也需审批 |
| `all` | 所有工具（包括只读）都需审批 |

**技能**（设置 → 技能）：配置若干技能目录（默认 `~/.deepagent/skills/`），目录下每个包含 `SKILL.md` 的子目录会被自动加载；多个目录中同名技能，后面的覆盖前面的。顶栏「⚡ N 技能」徽章可查看当前生效的技能。

**MCP 服务器**（设置 → MCP 服务器）：仅支持 Streamable HTTP 传输（不依赖本机的 npx / bun / uv 环境）。左侧选择服务器，右侧分「通用 / 工具 / 提示词 / 资源」页签：通用页配置 URL 和鉴权请求头并测试连接，其余页签展示服务器暴露的工具（含参数文档）、提示词和资源。工具页可逐个停用工具（停用的不注入 agent）；MCP 调用是否需要审批由通用页的审批模式统一控制（`dangerous+mcp`）。保存后下一条消息生效，工具名会以 `服务器名__工具名` 前缀注入。

**局域网访问**：默认只监听 `127.0.0.1`。如需手机等设备访问，在 `config.toml` 的 `[server]` 中设置 `host = "0.0.0.0"` 并**务必**设置 `auth_token`，访问时带 `?token=你的令牌` 或 `Authorization: Bearer` 头。

## 目录结构

```
app/
  main.py          FastAPI 服务：REST API + SSE 流式输出 + 静态文件
  config.py        服务启动配置（读取根目录 config.toml）
  agent.py         create_deep_agent 组装：模型、LocalShellBackend、审批中断、MCP 工具、技能
  providers.py     模型服务商配置（多 provider、解析会话模型、连通性检测）
  skills.py        技能目录扫描与 SKILL.md frontmatter 解析
  db.py            应用元数据（会话列表、MCP 配置、设置）
  mcp.py           MultiServerMCPClient 管理（按配置哈希缓存工具列表）
  serialize.py     LangChain 消息 -> 前端 JSON
public/
  index.html       完整前端（无构建步骤）
test/
  check_model.py   真实 API 自检（连通性 / tool calling / 流式）
  mock_llm.py      OpenAI 兼容 mock 模型（离线测试用）
config.example.toml  服务启动配置示例（复制为 config.toml 使用）
data/              SQLite 数据（app.db + checkpoints-py.db，自动创建）
workspaces/        自动创建的会话工作目录
```

## 安全须知

这是一个「运行在你自己机器上、拥有你权限」的 agent，与 Claude Code / opencode 的信任模型相同：

- 没有沙箱。审批模式是唯一防线，不建议在生产机器上使用 `off` 模式。
- 注意 prompt injection：agent 读取的文件内容、MCP 工具返回的内容都可能诱导模型执行恶意命令，审批时请看清命令内容再批准。
- API key 存在本地 `data/app.db`（`data/` 已加入 `.gitignore`），不要把数据目录提交到公开仓库。
- 不要在未设置 `AUTH_TOKEN` 的情况下把服务暴露到公网。

## 常见问题

**模型不调用工具 / 死循环**：运行 `uv run python -m test.check_model` 看第 2 项。tool calling 质量是这类 agent 的关键，弱模型会频繁失败，建议换用工具调用能力较强的模型。

**会话卡在「运行中」**：点「停止」按钮中断当前运行；状态由 checkpointer 保存，可继续对话。

**MCP 连不上**：确认 URL 可达、鉴权请求头正确。界面发消息时会显示 MCP 加载错误横幅。

**换模型**：设置 → 模型服务中修改即可，即时生效，历史会话不受影响。

**从旧的 Bun/JS 版本迁移**：`data/app.db`（会话列表、服务商、MCP、设置）直接兼容。但对话历史断点（旧 `data/checkpoints.db`）与 Python 版序列化格式不兼容，Python 版使用新文件 `data/checkpoints-py.db`——旧会话仍在列表里，但历史记录为空，可自行删除。
