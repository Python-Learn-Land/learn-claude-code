package llm_tracer

import kotlinx.serialization.json.Json
import kotlinx.serialization.serializer
import java.io.File
import java.time.LocalDateTime
import java.time.format.DateTimeFormatter
import kotlin.reflect.full.createType

/**
 * LLMTracer — Kotlin 版 LLM 调用追踪器
 *
 * 以 Markdown 格式记录每一次 LLM 请求-响应对，包含可折叠的 JSON 详情，
 * 方便人类阅读和调试。
 *
 * 使用方式：
 *
 *     val tracer = LLMTracer(name = "s01", outputDir = ".traces")
 *     tracer.logTurn(request = requestMap, response = assistantMessage, note = "Koog")
 *
 * 输出格式：
 *     .traces/
 *         s01_20250604_143052.md
 *         s01_20250604_143110.md
 *         ...
 */
class LLMTracer(
    private val name: String = "agent",
    private val outputDir: String = ".traces"
) {
    val traceFile: File
    private var turnCount = 0

    // kotlinx.serialization JSON 配置（支持 Koog 的 @Serializable 类型）
    private val json = Json {
        prettyPrint = true
        ignoreUnknownKeys = true
        isLenient = true
    }

    init {
        val dir = File(outputDir)
        dir.mkdirs()
        val timestamp = LocalDateTime.now()
            .format(DateTimeFormatter.ofPattern("yyyyMMdd_HHmmss"))
        traceFile = File(dir, "${name}_$timestamp.md")
        writeHeader()
    }

    private fun writeHeader() {
        val now = LocalDateTime.now()
            .format(DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss"))
        traceFile.writeText(
            buildString {
                appendLine("# 🤖 LLM Trace — `$name`")
                appendLine()
                appendLine("- **开始时间**: $now")
                appendLine("- **输出文件**: `${traceFile.absolutePath}`")
                appendLine("- **工作目录**: `${File("").absolutePath}`")
                appendLine()
                appendLine("---")
                appendLine()
            }
        )
    }

    /**
     * 记录一次完整的请求-响应对。
     *
     * @param request 请求参数（任意对象，支持 @Serializable 类型）
     * @param response 响应对象（任意对象，支持 @Serializable 类型）
     * @param note 可选备注，显示在 Turn 标题中
     */
    fun logTurn(request: Any, response: Any, note: String = "") {
        turnCount++
        val noteStr = if (note.isNotEmpty()) " — $note" else ""

        val reqJson = serializeToJson(request)
        val respJson = serializeToJson(response)

        traceFile.appendText(
            buildString {
                appendLine("## Turn $turnCount$noteStr")
                appendLine()
                appendLine("<details>")
                appendLine("<summary><b>📤 Request</b></summary>")
                appendLine()
                appendLine("```json")
                appendLine(reqJson)
                appendLine("```")
                appendLine()
                appendLine("</details>")
                appendLine()
                appendLine("<details open>")
                appendLine("<summary><b>📥 Response</b></summary>")
                appendLine()
                appendLine("```json")
                appendLine(respJson)
                appendLine("```")
                appendLine()
                appendLine("</details>")
                appendLine()
                appendLine("---")
                appendLine()
            }
        )
    }

    /**
     * 记录一条消息的流转（用于调试消息状态变化）。
     */
    fun logMessage(role: String, content: Any, note: String = "") {
        val noteStr = if (note.isNotEmpty()) " *($note)*" else ""
        val contentJson = serializeToJson(content)

        traceFile.appendText(
            buildString {
                appendLine("### $role$noteStr")
                appendLine()
                appendLine("```json")
                appendLine(contentJson)
                appendLine("```")
                appendLine()
            }
        )
    }

    /**
     * 记录一段纯文本注释。
     */
    fun logText(text: String) {
        traceFile.appendText(
            buildString {
                text.lineSequence().forEach { line ->
                    appendLine("> $line")
                }
                appendLine()
            }
        )
    }

    // ── 序列化 helpers ───────────────────────────────────────

    /**
     * 将任意对象序列化为 JSON 字符串。
     *
     * - String: 直接返回原字符串
     * - @Serializable 类型: 使用 kotlinx.serialization 序列化
     * - 其他类型: 退化为 toString()
     */
    @Suppress("UNCHECKED_CAST")
    private fun serializeToJson(obj: Any): String = when (obj) {
        is String -> obj
        else -> runCatching {
            val kType = obj::class.createType()
            val serializer = json.serializersModule.serializer(kType)
            json.encodeToString(serializer, obj)
        }.getOrDefault(obj.toString())
    }
}
