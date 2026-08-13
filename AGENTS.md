# Repository Guidelines

## Project Structure & Module Organization

`index.js` contains the Node.js terminal UI, provider loop, buffers, and remote-control server. Python tooling is split across `tools.py` (tool registry and execution), `harness.py` (persistent subagents), `kernel.py`, and `skills_deps.py`. The npm launcher lives in `bin/nexus.js`. Reusable workflows belong under `skills/<skill-name>/`; Android and Termux examples live in `android-smoke/` and `termux/`. Task fixtures and launchable examples are under `tasks/`. Generated artifacts such as `dist/`, `build/`, `nexus.exe`, and `tools*.exe` are ignored and should not be committed.

## Build, Test, and Development Commands

- `npm install` installs Node dependencies.
- `npm start` runs the TUI from source with `node index.js`.
- `npm test` runs the Node UI/format/execution/background/remote self-tests, the Python subagent test, and a JavaScript syntax check.
- `python tools.py --self-test-subagents` runs the focused persistent-worker regression suite.
- `npm run build` bundles the SEA executable and builds the console and windowless Python helpers with PyInstaller. This command is Windows-oriented.

Run `npm test` before submitting changes. Use focused self-tests while iterating, then run the complete suite.

## Coding Style & Naming Conventions

Use two-space indentation in JavaScript and four spaces in Python. Follow existing CommonJS conventions (`require`, `module.exports`) and prefer `camelCase` for JavaScript functions/variables, `UPPER_SNAKE_CASE` for constants, and `snake_case` for Python. Keep changes localized: `index.js` is large, so extend the nearest existing subsystem instead of adding parallel state. No formatter is enforced; use `node --check index.js`, `python -m py_compile <files>`, and `git diff --check`.

## Testing Guidelines

Tests are primarily built-in `--self-test-*` entry points rather than a separate framework. Add regression coverage beside the relevant self-test and use deterministic fixtures; never require live providers, MCP servers, or network access. Verify both source behavior and bundled-worker behavior when changing process launch, subagents, or packaging.

## Commit & Pull Request Guidelines

History includes terse commits, but prefer concise imperative subjects such as `Fix queued prompt handoff`. Keep commits scoped to one behavior. Pull requests should explain the user-visible change, list validation commands, link related issues, and include terminal screenshots for layout or color changes. Mention Windows and Termux impact when applicable.

## Security & Configuration

Never commit API keys or files from `~/.nexus/`. Preserve workspace path checks and process-tree cleanup when changing shell, MCP, remote-control, or subagent code.
