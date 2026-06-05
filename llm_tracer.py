#!/usr/bin/env python3
"""
llm_tracer.py — 轻量级 LLM 调用追踪器

以 Markdown 格式记录每一次 LLM 请求-响应对，包含可折叠的 JSON 详情，
方便人类阅读和调试。

使用方式（改动最少）：

    from llm_tracer import LLMTracer, wrap_client

    tracer = LLMTracer(name="s01")
    client = wrap_client(client, tracer)   # ← 只改这一行，agent_loop 无需变动

或者手动在 agent_loop 中记录（更灵活）：

    tracer = LLMTracer(name="s01")

    def agent_loop(messages):
        response = client.chat.completions.create(...)
        tracer.log_turn(request={"messages": messages, ...}, response=response)
"""

import json
import datetime
import os
import sys
from pathlib import Path
from typing import Any

# ── Optional: integrate with agent_logger ──
try:
    sys.path.insert(0, str(Path.cwd()))
    from agent_logger import log_print
except Exception:
    log_print = print  # fallback


# ── 序列化 helpers ───────────────────────────────────────

def _serialize(obj: Any) -> Any:
    """将 SDK 响应对象递归转换为可 JSON 序列化的纯 Python 对象。"""
    # Pydantic v2 (OpenAI SDK 1.30+)
    if hasattr(obj, "model_dump"):
        return _serialize(obj.model_dump())
    # Pydantic v1
    if hasattr(obj, "dict"):
        return _serialize(obj.dict())
    # dataclass
    if hasattr(obj, "__dataclass_fields__"):
        return {k: _serialize(v) for k, v in obj.__dict__.items()}
    # list / tuple
    if isinstance(obj, (list, tuple)):
        return [_serialize(i) for i in obj]
    # dict
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    # bytes → str
    if isinstance(obj, bytes):
        return obj.decode("utf-8", errors="replace")
    # 默认直接返回（int, str, float, bool, None 等）
    return obj


def _pretty_json(obj: Any) -> str:
    """将对象序列化为带缩进的 JSON 字符串。"""
    return json.dumps(_serialize(obj), indent=2, ensure_ascii=False, default=str)


# ── Tracer 类 ────────────────────────────────────────────

class LLMTracer:
    """
    记录 LLM 对话过程到 Markdown 文件。

    输出格式：
        .traces/
            s01_20250601_143052.md
            s01_20250601_143110.md
            ...

    每个 .md 文件包含：
        - 运行元信息（时间、名称）
        - 每次 Turn 的请求/响应对（可折叠的 JSON 代码块）
        - 消息流转记录（可选）
    """

    def __init__(self, name: str = "agent", output_dir: str = ".traces"):
        self.name = name
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.trace_file = self.output_dir / f"{name}_{timestamp}.md"
        self.turn_count = 0

        self._write_header()
        log_print(f"[llm_tracer] initialized: {self.trace_file}")

    def _write_header(self) -> None:
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(self.trace_file, "w", encoding="utf-8") as f:
            f.write(f"# 🤖 LLM Trace — `{self.name}`\n\n")
            f.write(f"- **开始时间**: {now}\n")
            f.write(f"- **输出文件**: `{self.trace_file}`\n")
            f.write(f"- **工作目录**: `{Path.cwd()}`\n\n")
            f.write("---\n\n")

    # ── 核心 API ─────────────────────────────────────────

    def log_turn(self, request: Any, response: Any, note: str = "") -> None:
        """
        记录一次完整的请求-响应对。

        Args:
            request: 请求参数（dict 或任意对象）
            response: 响应对象（SDK 返回的原始对象）
            note: 可选备注，显示在 Turn 标题中
        """
        self.turn_count += 1
        note_str = f" — {note}" if note else ""

        req_json = _pretty_json(request)
        resp_json = _pretty_json(response)

        log_print(f"[llm_tracer] turn {self.turn_count} logged{note_str}")

        with open(self.trace_file, "a", encoding="utf-8") as f:
            f.write(f"## Turn {self.turn_count}{note_str}\n\n")

            # Request（可折叠）
            f.write("<details>\n")
            f.write(f"<summary><b>📤 Request</b></summary>\n\n")
            f.write(f"```json\n{req_json}\n```\n\n")
            f.write("</details>\n\n")

            # Response（可折叠）
            f.write("<details open>\n")
            f.write(f"<summary><b>📥 Response</b></summary>\n\n")
            f.write(f"```json\n{resp_json}\n```\n\n")
            f.write("</details>\n\n")

            f.write("---\n\n")

    def log_message(self, role: str, content: Any, note: str = "") -> None:
        """记录一条消息的流转（用于调试消息状态变化）。"""
        note_str = f" *({note})*" if note else ""
        content_json = _pretty_json(content)

        with open(self.trace_file, "a", encoding="utf-8") as f:
            f.write(f"### {role}{note_str}\n\n")
            f.write(f"```json\n{content_json}\n```\n\n")

    def log_text(self, text: str) -> None:
        """记录一段纯文本注释。"""
        with open(self.trace_file, "a", encoding="utf-8") as f:
            f.write(f"> {text}\n\n")


# ── 自动包装 helper ──────────────────────────────────────

def wrap_client(client: Any, tracer: LLMTracer) -> Any:
    """
    自动包装 LLM 客户端，无需修改 agent_loop 即可记录所有调用。

    支持 Anthropic 和 OpenAI 两种客户端。

    使用示例：
        client = OpenAI(...)
        client = wrap_client(client, tracer)
        # 此后所有 client.chat.completions.create() 调用自动被记录
    """
    # Anthropic SDK
    if hasattr(client, "messages") and hasattr(client.messages, "create"):
        _orig = client.messages.create

        def _traced_anthropic(*args, **kwargs):
            response = _orig(*args, **kwargs)
            # 构建一个可读的请求记录
            request = {k: v for k, v in kwargs.items() if k != "client"}
            tracer.log_turn(request=request, response=response, note="Anthropic")
            log_print(f"Anthropic response: {response}")
            return response

        client.messages.create = _traced_anthropic
        log_print("[llm_tracer] wrapped Anthropic client")
        return client

    # OpenAI SDK
    if hasattr(client, "chat") and hasattr(client.chat.completions, "create"):
        _orig = client.chat.completions.create

        def _traced_openai(*args, **kwargs):
            response = _orig(*args, **kwargs)
            request = {k: v for k, v in kwargs.items() if k != "client"}
            tracer.log_turn(request=request, response=response, note="OpenAI")
            return response

        client.chat.completions.create = _traced_openai
        log_print("[llm_tracer] wrapped OpenAI client")
        return client

    raise ValueError("Unknown client type. Expected Anthropic or OpenAI client.")
