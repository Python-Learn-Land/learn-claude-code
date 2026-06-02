#!/usr/bin/env python3
"""
s05: TodoWrite — OpenAI SDK version

在 s04 hooks 基础上增加计划工具：

  +---------+      +-------+      +------------------+
  |  用户   | ---> |  LLM  | ---> | TOOL_HANDLERS    |
  | 输入    |      |       |      |  bash            |
  +---------+      +---+---+      |  read_file       |
                        ^         |  write_file      |
                        | 结果    |  edit_file       |
                        +---------+  glob            |
                                      todo_write ← 新增
                                   +------------------+
                                        |
                         内存中的 current_todos
                                        |
                        如果 rounds_since_todo >= 3:
                          注入 <reminder>提醒</reminder>

与 s04 的变化：
  + todo_write 工具 + run_todo_write() 实现
  + Nag 提醒器 (3 轮未更新 todo 后注入提醒)
  + SYSTEM 提示词增加 "先规划再执行" 引导
  + agent_loop 中增加 rounds_since_todo 计数器
  循环本身不变：新工具通过 TOOL_HANDLERS 自动分发。

运行: python s05_todo_write/code_openai.py
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
tracer = LLMTracer(name="s05_todo_write", output_dir=str(WORKDIR / ".traces"))
client = wrap_client(client, tracer)

MODEL = os.environ["OPENAI_MODEL_ID"]
CURRENT_TODOS: list[dict] = []

# s05 change: SYSTEM 提示词增加规划引导（中文）
SYSTEM = (
    f"你是一个编程助手，工作目录是 {WORKDIR}。"
    "在开始任何多步骤任务之前，先使用 todo_write 规划你的步骤。"
    "在执行过程中及时更新任务状态。"
)


# ═══════════════════════════════════════════════════════════
#  FROM s02-s04 (unchanged): Tool Implementations
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


# ═══════════════════════════════════════════════════════════
#  NEW in s05: todo_write tool — 仅规划，不执行
# ═══════════════════════════════════════════════════════════

def run_todo_write(todos: list) -> str:
    global CURRENT_TODOS
    # 验证必填字段
    for i, t in enumerate(todos):
        if "content" not in t or "status" not in t:
            return f"错误: todos[{i}] 缺少 'content' 或 'status'"
        if t["status"] not in ("pending", "in_progress", "completed"):
            return f"错误: todos[{i}] 状态无效 '{t['status']}'"
    CURRENT_TODOS = todos
    lines = ["\n\033[33m## 当前任务\033[0m"]
    for t in CURRENT_TODOS:
        icon = {"pending": " ", "in_progress": "\033[36m▸\033[0m", "completed": "\033[32m✓\033[0m"}[t["status"]]
        lines.append(f"  [{icon}] {t['content']}")
    print("\n".join(lines))
    return f"已更新 {len(CURRENT_TODOS)} 个任务"

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
    # s05: 新增工具
    {"type": "function", "function": {
        "name": "todo_write", "description": "创建并管理当前编程会话的任务列表。",
        "parameters": {"type": "object", "properties": {"todos": {"type": "array", "items": {"type": "object", "properties": {"content": {"type": "string"}, "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]}}, "required": ["content", "status"]}}}, "required": ["todos"]}}},
]

TOOL_HANDLERS = {
    "bash": run_bash, "read_file": run_read, "write_file": run_write,
    "edit_file": run_edit, "glob": run_glob, "todo_write": run_todo_write,
}


# ═══════════════════════════════════════════════════════════
#  FROM s04 (unchanged): Hook System
# ═══════════════════════════════════════════════════════════

HOOKS = {"UserPromptSubmit": [], "PreToolUse": [], "PostToolUse": [], "Stop": []}

def register_hook(event: str, callback):
    HOOKS[event].append(callback)

def trigger_hooks(event: str, *args):
    for callback in HOOKS[event]:
        result = callback(*args)
        if result is not None:
            return result
    return None

# s04 hooks preserved
DENY_LIST = ["rm -rf /", "sudo", "shutdown", "reboot", "mkfs", "dd if="]

def permission_hook(block):
    """PreToolUse: 拒绝列表检查。"""
    if block.name == "bash":
        for p in DENY_LIST:
            if p in block.input.get("command", ""):
                print(f"\n\033[31m⛔ 已拦截: '{p}'\033[0m")
                return "拒绝列表拦截"
    return None

def log_hook(block):
    """PreToolUse: 记录工具调用。"""
    print(f"\033[90m[HOOK] {block.name}\033[0m")
    return None

def context_inject_hook(query: str):
    """UserPromptSubmit: 记录工作目录。"""
    print(f"\033[90m[HOOK] UserPromptSubmit: 工作目录 {WORKDIR}\033[0m")
    return None

# 兼容 Anthropic 和 OpenAI 两种消息格式
def summary_hook(messages: list):
    """Stop: 打印工具调用次数。"""
    tool_count = 0
    for m in messages:
        content = m.get("content")
        if isinstance(content, list):
            for b in content:
                if isinstance(b, dict):
                    if b.get("type") == "tool_result":
                        tool_count += 1
        if m.get("role") == "tool":
            tool_count += 1
    print(f"\033[90m[HOOK] Stop: 本轮对话使用了 {tool_count} 次工具调用\033[0m")
    return None

register_hook("UserPromptSubmit", context_inject_hook)
register_hook("PreToolUse", permission_hook)
register_hook("PreToolUse", log_hook)
register_hook("Stop", summary_hook)


# ═══════════════════════════════════════════════════════════
#  agent_loop — 与 s04 相同 + nag reminder 计数器
# ═══════════════════════════════════════════════════════════

rounds_since_todo = 0

def agent_loop(messages: list):
    global rounds_since_todo
    while True:
        # s05: nag reminder — 如果模型 3 轮未更新 todo，注入提醒
        if rounds_since_todo >= 3 and messages:
            messages.append({"role": "user",
                             "content": "<reminder>请更新你的任务列表。</reminder>"})
            rounds_since_todo = 0

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

        rounds_since_todo += 1
        results = []
        for call in msg.tool_calls:
            # 构造类似 Anthropic block 的对象，使 hook 无需改动
            block = SimpleNamespace(
                name=call.function.name,
                input=json.loads(call.function.arguments),
                id=call.id,
            )

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

            trigger_hooks("PostToolUse", block, output)

            # s05: 调用 todo_write 时重置 nag 计数器
            if block.name == "todo_write":
                rounds_since_todo = 0

            results.append({
                "role": "tool",
                "tool_call_id": call.id,
                "content": output,
            })

        messages.extend(results)


if __name__ == "__main__":
    print("s05: TodoWrite — 先规划再执行，忘记时会提醒 (OpenAI SDK)")
    print("输入问题，回车发送。输入 q 退出。")
    print(f"📝 Trace 文件: {tracer.trace_file}\n")

    history = []
    while True:
        try:
            query = input("\033[36ms05(openai) >> \033[0m")
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
