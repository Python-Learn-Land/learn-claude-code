#!/usr/bin/env python3
"""
s04: Hooks — OpenAI SDK version

将扩展逻辑从循环中移出，放到 hook 上：

  用户输入查询
       │
       ▼
  ┌──────────────────┐
  │ UserPromptSubmit │ ── trigger_hooks() 在 LLM 之前触发
  └────────┬─────────┘
           ▼
  ┌────────────┐     ┌─────────────────────────────┐
  │  messages  │────▶│  LLM (存在 tool_calls?)     │
  └────────────┘     │   否 ──▶ Stop hooks ──▶ 退出 │
                     │   是 ──▶ tool_calls ────┐   │
                     └─────────────────────────┘   │
                                                    ▼
                                          ┌──────────────────┐
                                          │ trigger_hooks()   │
                                          │  PreToolUse:      │
                                          │   permission_hook │
                                          │   log_hook        │
                                          └───────┬──────────┘
                                                  │ (未被拦截)
                                          ┌───────▼──────────┐
                                          │ TOOL_HANDLERS[x]  │
                                          └───────┬──────────┘
                                                  │
                                          ┌───────▼──────────┐
                                          │ trigger_hooks()   │
                                          │  PostToolUse:     │
                                          │   large_output    │
                                          └───────┬──────────┘
                                                  │
                                          results ──▶ 回到 messages

与 s03 的变化：
  + HOOKS 注册表 (事件 -> 回调列表)
  + register_hook() / trigger_hooks()
  + context_inject_hook (UserPromptSubmit)
  + permission_hook, log_hook (PreToolUse)
  + large_output_hook (PostToolUse)
  + summary_hook (Stop)
  - check_permission() 从循环体中移除
    (逻辑移入 permission_hook，通过 PreToolUse 触发)

运行: python s04_hooks/code_openai.py
需要: pip install openai python-dotenv + .env 中配置 OPENAI_API_KEY
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

# 将仓库根目录加入 sys.path，以便导入 llm_tracer
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    import readline
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

WORKDIR = Path.cwd()
client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    base_url=os.getenv("OPENAI_BASE_URL"),
)

# 初始化 tracer，自动包装 client —— agent_loop 无需任何改动
tracer = LLMTracer(name="s04_hooks", output_dir=str(WORKDIR / ".traces"))
client = wrap_client(client, tracer)

MODEL = os.environ["OPENAI_MODEL_ID"]

SYSTEM = f"你是一个编程助手，工作目录是 {WORKDIR}。使用工具解决任务。不要解释，直接行动。"


# ═══════════════════════════════════════════════════════════
#  FROM s02-s03 (unchanged): Tool Implementations
# ═══════════════════════════════════════════════════════════

def safe_path(p: str) -> Path:
    path = (WORKDIR / p).resolve()
    if not path.is_relative_to(WORKDIR):
        raise ValueError(f"路径超出工作区范围: {p}")
    return path

def run_bash(command: str) -> str:
    try:
        r = subprocess.run(command, shell=True, cwd=WORKDIR,
                           capture_output=True, text=True, timeout=120)
        out = (r.stdout + r.stderr).strip()
        return out[:50000] if out else "(无输出)"
    except subprocess.TimeoutExpired:
        return "错误: 超时 (120秒)"

def run_read(path: str, limit: int | None = None) -> str:
    try:
        lines = safe_path(path).read_text().splitlines()
        if limit and limit < len(lines):
            lines = lines[:limit] + [f"... ({len(lines) - limit} 行已省略)"]
        return "\n".join(lines)
    except Exception as e:
        return f"错误: {e}"

def run_write(path: str, content: str) -> str:
    try:
        file_path = safe_path(path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content)
        return f"已写入 {len(content)} 字节到 {path}"
    except Exception as e:
        return f"错误: {e}"

def run_edit(path: str, old_text: str, new_text: str) -> str:
    try:
        file_path = safe_path(path)
        text = file_path.read_text()
        if old_text not in text:
            return f"错误: 在 {path} 中未找到指定文本"
        file_path.write_text(text.replace(old_text, new_text, 1))
        return f"已编辑 {path}"
    except Exception as e:
        return f"错误: {e}"

def run_glob(pattern: str) -> str:
    import glob as g
    try:
        results = []
        for match in g.glob(pattern, root_dir=WORKDIR):
            if (WORKDIR / match).resolve().is_relative_to(WORKDIR):
                results.append(match)
        return "\n".join(results) if results else "(无匹配)"
    except Exception as e:
        return f"错误: {e}"

# OpenAI 格式工具定义
TOOLS = [
    {"type": "function", "function": {
        "name": "bash", "description": "运行 shell 命令。",
        "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}}},
    {"type": "function", "function": {
        "name": "read_file", "description": "读取文件内容。",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "write_file", "description": "写入内容到文件。",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}}},
    {"type": "function", "function": {
        "name": "edit_file", "description": "替换文件中的指定文本（仅替换第一次出现）。",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}}, "required": ["path", "old_text", "new_text"]}}},
    {"type": "function", "function": {
        "name": "glob", "description": "查找匹配 glob 模式的文件。",
        "parameters": {"type": "object", "properties": {"pattern": {"type": "string"}}, "required": ["pattern"]}}},
]

TOOL_HANDLERS = {
    "bash": run_bash, "read_file": run_read, "write_file": run_write,
    "edit_file": run_edit, "glob": run_glob,
}


# ═══════════════════════════════════════════════════════════
#  NEW in s04: Hook System (s03 permission logic now via hooks)
# ═══════════════════════════════════════════════════════════

HOOKS = {"UserPromptSubmit": [], "PreToolUse": [], "PostToolUse": [], "Stop": []}

def register_hook(event: str, callback):
    HOOKS[event].append(callback)

def trigger_hooks(event: str, *args):
    for callback in HOOKS[event]:
        result = callback(*args)
        if result is not None:  # 教学简化：拦截此工具调用
            return result
    return None


# s03 permission check logic, now wrapped as a hook
DENY_LIST = ["rm -rf /", "sudo", "shutdown", "reboot", "mkfs", "dd if="]
DESTRUCTIVE = ["rm ", "> /etc/", "chmod 777"]

def permission_hook(block):
    """PreToolUse: s03 check_permission() logic moved here."""
    if block.name == "bash":
        for pattern in DENY_LIST:
            if pattern in block.input.get("command", ""):
                print(f"\n\033[31m⛔ 已拦截: '{pattern}'\033[0m")
                return "拒绝列表拦截"
        for kw in DESTRUCTIVE:
            if kw in block.input.get("command", ""):
                print(f"\n\033[33m⚠  潜在破坏性命令\033[0m")
                print(f"   工具: {block.name}({block.input})")
                choice = input("   允许执行? [y/N] ").strip().lower()
                if choice not in ("y", "yes"):
                    return "用户拒绝"
    if block.name in ("write_file", "edit_file"):
        path = block.input.get("path", "")
        if not (WORKDIR / path).resolve().is_relative_to(WORKDIR):
            print(f"\n\033[33m⚠  试图写入工作区外\033[0m")
            print(f"   工具: {block.name}({block.input})")
            choice = input("   允许执行? [y/N] ").strip().lower()
            if choice not in ("y", "yes"):
                return "用户拒绝"
    return None

def log_hook(block):
    """PreToolUse: log every tool call."""
    args_preview = str(list(block.input.values())[:2])[:60]
    print(f"\033[90m[HOOK] {block.name}({args_preview})\033[0m")
    return None

def large_output_hook(block, output):
    """PostToolUse: warn on large output."""
    if len(str(output)) > 100000:
        print(f"\033[33m[HOOK] ⚠ 大输出警告 {block.name}: {len(str(output))} 字符\033[0m")
    return None

# UserPromptSubmit hook: log user input before it reaches the LLM
def context_inject_hook(query: str):
    print(f"\033[90m[HOOK] UserPromptSubmit: 工作目录 {WORKDIR}\033[0m")
    return None

# Stop hook: print summary when loop is about to exit
# 兼容 Anthropic 和 OpenAI 两种消息格式
def summary_hook(messages: list):
    tool_count = 0
    for m in messages:
        content = m.get("content")
        if isinstance(content, list):
            for b in content:
                if isinstance(b, dict):
                    # Anthropic format
                    if b.get("type") == "tool_result":
                        tool_count += 1
        # OpenAI format: tool results are separate messages with role="tool"
        if m.get("role") == "tool":
            tool_count += 1
    print(f"\033[90m[HOOK] Stop: 本轮对话使用了 {tool_count} 次工具调用\033[0m")
    return None

register_hook("UserPromptSubmit", context_inject_hook)
register_hook("PreToolUse", permission_hook)
register_hook("PreToolUse", log_hook)
register_hook("PostToolUse", large_output_hook)
register_hook("Stop", summary_hook)


# ═══════════════════════════════════════════════════════════
#  agent_loop — same structure as s03, but no hard-coded check
#  s03: if not check_permission(block): ...
#  s04: if trigger_hooks("PreToolUse", block): ...
# ═══════════════════════════════════════════════════════════

def agent_loop(messages: list):
    while True:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "system", "content": SYSTEM}] + messages,
            tools=TOOLS,
            max_tokens=8000,
        )

        msg = response.choices[0].message

        # Append assistant turn（含 tool_calls）
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

        if not msg.tool_calls:
            force = trigger_hooks("Stop", messages)
            if force:
                messages.append({"role": "user", "content": force})
                continue
            return

        results = []
        for call in msg.tool_calls:
            # 构造类似 Anthropic block 的对象，使 hook 无需改动
            block = SimpleNamespace(
                name=call.function.name,
                input=json.loads(call.function.arguments),
                id=call.id,
            )

            # s04 change: hook replaces hard-coded check_permission()
            blocked = trigger_hooks("PreToolUse", block)
            if blocked:
                results.append({
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": str(blocked),
                })
                continue

            handler = TOOL_HANDLERS.get(call.function.name)
            output = handler(**block.input) if handler else f"未知工具: {call.function.name}"

            trigger_hooks("PostToolUse", block, output)  # s04: post hook

            results.append({
                "role": "tool",
                "tool_call_id": call.id,
                "content": output,
            })

        messages.extend(results)


if __name__ == "__main__":
    print("s04: Hooks — 扩展逻辑通过 hook 实现，循环体保持简洁 (OpenAI SDK)")
    print("输入问题，回车发送。输入 q 退出。")
    print(f"📝 Trace 文件: {tracer.trace_file}\n")

    history = []
    while True:
        try:
            query = input("\033[36ms04(openai) >> \033[0m")
        except (EOFError, KeyboardInterrupt):
            break
        if query.strip().lower() in ("q", "exit", ""):
            break
        trigger_hooks("UserPromptSubmit", query)
        history.append({"role": "user", "content": query})
        agent_loop(history)
        last_msg = history[-1]
        if last_msg.get("role") == "assistant" and last_msg.get("content"):
            print(last_msg["content"])
        print()
