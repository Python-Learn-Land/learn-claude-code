# S01-S06 学习笔记与问答整理

> 学习周期：2025/06/02
> 学习者：通过 OpenAI SDK 实现 AI Agent 教程
> 核心产出：`llm_tracer.py` 模块 + s01-s06 全部 `code_openai.py`

---

## 学习概览

### 完成的工作

| 章节 | Anthropic (`code.py`) | OpenAI (`code_openai.py`) | 关键新增 |
|------|----------------------|---------------------------|----------|
| s01 Agent Loop | ✅ tracer | ✅ tracer | SDK 迁移 5 处差异 |
| s02 Tool Use | ✅ tracer | ✅ tracer | 多工具 + 分发映射 |
| s03 Permission | ✅ tracer + 中文 | ✅ tracer + 中文 | 三层权限门控 |
| s04 Hooks | ✅ tracer | ✅ tracer + 中文 | Hook 注册表 |
| s05 TodoWrite | ✅ tracer | ✅ tracer + 中文 | 任务规划 + Nag 提醒 |
| s06 Subagent | ✅ tracer | ✅ tracer + 中文 | 子代理 + 上下文隔离 |

### 新增模块

- **`llm_tracer.py`**：通用 LLM 调用追踪器，输出 Markdown 格式 trace 文件，同时支持 Anthropic 和 OpenAI SDK。
- **`.traces/`**：按运行时间命名的 Markdown trace 文件，含可折叠的请求/响应详情。

---

## 问答记录

### Q1: OpenAI SDK 代码应该如何组织？

**问题背景**：教程原代码使用 Anthropic SDK，希望为每个章节添加 OpenAI SDK 实现。
**讨论要点**：
- 分析了 4 种方案：同文件适配层、同目录 `code_openai.py`、顶层镜像目录、分支替换。
- **推荐方案**：每个章节目录下新增 `code_openai.py`，与 `code.py` 并排对比。
- 理由：直观对比、零侵入现有文件、Web 提取不受影响、独立运行。

**决策**：采用方案 B（同目录 `code_openai.py`）。

---

### Q2: 如何将 LLM 对话详情保存到文件中？

**问题背景**：在控制台运行时代码，无法方便地查看大模型返回的详细数据。
**需求**：
1. 保存完整的请求/响应详情
2. 方便阅读和查看的格式
3. 项目代码改动尽量少

**解决方案**：
- 创建通用模块 `llm_tracer.py`，输出 Markdown 格式（含可折叠 JSON 代码块）。
- 提供 `wrap_client()` 自动包装 SDK 客户端，**agent_loop 一行不改**即可启用。
- 每个章节只需 5 行代码：导入 tracer + 初始化 + 包装 client。

**技术细节**：
- `_serialize()` 自动处理 Pydantic v1/v2、dataclass、嵌套结构。
- `wrap_client()` 通过 monkey-patch 替换 `create` 方法，自动记录每次调用。
- 输出路径：`.traces/sXX_name_YYYYMMDD_HHMMSS.md`。

---

### Q3: s05 TodoWrite 的 todo 实现机制是什么？

**问题**：todo 的实现是依靠大模型能力来编排和更新么？有用到代码逻辑去记录进展么？

**回答**：**混合架构** — 大模型负责智能决策，代码负责状态管理和监督。

| 责任方 | 具体工作 |
|--------|---------|
| **大模型** (智能决策) | SYSTEM 提示词引导 LLM 主动调用 `todo_write`；决定任务分解为几步、何时更新状态 |
| **代码** (状态管理) | `CURRENT_TODOS` 全局变量存储当前列表；`rounds_since_todo` 计数器追踪更新频率 |
| **代码** (监督提醒) | 当 `>= 3` 轮未更新时，自动注入 `<reminder>Update your todos.</reminder>` |

**一句话总结**：大模型是"项目经理"（决定做什么），代码是"进度看板"（记录状态、倒计时提醒）。

---

### Q4: Subagent 的核心和主 Agent 有什么区别？

**问题**：看上去 agent 的核心就是和大模型做网络请求、解析结果。那么 subagent 其实也是一样，上下文是不同的是吗？

**回答**：**完全正确**。Subagent 本质上就是**同一个 agent_loop**，区别只有三处：

| | 主 Agent | Subagent |
|---|---|---|
| **上下文** | `messages` 包含完整对话历史 | `messages` 只有任务描述（全新） |
| **工具集** | 有 `task` 工具（可再 spawn） | 无 `task` 工具（防止递归） |
| **结果处理** | 继续对话 | 只返回最终文本，中间历史全部丢弃 |

**关键设计**：上下文隔离 — 子任务的中间探索不混入主对话，节省 Token，聚焦任务。

---

### Q5: Subagent 是无限循环吗？

**问题**：看上去 subagent 不是一个无限的 loop 是么，我看教程中限制了最多 30 步。

**回答**：
- 主 Agent 用 `while True`（用户在旁，可随时打断）。
- Subagent 用 `for _ in range(30)`（无人值守，必须自带刹车）。
- **30 轮安全限制**防止：无限循环、API 费用爆炸、递归雪崩。
- 30 轮耗尽后有 fallback：回溯找最后的 assistant 文本，实在不行返回兜底消息。

---

### Q6: Anthropic `stop_reason != 