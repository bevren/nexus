# RLM subagents + continual harness (Prime Agent-style interfaces)
import ast
import asyncio
import builtins
import hashlib
import inspect
import io
import json
import os
import queue
import re
import signal
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import urllib.request
import urllib.error
import uuid
from pathlib import Path

_AGENT_RUNTIME: dict[str, object] = {
    "system_prompt": "",
    "model": "",
    "reasoning_enabled": False,
    "reasoning_effort": "low",
    "session_id": "",
}

HARNESS_FILE = Path.home() / ".nexus" / "harness.json"
DEFAULT_SUBAGENT_ROOT = Path.home() / ".nexus" / "subagents"

SUBAGENT_EXECUTION_CONTRACT = """SUBAGENT EXECUTION CONTRACT:
- Complete the delegated task with the available execute tools before returning a final answer.
- A sentence announcing a next step (for example, "I need to inspect..." or "Let me implement...") is not a final answer. Emit the execute block in that same response instead.
- Return a normal final answer only after the requested work is complete and verified, or when you have a concrete blocker that tools cannot resolve."""

_UNFINISHED_RESPONSE_PATTERNS = (
    re.compile(r"(?:^|[.!?]\s+)(?:i|we)\s+(?:need|have|want)\s+to\b", re.IGNORECASE),
    re.compile(r"(?:^|[.!?]\s+)(?:i|we)(?:'ll|\s+will|\s+am\s+going\s+to)\b", re.IGNORECASE),
    re.compile(r"(?:^|[.!?]\s+)let\s+me\b", re.IGNORECASE),
    re.compile(r"(?:^|[.!?]\s+)before\s+(?:implementing|editing|writing|creating|continuing|finishing)\b", re.IGNORECASE),
)

_CONCRETE_BLOCKER_PATTERN = re.compile(
    r"\b(?:cannot|can't|unable|blocked|permission denied|credentials? (?:are |is )?missing|unavailable)\b",
    re.IGNORECASE,
)


def _looks_like_unfinished_response(content: str) -> bool:
    """Reject planning narration that would otherwise be mistaken for completion."""
    text = str(content or "").strip()
    if not text:
        return False
    if _CONCRETE_BLOCKER_PATTERN.search(text):
        return False
    return any(pattern.search(text) for pattern in _UNFINISHED_RESPONSE_PATTERNS)


def _with_subagent_contract(system_prompt: str) -> str:
    base = str(system_prompt or "").strip()
    if SUBAGENT_EXECUTION_CONTRACT in base:
        return base
    return f"{base}\n\n{SUBAGENT_EXECUTION_CONTRACT}".strip()


def _nexus_config_path():
    return Path(os.path.expanduser("~/.nexus/config.json"))


def _nexus_providers_path():
    return Path(os.path.expanduser("~/.nexus/providers.json"))


def _active_provider() -> dict:
    config = {}
    providers = []
    try:
        if _nexus_config_path().exists():
            config = json.loads(_nexus_config_path().read_text(encoding="utf-8"))
    except Exception:
        config = {}
    try:
        if _nexus_providers_path().exists():
            providers = json.loads(_nexus_providers_path().read_text(encoding="utf-8"))
            if not isinstance(providers, list):
                providers = []
    except Exception:
        providers = []
    name = config.get("provider") or ""
    for p in providers:
        if p.get("name") == name:
            return p
    return providers[0] if providers else {}


def configure_agent_runtime(
    system_prompt: str,
    model: str = "",
    reasoning_enabled: bool = False,
    reasoning_effort: str = "low",
    session_id: str = "",
) -> None:
    """Install the parent Nexus runtime inherited by subsequently spawned agents."""
    _AGENT_RUNTIME.update(
        {
            "system_prompt": str(system_prompt or ""),
            "model": str(model or ""),
            "reasoning_enabled": bool(reasoning_enabled),
            "reasoning_effort": str(reasoning_effort or "low"),
            "session_id": str(session_id or ""),
        }
    )


def _runtime_scope_id() -> str:
    raw = str(_AGENT_RUNTIME.get("session_id") or "").strip()
    if not raw:
        digest = hashlib.sha256(str(Path.cwd().resolve()).encode("utf-8")).hexdigest()[:16]
        raw = f"workspace-{digest}"
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", raw).strip("-.")
    return safe[:96] or "default"


