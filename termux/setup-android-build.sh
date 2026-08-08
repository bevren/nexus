#!/data/data/com.termux/files/usr/bin/sh
set -eu

if [ -z "${PREFIX:-}" ] || [ ! -x "${PREFIX}/bin/pkg" ]; then
  echo "This setup script must be run inside Termux." >&2
  exit 1
fi

echo "Installing the on-phone Android build toolchain..."
pkg install -y openjdk-21 aapt d8 apksigner

missing=""
for command_name in java javac jar keytool aapt d8 apksigner; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    missing="$missing $command_name"
  fi
done

if [ -n "$missing" ]; then
  echo "Missing required commands:$missing" >&2
  exit 1
fi

ANDROID_JAR="${PREFIX}/share/aapt/android.jar"
if [ ! -f "$ANDROID_JAR" ]; then
  echo "Android framework jar was not installed at: $ANDROID_JAR" >&2
  exit 1
fi

echo "Android build toolchain ready."
echo "Framework: $ANDROID_JAR"
echo "Build the smoke app with: sh android-smoke/build-termux.sh --install"
