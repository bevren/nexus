# Nexus

Nexus is a terminal coding agent with persistent Python tools, skills, MCP
servers, background jobs, reminders, plans, and autonomous kernels. It pairs a
full-screen TUI with an agentic loop that runs native `code_execution` tool
calls — no markdown execute fences — and can orchestrate persistent named
agents that keep working in the background.

## Install

Nexus requires Node.js 20 or newer and Python 3 available as `python`. On
Windows, the `py -3` launcher is also supported.

```sh
npm install --global @bevren/nexus
```

Launch Nexus from the project directory you want it to work in:

```sh
nexus
```

`nexus --version` (or `-v`) prints the installed version. To run from a source
checkout use `npm start` (node index.js). Nexus stores user configuration,
sessions, skills, and kernel state under `~/.nexus`.

## The TUI

Nexus is a full-screen terminal UI. The main window shows the conversation
with the model, streaming reasoning blocks (when the model supports them),
code-highlighted tool invocations, and tool results. Type normally to chat;
press `/` for the command menu and `@` for the agent picker.

### Keybindings

| Keys | Action |
| --- | --- |
| `Enter` | submit the current input |
| `Shift+Enter` / `Ctrl+J` | insert a newline |
| `Ctrl+A` / `Ctrl+E` | cursor to start / end of input |
| `Ctrl+W` | delete word backward |
| `Ctrl+Left` / `Ctrl+Right` | move word left / right |
| `Left` / `Right` | move cursor |
| `Up` / `Down` | browse submitted-input history |
| `PageUp` / `PageDown` | scroll the chat up / down |
| `Home` / `End` | scroll to top / bottom of chat |
| `Alt+V` | paste an image from the clipboard (Windows) |
| `Esc` | stop the running turn / close the current buffer |
| `Ctrl+C` | quit Nexus (except in the sessions buffer) |
| `/` | open the command menu |
| `@` | open the agent mention picker |

Buffers (models, providers, agents, sessions, loops, kernels, settings, MCP,
remote control, update) share the same navigation: `Up`/`Down` to move,
`Enter` to select, `Esc` to return. Their footer line always shows the
relevant keys (e.g. `Del` to delete, `F1`/`F2` to create/edit, `R` to
restart, `S` to stop).

### Footer status

