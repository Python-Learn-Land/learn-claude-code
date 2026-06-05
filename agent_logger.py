#!/usr/bin/env python3
"""
agent_logger.py — 轻量级 Agent 控制台日志记录器

同时输出到控制台和日志文件，自动去除 ANSI 颜色代码。
线程安全，适合多线程场景（如后台任务章节）。

使用方式（改动最少）：

    from agent_logger import setup_logger, log_print

    setup_logger(name="s13")          # ← 只加这一行，初始化日志文件
    log_print("hello")                # ← 替换 print，同时写文件

或者获取 logger 实例手动管理：

    from agent_logger import AgentLogger

    logger = AgentLogger(name="s13")
    logger.log_print("hello")
    logger.close()
"""

import re
import threading
from pathlib import Path
from datetime import datetime


class AgentLogger:
    """同时输出到控制台和文件的日志记录器。"""

    _ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

    def __init__(self, name: str = "agent", output_dir: str = ".logs"):
        self.name = name
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_file = self.output_dir / f"{name}_{timestamp}.log"
        self._lock = threading.Lock()
        self._fh = None

    def _open(self):
        if self._fh is None:
            self._fh = open(self.log_file, "a", encoding="utf-8")
        return self._fh

    def log_print(self, text: str = "", end: str = "\n") -> None:
        """Append to log file only (ANSI stripped)."""
        with self._lock:
            fh = self._open()
            clean = self._ANSI_RE.sub("", text)
            fh.write(clean + end)
            fh.flush()

    def close(self) -> None:
        if self._fh:
            self._fh.close()
            self._fh = None


# ── 全局默认 logger 和快捷函数 ──────────────────────────────
_default_logger: AgentLogger | None = None


def setup_logger(name: str = "agent", output_dir: str = ".logs") -> AgentLogger:
    """初始化全局默认 logger。"""
    global _default_logger
    _default_logger = AgentLogger(name, output_dir)
    return _default_logger


def log_print(text: str = "", end: str = "\n") -> None:
    """Append to log file only. Silently does nothing if logger not initialized."""
    if _default_logger is None:
        return
    _default_logger.log_print(text, end=end)
