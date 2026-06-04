#!/usr/bin/env python3
"""
s01_agent_loop_langchain.py - The Agent Loop (LangChain version)

The same core pattern as code.py, implemented with LangChain primitives:

    while tool_calls exist:
        response = llm_with_tools.invoke(messages)
        execute tools
        append results

This file demonstrates the 4 LangChain-level differences compared to
the raw Anthropic SDK:

    1. Model: ChatAnthropic wraps the Anthropic client
    2. Tools: @tool decorator auto-generates JSON schema
    3. Messages: BaseMessage subclasses instead of raw dicts
    4. Tool binding: llm.bind_tools(tools) instead of passing tools=TOOLS

The business logic (loop structure, tool execution, state management)
is identical to the Anthropic version.

Usage:
    pip install langchain-anthropic python-dotenv
    ANTHROPIC_API_KEY=... python s01_agent_loop/code_langchain.py
"""

import os
import subprocess
import sys
from pathlib import Path

# 将仓库根目录加入 sys.path，以便导入 llm_tracer
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    import readline
    # macOS 的 libedit 在处理中文输入时有退格问题，这四行修复它
    readline.parse_and_bind('set bind-tty-special-chars off')
    readline.parse_and_bind('set input-meta on')
    readline.parse_and_bind('set output-meta on')
    readline.parse_and_bind('set convert-meta off')
except ImportError:
    pass

from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool

from llm_tracer import LLMTracer

load_dotenv(override=True)

if os.getenv("ANTHROPIC_BASE_URL"):
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

MODEL = os.environ["MODEL_ID"]

# 初始化 tracer —— langchain 没有 wrap_client 可用的 hook，所以在循环内手动记录
_tracer = LLMTracer(name="s01_agent_loop_langchain", output_dir=str(Path.cwd() / ".traces"))

SYSTEM = f"You are a coding agent at {os.getcwd()}. Use bash to solve tasks. Act, don't explain."


# ── Tool definition: bash with auto-generated schema ───────
@tool
def bash(command: str) -> str:
    """Run a shell command."""
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]
    if any(d in command for d in dangerous):
        return "Error: Dangerous command blocked"
    try:
        r = subprocess.run(command, shell=True, cwd=os.getcwd(),
                           capture_output=True, text=True, timeout=120)
        out = (r.stdout + r.stderr).strip()
        return out[:50000] if out else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"
    except (FileNotFoundError, OSError) as e:
        return f"Error: {e}"


TOOLS = [bash]
llm = ChatAnthropic(
    model=MODEL,
    anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
    anthropic_api_url=os.getenv("ANTHROPIC_BASE_URL"),
    max_tokens=8000,
)
llm_with_tools = llm.bind_tools(TOOLS)


# ── The core pattern: a while loop that calls tools until the model stops ──
def agent_loop(messages: list):
    while True:
        # LangChain: messages 是 BaseMessage 子类对象；SystemMessage 放在列表开头
        response = llm_with_tools.invoke([SystemMessage(content=SYSTEM)] + messages)

        # 手动记录 LLM 调用（langchain 没有统一的 client.create 可包装）
        _tracer.log_turn(
            request={
                "model": MODEL,
                "system": SYSTEM,
                "messages": [m.model_dump() if hasattr(m, "model_dump") else str(m) for m in messages],
                "tools": [t.name for t in TOOLS],
            },
            response=response,
            note="LangChain",
        )

        # Append assistant turn
        messages.append(response)

        # If the model didn't call a tool, we're done
        # LangChain: tool_calls 是 AIMessage 上的属性
        if not response.tool_calls:
            return

        # Execute each tool call, collect results
        results = []
        for call in response.tool_calls:
            print(f"\033[33m$ {call['args']['command']}\033[0m")
            output = bash.invoke(call["args"])
            print(output[:200])
            results.append(ToolMessage(
                tool_call_id=call["id"],
                content=output,
            ))

        # Feed tool results back, loop continues
        messages.extend(results)


# ── Response printing helper ─────────────────────────────
def print_ai_response(message):
    """打印 LangChain AIMessage 中的 thinking/text 内容，跳过原始列表结构。"""
    if not isinstance(message, AIMessage):
        return
    content = message.content
    if isinstance(content, str) and content:
        print(content)
        return
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict):
                block_type = block.get("type")
                if block_type == "thinking":
                    print(f"\033[90m[thinking] {block.get('thinking', '')}\033[0m")
                elif block_type == "text":
                    print(block.get("text", ""))


# ── Entry point ──────────────────────────────────────────
if __name__ == "__main__":
    print("s01: Agent Loop (LangChain)")
    print("输入问题，回车发送。输入 q 退出。")
    print(f"📝 Trace 文件: {_tracer.trace_file}\n")

    history = []
    while True:
        try:
            query = input("\033[36ms01(lc) >> \033[0m")
        except (EOFError, KeyboardInterrupt):
            break
        if query.strip().lower() in ("q", "exit", ""):
            break
        history.append(HumanMessage(content=query))
        agent_loop(history)
        # Print the model's final text response
        print_ai_response(history[-1])
        print()