The footer shows context-window usage, plan mode, the active model and
thinking effort, the workspace, and the active agent (`Main` or the named
agent's name).

## Commands

Run any of these by typing `/name` in the input, or browse them with `/`.

| Command | Description |
| --- | --- |
| `/agent <name> [task]` | create or task a persistent background agent |
| `/list-agents` | view agents/statuses; switch agent sessions |
| `/models` | manage model providers and credentials |
| `/settings` | view and change runtime settings |
| `/plan [on\|off\|status]` | toggle read-only Plan mode |
| `/model` | open the providers buffer and pick the active model |
| `/providers` | open the providers buffer |
| `/resume` | show session list and resume a selected chat |
| `/new` | start a new chat (new session uid) |
| `/clear` | clear the chat and delete the current session history |
| `/compact [instruction]` | manually compact the context window |
| `/cache` | show prompt fingerprint and provider cache-token telemetry |
| `/loop <interval> <prompt>` | schedule a recurring loop (see Loops) |
| `/loop once <when> <prompt>` | schedule a one-shot (e.g. `/loop once 3pm push the release`) |
| `/loops` | list loops (buffer); `/loops cancel <id>` to cancel |
| `/solve <directory>` | run an autonomous solve loop in an isolated workspace |
| `/kernels` | view, resume, restart, or delete `/solve` sessions |
| `/mcp` | manage MCP servers (start/stop/reload) |
| `/skills` | list installed skills |
| `/hooks` | show configured lifecycle hooks (read-only) |
| `/remote-control` | connect a phone over the local network |
| `/update` | check for a newer release and update |
| `/init` | create an `AGENTS.md` contributor guide for the workspace |
| `/review` | review current changes (declared; not supported in this build) |
| `/rename` | rename the current thread (declared; not supported in this build) |
| `/permissions` | choose what Nexus is allowed to do (declared; not supported in this build) |
| `/experimental` | toggle experimental features (declared; not supported in this build) |

## Reasoning & thinking

- `/settings → thinking` toggles native reasoning per model (`/thinking` is
  deprecated and points to `/settings`).
- `/settings → thinking effort` controls effort (`low` / `high` / `xhigh` / `max`).
- `/settings → thinking blocks` shows/hides the reasoning trace in the UI.
- `/settings → external thinking` enables the `deep_think()` tool path instead
  of native reasoning.

Reasoning traces are displayed as dim `◦` blocks above the assistant reply.
Nexus auto-retries transient provider errors without disabling thinking; it
only auto-disables thinking for a model when the provider explicitly rejects
the reasoning parameter (the notice appears in chat; `/settings` re-enables
it).

## Plan mode

`/plan` switches the workspace to read-only Plan mode. The model is restricted
to inspection helpers (`get_file_content`, `find_in_file`, `get_git_diff`,
`web_search`, …) plus the plan tools `create_plan`, `update_plan`, and
`get_current_plan`. Run `/plan` again to return to Build mode.

## Settings

`/settings` opens a live buffer. `Left`/`Right` (or `Enter`) cycle values:

- thinking (on/off), thinking blocks (on/off), external thinking (on/off)
- thinking effort (low / high / xhigh / max)
- text-to-speech, speech-to-text, and vision model pickers
- context window (128k – 1M tokens)
- request timeout (30s – 10m)
- max output tokens (16k – 393k)

Settings are session-scoped per agent and persist across restarts.

## Sessions

Every chat is persisted to `~/.nexus/sessions/` as it runs. `/resume` opens
the session list for the active agent; select one to restore the conversation,
including reasoning state, model, and runtime settings. `/new` starts a fresh
session. Named-agent sessions are stored under
`~/.nexus/agents/<workspace-scope>/` and can be transferred between agents.

## Agent orchestration

### Named agents

Create a persistent named agent with `/agent <name> [task]` (omitting the task
creates an idle session). `/list-agents` shows the main session and every
named agent with running/idle/stopped status; select one to switch chats.
Named agents run in detached processes and keep working when you switch back
to the main session. Tasks submitted to a busy agent are queued for its next
turn.

While viewing an agent's buffer you can chat directly with it; `/plan` and
`/settings` operate on that agent's session. `/clear`, `/compact`, and
`/new` apply to the active agent's session too.

### Delegation tools

The model can delegate work with the `delegate_agent` and `notify_agent`
helper tools (exposed via `code_execution`):

- `delegate_agent(name, task, timeout, poll_interval)` — send a task, wait for
  the agent's final result, and return it.
- `notify_agent(name, task)` — start the task and return immediately
  (fire-and-forget).

`list_subagents()` / `wait_subagents(ids, timeout)` / `delete_subagent(id)`
manage spawned agents. Named agents inherit the active provider/model, system
prompt, tools, and workspace.

### Handoffs (`@mention`)

Type `@name` (or `@` for the picker) followed by a task, e.g.
`@price_checker_agent hey, get current gold prices`, and press Enter. The
main session executes the delegation (visible as a single `delegate_agent`
tool result), then hands the task off:

- `@name` — delegate and continue (waits for the agent's result).
- `@name -notify` — fire-and-forget notify.
- `@name -wait` — delegate and wait for user confirmation before continuing.

Handoffs work in both directions: a named agent can hand work back to the
main session with `@main`. A completion note is injected after a handoff so
the follow-up turn does not re-submit the same delegation.

### Child (spawned) agents

`rlm_spawn(prompt, ...)` starts a persistent child Nexus agent with no
tool-turn ceiling. Children share the workspace and run the same native
tool-calling loop as the parent; they keep working after the spawning
`code_execution` call ends. Collect results later with `wait_subagents([...])`.

## Loops & reminders

Loops fire a prompt on a schedule; each fire is delivered as a `[tool
set_reminder result]` turn to the owning agent.

- `/loop 10m check deploy` — every 10 minutes.
- `/loop check the build` — dynamic interval (grows when nothing changes).
- `/loop once 3pm push the release` — one-shot at a wall-clock time.
- `/loop once in 45 minutes check tests` — relative one-shot.
- `set_reminder("in 10 minutes", "...")` — the model schedules a reminder
  (the user-facing equivalent of a one-shot loop).

`/loops` opens a buffer listing every task with its cadence, the prompt, and
when it fires next (`fires Today at 3:42pm (in 10m)`). `Enter` pauses/resumes,
`Del` deletes, `Esc` returns. `set_reminder("every 5 seconds", ...)` schedules
a sub-minute recurring loop for quick polling.

## Kernels & /solve

`/solve <directory>` runs an autonomous solve loop: Nexus reads `task.md`
(or `README.md`) from the directory, prepares an isolated venv, and iterates —
running code in a persistent Python kernel until the task's `SOLVE_OK`
sentinel appears. The solve transcript lives in its own window and sessions
are persisted under `~/.nexus/kernels/`.

`/kernels` opens the session list: `Enter` views the transcript, `R` resumes,
`F5` restarts, `S` stops a running session, `Del` deletes. While a solve is
running, `Esc` sends it to the background and `S` stops it.

Inside `code_execution` runs the `kernel_exec(code)` / `kernel_reset()`
helpers expose the same persistent kernel with state across calls.

## Hooks

Lifecycle hooks run external commands at deterministic points. Configure
project hooks in `.nexus/hooks.json` and user hooks in
`~/.nexus/hooks.json`:

```json
{
  "hooks": {
    "UserPromptSubmit": [
      { "matcher": "*", "hooks": [{ "type": "command", "command": "my-checker" }] }
    ]
  }
}
```

Events: `SessionStart`, `UserPromptSubmit`, `PreToolUse`, `PostToolUse`,
`PostToolUseFailure`, `Stop`, `Notification`, `PreCompact`, `PostCompact`,
`SessionEnd`. `/hooks` lists what is configured. Exit code 2 from a hook
blocks the associated action; stdout from `PreToolUse`/`PostToolUse`/
`UserPromptSubmit` is injected as additional context.

## MCP

Nexus supports MCP servers configured in `~/.nexus/mcp_config.json` (stdio and
streamable HTTP). `/mcp` opens a buffer to enable/disable servers per agent
(`Enter`), start/stop servers (`S`), and reload the config (`R`). The model
discovers MCP tools through `mcp_search(action='list' | 'search' | 'describe' |
'call', ...)` and can call them directly. A local bridge server
(`~/.nexus/mcp_bridge.json`) lets the Python tool layer reach MCP tools.

## Skills

Skills are reusable workflows stored as `SKILL.md` directories. Nexus loads
them from `~/.nexus/skills`, `<workspace>/skills`, and the bundled `skills/`
directory. The model discovers them with `list_skills()` and loads instructions
with `get_skill(name)`. `/skills` lists what's installed.

## Tools

The model drives work through `code_execution` native tool calls. Inside the
`code_execution` scope the full helper registry is available (see
`tool_search` for exact signatures):

- **Files & workspace**: `get_file_list`, `get_file_content`, `find_files`,
  `find_in_file`, `list_directory`, `path_exists`, `read_file_summary`,
  `write_file`, `replace_in_file`, `make_directory`, `move_path`,
  `copy_path`, `delete_path`, `get_current_working_directory`
- **Git**: `get_git_status`, `get_git_diff`, `get_git_log`
- **Shell**: `run_shell` (sync with timeout, or `background=True` for a
  TUI-owned 10-minute background job)
- **Plans**: `create_plan`, `update_plan`, `get_current_plan`
- **Agents**: `delegate_agent`, `notify_agent`, `rlm_spawn`, `list_subagents`,
  `wait_subagents`, `delete_subagent`
- **Harness**: `harness_overview`, `harness_memory`, `harness_prompt_note`,
  `harness_subagent`, `record_refinement`, `refine_reflection`
- **Skills**: `list_skills`, `get_skill`, `search_skill`, `manage_skill`,
  `skill_python_path`
- **MCP**: `mcp_list`, `mcp_search`, `mcp_call`
- **Web**: `web_search`, `fetch_url`
- **Media**: `transcribe_audio`, `describe_image`
- **Kernel**: `kernel_exec`, `kernel_reset`
- **Other**: `set_reminder`, `deep_think`, `tool_search`, `android_build`

## Phone remote control

Run `/remote-control`, then scan the QR code with a phone on the same local
network. The mobile page mirrors the conversation (including reasoning and
tool status), accepts new or queued messages, and can stop the active turn.
`Esc` returns to the terminal while the server keeps running; reopen
`/remote-control` to view connected clients or restart/stop the server
(`R`/`S`).

## Updates

On startup Nexus checks the npm registry for a newer release and opens the
update buffer: `Update now` installs `@bevren/nexus@latest` via npm,
`Continue` dismisses. `/update` re-checks manually.

## Development

```sh
npm install
npm test
npm start
```

The npm package ships the cross-platform source distribution (`index.js` +
Python tooling). The test suite is built in:

```sh
node index.js --self-test-append
node index.js --self-test-format
node index.js --self-test-execute
node index.js --self-test-background
node index.js --self-test-loop
node index.js --self-test-compact
node index.js --self-test-remote
node index.js --self-test-agents
node index.js --self-test-update
python tools.py --self-test-subagents
```

Run `npm test` before submitting changes. Reusable workflows belong under
`skills/<skill-name>/`; see `AGENTS.md` in the repository for full
contribution guidelines.