def _scope_job_dir() -> Path:
    configured = str(os.environ.get("NEXUS_SUBAGENT_ROOT") or "").strip()
    root = Path(configured).resolve() if configured else DEFAULT_SUBAGENT_ROOT
    return root / _runtime_scope_id()


def _job_path(entry_id: str) -> Path:
    return _scope_job_dir() / f"{entry_id}.json"


def _job_payload(entry: dict) -> dict:
    excluded = {"api_key", "url", "thread", "process"}
    payload = {key: value for key, value in entry.items() if key not in excluded}
    payload["updated_at"] = time.time()
    return payload


def _write_job(path: Path, entry: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(_job_payload(entry), ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


def _read_job(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def _tools_command(*args: str) -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, *args]
    return [sys.executable, str(Path(__file__).with_name("tools.py")), *args]


def _worker_command(job_path: Path) -> list[str]:
    if getattr(sys, "frozen", False) and os.name == "nt":
        windowless_worker = Path(sys.executable).with_name("tools-worker.exe")
        if windowless_worker.exists():
            return [str(windowless_worker), "--run-subagent", str(job_path)]
    return _tools_command("--run-subagent", str(job_path))


def _launch_subagent_process(job_path: Path, workspace: str, extra_env: dict | None = None) -> int:
    child_env = {**os.environ, **(extra_env or {})}
    if getattr(sys, "frozen", False):
        # This worker must outlive the short-lived bundled code-execution
        # process that admitted it. Tell PyInstaller to start an independent
        # application instance with its own extraction lifecycle.
        child_env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    options: dict[str, object] = {
        "cwd": workspace,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "env": child_env,
        "close_fds": True,
    }
    if os.name == "nt":
        # The bundled worker uses the windowless PyInstaller bootloader. True
        # detachment is still required so it survives the short-lived tool
        # process that admitted it. STARTUPINFO also hides source-mode Python.
        options["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        options["startupinfo"] = startupinfo
    else:
        options["start_new_session"] = True
    process = subprocess.Popen(_worker_command(job_path), **options)
    return int(process.pid)


def launch_subagent_job(job_path: str, self_test: bool = False) -> int:
    path = Path(job_path).resolve()
    entry = _read_job(path)
    if not entry:
        raise FileNotFoundError(f"subagent job not found: {path}")
    extra_env = {"NEXUS_SUBAGENT_SELF_TEST": "1"} if self_test else None
    return _launch_subagent_process(path, str(entry.get("workspace") or Path.cwd()), extra_env)


def _load_harness() -> dict:
    try:
        if HARNESS_FILE.exists():
            raw = HARNESS_FILE.read_text(encoding="utf-8")
            data = json.loads(raw)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {"memories": {}, "subagents": {}, "prompt_notes": {}, "refinements": []}


def _save_harness(h: dict) -> bool:
    try:
        HARNESS_FILE.parent.mkdir(parents=True, exist_ok=True)
        HARNESS_FILE.write_text(json.dumps(h, indent=2), encoding="utf-8")
        return True
    except Exception:
        return False


def _assistant_text(response: dict) -> str:
    choices = response.get("choices") or []
    message = (choices[0] or {}).get("message", {}) if choices else {}
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            str(part.get("text") or part.get("content") or "")
            for part in content
            if isinstance(part, dict)
        )
    return ""


def _matching_fence(line: str, character: str, minimum: int) -> bool:
    value = line.strip()
    return len(value) >= minimum and set(value) == {character}


def _extract_execute_blocks(text: str) -> list[dict]:
    lines = str(text or "").replace("\r", "").split("\n")
    blocks: list[dict] = []
    index = 0
    while index < len(lines):
        opening = re.match(r"^\s*(`{3,}|~{3,})execute\s*$", lines[index], re.IGNORECASE)
        if not opening:
            index += 1
            continue
        fence = opening.group(1)
        # Any backtick/tilde run of 3+ is a potential closer. Runs at least as
        # long as the opener are unambiguous and win; when only shorter runs
        # exist (e.g. a 4-tick opener closed by a 3-tick run, a common
        # mistake), fall back to the LAST such run instead of truncating.
        close_candidates = [
            position
            for position in range(index + 1, len(lines))
            if _matching_fence(lines[position], fence[0], 3)
        ]
        if not close_candidates:
            blocks.append({"code": "\n".join(lines[index + 1 :]), "complete": False})
            break
        if len(fence) == 3:
            close_index = close_candidates[-1]
        else:
            strong = [
                position
                for position in close_candidates
                if len(lines[position].strip()) >= len(fence)
            ]
            close_index = strong[0] if strong else close_candidates[-1]
        blocks.append({"code": "\n".join(lines[index + 1 : close_index]), "complete": True})
        index = close_index + 1
    return blocks


def _execute_nexus_code(code: str) -> dict:
    """Run one child execute block with the same helper registry as the parent."""
    import tools  # Lazy import avoids the harness.py <-> tools.py import cycle.

    output = io.StringIO()

    def local_print(*args, **kwargs):
        options = dict(kwargs)
        options.setdefault("file", output)
        return builtins.print(*args, **options)

    scope: dict[str, object] = {}
    if isinstance(getattr(tools, "FUNCTIONS", None), dict):
        scope.update(tools.FUNCTIONS)
    maybe_functions = tools.get_functions() if hasattr(tools, "get_functions") else None
    if isinstance(maybe_functions, dict):
        scope.update(maybe_functions)
    safe_builtins = dict(vars(builtins))
    safe_builtins["print"] = local_print
    scope["__builtins__"] = safe_builtins
    scope["__name__"] = "__main__"

    try:
        compiled = compile(
            str(code or ""),
            "<subagent-execute>",
            "exec",
            flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT,
        )
        returned = eval(compiled, scope, scope)
        if inspect.isawaitable(returned):
            asyncio.run(returned)
        return {"ok": True, "output": output.getvalue()}
    except Exception as exc:
        return {
            "ok": False,
            "output": output.getvalue(),
            "error": f"{exc.__class__.__name__}: {exc}",
            "traceback": traceback.format_exc(),
        }


def _run_with_hard_timeout(operation, timeout_seconds: float, label: str):
    """Run a blocking operation with a real wall-clock deadline on Windows.

    Socket timeouts only bound individual I/O operations; a connected server
    can otherwise keep a response alive forever. The daemon thread is allowed
    to die with the worker after the deadline is reported to the job record.
    """
    outcome: queue.Queue = queue.Queue(maxsize=1)

    def run_operation() -> None:
        try:
            outcome.put((True, operation()))
        except BaseException as exc:
            outcome.put((False, exc))

    thread = threading.Thread(target=run_operation, name="nexus-subagent-request", daemon=True)
    thread.start()
    try:
        ok, value = outcome.get(timeout=max(0.05, float(timeout_seconds)))
    except queue.Empty as exc:
        raise TimeoutError(f"{label} exceeded hard {timeout_seconds:g}s wall-clock timeout") from exc
    if ok:
        return value
    raise value


def _perform_subagent_request(entry: dict) -> dict:
    payload = {
        "model": entry.get("model") or "",
        "messages": entry.get("messages") or [],
        "max_tokens": entry.get("max_tokens", 2048),
    }
    if entry.get("reasoning_enabled"):
        payload["reasoning_effort"] = entry.get("reasoning_effort") or "low"
        payload["reasoning"] = {"enabled": True}
        payload["thinking"] = {"type": "enabled"}
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        entry["url"].rstrip("/") + "/chat/completions",
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + entry["api_key"],
        },
    )
    with urllib.request.urlopen(req, timeout=entry.get("timeout", 300)) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def _request_subagent(entry: dict) -> dict:
    if os.environ.get("NEXUS_SUBAGENT_SELF_TEST") == "1":
        responses = entry.get("self_test_responses")
        if isinstance(responses, list) and responses:
            return responses.pop(0)
        raise RuntimeError("subagent self-test ran out of responses")
    try:
        timeout_seconds = max(0.05, float(entry.get("timeout", 300)))
    except (TypeError, ValueError):
        timeout_seconds = 300.0
    return _run_with_hard_timeout(
        lambda: _perform_subagent_request(entry),
        timeout_seconds,
        "subagent provider request",
    )


