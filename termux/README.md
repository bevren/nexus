# Run simple-code-tui on Android

This first milestone runs the complete TUI, agent tools, Git workspace, and
Python kernels locally on the phone through Termux. It does not use a PC
backend.

## Install

Install the current Termux release from F-Droid or the official Termux GitHub
releases. Do not use an obsolete store build.

In Termux, run:

```sh
pkg update -y
pkg install -y git
git clone --branch agent/kernel-tui-reliability \
  https://github.com/bevren/simple-code-tui.git
cd simple-code-tui
sh termux/setup.sh
```

## Launch

```sh
cd "$HOME/simple-code-tui"
sh termux/run.sh
```

On the first launch, open `/providers` and configure the provider, API key,
and model. Phone-local Nexus state is stored under `$HOME/.nexus`.
New installations default to a 1,000,000-token context window. Override
`model_context_window_override` in `$HOME/.nexus/config.json` when the selected
model has a different limit.

To keep a long kernel run alive while the screen is off, install Termux:API
from the same source as Termux, install its command package, and opt into the
wake lock when launching:

```sh
pkg install -y termux-api
NEXUS_WAKE_LOCK=1 sh termux/run.sh
```

Android may still stop Termux under aggressive battery management. Exclude
Termux from battery optimization for unattended solve sessions.

## Update

```sh
cd "$HOME/simple-code-tui"
git pull --ff-only
npm install --omit=dev
sh termux/run.sh
```

## Terminal controls

- Volume Down plus `C` sends Ctrl+C in Termux.
- Use Termux's extra-key row for Esc, arrows, and Ctrl.
- Mouse tracking is disabled by the launcher because touch gestures can emit
  terminal mouse sequences. Set `TUI_ENABLE_MOUSE=1` to enable it deliberately.

## Build Android apps on the phone

The repository includes an editable starter app and an `android_build` agent
tool. Set up the compiler and pair Wireless Debugging once:

```sh
sh termux/setup-android-build.sh
sh termux/connect-adb.sh IP:PAIR_PORT PAIR_CODE IP:DEBUG_PORT
```

Then ask the TUI agent to edit the app and deploy it, or run:

```sh
sh android-smoke/build-termux.sh --deploy
```
