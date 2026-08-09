---
name: create-android-app
description: Create complete phone-native Android application projects with Java, XML resources, a manifest, and Termux build/deploy scripts. Use when a user asks to make, create, scaffold, start, prototype, or build an Android app or Android project, including requests such as "make me an Android app", "build a phone app", or "create an APK".
---

# Create Android App

Create a standalone, zero-dependency Android project that builds directly on
the phone with AAPT, javac, D8, and apksigner.

## Workflow

1. Derive a short kebab-case folder name and an app name from the request.
2. Default the package to `dev.nexus.<slug_without_hyphens>`. Honor a package
   name or output directory supplied by the user.
3. Refuse to overwrite a non-empty directory. Inspect an existing Android
   project and edit it in place instead of scaffolding over it.
4. Run the bundled generator; do not recreate its boilerplate manually:

   ```text
   python <skill-path>/scripts/create_android_project.py --output <folder> --name "<App Name>" [--package <package.name>]
   ```

   Use the `path` returned by `get_skill("create-android-app")` as
   `<skill-path>`.
5. Implement the requested UI and behavior in the generated project. Prefer
   Android platform APIs so the phone-native build remains dependency-free.
6. Validate with `android_build(project_path="<folder>", deploy=False)`.
7. When running in Termux with paired ADB and the user wants to see the result,
   call `android_build(project_path="<folder>", deploy=True)`. Report
   `PHONE_DEPLOY_OK` only when the tool returns success.

## Generated project

- `AndroidManifest.xml`: package, SDK limits, app, and activity declarations
- `res/layout/activity_main.xml`: primary screen layout
- `res/values/strings.xml`: user-visible text
- `res/values/colors.xml`: palette
- `src/<package>/MainActivity.java`: behavior
- `build-termux.sh`: build, interactive install, and ADB deploy/relaunch

For another screen, add its Java class, layout resource, and manifest activity.
For permissions, declare them in the manifest and request dangerous permissions
at runtime on Android 6+.

## Guardrails

- Keep the signing key outside the project at `~/.nexus/android/debug.keystore`.
- Never claim an APK was installed or launched based only on a local build.
- Do not introduce Gradle, Kotlin, Compose, or external libraries unless the
  user explicitly requests them; the bundled phone toolchain does not resolve
  Maven dependencies.
- If the Android toolchain is missing, direct the user to
  `sh termux/setup-android-build.sh` from the simple-code-tui repository.
- If ADB is disconnected, build successfully and explain how to reconnect with
  `sh termux/connect-adb.sh`; retain `--install` as the interactive fallback.
