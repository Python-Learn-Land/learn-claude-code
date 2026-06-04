# CLAUDE.md

本文件为 Claude Code (claude.ai/code) 提供该代码库的工作指南。

## 项目概述

这是一个 AI Agent  Harness 工程教学仓库，包含 20 个渐进式课程（`s01_agent_loop` 到 `s20_comprehensive`），每个课程围绕一个不变的 Agent 核心循环添加一种机制。每个课程都是一个独立的、可直接运行的 Python 脚本。

仓库存在**三条教程轨道**：
- **Python（主轨道）：** 根目录下的 `s01_*` 到 `s20_*` 文件夹。每个文件夹包含 `README.md`（中文原文）、`README.en.md`、`README.ja.md`、`code.py` 和 `images/`。
- **Kotlin（新增）：** `kotlin/` 目录，使用 JetBrains [Koog](https://www.jetbrains.com/koog/) 框架实现相同的 20 个章节。与 Python 轨道一一对应。
- **旧版（过渡中）：** `agents/`（12 个可运行的 Python 文件）、`docs/`（`en/`、`zh/`、`ja/` 下的 12 篇 Markdown 教程）和 `web/`（渲染旧版轨道）。这些内容保留给现有读者和 web 平台使用。

当前轨道的终点是 `s20_comprehensive/code.py`，它将所有机制整合到一个循环中。

## 常用命令

### Python 课程

仓库已配置虚拟环境，位于 `.venv/`。运行 Python 课程前请先激活它：

```bash
# macOS / Linux
source .venv/bin/activate

# Windows (PowerShell)
.venv\Scripts\Activate.ps1
```

之后安装依赖并运行课程：

```bash
# 安装依赖
pip install -r requirements.txt

# 配置 API 密钥
cp .env.example .env
# 编辑 .env：设置 ANTHROPIC_API_KEY 和 MODEL_ID

# 运行任意单个课程
python s01_agent_loop/code.py
python s20_comprehensive/code.py

# 运行所有测试
python -m pytest tests/ -q
```

### Kotlin 课程（Koog）

```bash
cd kotlin

# 首次构建（自动下载 Gradle wrapper）
./gradlew build

# 配置 API 密钥
cp src/main/resources/.env.example .env
# 编辑 .env：设置 ANTHROPIC_API_KEY 和 MODEL_ID

# 运行单个课程
./gradlew runS01
# 或指定 main class
./gradlew run -DmainClass=s01_agent_loop.CodeKt

# 运行全部测试
./gradlew test
```

Kotlin 轨道与 Python 主轨道一一对应：`kotlin/src/main/kotlin/s01_agent_loop/Code.kt` 对应 `s01_agent_loop/code.py`。

### Web 平台

```bash
cd web
npm install

# 开发服务器（同时运行内容提取）
npm run dev        # http://localhost:3000

# 内容提取（解析根目录 s01-s20 章节到 src/data/generated/）
npm run extract

# 生产构建
npm run build
```

Web 应用基于 Next.js 16 + App Router + TypeScript + Tailwind CSS v4。它渲染的是**旧版** `docs/` 轨道；当前 s01-s20 轨道通过 `scripts/extract-content.ts` 解析 `code.py` 文件并生成 `src/data/generated/versions.json` 和 `docs.json`。

## 架构

### 核心模式：一个循环，多种机制

每个课程共享相同的不变结构：

```python
def agent_loop(messages):
    while True:
        response = client.messages.create(model=MODEL, system=SYSTEM,
                                          messages=messages, tools=TOOLS)
        messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason != "tool_use":
            return
        results = [execute_tool(block) for block in response.content if block.type == "tool_use"]
        messages.append({"role": "user", "content": results})
```

循环本身在所有课程中保持不变。变化的是围绕它的 **Harness**：工具调度表、权限门控、钩子、待办计划、子 Agent 隔离、技能加载、上下文压缩、记忆、提示词组装、错误恢复、任务图、后台执行、定时调度、团队邮箱、工作树隔离和 MCP 桥接。

### 课程分层

课程按概念层组织（见 `web/src/lib/constants.ts`）：

- **工具与执行（s01-s04）：** 循环、调度、权限、钩子
- **规划与控制（s05-s07、s10-s11）：** 待办计划、子 Agent、技能、提示词组装、错误恢复
- **内存管理（s08-s09）：** 上下文压缩、持久记忆
- **并发与调度（s13-s14）：** 后台任务、定时调度器
- **多 Agent 平台（s12、s15-s20）：** 任务系统、团队、协议、自主 Agent、工作树、MCP

编辑某个课程时，参考 `s20_comprehensive/code.py` 了解该机制如何与其他所有机制整合。修复早期课程的 bug 时，请检查后续课程中是否存在相同的模式。

### 代码文件结构

每个 `code.py` 都是**独立脚本**，不是可导入的模块。它们：
- 在模块级别初始化 Anthropic 客户端（导入时执行）
- 全局定义 `SYSTEM`、`TOOLS` 和 `TOOL_HANDLERS`
- 在 `if __name__ == "__main__"` 中运行交互式 REPL

不要尝试将 `code.py` 文件作为模块导入——它们会在导入时产生副作用。

### Skills 目录

`skills/` 包含被 s07 使用的 Markdown 知识文件：
```
skills/
  agent-builder/SKILL.md
  code-review/SKILL.md
  mcp-builder/SKILL.md
  pdf/SKILL.md
```

每个 `SKILL.md` 可以包含 YAML 前置元数据。s07 脚本在启动时扫描此目录，将技能目录注入系统提示词，并通过 `load_skill(name)` 按需加载完整内容。

### Web 应用数据管道

`web/scripts/extract-content.ts` 是根目录章节与 Web UI 之间的桥梁：
1. 扫描根目录 `s##_*` 目录中的 `code.py`
2. 提取类、函数、工具名和代码行数
3. 解析 README 翻译并重写图片/资源路径
4. 将 `images/` 复制到 `public/course-assets/`
5. 输出 `src/data/generated/versions.json` 和 `docs.json`

此脚本通过 `predev`/`prebuild` 钩子，在 `npm run dev` 和 `npm run build` 时自动运行。

### 测试

测试是最小化的冒烟测试：
- `tests/test_agents_smoke.py` — 用 `py_compile` 验证所有 `agents/*.py` 文件能否编译
- `tests/test_s_full_background.py` — 使用模块模拟对 `agents/s_full.py` 中的 `BackgroundManager` 类进行单元测试

没有需要真实 LLM API 密钥的集成测试。

## 编辑规范

- 每个课程的 `code.py` 应始终保持可用 `python s##/code.py` 独立运行
- 添加新机制时遵循模式：循环本身保持不变；新机制注册到现有的调度/钩子/任务结构中
- 中文（`README.md`）是原文；`README.en.md` 和 `README.ja.md` 是翻译。修改叙事内容时，三个文件都需要更新
- SVG 图表位于每个章节的 `images/` 目录中，在 README 中使用相对路径引用（如 `images/diagram.svg`）
- Web 应用在提取过程中将这些路径重写为 `/course-assets/s##_chapter_name/diagram.svg`

## 环境要求

- Python 3.11+
- Node.js 20+
- 需要在 `.env`（或环境变量）中设置 `ANTHROPIC_API_KEY`
- 通过 `ANTHROPIC_BASE_URL` 支持 Anthropic 兼容的提供商（详见 `.env.example` 中的提供商列表）
