#!/usr/bin/env python3
"""
s01_agent_loop_langgraph.py - The Agent Loop (LangGraph version)

The same core pattern as code.py, modeled as an explicit state graph:

    +--------+   no tool_calls   +---+
    | agent  | ----------------> |END|
    +--------+                   +---+
         |
         | tool_calls
         v
    +--------+
    | tools  |
    +--------+
         |
         +-----> agent (loop continues)

This file demonstrates how LangGraph makes the loop structure explicit:
nodes represent the LLM call and tool execution, and conditional edges
route the flow. The underlying mechanism is still the same ReAct loop.

Usage:
    pip install langchain-anthropic langgraph python-dotenv
    ANTHROPIC_API_KEY=... python s01_agent_loop/code_langgraph.py
"""

import operator
import os
import subprocess
import sys
from pathlib import Path
from typing import Annotated, TypedDict

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
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.graph import END, StateGraph

from llm_tracer import LLMTracer

load_dotenv(override=True)

if os.getenv("ANTHROPIC_BASE_URL"):
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

MODEL = os.environ["MODEL_ID"]

# 初始化 tracer —— 在 LangGraph 节点内手动记录 LLM 调用
_tracer = LLMTracer(name="s01_agent_loop_langgraph", output_dir=str(Path.cwd() / ".traces"))

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


# ── Graph state ───────────────────────────────────────────
class AgentState(TypedDict):
    # Annotated + operator.add 表示新消息会追加到列表
    messages: Annotated[list[BaseMessage], operator.add]


# ── Node: agent（对应 code.py 的 LLM 调用，第 100-106 行）──
def agent_node(state: AgentState):
    response = llm_with_tools.invoke([SystemMessage(content=SYSTEM)] + state["messages"])

    _tracer.log_turn(
        request={
            "model": MODEL,
            "system": SYSTEM,
            "messages": [m.model_dump() if hasattr(m, "model_dump") else str(m) for m in state["messages"]],
            "tools": [t.name for t in TOOLS],
        },
        response=response,
        note="LangGraph-agent",
    )

    # 只返回新增消息，由 operator.add 合并到 state
    return {"messages": [response]}


# ── Node: tools（对应 code.py 的 tool 执行，第 114-126 行）──
def tools_node(state: AgentState):
    last_message = state["messages"][-1]
    tool_messages = []
    for call in last_message.tool_calls:
        print(f"\033[33m$ {call['args']['command']}\033[0m")
        output = bash.invoke(call["args"])
        print(output[:200])
        tool_messages.append(ToolMessage(
            tool_call_id=call["id"],
            content=output,
        ))
    return {"messages": tool_messages}


# ── Conditional edge: 是否有 tool_calls？──────────────────
def should_continue(state: AgentState):
    """对应 code.py 第 109 行：if response.stop_reason != 'tool_use'"""
    last_message = state["messages"][-1]
    if last_message.tool_calls:
        return "continue"
    return "end"


# ── Build the graph ───────────────────────────────────────
workflow = StateGraph(AgentState)

workflow.add_node("agent", agent_node)   # LLM 节点
workflow.add_node("tools", tools_node)   # 工具执行节点

workflow.set_entry_point("agent")

# agent -> tools（继续循环）或 END（结束）
workflow.add_conditional_edges(
    "agent",
    should_continue,
    {"continue": "tools", "end": END},
)

# tools -> agent（反馈结果，循环继续）
workflow.add_edge("tools", "agent")

app = workflow.compile()


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
    print("s01: Agent Loop (LangGraph)")
    print("输入问题，回车发送。输入 q 退出。")
    print(f"📝 Trace 文件: {_tracer.trace_file}\n")

    history = []
    while True:
        try:
            query = input("\033[36ms01(lg) >> \033[0m")
        except (EOFError, KeyboardInterrupt):
            break
        if query.strip().lower() in ("q", "exit", ""):
            break
        history.append(HumanMessage(content=query))

        # 运行图，返回最终状态
        final_state = app.invoke({"messages": history})
        history[:] = final_state["messages"]

        # Print the model's final text response
        print_ai_response(history[-1])
        print()
