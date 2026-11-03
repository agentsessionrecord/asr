import org.jetbrains.intellij.platform.gradle.TestFrameworkType

plugins {
    kotlin("jvm") version "2.2.21"
    id("org.jetbrains.intellij.platform") version "2.10.5"
}
group = "org.agentsessionrecord"
version = "0.1.0"
layout.buildDirectory.set(file("../../target/jetbrains"))
repositories {
    mavenCentral()
    intellijPlatform { defaultRepositories() }
}
dependencies {
    intellijPlatform {
        intellijIdeaCommunity("2025.1.4")
        testFramework(TestFrameworkType.Platform)
    }
    testImplementation("junit:junit:4.13.2")
}
kotlin { jvmToolchain(21) }
intellijPlatform {
    pluginConfiguration {
        name = "ASR Sessions"
        ideaVersion { sinceBuild = "251" }
    }
    buildSearchableOptions = false
}
tasks.test {
    systemProperty("java.awt.headless", "true")
    systemProperty("asr.test.root", rootDir.parentFile.parentFile.absolutePath)
    systemProperty("asr.test.cli", providers.environmentVariable("ASR_EDITOR_CLI").getOrElse(rootDir.resolve("../../target/debug/asr").absolutePath))
    systemProperty("asr.test.fixture", layout.buildDirectory.dir("synthetic").get().asFile.absolutePath)
    maxHeapSize = "2g"
}
val syntheticFixture by tasks.registering(Exec::class) {
    commandLine("node", "../vscode/test/fixture.mjs", layout.buildDirectory.dir("synthetic").get().asFile.absolutePath)
}
val bundleViewer by tasks.registering(Exec::class) {
    commandLine("node", "../vscode/scripts/bundle-viewer.mjs", layout.buildDirectory.file("generated-resources/viewer.html").get().asFile.absolutePath)
}
sourceSets.main { resources.srcDir(layout.buildDirectory.dir("generated-resources")) }
tasks.processResources { dependsOn(bundleViewer) }
tasks.test { dependsOn(syntheticFixture) }

val cleanSyntheticFixture by tasks.registering(Delete::class) { delete(layout.buildDirectory.dir("synthetic")) }
tasks.test { finalizedBy(cleanSyntheticFixture) }
