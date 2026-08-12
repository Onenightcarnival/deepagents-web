# 项目开发规范

1. Python 使用 3.12。
2. httpx 必须使用 `trust_env=False, verify=False`。
3. 禁止使用难以维护的高级语法。
4. 项目架构设计要模块化、分层（优先纵切、其次横切），整体符合 pythonic。
5. 配置与代码分离，配置项使用 toml 文件保存。
6. 所有大模型服务客户端都需传入自定义 httpx 的客户端实例，确保 `trust_env` 这些参数生效。
7. 每次代码提交前必须执行 `ruff format` 并通过 `ruff check`。代码层面的硬性规则（禁 global、禁相对导入、禁内联 import、禁 sys.path 打补丁等）统一由 pyproject.toml 中的 ruff 配置约束，不在本文档重复；豁免场景（如第三方 SDK 依赖隔离的内联 import）标注对应 `# noqa`。
8. 文件头部 import 禁止防御性写法（如 try/except ImportError）。
