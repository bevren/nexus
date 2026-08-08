# Phone-local Android build smoke test

This app proves that the Android phone can compile Java, create DEX bytecode,
package resources, sign an APK, and open the Android installer without a PC.

From the `simple-code-tui` repository in Termux:

```sh
git pull --ff-only
sh termux/setup-android-build.sh
sh android-smoke/build-termux.sh --install
```

The build succeeds when the script prints `PHONE_BUILD_OK`. Android then asks
for permission to install the APK. Allow Termux as an installation source if
the system settings page appears.

The signed output is:

```text
android-smoke/build/nexus-phone-build.apk
```

This deliberately avoids Gradle. It validates the smallest useful native
pipeline first: `javac -> D8 -> AAPT -> apksigner`. Gradle and an agent-facing
`android_build` tool come after this passes on the target phone.
