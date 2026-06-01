#!/usr/bin/env python3
"""
s01_agent_loop_openai.py - The Agent Loop (OpenAI SDK version)

The same core pattern as code.py, implemented with the OpenAI SDK:

    while tool_calls exist:
        response = LLM(messages, tools)
        execute tools
        append results

    +----------+      +-------+      +---------+
    |   User   | ---> |  LLM  | ---> |  Tool   |
    |  prompt  |      |       |      | execute |
    +----------+      +---+---+      +----+----+
                          ^               |
                          |   tool result |
                          +---------------+
                          (loop continues)

This file demonstrates the 5 SDK-level differences when using OpenAI
instead of Anthropic:

    1. Client import: openai.OpenAI vs anthropic.Anthropic
    2. System prompt: goes into messages list, not a separate parameter
    3. Tool schema: wrapped in {"type": "function", "function": {...}}
    4. Response parsing: response.choices[0].message.tool_calls
    5. Tool result format: {"role": "tool", "tool_call_id": ...}

The business logic (loop structure, tool execution, state management)
is identical to the Anthropic version.

Usage:
    pip install openai python-dotenv
    OPENAI_API_KEY=... python s01_agent_loop/code_openai.py
"""

import json
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

from openai import OpenAI
from dotenv import load_dotenv
from llm_tracer import LLMTracer, wrap_client

load_dotenv(override=True)

client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    base_url=os.getenv("OPENAI_BASE_URL"),
)

# 初始化 tracer，自动包装 client —— agent_loop 无需任何改动
tracer = LLMTracer(name="s01_agent_loop", output_dir=str(Path.cwd() / ".traces"))
client = wrap_client(client, tracer)
MODEL = os.environ["OPENAI_MODEL_ID"]

SYSTEM = f"You are a coding agent at {os.getcwd()}. Use bash to solve tasks. Act, don't explain."

# ── Tool definition: just bash ────────────────────────────
# OpenAI 格式：需要包裹在 {"type": "function", "function": {...}} 中
# 且 schema 字段名从 input_schema 变为 parameters
TOOLS = [{
    "type": "function",
    "function": {
        "name": "bash",
        "description": "Run a shell command.",
        "parameters": {
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
        },
    }
}]


# ── Tool execution ────────────────────────────────────────
def run_bash(command: str) -> str:
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


# ── The core pattern: a while loop that calls tools until the model stops ──
def agent_loop(messages: list):
    while True:
        # OpenAI: system prompt 放入 messages 列表开头
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "system", "content": SYSTEM}] + messages,
            tools=TOOLS,
            max_tokens=8000,
        )

        msg = response.choices[0].message

        # Append assistant turn
        # OpenAI: 需要把 assistant 消息（含 tool_calls）放回对话历史
        messages.append({
            "role": "assistant",
            "content": msg.content,
            "tool_calls": [
                {
                    "id": c.id,
                    "type": "function",
                    "function": {
                        "name": c.function.name,
                        "arguments": c.function.arguments,
                    },
                }
                for c in (msg.tool_calls or [])
            ] if msg.tool_calls else None,
        })

        # If the model didn't call a tool, we're done
        # OpenAI: 用 msg.tool_calls 是否存在来判断
        if not msg.tool_calls:
            return

        # Execute each tool call, collect results
        results = []
        for call in msg.tool_calls:
            # OpenAI: arguments 是 JSON 字符串，需要解析
            args = json.loads(call.function.arguments)
            print(f"\033[33m$ {args['command']}\033[0m")
            output = run_bash(args["command"])
            print(output[:200])
            # OpenAI: tool result 格式为 {"role": "tool", "tool_call_id": ...}
            results.append({
                "role": "tool",
                "tool_call_id": call.id,
                "content": output,
            })

        # Feed tool results back, loop continues
        messages.extend(results)


# ── Entry point ──────────────────────────────────────────
if __name__ == "__main__":
    print("s01: Agent Loop (OpenAI SDK)")
    print("输入问题，回车发送。输入 q 退出。")
    print(f"📝 Trace 文件: {tracer.trace_file}\n")

    history = []
    while True:
        try:
            query = input("\033[36ms01(openai) >> \033[0m")
        except (EOFError, KeyboardInterrupt):
            break
        if query.strip().lower() in ("q", "exit", ""):
            break
        history.append({"role": "user", "content": query})
        agent_loop(history)
        # Print the model's final text response
        # OpenAI: 最终回复直接在 messages 末尾的 content 字段中
        last_msg = history[-1]
        if last_msg.get("role") == "assistant" and last_msg.get("content"):
            print(last_msg["content"])
        print()
