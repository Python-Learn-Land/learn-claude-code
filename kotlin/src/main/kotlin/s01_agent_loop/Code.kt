package s01_agent_loop

import ai.koog.agents.core.agent.AIAgent
import ai.koog.agents.core.agent.functionalStrategy
import ai.koog.agents.core.tools.ToolRegistry
import ai.koog.agents.core.tools.annotations.LLMDescription
import ai.koog.agents.core.tools.annotations.Tool
import ai.koog.agents.core.tools.reflect.ToolSet
import ai.koog.prompt.executor.clients.anthropic.AnthropicClientSettings
import ai.koog.prompt.executor.clients.anthropic.AnthropicModels
import ai.koog.prompt.executor.model.PromptExecutor
import ai.koog.prompt.message.MessagePart
import io.github.cdimascio.dotenv.Dotenv
import kotlinx.coroutines.runBlocking
import llm_tracer.LLMTracer
import java.io.File
import java.util.concurrent.TimeUnit

/**
 * s01: Agent Loop — Kotlin + Koog (JetBrains)
 *
 * The same core pattern as Python code.py:
 *
 *     while tool_calls exist:
 *         response = LLM(messages, tools)
 *         execute tools
 *         append results
 *
 * Koog differences:
 *   1. Executor: PromptExecutor.builder().anthropic(apiKey).build()
 *   2. Tool schema: @Tool + @LLMDescription annotations auto-generate JSON schema
 *   3. Message parts: MessagePart.Text / MessagePart.Tool.Call strong types
 *   4. Loop: functionalStrategy { requestLLM -> executeTools -> sendToolResults }
 *   5. Shell: ProcessBuilder instead of subprocess.run()
 */

// ── Tool definition: bash with auto-generated schema ───────
@LLMDescription("Shell command tools")
class BashToolSet : ToolSet {
    @Tool
    @LLMDescription("Run a shell command")
    fun bash(command: String): String {
        val dangerous = listOf("rm -rf /", "sudo", "shutdown", "reboot", "> /dev/")
        if (dangerous.any { it in command }) {
            return "Error: Dangerous command blocked"
        }
        return try {
            val process = ProcessBuilder("bash", "-c", command)
                .directory(File("."))
                .redirectErrorStream(true)
                .start()
            process.waitFor(120, TimeUnit.SECONDS)
            process.inputStream.bufferedReader().readText().take(50000)
                .ifEmpty { "(no output)" }
        } catch (e: Exception) {
            "Error: ${e.message}"
        }
    }
}


// ── The core pattern: a while loop that calls tools until the model stops ──
fun main() = runBlocking {
    // 加载 .env 文件（如果存在），同时允许 System.getenv() 覆盖
    val dotenv = Dotenv.configure()
        .directory(".")
        .ignoreIfMissing()
        .load()

    val apiKey = dotenv["ANTHROPIC_API_KEY"]
        ?: System.getenv("ANTHROPIC_API_KEY")
        ?: error("ANTHROPIC_API_KEY not set. Please create kotlin/.env or export the environment variable.")

    // 模型选择：从 .env / 环境变量读取 ID，在 AnthropicModels.models 中查找匹配项
    val model = (dotenv["MODEL_ID"] ?: System.getenv("MODEL_ID"))?.let { modelId ->
        AnthropicModels.models.find { it.id == modelId }
    } ?: AnthropicModels.Sonnet_4_6

    val toolRegistry = ToolRegistry {
        tool(BashToolSet()::bash)
    }

    // 初始化 tracer —— functionalStrategy 内手动记录 LLM 调用
    val tracer = LLMTracer(name = "s01_agent_loop", outputDir = ".traces")

    // Koog functionalStrategy: 显式控制 ReAct 循环
    val strategy = functionalStrategy<String, String>("s01AgentLoop") { input ->
        tracer.logText("User input: $input")

        // 第 1 轮：发送用户输入
        var response = requestLLM(input)
        tracer.logTurn(
            request = mapOf("input" to input),
            response = response,
            note = "Koog-initial"
        )

        // 检查是否有 tool_calls（对应 Python code.py 第 109 行）
        var toolCalls = response.parts.filterIsInstance<MessagePart.Tool.Call>()

        while (toolCalls.isNotEmpty()) {
            // 打印工具调用（对应 Python 的 print(f"\033[33m$ ...\033[0m")）
            for (call in toolCalls) {
                println("[33m$ ${call.tool} ${call.args}[0m")
            }

            // 执行工具（对应 Python code.py 第 114-123 行）
            val results = executeTools(toolCalls)
            tracer.logMessage(role = "tool", content = results, note = "execution")

            // 反馈结果给 LLM，获取下一轮（对应 Python code.py 第 126 行）
            response = sendToolResults(results)
            tracer.logTurn(
                request = mapOf("toolResults" to results),
                response = response,
                note = "Koog-followup"
            )

            // 再次检查（循环继续或结束）
            toolCalls = response.parts.filterIsInstance<MessagePart.Tool.Call>()
        }

        // 提取最终文本回复
        response.parts.filterIsInstance<MessagePart.Text>().joinToString("\n") { it.text }
    }

    val baseUrl = dotenv["ANTHROPIC_BASE_URL"] ?: System.getenv("ANTHROPIC_BASE_URL")

    val systemPrompt = "You are a coding agent at ${File("").absolutePath}. " +
        "Use bash to solve tasks. Act, don't explain."

    val executor = if (baseUrl != null) {
        PromptExecutor.builder()
            .anthropic(apiKey, AnthropicClientSettings(baseUrl = baseUrl))
            .build()
    } else {
        PromptExecutor.builder()
            .anthropic(apiKey)
            .build()
    }

    val agent = AIAgent.builder()
        .promptExecutor(executor)
        .llmModel(model)
        .systemPrompt(systemPrompt)
        .toolRegistry(toolRegistry)
        .functionalStrategy(strategy)
        .build()

    println("s01: Agent Loop (Kotlin + Koog)")
    println("Enter a query, or 'q' to quit.")
    println("📝 Trace 文件: ${tracer.traceFile}\n")

    while (true) {
        print("[36ms01(kt) >> [0m")
        val query = readlnOrNull()?.trim() ?: break
        if (query.lowercase() in setOf("q", "exit", "")) break

        val result = agent.run(query)
        println(result)
        println()
    }
}
