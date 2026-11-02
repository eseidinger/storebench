plugins {
    kotlin("jvm") version "2.4.21"
    application
}

repositories {
    mavenCentral()
}

dependencies {
    implementation("org.postgresql:postgresql:42.7.14")
    implementation("org.opensearch.client:opensearch-java:3.10.0")
    runtimeOnly("org.slf4j:slf4j-nop:1.7.36")
    implementation("com.fasterxml.jackson.core:jackson-databind:2.20.0")
}

application {
    mainClass.set("SearchKt")
}

kotlin {
    compilerOptions {
        jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17)
    }
}

java {
    sourceCompatibility = JavaVersion.VERSION_17
    targetCompatibility = JavaVersion.VERSION_17
}
