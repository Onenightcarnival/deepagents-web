"""模型连通性与 tool calling 自检。
在 .env 配好 MODEL_* 后运行：uv run python test/check_model.py
"""
import json
import os
import sys

from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langchain_core.tools import tool

from app.agent import build_model
from app.providers import env_provider, provider_type_of

provider = env_provider()
if not provider:
    print("请先在 .env 中配置 MODEL_BASE_URL / MODEL_API_KEY / MODEL_NAME")
    sys.exit(1)

model = build_model({
    "baseUrl": provider["baseUrl"],
    "apiKey": provider["apiKey"],
    "model": provider["models"][0],
    "type": provider_type_of(provider),
})
print(f"模型: {provider['models'][0]} @ {provider['baseUrl']}")

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

print("\n全部通过，可以运行 uv run python -m app.main 启动服务。")
