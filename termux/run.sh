#!/data/data/com.termux/files/usr/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIR=$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)

if ! command -v node >/dev/null 2>&1; then
  echo "Node.js is missing. Run: sh termux/setup.sh" >&2
  exit 1
fi

if ! command -v python >/dev/null 2>&1; then
  echo "Python is missing. Run: sh termux/setup.sh" >&2
  exit 1
fi

cd "$PROJECT_DIR"

# Touch gestures in phone terminals can produce mouse escape sequences. Keep
# terminal mouse tracking off unless the user explicitly opts in.
export TUI_ENABLE_MOUSE="${TUI_ENABLE_MOUSE:-0}"
export PYTHONUTF8="${PYTHONUTF8:-1}"
export TERM="${TERM:-xterm-256color}"
export COLORTERM="${COLORTERM:-truecolor}"

if [ "${NEXUS_WAKE_LOCK:-0}" = "1" ] && command -v termux-wake-lock >/dev/null 2>&1; then
  termux-wake-lock
  trap 'termux-wake-unlock >/dev/null 2>&1 || true' EXIT INT TERM
  node index.js "$@"
else
  exec node index.js "$@"
fi
