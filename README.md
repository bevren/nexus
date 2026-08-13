# Nexus

Nexus is a terminal coding agent with persistent Python tools, skills, MCP
servers, background jobs, reminders, plans, and autonomous kernels.

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

Nexus stores user configuration, sessions, skills, and kernel state under
`~/.nexus`.

## Agent orchestration

Create a persistent named agent with `/agent <name> [task]`. Omitting the task
creates an idle session. `/list-agents` shows the main and named sessions with
running, idle, or stopped status; select one to switch chats. Named agents keep
working in detached processes when another session is selected, and additional
messages submitted to a busy agent are queued for its next turn.

Nexus can launch concurrent child agents for independent work. Child agents
inherit the active provider/model, parent system prompt, execute-block loop,
workspace, and tools. They run as persistent child processes and may edit their
assigned files directly after the spawning execute block ends. Collect them
immediately or later with `wait_subagents`; the parent then integrates and
verifies the combined result.

## Phone remote control

Run `/remote-control` inside Nexus, then scan the QR code with a phone on the
same local network. The mobile page mirrors the current conversation, shows
thinking and tool status, accepts new or queued messages, and can stop the
active turn. Pressing Escape returns to the terminal chat while the remote
server keeps running; reopen `/remote-control` to view or restart it.

## Development

```sh
npm install
npm test
npm start
```

The npm package runs the cross-platform source distribution. The native
Windows executable remains available through the separate `npm run build`
workflow.
