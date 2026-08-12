#!/data/data/com.termux/files/usr/bin/sh
set -eu

if [ -z "${PREFIX:-}" ]; then
  echo "This build must run inside Termux." >&2
  exit 1
fi

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
BUILD_DIR="$SCRIPT_DIR/build"
CLASSES_DIR="$BUILD_DIR/classes"
DEX_DIR="$BUILD_DIR/dex"
GENERATED_DIR="$BUILD_DIR/generated"
UNSIGNED_APK="$BUILD_DIR/app-unsigned.apk"
ALIGNED_APK="$BUILD_DIR/app-aligned.apk"
SIGNED_APK="$BUILD_DIR/app-debug.apk"
KEYSTORE_DIR="$HOME/.nexus/android"
KEYSTORE="$KEYSTORE_DIR/debug.keystore"
APP_PACKAGE="__PACKAGE__"
APP_ACTIVITY="$APP_PACKAGE/.MainActivity"

find_android_jar() {
  for candidate in \
    "${NEXUS_ANDROID_JAR:-}" \
    "$HOME/.nexus/android-sdk/platforms/android-34/android.jar" \
    "${ANDROID_HOME:-}/platforms/android-34/android.jar" \
    "${PREFIX}/share/aapt/android.jar"; do
    if [ -n "$candidate" ] && [ -f "$candidate" ]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}

for command_name in javac jar keytool aapt d8 apksigner; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "Missing $command_name. Run nexus/termux/setup-android-build.sh" >&2
    exit 1
  fi
done

ANDROID_JAR=$(find_android_jar || true)
if [ -z "$ANDROID_JAR" ]; then
  echo "Missing Android framework (android.jar)." >&2
  echo "Run nexus/termux/setup-android-build.sh" >&2
  exit 1
fi

echo "Using Android framework: $ANDROID_JAR"
rm -rf "$BUILD_DIR"
mkdir -p "$CLASSES_DIR" "$DEX_DIR" "$GENERATED_DIR" "$KEYSTORE_DIR"

echo "[1/5] Packaging resources and generating R.java..."
aapt package \
  -f \
  -m \
  -J "$GENERATED_DIR" \
  -M "$SCRIPT_DIR/AndroidManifest.xml" \
  -S "$SCRIPT_DIR/res" \
  -I "$ANDROID_JAR" \
  -F "$UNSIGNED_APK"

echo "[2/5] Compiling Java..."
find "$SCRIPT_DIR/src" "$GENERATED_DIR" -name '*.java' -exec javac \
  -source 8 \
  -target 8 \
  -bootclasspath "$ANDROID_JAR" \
  -d "$CLASSES_DIR" \
  {} +

echo "[3/5] Creating classes.dex..."
jar cf "$BUILD_DIR/classes.jar" -C "$CLASSES_DIR" .
d8 \
  --lib "$ANDROID_JAR" \
  --min-api 23 \
  --output "$DEX_DIR" \
  "$BUILD_DIR/classes.jar"

echo "[4/5] Adding bytecode, aligning, and signing..."
UNSIGNED_ABS=$(CDPATH= cd -- "$(dirname -- "$UNSIGNED_APK")" && pwd)/$(basename -- "$UNSIGNED_APK")
(
  cd "$DEX_DIR"
  aapt add "$UNSIGNED_ABS" classes.dex >/dev/null
)

if command -v zipalign >/dev/null 2>&1; then
  zipalign -f 4 "$UNSIGNED_APK" "$ALIGNED_APK"
else
  cp "$UNSIGNED_APK" "$ALIGNED_APK"
fi

if [ ! -f "$KEYSTORE" ]; then
  keytool -genkeypair \
    -keystore "$KEYSTORE" \
    -storepass android \
    -keypass android \
    -alias androiddebugkey \
    -keyalg RSA \
    -keysize 2048 \
    -validity 10000 \
    -dname "CN=Android Debug,O=Nexus,C=US" \
    -noprompt >/dev/null 2>&1
fi

apksigner sign \
  --ks "$KEYSTORE" \
  --ks-pass pass:android \
  --key-pass pass:android \
  --out "$SIGNED_APK" \
  "$ALIGNED_APK"

echo "[5/5] Verifying APK..."
apksigner verify --verbose "$SIGNED_APK"
echo
echo "PHONE_BUILD_OK"
echo "APK: $SIGNED_APK"

if [ "${1:-}" = "--deploy" ]; then
  if ! command -v adb >/dev/null 2>&1; then
    echo "Missing adb. Run nexus/termux/setup-android-build.sh" >&2
    exit 1
  fi
  if [ "$(adb get-state 2>/dev/null || true)" != "device" ]; then
    echo "No paired Android debugging device is connected." >&2
    echo "Reconnect with nexus/termux/connect-adb.sh" >&2
    exit 1
  fi
  echo "Installing updated APK through on-phone ADB..."
  adb install -r -t "$SIGNED_APK"
  echo "Relaunching $APP_PACKAGE..."
  adb shell am force-stop "$APP_PACKAGE"
  adb shell am start -W -n "$APP_ACTIVITY"
  echo "PHONE_DEPLOY_OK"
elif [ "${1:-}" = "--install" ]; then
  TERMUX_PROPERTIES="$HOME/.termux/termux.properties"
  if ! grep -Eq '^[[:space:]]*allow-external-apps[[:space:]]*=[[:space:]]*true[[:space:]]*$' "$TERMUX_PROPERTIES" 2>/dev/null; then
    echo "Enable allow-external-apps in $TERMUX_PROPERTIES, reload settings, and retry." >&2
    exit 1
  fi
  termux-open \
    --view \
    --content-type application/vnd.android.package-archive \
    "$SIGNED_APK"
fi
