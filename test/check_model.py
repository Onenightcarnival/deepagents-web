"""模型连通性与 tool calling 自检，检查当前默认模型（设置 → 模型服务）。
在项目根目录运行：uv run python -m test.check_model
"""

import json
import sys

from langchain_core.tools import tool

from src.providers.service import resolve_model
from src.sessions.agent import build_model


def main() -> None:
    try:
        resolved = resolve_model(None)
    except RuntimeError as e:
        print(e)
        print("请先启动服务，在网页设置 → 模型服务中添加服务商。")
        sys.exit(1)

    model = build_model(resolved)
    print(f"模型: {resolved['model']} @ {resolved['baseUrl']}（{resolved['provider']}）")

    # 1. 基本对话
    print("1) 基本对话 … ", end="", flush=True)
    r1 = model.invoke([{"role": "user", "content": "回复「ok」两个字母即可"}])
    print(f"通过（{json.dumps(r1.content, ensure_ascii=False)[:60]}）")

    # 2. tool calling
    print("2) tool calling … ", end="", flush=True)

    @tool
    def echo(text: str) -> str:
        """Echo the given text back verbatim."""
        return text

    bound = model.bind_tools([echo])
    r2 = bound.invoke([{"role": "user", "content": "请调用 echo 工具，参数 text 为 hello"}])
    if r2.tool_calls:
        call = r2.tool_calls[0]
        print(f"通过（调用了 {call['name']}，args={json.dumps(call['args'], ensure_ascii=False)}）")
    else:
        print("失败：模型没有返回 tool_calls。该模型可能不支持工具调用，agent 无法正常工作。")
        sys.exit(1)

    # 3. 流式输出
    print("3) 流式输出 … ", end="", flush=True)
    n = sum(1 for _ in model.stream([{"role": "user", "content": "从1数到5"}]))
    print(f"通过（{n} 个 chunk）")

    print("\n全部通过，可以运行 uv run python main.py 启动服务。")


if __name__ == "__main__":
    main()