def _subagent_worker(entry: dict, on_update=None) -> None:
    notify = on_update if callable(on_update) else (lambda _entry: None)
    entry["status"] = "running"
    entry["pid"] = os.getpid()
    notify(entry)
    try:
        provider = _active_provider()
        entry["url"] = (provider.get("base_url") or "").rstrip("/")
        entry["api_key"] = provider.get("api_key") or ""
        if os.environ.get("NEXUS_SUBAGENT_SELF_TEST") == "1":
            entry["url"] = "http://self-test.invalid"
            entry["api_key"] = "self-test"
        if not entry.get("api_key") or not entry.get("url"):
            entry["status"] = "error"
            entry["error"] = "no active provider configured"
            notify(entry)
            return
        turn = 0
        while True:
            turn += 1
            entry["turn"] = turn
            notify(entry)
            response = _request_subagent(entry)
            content = _assistant_text(response)
            if not content.strip():
                entry["status"] = "error"
                entry["error"] = "subagent returned no content"
                notify(entry)
                return
            entry["messages"].append({"role": "assistant", "content": content})
            blocks = _extract_execute_blocks(content)
            if not blocks:
                if _looks_like_unfinished_response(content):
                    entry["unfinished_response_retries"] = int(entry.get("unfinished_response_retries") or 0) + 1
                    entry["messages"].append(
                        {
                            "role": "user",
                            "content": (
                                "[orchestrator] That response only announced a next action, so the delegated task "
                                "is still running. Perform the inspection or implementation now using one complete "
                                "execute block. Return a final answer only after completion, verification, or a "
                                "concrete blocker."
                            ),
                        }
                    )
                    notify(entry)
                    continue
                entry["result"] = content
                entry["status"] = "done"
                notify(entry)
                return

            results = []
            for block in blocks:
                if not block["complete"]:
                    tool_result = {
                        "ok": False,
                        "output": "",
                        "error": "Execute block was truncated before its closing fence and was not run.",
                    }
                else:
                    try:
                        tool_timeout = max(0.05, float(entry.get("timeout", 300)))
                    except (TypeError, ValueError):
                        tool_timeout = 300.0
                    tool_result = _run_with_hard_timeout(
                        lambda code=block["code"]: _execute_nexus_code(code),
                        tool_timeout,
                        "subagent execute block",
                    )
                results.append(tool_result)
            entry["messages"].append(
                {
                    "role": "user",
                    "content": "[tool code_execution result]\n" + json.dumps(results, ensure_ascii=False),
                }
            )
            notify(entry)

    except Exception as exc:
        entry["status"] = "error"
        entry["error"] = str(exc)
        notify(entry)


