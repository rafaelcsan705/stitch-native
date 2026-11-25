// Compile-only check for generated Compose code (desktop target, no Android SDK needed).
// The Android `@Preview` annotation is stubbed in src/main/kotlin/androidx/compose/ui/tooling/preview/Preview.kt.
plugins {
    kotlin("jvm") version "2.0.21"
    id("org.jetbrains.compose") version "1.7.1"
    id("org.jetbrains.kotlin.plugin.compose") version "2.0.21"
}
repositories { mavenCentral(); google() }
dependencies {
    implementation(compose.desktop.currentOs)
    implementation(compose.material3)
    implementation(compose.materialIconsExtended)
    implementation("io.coil-kt.coil3:coil-compose:3.0.4")
    implementation("io.coil-kt.coil3:coil-network-ktor3:3.0.4")
}
