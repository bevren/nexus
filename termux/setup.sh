#!/data/data/com.termux/files/usr/bin/sh
set -eu

if [ -z "${PREFIX:-}" ] || [ ! -x "${PREFIX}/bin/pkg" ]; then
  echo "This setup script must be run inside Termux." >&2
  exit 1
fi

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIR=$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)

echo "Installing the phone-local runtime..."
pkg install -y nodejs-lts python git

echo "Installing TUI dependencies..."
cd "$PROJECT_DIR"
npm install --omit=dev

echo "Checking Node and Python..."
node --check index.js
python -c "import json, pathlib, venv; print('Python runtime OK')"

mkdir -p "$HOME/.nexus"

echo
echo "Setup complete. Launch with:"
echo "  cd \"$PROJECT_DIR\""
echo "  sh termux/run.sh"