def run_subagent_job(job_path: str) -> int:
    """Worker entrypoint used by a detached Python/tools.exe process."""
    path = Path(job_path).resolve()
    entry = _read_job(path)
    if not entry:
        return 2
    workspace = str(entry.get("workspace") or "")
    if workspace:
        os.chdir(workspace)
    runtime = entry.get("runtime") if isinstance(entry.get("runtime"), dict) else {}
    configure_agent_runtime(
        system_prompt=str(runtime.get("system_prompt") or ""),
        model=str(runtime.get("model") or entry.get("model") or ""),
        reasoning_enabled=bool(runtime.get("reasoning_enabled")),
        reasoning_effort=str(runtime.get("reasoning_effort") or "low"),
        session_id=str(runtime.get("session_id") or entry.get("scope_id") or ""),
    )
    _subagent_worker(entry, on_update=lambda current: _write_job(path, current))
    return 0 if entry.get("status") == "done" else 1


class SubagentHandle:
    def __init__(self, entry: dict):
        self._entry = entry

    @property
    def id(self) -> str:
        return self._entry["id"]

    @property
    def status(self) -> str:
        return self._current().get("status") or "unknown"

    @property
    def prompt(self) -> str:
        return self._entry.get("prompt") or ""

    def result(self):
        return self._current().get("result")

    def error(self):
        return self._current().get("error")

    def _current(self) -> dict:
        current = _read_job(_job_path(self.id))
        return current or self._entry

    def join(self, timeout: float | None = None):
        deadline = time.monotonic() + (300.0 if timeout is None else max(0.0, float(timeout)))
        while True:
            current = self._current()
            if current.get("status") == "done":
                return current.get("result")
            if current.get("status") == "error":
                raise RuntimeError("subagent failed: %s" % (current.get("error") or "unknown error"))
            if time.monotonic() >= deadline:
                raise TimeoutError("subagent %s still running" % self.id)
            time.sleep(0.2)

    def to_dict(self) -> dict:
        return entry_to_dict(self._current())

    def __await__(self):
        async def wait_for_result():
            while True:
                current = self._current()
                if current.get("status") == "done":
                    return current.get("result")
                if current.get("status") == "error":
                    raise RuntimeError("subagent failed: %s" % (current.get("error") or "unknown error"))
                await asyncio.sleep(0.2)
        return wait_for_result().__await__()

    def __repr__(self) -> str:
        return "SubagentHandle(id=%r, status=%r)" % (self._entry["id"], self._entry["status"])


