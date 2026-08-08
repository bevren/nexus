# ARC ft09 kernel workspace

This is a self-contained `/solve` workspace for the official ARC-AGI toolkit. Nexus creates a private `.venv` on first launch, reuses it for resume/restart, and verifies the pinned dependency from `requirements.txt` before starting the kernel.

`ARC_API_KEY` is inherited from your environment. The preflight reports only whether it is set and never prints its value. Without a key, the official toolkit can use anonymous access.

Launch from PowerShell:

```powershell
.\tasks\arc-ft09-kernel\launch.ps1
```

Or double-click `launch.cmd`.

The launcher runs a safe preflight and then starts:

```text
node index.js --solve <this-directory>
```

The game agent may use the official ARC API through `arc_agi.Arcade`; it must not search for solutions or inspect game/package source.
