#!/data/data/com.termux/files/usr/bin/sh
set -eu

if [ -z "${PREFIX:-}" ] || ! command -v adb >/dev/null 2>&1; then
  echo "Run this inside Termux after: sh termux/setup-android-build.sh" >&2
  exit 1
fi

if [ "$(adb get-state 2>/dev/null || true)" = "device" ]; then
  echo "ADB is already connected."
  adb devices
  exit 0
fi

if [ "$#" -eq 3 ]; then
  PAIR_ADDRESS="$1"
  PAIR_CODE="$2"
  CONNECT_ADDRESS="$3"
  adb pair "$PAIR_ADDRESS" "$PAIR_CODE"
  adb connect "$CONNECT_ADDRESS"
elif [ "$#" -eq 1 ]; then
  adb connect "$1"
else
  echo "On the phone, open Settings > Developer options > Wireless debugging."
  echo "Choose 'Pair device with pairing code', then run:"
  echo
  echo "  sh termux/connect-adb.sh IP:PAIR_PORT PAIR_CODE IP:DEBUG_PORT"
  echo
  echo "PAIR_PORT is shown in the pairing dialog. DEBUG_PORT is shown on the"
  echo "main Wireless debugging screen; Android normally uses different ports."
  echo "Use the displayed phone IP, or 127.0.0.1 when loopback works on the device."
  exit 2
fi

if [ "$(adb get-state 2>/dev/null || true)" != "device" ]; then
  echo "ADB pairing or connection did not complete." >&2
  exit 1
fi

echo "PHONE_ADB_OK"
adb devices
echo "Automatic app updates are ready:"
echo "  sh android-smoke/build-termux.sh --deploy"
