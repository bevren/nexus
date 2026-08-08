# ARC-AGI-3: play game `ft09`

You are playing the official ARC-AGI-3 interactive game `ft09`. Its rules are unknown by design. Discover the mechanics through gameplay observations and beat every level.

## Integrity rules

Violation invalidates the run.

Prohibited:

- Web search, walkthroughs, solution lookup, replay lookup, or fetching unrelated URLs.
- Reading game implementation source, downloaded environment source, recordings, or files outside this workspace.
- Inspecting the `arc_agi`, `arcengine`, or game package source to infer mechanics.
- Installing packages or changing the environment during the solve. Dependencies are prepared by the launcher.
- Tampering with the API, scorecard, credentials, recordings, or file permissions.

Allowed:

- Online gameplay through the official ARC API used by the installed `arc-agi` toolkit. The default endpoint is `https://three.arcprize.org`.
- The existing `ARC_API_KEY` environment variable. Never print, log, or expose its value.
- Files inside this workspace, including `notes.md` and helper scripts you create.
- Pure reasoning and computation over frames observed during this run.

## Python interface

Use the persistent Python kernel. Initialize the client and game only once so the same environment and scorecard remain active across kernel calls:

```python
import arc_agi
from arc_agi import OperationMode
from arcengine import GameAction, GameState

arc = arc_agi.Arcade(operation_mode=OperationMode.ONLINE)
env = arc.make("ft09", render_mode="terminal-fast")
if env is None:
    raise RuntimeError("Failed to create ft09 environment")

obs = env.observation_space
print([action.name for action in env.action_space])
```

Take a simple action:

```python
obs = env.step(
    GameAction.ACTION1,
    reasoning={"thought": "brief gameplay-based reason"},
)
```

Take a coordinate action when `ACTION6` is available:

```python
obs = env.step(
    GameAction.ACTION6,
    data={"x": 32, "y": 32},
    reasoning={"thought": "brief gameplay-based reason"},
)
```

Useful interfaces:

- `env.action_space`: currently available `GameAction` values; check it after every step.
- `env.observation_space`: most recent `FrameDataRaw` observation.
- `env.reset()`: reset after `GameState.GAME_OVER`.
- `obs.state`, `obs.levels_completed`, and the returned frame data: current progress and visual evidence.
- `arc.get_scorecard()`: scorecard information. Do not expose credentials.

`ACTION6` coordinates are zero-based and range from 0 through 63.

## Goal

Reach `GameState.WIN` by completing all levels. After `GameState.GAME_OVER`, reset and retry while preserving learned mechanics in `notes.md`.

## Strategy

1. Inspect the initial observation and available actions.
2. Probe actions conservatively and study frame changes and animations.
3. Form explicit hypotheses about objects, controls, goals, and obstacles; test them cheaply.
4. Write reusable frame-diff, object-detection, pathfinding, and action helpers in the persistent kernel.
5. Keep concise discoveries and attempted sequences in `notes.md`.
6. Do not recreate `arc` or call `arc.make("ft09")` again unless initialization failed before an environment was returned.
7. Continue until `WIN` or the available time is exhausted, then summarize levels completed and mechanics discovered.
