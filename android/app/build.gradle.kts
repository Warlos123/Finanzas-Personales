import java.util.Properties
import org.jetbrains.kotlin.gradle.dsl.JvmTarget

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

// Llave de firma fuera del código: android/firma.properties (storeFile, storePassword, keyAlias,
// keyPassword). Firmar siempre con la misma llave permite instalar actualizaciones encima.
val archivoFirma = rootProject.file("firma.properties")
val firma = Properties()
if (archivoFirma.exists()) {
    archivoFirma.inputStream().use { firma.load(it) }
}

android {
    namespace = "cr.finanzas.sms"
    compileSdk = 35

    defaultConfig {
        applicationId = "cr.finanzas.sms"
        minSdk = 31
        targetSdk = 35
        versionCode = 1
        versionName = "0.1.0"
    }

    signingConfigs {
        create("finanzas") {
            if (archivoFirma.exists()) {
                storeFile = rootProject.file(firma.getProperty("storeFile"))
                storePassword = firma.getProperty("storePassword")
                keyAlias = firma.getProperty("keyAlias")
                keyPassword = firma.getProperty("keyPassword")
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            if (archivoFirma.exists()) {
                signingConfig = signingConfigs.getByName("finanzas")
            }
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

kotlin {
    compilerOptions {
        jvmTarget.set(JvmTarget.JVM_17)
    }
}

dependencies {
    implementation("androidx.documentfile:documentfile:1.0.1")
    implementation("androidx.work:work-runtime:2.10.2")
    testImplementation("junit:junit:4.13.2")
    // org.json real para las pruebas en la JVM (el de android.jar son stubs).
    testImplementation("org.json:json:20240303")
}
