# DeepAgent Web

自托管的 Web Agent，形态类似 Codex / Claude Code：网页界面下达任务，agent 在你的机器上读写文件、执行 shell 命令、调用 MCP 工具，危险操作需要你在界面上审批。

技术栈：[deepagentsjs](https://github.com/langchain-ai/deepagentsjs)（agent 内核）+ Bun（运行时与包管理）+ SQLite（会话与状态持久化）+ 单文件 vanilla JS 前端。

## 特性

- **多服务商模型管理**：设置页内配置多个 OpenAI 兼容服务商（DeepSeek、vLLM、Ollama、各类中转），支持连通性检测、默认模型和会话级模型切换，改完即时生效；`.env` 仅作首次种子/兜底
- **项目化会话管理**：侧栏按项目文件夹分组，新建会话时选择工作目录（最近使用一键选取），会话可重命名
- **本地执行**：agent 直接操作你机器上的文件和 shell（每个会话绑定一个工作目录）
- **审批机制**：`execute` / `write_file` / `edit_file` 等危险操作默认中断，界面上批准或拒绝后继续；审批状态落库，刷新页面甚至重启服务后仍在
- **技能（Skills）**：指定技能目录（默认 `~/.deepagent/skills/`），每个含 `SKILL.md` 的子目录自动加载为技能（与 Claude Code 技能格式一致，由 deepagents SkillsMiddleware 渐进式披露）
- **MCP 接入**：设置页添加 stdio / HTTP 的 MCP 服务器，支持启用开关和连接测试，工具自动注入 agent
- **SQLite 持久化**：会话历史、断点状态全部本地存储，无外部依赖
- **规划能力**：deepagents 内置 todo list、子代理、上下文管理

## 快速开始

前置要求：安装 [Bun](https://bun.sh)（`curl -fsSL https://bun.sh/install | bash`）。

```bash
bun install

# 编辑 .env，填入你的模型配置（已有示例）
# MODEL_BASE_URL=https://api.deepseek.com
# MODEL_API_KEY=sk-...
# MODEL_NAME=deepseek-v4-flash

# 自检：验证 API 连通性和 tool calling 能力（agent 能否工作的关键）
bun run check

# 启动
bun start
# 打开 http://127.0.0.1:3080
```

## 使用说明

**会话与工作目录**：每个会话绑定一个工作目录。「新建会话」弹窗里可选择最近使用的目录或填入项目路径（如 `~/my-project`），agent 的文件操作和 shell 命令都在该目录下执行；留空则在 `workspaces/` 下自动创建独立目录。侧栏按项目文件夹分组展示会话。

**模型服务**（设置 → 模型服务）：Cherry Studio 式配置。每个服务商有启用开关、API 地址、API 密钥（带「检测」按钮）和模型列表；顶栏模型 chip 可为单个会话切换模型，不选则用默认。首次启动会把 `.env` 中的 `MODEL_*` 自动迁移为「默认服务商」。

**审批模式**（设置 → 通用）：

| 模式 | 行为 |
|------|------|
| `off` | 全自动，不审批（信任模式，慎用） |
| `dangerous`（默认） | shell 命令、写文件、改文件需审批 |
| `dangerous+mcp` | 上述基础上，MCP 工具调用也需审批 |
| `all` | 所有工具（包括只读）都需审批 |

**技能**（设置 → 技能）：配置若干技能目录（默认 `~/.deepagent/skills/`），目录下每个包含 `SKILL.md` 的子目录会被自动加载；多个目录中同名技能，后面的覆盖前面的。顶栏「⚡ N 技能」徽章可查看当前生效的技能。

**MCP 服务器**（设置 → MCP 服务器）：支持两种传输方式。stdio 例：命令填 `npx -y @modelcontextprotocol/server-filesystem /tmp`；HTTP 例：URL 填 `http://localhost:8000/mcp`。「测试连接」可即时列出该服务器的工具；保存后下一条消息生效，工具名会以 `服务器名__工具名` 前缀注入。

**局域网访问**：默认只监听 `127.0.0.1`。如需手机等设备访问，在 `.env` 设置 `HOST=0.0.0.0` 并**务必**设置 `AUTH_TOKEN`，访问时带 `?token=你的令牌` 或 `Authorization: Bearer` 头。

## 目录结构

```
src/
  server.js        Bun HTTP 服务：REST API + SSE 流式输出 + 静态文件
  agent.js         createDeepAgent 组装：模型、LocalShellBackend、审批中断、MCP 工具、技能
  providers.js     模型服务商配置（多 provider、解析会话模型、连通性检测）
  skills.js        技能目录扫描与 SKILL.md frontmatter 解析
  checkpointer.js  bun:sqlite 适配的 LangGraph SqliteSaver（better-sqlite3 在 Bun 下不可用）
  db.js            应用元数据（会话列表、MCP 配置、设置）
  mcp.js           MultiServerMCPClient 管理（按配置哈希缓存连接）
  serialize.js     LangChain 消息 -> 前端 JSON
public/
  index.html       完整前端（无构建步骤）
test/
  check-model.js   真实 API 自检（连通性 / tool calling / 流式）
  mock-llm.js      OpenAI 兼容 mock 模型（离线测试用）
  ui-test.js       Playwright 浏览器端到端测试
data/              SQLite 数据（app.db + checkpoints.db，自动创建）
workspaces/        自动创建的会话工作目录
```

## 安全须知

这是一个「运行在你自己机器上、拥有你权限」的 agent，与 Claude Code / opencode 的信任模型相同：

- 没有沙箱。审批模式是唯一防线，不建议在生产机器上使用 `off` 模式。
- 注意 prompt injection：agent 读取的文件内容、MCP 工具返回的内容都可能诱导模型执行恶意命令，审批时请看清命令内容再批准。
- `.env` 里有 API key，已加入 `.gitignore`，不要提交到公开仓库。
- 不要在未设置 `AUTH_TOKEN` 的情况下把服务暴露到公网。

## 常见问题

**模型不调用工具 / 死循环**：运行 `bun run check` 看第 2 项。tool calling 质量是这类 agent 的关键，弱模型会频繁失败，建议换用工具调用能力较强的模型。

**会话卡在「运行中」**：点「停止」按钮中断当前运行；状态由 checkpointer 保存，可继续对话。

**MCP 连不上**：stdio 方式确认命令在你的 PATH 中可执行；HTTP 方式确认 URL 可达。界面发消息时会显示 MCP 加载错误横幅。

**换模型**：改 `.env` 后重启 `bun start` 即可，历史会话不受影响。