class _RLM:
    def __call__(self, prompt, *, system=None, timeout=300, max_tokens=2048, template=None):
        """Spawn a child sub-agent. Returns an admission handle immediately.
        Use handle.join() / await handle / handle.result() to get the result."""
        provider = _active_provider()
        if not provider:
            raise RuntimeError("no active LLM provider configured (check ~/.nexus/providers.json)")
        entry_id = uuid.uuid4().hex[:12]
        resolved_model = str(_AGENT_RUNTIME.get("model") or provider.get("model") or "")
        if not resolved_model:
            raise RuntimeError("no model configured for active provider")

        if template:
            cached = _load_harness().get("subagents", {}).get(template)
            if not cached:
                raise KeyError("unknown subagent template: %s" % template)
            base_system = str(_AGENT_RUNTIME.get("system_prompt") or "")
            specialization = str(cached.get("system") or "").strip()
            sys_text = base_system
            if specialization:
                sys_text = f"{base_system}\n\nSUBAGENT SPECIALIZATION:\n{specialization}".strip()
            sys_text = _with_subagent_contract(sys_text)
            task_prompt = str(prompt or cached.get("prompt") or template)
            msgs = [
                {"role": "system", "content": sys_text or "You are a focused Nexus subagent."},
                {"role": "user", "content": task_prompt},
            ]
        else:
            base_system = str(_AGENT_RUNTIME.get("system_prompt") or "")
            specialization = str(system or "").strip()
            sys_text = base_system
            if specialization:
                sys_text = f"{base_system}\n\nSUBAGENT SPECIALIZATION:\n{specialization}".strip()
            if not sys_text:
                sys_text = "You are a focused Nexus subagent completing exactly one task."
            sys_text = _with_subagent_contract(sys_text)
            msgs = [{"role": "system", "content": sys_text}, {"role": "user", "content": str(prompt)}]

        entry = {
            "id": entry_id,
            "prompt": json.dumps(prompt) if not isinstance(prompt, str) else prompt,
            "model": resolved_model,
            "timeout": timeout,
            "max_tokens": max_tokens,
            "reasoning_enabled": bool(_AGENT_RUNTIME.get("reasoning_enabled")),
            "reasoning_effort": str(_AGENT_RUNTIME.get("reasoning_effort") or "low"),
            "messages": msgs,
            "status": "admitted",
            "result": None,
            "error": None,
            "created_at": time.time(),
            "turn": 0,
            "workspace": str(Path.cwd().resolve()),
            "scope_id": _runtime_scope_id(),
            "runtime": dict(_AGENT_RUNTIME),
        }
        job_path = _job_path(entry_id)
        _write_job(job_path, entry)
        try:
            entry["pid"] = _launch_subagent_process(job_path, entry["workspace"])
        except Exception as exc:
            entry["status"] = "error"
            entry["error"] = f"failed to launch child process: {exc}"
            _write_job(job_path, entry)
            raise
        return SubagentHandle(entry)

    def list_subagents(self) -> list[dict]:
        directory = _scope_job_dir()
        if not directory.exists():
            return []
        entries = []
        for job_path in directory.glob("*.json"):
            entry = _read_job(job_path)
            if entry:
                entries.append(entry_to_dict(entry))
        return sorted(entries, key=lambda item: float(item.get("created_at") or 0))

    def delete_subagent(self, child) -> dict:
        cid = child.id if isinstance(child, SubagentHandle) else str(child)
        job_path = _job_path(cid)
        entry = _read_job(job_path)
        if entry and entry.get("status") in ("admitted", "running") and entry.get("pid"):
            try:
                os.kill(int(entry["pid"]), signal.SIGTERM)
            except (OSError, ValueError, TypeError):
                pass
        try:
            job_path.unlink()
            deleted = True
        except FileNotFoundError:
            deleted = False
        return {"deleted": deleted, "id": cid}


