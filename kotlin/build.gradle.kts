plugins {
    kotlin("jvm") version "2.2.0"
    application
}

group = "ai.agent.harness"
version = "1.0"

repositories {
    mavenCentral()
}

dependencies {
    // Koog — JetBrains Kotlin AI Agent framework
    implementation("ai.koog:koog-agents:1.0.0")

    // Kotlin coroutines (Koog uses suspend functions)
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-core:1.9.0")

    // dotenv for loading .env files
    implementation("io.github.cdimascio:dotenv-java:3.0.0")

    // SLF4J simple provider (消除 "No SLF4J providers were found" 警告)
    implementation("org.slf4j:slf4j-simple:2.0.16")
}

kotlin {
    jvmToolchain(17)
}

// Default main class (s01)
application {
    mainClass.set("s01_agent_loop.CodeKt")
}

// ── Per-chapter run tasks ────────────────────────────────
tasks.register<JavaExec>("runS01") {
    group = "application"
    description = "Run s01: Agent Loop"
    classpath = sourceSets.main.get().runtimeClasspath
    mainClass.set("s01_agent_loop.CodeKt")
}

tasks.register<JavaExec>("runS02") {
    group = "application"
    description = "Run s02: Tool Use (placeholder)"
    classpath = sourceSets.main.get().runtimeClasspath
    mainClass.set("s02_tool_use.CodeKt")
}
