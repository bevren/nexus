"""Persistent Python kernel for Nexus.

Reads newline-delimited JSON from stdin:  {"id": "1", "code": "x = 40"}
Executes `code` in a long-lived scope (state persists across requests).
Writes newline-delimited JSON results:   {"id": "1", "ok": true, "output": "..."}
"""
import io
import json
import sys
import traceback
from contextlib import redirect_stdout


def main() -> int:
    scope = {"__name__": "__main__", "__builtins__": __builtins__}
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            msg = json.loads(raw)
        except Exception:
            continue
        rid = msg.get("id")
        code = msg.get("code", "")
        result = {"id": rid, "ok": True, "output": "", "error": "", "traceback": ""}
        buf = io.StringIO()
        try:
            with redirect_stdout(buf):
                exec(compile(code, "<kernel>", "exec"), scope, scope)
            result["output"] = buf.getvalue()
        except Exception as exc:
            result["ok"] = False
            result["output"] = buf.getvalue()
            result["error"] = f"{exc.__class__.__name__}: {exc}"
            result["traceback"] = traceback.format_exc()
        sys.stdout.write(json.dumps(result) + "\n")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