def entry_to_dict(e: dict) -> dict:
    return {
        "id": e["id"],
        "status": e["status"],
        "prompt": (e.get("prompt") or "")[:200],
        "result": e.get("result"),
        "error": e.get("error"),
        "model": e.get("model"),
        "turn": e.get("turn", 0),
        "pid": e.get("pid"),
        "created_at": e.get("created_at"),
        "updated_at": e.get("updated_at"),
    }


def list_subagents() -> list[dict]:
    return rlm.list_subagents()


def delete_subagent(child) -> dict:
    return rlm.delete_subagent(child)


def run_subagent_self_test() -> dict:
    """Offline cross-process proof of persistent status and the shared tool loop."""
    timeout_started = time.monotonic()
    try:
        _run_with_hard_timeout(lambda: time.sleep(0.25), 0.05, "self-test request")
        raise AssertionError("hard request watchdog did not time out")
    except TimeoutError as exc:
        if "hard 0.05s wall-clock timeout" not in str(exc):
            raise AssertionError(f"unexpected hard-timeout error: {exc}") from exc
    if time.monotonic() - timeout_started >= 0.2:
        raise AssertionError("hard request watchdog waited for the blocking operation")

    test_root = Path(tempfile.mkdtemp(prefix="nexus-subagent-test-", dir=Path.cwd()))
    previous_root = os.environ.get("NEXUS_SUBAGENT_ROOT")
    os.environ["NEXUS_SUBAGENT_ROOT"] = str(test_root)
    scope_id = f"self-test-{uuid.uuid4().hex}"
    configure_agent_runtime(
        system_prompt="PARENT NEXUS SYSTEM PROMPT",
        model="inherited-model",
        session_id=scope_id,
    )
    entry_id = uuid.uuid4().hex[:12]
    output_name = f".nexus-subagent-self-test-{entry_id}.tmp"
    output_path = Path.cwd() / output_name
    entry = {
        "id": entry_id,
        "prompt": f"write {output_name}",
        "model": "inherited-model",
        "timeout": 5,
        "max_tokens": 256,
        "reasoning_enabled": False,
        "reasoning_effort": "low",
        "messages": [
            {"role": "system", "content": _with_subagent_contract("PARENT NEXUS SYSTEM PROMPT")},
            {"role": "user", "content": f"write {output_name}"},
        ],
        "status": "admitted",
        "result": None,
        "error": None,
        "created_at": time.time(),
        "turn": 0,
        "workspace": str(Path.cwd().resolve()),
        "scope_id": scope_id,
        "runtime": dict(_AGENT_RUNTIME),
        "self_test_responses": [
            {
                "choices": [
                    {
                        "message": {
                            "content": "We need to inspect the workspace before implementing."
                        }
                    }
                ]
            },
            {
                "choices": [
                    {
                        "message": {
                            "content": f"````execute\nimport time\ntime.sleep(3)\nprint(write_file({output_name!r}, 'landed'))\n````"
                        }
                    }
                ]
            },
            {"choices": [{"message": {"content": "Child tool loop complete."}}]},
        ],
    }
    job_path = _job_path(entry_id)
    _write_job(job_path, entry)
    try:
        launch_started = time.monotonic()
        launcher = subprocess.run(
            _tools_command("--launch-subagent-test", str(job_path)),
            cwd=entry["workspace"],
            env={**os.environ, "NEXUS_SUBAGENT_SELF_TEST": "1"},
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
        )
        launch_elapsed = time.monotonic() - launch_started
        if launcher.returncode != 0:
            raise AssertionError(f"subagent launcher failed: {launcher.stderr or launcher.stdout}")
        if launch_elapsed >= 2.5:
            raise AssertionError(f"subagent launcher blocked for {launch_elapsed:.2f}s")
        if output_path.exists():
            raise AssertionError("subagent completed before detached launcher returned")
        deadline = time.monotonic() + 30.0
        current = None
        while time.monotonic() < deadline:
            current = _read_job(job_path)
            if current and current.get("status") in ("done", "error"):
                break
            time.sleep(0.1)
        if not current or current.get("status") != "done" or current.get("result") != "Child tool loop complete.":
            raise AssertionError(f"unexpected persistent terminal entry: {current}")
        if current.get("turn") != 3:
            raise AssertionError("child did not retry unfinished narration before its tool turn")
        if current.get("unfinished_response_retries") != 1:
            raise AssertionError("child did not record the unfinished-response retry")
        tool_context = "\n".join(
            str(message.get("content") or "")
            for message in current.get("messages", [])
            if isinstance(message, dict)
        )
        if output_name not in tool_context or "landed" not in tool_context:
            raise AssertionError("persistent child did not receive the workspace tool result")
        if not output_path.exists() or output_path.read_text(encoding="utf-8") != "landed":
            raise AssertionError("persistent child workspace write did not land")
        unlimited_entry = {
            "id": uuid.uuid4().hex[:12],
            "model": "inherited-model",
            "messages": [{"role": "user", "content": "continue beyond sixteen tool turns"}],
            "status": "admitted",
            "result": None,
            "error": None,
            "turn": 0,
            "self_test_responses": [
                {
                    "choices": [
                        {
                            "message": {
                                "content": f"````execute\nprint('continuing turn {index}')\n````"
                            }
                        }
                    ]
                }
                for index in range(1, 18)
            ] + [{"choices": [{"message": {"content": "Unlimited loop complete."}}]}],
        }
        previous_self_test = os.environ.get("NEXUS_SUBAGENT_SELF_TEST")
        os.environ["NEXUS_SUBAGENT_SELF_TEST"] = "1"
        try:
            _subagent_worker(unlimited_entry)
        finally:
            if previous_self_test is None:
                os.environ.pop("NEXUS_SUBAGENT_SELF_TEST", None)
            else:
                os.environ["NEXUS_SUBAGENT_SELF_TEST"] = previous_self_test
        if (
            unlimited_entry.get("status") != "done"
            or unlimited_entry.get("turn") != 18
            or unlimited_entry.get("result") != "Unlimited loop complete."
        ):
            raise AssertionError("child did not continue beyond the former 16-turn ceiling")
        listed = rlm.list_subagents()
        if not any(item.get("id") == entry_id and item.get("status") == "done" for item in listed):
            raise AssertionError("completed child was not visible from the persistent registry")
        return {"ok": True, "turns": current.get("turn"), "result": current.get("result")}
    finally:
        rlm.delete_subagent(entry_id)
        try:
            output_path.unlink()
        except FileNotFoundError:
            pass
        if previous_root is None:
            os.environ.pop("NEXUS_SUBAGENT_ROOT", None)
        else:
            os.environ["NEXUS_SUBAGENT_ROOT"] = previous_root
        shutil.rmtree(test_root, ignore_errors=True)


