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

## Development

```sh
npm install
npm test
npm start
```

The npm package runs the cross-platform source distribution. The native
Windows executable remains available through the separate `npm run build`
workflow.
