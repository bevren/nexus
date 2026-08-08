# Phone-local live Android project

This is an editable Android app that the TUI can build, update, and relaunch
entirely on the phone. It deliberately uses the small native toolchain instead
of Gradle: `AAPT -> javac -> D8 -> apksigner`.

From the `simple-code-tui` repository in Termux:

```sh
git pull --ff-only
sh termux/setup-android-build.sh
sh android-smoke/build-termux.sh --install
```

The setup downloads Google's Android SDK Platform 34 archive (about 63 MB),
verifies its published SHA-1 checksum, and stores it under
`$HOME/.nexus/android-sdk`. The Termux `aapt` package supplies the native ARM64
packaging binary but does not itself contain `android.jar`.

The build succeeds when the script prints `PHONE_BUILD_OK`. Android then asks
for permission to install the APK. Allow Termux as an installation source if
the system settings page appears.

Android also needs permission to read the APK through Termux. If the build
reports that file sharing is disabled, run:

```sh
mkdir -p "$HOME/.termux"
sed -i '/^[[:space:]]*allow-external-apps[[:space:]]*=/d' "$HOME/.termux/termux.properties"
echo 'allow-external-apps = true' >> "$HOME/.termux/termux.properties"
termux-reload-settings
sh android-smoke/build-termux.sh --install
```

The signed output is:

```text
android-smoke/build/nexus-phone-build.apk
```

## Automatic edit-build-run loop

Install the current toolchain, including on-phone ADB:

```sh
sh termux/setup-android-build.sh
```

Enable **Developer options > Wireless debugging**. Open **Pair device with
pairing code**, note its address and code, and also note the separate address
on the main Wireless debugging screen. Then pair once:

```sh
sh termux/connect-adb.sh IP:PAIR_PORT PAIR_CODE IP:DEBUG_PORT
```

After ADB reports `PHONE_ADB_OK`, one command rebuilds, reinstalls, and
relaunches the app:

```sh
sh android-smoke/build-termux.sh --deploy
```

The TUI agent has the equivalent tool:

```python
android_build(project_path="android-smoke", deploy=True)
```

Ask the agent to change the app and show it on screen. It can edit these files:

- `res/layout/activity_main.xml` for layout
- `res/values/strings.xml` for text
- `res/values/colors.xml` for colors
- `src/dev/nexus/smoke/MainActivity.java` for behavior

Wireless debugging may disconnect after a reboot or when Android disables the
setting. Run `sh termux/connect-adb.sh IP:DEBUG_PORT` to reconnect.