class _Harness:
    def get_memory(self, key: str) -> dict:
        h = _load_harness()
        entry = h.get("memories", {}).get(key)
        if not isinstance(entry, dict):
            return {"ok": False, "kind": "memory", "key": key, "error": "memory not found"}
        return {
            "ok": True,
            "kind": "memory",
            "key": key,
            "content": entry.get("content", ""),
            "metadata": entry.get("metadata", {}),
            "updated_at": entry.get("updated_at"),
        }

    def create_memory(self, key: str, content: str, metadata: dict | None = None) -> dict:
        h = _load_harness()
        h.setdefault("memories", {})[key] = {
            "content": content,
            "metadata": metadata or {},
            "updated_at": time.time(),
        }
        _save_harness(h)
        return {"ok": True, "kind": "memory", "key": key}

    def update_memory(self, key: str, content: str) -> dict:
        return self.create_memory(key, content)

    def delete_memory(self, key: str) -> dict:
        h = _load_harness()
        existed = h.get("memories", {}).pop(key, None) is not None
        _save_harness(h)
        return {"deleted": existed, "kind": "memory", "key": key}

    def create_subagent(self, name: str, prompt: str, model: str | None = None, system: str | None = None) -> dict:
        h = _load_harness()
        h.setdefault("subagents", {})[name] = {
            "prompt": prompt,
            "model": model or (_active_provider().get("model") or ""),
            "system": system or "You are a focused subagent completing exactly one task. Return only the final result.",
            "updated_at": time.time(),
        }
        _save_harness(h)
        return {"ok": True, "kind": "subagent", "name": name}

    def update_subagent(self, name: str, **fields) -> dict:
        h = _load_harness()
        entry = h.get("subagents", {}).get(name)
        if not entry:
            return {"ok": False, "error": "subagent template not found"}
        for k, v in fields.items():
            if k in ("prompt", "model", "system"):
                entry[k] = v
        entry["updated_at"] = time.time()
        _save_harness(h)
        return {"ok": True, "kind": "subagent", "name": name}

    def delete_subagent(self, name: str) -> dict:
        h = _load_harness()
        existed = h.get("subagents", {}).pop(name, None) is not None
        _save_harness(h)
        return {"deleted": existed, "kind": "subagent", "name": name}

    def create_prompt_note(self, name: str, content: str) -> dict:
        h = _load_harness()
        h.setdefault("prompt_notes", {})[name] = {"content": content, "updated_at": time.time()}
        _save_harness(h)
        return {"ok": True, "kind": "prompt_note", "name": name}

    def update_prompt_note(self, name: str, content: str) -> dict:
        return self.create_prompt_note(name, content)

    def delete_prompt_note(self, name: str) -> dict:
        h = _load_harness()
        existed = h.get("prompt_notes", {}).pop(name, None) is not None
        _save_harness(h)
        return {"deleted": existed, "kind": "prompt_note", "name": name}

    def overview(self) -> dict:
        h = _load_harness()
        return {
            "memories": sorted(h.get("memories", {}).keys()),
            "subagents": sorted(h.get("subagents", {}).keys()),
            "prompt_notes": sorted(h.get("prompt_notes", {}).keys()),
            "refinements": len(h.get("refinements", [])),
            "running_subagents": [
                entry["id"]
                for entry in rlm.list_subagents()
                if entry.get("status") in ("admitted", "running")
            ],
        }

    def record_refinement(self, summary: str, evidence: str | None = None) -> dict:
        h = _load_harness()
        h.setdefault("refinements", []).append({
            "summary": summary,
            "evidence": evidence or "",
            "recorded_at": time.time(),
        })
        _save_harness(h)
        return {"ok": True, "count": len(h["refinements"])}


class _Refine:
    def run(self, summary: str | None = None, evidence: str | None = None, auto: bool = True) -> dict:
        """Persist a reusable pattern into the continual harness.

        If summary is omitted and auto=True, scans recent done subagent results
        and prompt notes to synthesize a refinement record."""
        harness = _Harness()
        if summary:
            return harness.record_refinement(summary, evidence)
        recent = [entry for entry in rlm.list_subagents() if entry.get("status") == "done"]
        notes = _load_harness().get("prompt_notes", {})
        collected = []
        for e in recent[-5:]:
            if e.get("result"):
                collected.append("subagent %s: %s" % (e["id"], str(e["result"])[:200]))
        for name, note in list(notes.items())[-5:]:
            collected.append("note %s: %s" % (name, str(note.get("content"))[:200]))
        if not collected:
            return {"ok": False, "error": "no recent subagent results or prompt notes to refine"}
        summary_text = "Reusable pattern captured from recent subagent results and notes"
        return harness.record_refinement(summary_text, "\n".join(collected))


rlm = _RLM()
rlm_harness = _Harness()
refine = _Refine()
rlm.harness = rlm_harness
