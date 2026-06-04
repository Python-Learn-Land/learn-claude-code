# Kotlin Agent Harness Track (Koog)

本目录使用 [Koog](https://www.jetbrains.com/koog/)（JetBrains 官方 Kotlin AI Agent 框架）实现与 Python 主轨道相同的 20 个教学章节。

## 快速开始

```bash
cd kotlin

# 首次构建
./gradlew build

# 运行 s01: Agent Loop
./gradlew runS01

# 或指定 main class 运行任意章节
./gradlew run -DmainClass=s01_agent_loop.CodeKt
```

## 环境配置

在 `kotlin/` 目录下创建 `.env` 文件（程序会自动读取，同时兼容系统环境变量）：

```bash
cd kotlin
cp src/main/resources/.env.example .env
# 编辑 .env，填入 ANTHROPIC_API_KEY 和 MODEL_ID
```

如果没有 `.env` 文件，程序会回退到读取系统环境变量 `ANTHROPIC_API_KEY` 和 `MODEL_ID`。

## 章节对照

| 章节 | Python | Kotlin (Koog) |
|------|--------|---------------|
| s01 Agent Loop | `s01_agent_loop/code.py` | `s01_agent_loop/Code.kt` |

## 与 Python 版的核心差异

- **循环控制**: Koog `functionalStrategy` 显式写出 `while (toolCalls.isNotEmpty())`
- **工具定义**: `@Tool` + `@LLMDescription` 注解自动生成 schema
- **消息类型**: `MessagePart.Text` / `MessagePart.Tool.Call` 强类型
- **Shell 执行**: `ProcessBuilder` 替代 `subprocess.run()`
- **并发**: Kotlin 协程 `suspend` 替代 Python `asyncio`
