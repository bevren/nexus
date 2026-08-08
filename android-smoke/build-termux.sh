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
UNSIGNED_APK="$BUILD_DIR/nexus-phone-build-unsigned.apk"
ALIGNED_APK="$BUILD_DIR/nexus-phone-build-aligned.apk"
SIGNED_APK="$BUILD_DIR/nexus-phone-build.apk"
KEYSTORE_DIR="$HOME/.nexus/android"
KEYSTORE="$KEYSTORE_DIR/debug.keystore"

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
    echo "Missing $command_name. Run: sh termux/setup-android-build.sh" >&2
    exit 1
  fi
done

ANDROID_JAR=$(find_android_jar || true)
if [ -z "$ANDROID_JAR" ]; then
  echo "Missing Android framework (android.jar)." >&2
  echo "Run: sh termux/setup-android-build.sh" >&2
  exit 1
fi

echo "Using Android framework: $ANDROID_JAR"

rm -rf "$BUILD_DIR"
mkdir -p "$CLASSES_DIR" "$DEX_DIR" "$KEYSTORE_DIR"

echo "[1/5] Compiling Java..."
javac \
  -source 8 \
  -target 8 \
  -bootclasspath "$ANDROID_JAR" \
  -d "$CLASSES_DIR" \
  "$SCRIPT_DIR/src/dev/nexus/smoke/MainActivity.java"

echo "[2/5] Creating classes.dex..."
jar cf "$BUILD_DIR/classes.jar" -C "$CLASSES_DIR" .
d8 \
  --lib "$ANDROID_JAR" \
  --min-api 23 \
  --output "$DEX_DIR" \
  "$BUILD_DIR/classes.jar"

echo "[3/5] Packaging resources and manifest..."
aapt package \
  -f \
  -M "$SCRIPT_DIR/AndroidManifest.xml" \
  -I "$ANDROID_JAR" \
  -F "$UNSIGNED_APK"

UNSIGNED_ABS=$(CDPATH= cd -- "$(dirname -- "$UNSIGNED_APK")" && pwd)/$(basename -- "$UNSIGNED_APK")
(
  cd "$DEX_DIR"
  aapt add "$UNSIGNED_ABS" classes.dex >/dev/null
)

echo "[4/5] Aligning and signing APK..."
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

if [ "${1:-}" = "--install" ]; then
  echo "Opening Android package installer..."
  termux-open --view "$SIGNED_APK"
fi
