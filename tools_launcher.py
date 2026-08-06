"""Launcher that becomes tools.exe.

Supports the invocation shapes index.js uses with system python:
  tools.exe tools.py --describe-json
  tools.exe tools.py --list-skills-json
  tools.exe -c <runner_code> <base64_encoded_user_code>

Importing tools here statically ensures PyInstaller bundles tools.py and all
its dependencies (difflib, urllib, harness, skills_deps, ...) into the PYZ.
"""
import asyncio
import base64
import contextlib
import io
import os
import sys
import textwrap
import traceback
import ast

import tools


def main() -> int:
    args = sys.argv[1:]

    # Normalize: drop a leading tools.py path if present.
    if args and os.path.basename(args[0]) == "tools.py":
        args = args[1:]

    if not args:
        return 0

    # -c <runner_code> [<base64_arg>] -> exec code string with arg in sys.argv
    if args[0] == "-c":
        code = args[1]
        saved_argv = sys.argv[:]
        if len(args) > 2:
            sys.argv = ["-c"] + args[2:]
        try:
            g = {"__name__": "__main__"}
            exec(compile(code, "<string>", "exec"), g, g)
        finally:
            sys.argv = saved_argv
        return 0

    # Regular tools.py CLI (--describe-json, --list-skills-json, etc.)
    sys.argv = ["tools.py"] + args
    return tools.main()


if __name__ == "__main__":
    raise SystemExit(main())