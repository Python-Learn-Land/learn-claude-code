#!/usr/bin/env python3
"""
s03: Permission System — OpenAI SDK version

三层权限门控，使用 OpenAI SDK 实现：

    Gate 1: 硬拒绝列表 (rm -rf /, sudo, ...)
    Gate 2: 规则匹配 (写到工作区外? 破坏性命令?)
    Gate 3: 用户确认 (暂停等待人工确认)

    +-------+    +--------+    +--------+    +--------+    +------+
    | Tool  | -> | Gate 1 | -> | Gate 2 | -> | Gate 3 | -> | Exec |
    | call  |    | deny?  |    | match? |    | allow? |    |      |
    +-------+    +--------+    +--------+    +--------+    +------+
         |            |             |             |
         v            v             v             v
      (normal)     (blocked)    (ask user)   (user says no?)

在 agent_loop 中只插入了一行：

    if not check_permission(call):
        continue

基于 s02 (多工具)。运行方式：

    python s03_permission/code_openai.py
    需要: pip install openai python-dotenv + .env 中配置 OPENAI_API_KEY
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
tracer = LLMTracer(name="s03_permission", output_dir=str(WORKDIR / ".traces"))
client = wrap_client(client, tracer)

MODEL = os.environ["OPENAI_MODEL_ID"]

# 系统提示词改为中文
SYSTEM = f"你是一个编程助手，工作目录是 {WORKDIR}。所有破坏性操作都需要用户确认后才能执行。"


# ═══════════════════════════════════════════════════════════
#  FROM s02 (unchanged): Tool Implementations
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
#  FROM s02: Tool Definitions (OpenAI 格式)
# ═══════════════════════════════════════════════════════════

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
#  NEW in s03: Three-Gate Permission Pipeline
# ═══════════════════════════════════════════════════════════

# Gate 1: 硬拒绝列表 — 始终禁止
DENY_LIST = ["rm -rf /", "sudo", "shutdown", "reboot", "mkfs", "dd if=", "> /dev/sda"]

def check_deny_list(command: str) -> str | None:
    for pattern in DENY_LIST:
        if pattern in command:
            return f"已拦截: '{pattern}' 在拒绝列表中"
    return None


# Gate 2: 规则匹配 — 根据上下文判断
PERMISSION_RULES = [
    {"tools": ["write_file", "edit_file"],
     "check": lambda args: not (WORKDIR / args.get("path", "")).resolve().is_relative_to(WORKDIR),
     "message": "试图写入工作区外的路径"},
    {"tools": ["bash"],
     "check": lambda args: any(kw in args.get("command", "") for kw in ["rm ", "> /etc/", "chmod 777"]),
     "message": "潜在破坏性命令"},
]

def check_rules(tool_name: str, args: dict) -> str | None:
    for rule in PERMISSION_RULES:
        if tool_name in rule["tools"] and rule["check"](args):
            return rule["message"]
    return None


# Gate 3: 用户确认 — 规则匹配后等待人工确认
def ask_user(tool_name: str, args: dict, reason: str) -> str:
    print(f"\n\033[33m⚠  {reason}\033[0m")
    print(f"   工具: {tool_name}({args})")
    choice = input("   允许执行? [y/N] ").strip().lower()
    return "allow" if choice in ("y", "yes") else "deny"


# Pipeline: 三层门控串联
# OpenAI 版本：接收 tool_call 对象而非 block
def check_permission(tool_name: str, args: dict) -> bool:
    if tool_name == "bash":
        reason = check_deny_list(args.get("command", ""))
        if reason:
            print(f"\n\033[31m⛔ {reason}\033[0m")
            return False
    reason = check_rules(tool_name, args)
    if reason:
        decision = ask_user(tool_name, args, reason)
        if decision == "deny":
            return False
    return True


# ═══════════════════════════════════════════════════════════
#  agent_loop — 与 s02_openai 结构一致，插入 check_permission()
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
            return

        results = []
        for call in msg.tool_calls:
            print(f"\033[36m> {call.function.name}\033[0m")
            args = json.loads(call.function.arguments)

            # s03 change: 权限检查
            if not check_permission(call.function.name, args):
                results.append({
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": "权限被拒绝。",
                })
                continue

            handler = TOOL_HANDLERS.get(call.function.name)
            output = handler(**args) if handler else f"未知工具: {call.function.name}"
            print(str(output)[:200])
            results.append({
                "role": "tool",
                "tool_call_id": call.id,
                "content": output,
            })

        messages.extend(results)


if __name__ == "__main__":
    print("s03: 权限系统 — 在 s02 基础上增加了三层权限门控 (OpenAI SDK)")
    print("输入问题，回车发送。输入 q 退出。")
    print(f"📝 Trace 文件: {tracer.trace_file}\n")

    history = []
    while True:
        try:
            query = input("\033[36ms03(openai) >> \033[0m")
        except (EOFError, KeyboardInterrupt):
            break
        if query.strip().lower() in ("q", "exit", ""):
            break
        history.append({"role": "user", "content": query})
        agent_loop(history)
        last_msg = history[-1]
        if last_msg.get("role") == "assistant" and last_msg.get("content"):
            print(last_msg["content"])
        print()
