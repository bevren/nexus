#!/data/data/com.termux/files/usr/bin/sh
set -eu

if [ -z "${PREFIX:-}" ] || [ ! -x "${PREFIX}/bin/pkg" ]; then
  echo "This setup script must be run inside Termux." >&2
  exit 1
fi

echo "Installing the on-phone Android build toolchain..."
pkg install -y openjdk-21 aapt aapt2 d8 apksigner curl unzip

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

SDK_ROOT="${NEXUS_ANDROID_SDK_ROOT:-$HOME/.nexus/android-sdk}"
PLATFORM_DIR="$SDK_ROOT/platforms/android-34"
ANDROID_JAR="$PLATFORM_DIR/android.jar"
PLATFORM_URL="https://dl.google.com/android/repository/platform-34-ext7_r03.zip"
PLATFORM_SHA1="1f2e9478d6a7601425ceaa553311dc43191f103d"

if [ ! -f "$ANDROID_JAR" ]; then
  DOWNLOAD_DIR="${TMPDIR:-${PREFIX}/tmp}"
  PLATFORM_ZIP="$DOWNLOAD_DIR/nexus-platform-34.zip"
  mkdir -p "$DOWNLOAD_DIR" "$SDK_ROOT/platforms"

  echo "Downloading Android SDK Platform 34 (about 63 MB)..."
  curl -fL --retry 3 --progress-bar "$PLATFORM_URL" -o "$PLATFORM_ZIP"
  if ! echo "$PLATFORM_SHA1  $PLATFORM_ZIP" | sha1sum -c -; then
    rm -f "$PLATFORM_ZIP"
    echo "Android platform checksum verification failed." >&2
    exit 1
  fi

  rm -rf "$PLATFORM_DIR"
  unzip -q "$PLATFORM_ZIP" -d "$SDK_ROOT/platforms"
  rm -f "$PLATFORM_ZIP"
fi

if [ ! -f "$ANDROID_JAR" ]; then
  echo "Android framework jar was not created at: $ANDROID_JAR" >&2
  exit 1
fi

echo "Android build toolchain ready."
echo "Framework: $ANDROID_JAR"
echo "Build the smoke app with: sh android-smoke/build-termux.sh --install"
