# ARC-AGI-3: play game `ft09`
You are playing an ARC-AGI-3 interactive reasoning game. The rules are UNKNOWN by design — you must discover the mechanics by experimenting, then beat all levels.

INTEGRITY RULES — VIOLATION INVALIDATES THE RUN

This is a benchmark of your reasoning from gameplay observation ONLY. You are playing a game whose rules you must discover by acting and observing frames — nothing else.

PROHIBITED, without exception:

Any internet or network access other than http://127.0.0.1:8765 (the game bridge). No web_search, no fetch, no URLs, no package installation.
Reading ANY file outside your own working directory. Specifically forbidden: /work/arc3/environment_files (game source code), /work/arc3/server.py, /work/arc3/recordings, other games' directories, and the arcengine / arc_agi packages' source.
Attempting to obtain game source code, solutions, walkthroughs, replays, or recordings from anywhere, local or remote.
Tampering with the bridge, the scorecard, or file permissions.
ALLOWED: the arc3 python client module, your own working directory (notes.md etc.), and pure reasoning/computation over frames you observed yourself.

Interface — python tool
Use your python eval tool (persistent kernel). The client module is on PYTHONPATH:

```python
import arc3
g = arc3.game("ft09")
g.reset()            # start / restart (required first, and after GAME_OVER)
g.act("a1", "a2")    # batch simple actions a1..a5, a7 (semantics unknown — discover!)
g.click(x, y)        # ACTION6 click at column x, row y (0,0 = top-left)
g.show()             # reprint current frame
g.grid               # list[str]: 64 rows of 64 hex digits (one char = cell color 0-f)
g.state, g.levels, g.win_levels, g.changed, g.available
g.frames             # ALL animation frames of the last action (list of grids); some
                     # games animate — motion direction/order carries information.
                     # grid == frames[-1]; status shows anim_frames=N when N > 1
```

Every action prints state levels/win_levels changed(=cells that differ from previous frame) and then the frame. g.available lists the action ids this game accepts. Pass show=False to suppress frame printing when batching. g.grid is plain data — diff, locate objects, and search with your own python code.

### Goal
Reach state=WIN by completing all levels (levels=N/N). GAME_OVER = failed attempt; reset and retry — knowledge persists across resets. Score = levels completed.

### Strategy
Reset first, study the frame, then probe each available action and watch changed + frame diffs to infer mechanics.
Form explicit hypotheses about objects, the avatar, goals, obstacles; verify them cheaply.
Write python helpers in the kernel (frame diffing, object detection, BFS over the grid, scripted action sequences) — but decide WHAT to do yourself.
Keep concise notes of learned mechanics in notes.md so you don't re-derive them.
Do not stop until WIN or you are out of time. If stuck, try un-probed actions, clicks on salient objects, and combinations.
Finish with a summary: levels completed, mechanics discovered.