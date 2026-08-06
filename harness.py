# RLM subagents + continual harness (Prime Agent-style interfaces)
import json
import os
import threading
import time
import urllib.request
import urllib.error
import uuid
from pathlib import Path

_SUBAGENTS: dict[str, dict] = {}
_SUBAGENT_LOCK = threading.Lock()

HARNESS_FILE = Path.home() / ".nexus" / "harness.json"


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


def _load_harness() -> dict:
    try:
        if HARNESS_FILE.exists():
            raw = HARNESS_FILE.read_text(encoding="utf-8")
            data = json.loads(raw)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {"memories": {}, "skills": {}, "subagents": {}, "prompt_notes": {}, "refinements": []}


def _save_harness(h: dict) -> bool:
    try:
        HARNESS_FILE.parent.mkdir(parents=True, exist_ok=True)
        HARNESS_FILE.write_text(json.dumps(h, indent=2), encoding="utf-8")
        return True
    except Exception:
        return False


def _subagent_worker(entry: dict) -> None:
    entry["status"] = "running"
    try:
        if not entry.get("api_key") or not entry.get("url"):
            entry["status"] = "error"
            entry["error"] = "no active provider configured"
            return
        payload = {
            "model": entry.get("model") or "",
            "messages": entry.get("messages") or [],
            "max_tokens": entry.get("max_tokens", 2048),
        }
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
            out = json.loads(resp.read().decode("utf-8", errors="replace"))
        choices = out.get("choices") or []
        content = (choices[0] or {}).get("message", {}).get("content") if choices else None
        if content is None:
            entry["status"] = "error"
            entry["error"] = "subagent returned no content"
            return
        entry["result"] = str(content)
        entry["status"] = "done"
    except Exception as exc:
        entry["status"] = "error"
        entry["error"] = str(exc)


class SubagentHandle:
    def __init__(self, entry: dict):
        self._entry = entry

    @property
    def id(self) -> str:
        return self._entry["id"]

    @property
    def status(self) -> str:
        return self._entry["status"]

    @property
    def prompt(self) -> str:
        return self._entry.get("prompt") or ""

    def result(self):
        return self._entry.get("result")

    def error(self):
        return self._entry.get("error")

    def join(self, timeout: float | None = None):
        thread = self._entry.get("thread")
        if thread and thread.is_alive():
            thread.join(timeout)
        if self._entry.get("status") == "done":
            return self._entry.get("result")
        if self._entry.get("status") == "error":
            raise RuntimeError("subagent failed: %s" % (self._entry.get("error") or "unknown error"))
        raise TimeoutError("subagent %s still running" % self._entry["id"])

    def to_dict(self) -> dict:
        return {
            "id": self._entry["id"],
            "status": self._entry["status"],
            "prompt": (self._entry.get("prompt") or "")[:200],
            "result": self._entry.get("result"),
            "error": self._entry.get("error"),
        }

    def __await__(self):
        return self.join().__await__()

    def __repr__(self) -> str:
        return "SubagentHandle(id=%r, status=%r)" % (self._entry["id"], self._entry["status"])


class _RLM:
    def __call__(self, prompt, *, model=None, system=None, timeout=300, max_tokens=2048, template=None):
        """Spawn a child sub-agent. Returns an admission handle immediately.
        Use handle.join() / await handle / handle.result() to get the result."""
        provider = _active_provider()
        if not provider:
            raise RuntimeError("no active LLM provider configured (check ~/.nexus/providers.json)")
        entry_id = uuid.uuid4().hex[:12]
        resolved_model = model or provider.get("model") or ""
        if not resolved_model:
            raise RuntimeError("no model configured for active provider")

        if template:
            cached = _load_harness().get("subagents", {}).get(template)
            if not cached:
                raise KeyError("unknown subagent template: %s" % template)
            msgs = cached.get("messages") or [
                {"role": "system", "content": cached.get("system") or "You are a focused subagent."},
                {"role": "user", "content": cached.get("prompt") or prompt},
            ]
        else:
            sys_text = system or "You are a focused subagent completing exactly one task. Return only the final result, no preamble."
            msgs = [{"role": "system", "content": sys_text}, {"role": "user", "content": str(prompt)}]

        entry = {
            "id": entry_id,
            "prompt": json.dumps(prompt) if not isinstance(prompt, str) else prompt,
            "model": resolved_model,
            "url": (provider.get("base_url") or "").rstrip("/"),
            "api_key": provider.get("api_key") or "",
            "timeout": timeout,
            "max_tokens": max_tokens,
            "messages": msgs,
            "status": "admitted",
            "result": None,
            "error": None,
            "created_at": time.time(),
        }
        thread = threading.Thread(target=_subagent_worker, args=(entry,), daemon=True)
        entry["thread"] = thread
        with _SUBAGENT_LOCK:
            _SUBAGENTS[entry_id] = entry
        thread.start()
        return SubagentHandle(entry)

    def list_subagents(self) -> list[dict]:
        with _SUBAGENT_LOCK:
            return [entry_to_dict(e) for e in _SUBAGENTS.values()]

    def delete_subagent(self, child) -> dict:
        cid = child.id if isinstance(child, SubagentHandle) else str(child)
        with _SUBAGENT_LOCK:
            entry = _SUBAGENTS.pop(cid, None)
        return {"deleted": entry is not None, "id": cid}


def entry_to_dict(e: dict) -> dict:
    return {
        "id": e["id"],
        "status": e["status"],
        "prompt": (e.get("prompt") or "")[:200],
        "result": e.get("result"),
        "error": e.get("error"),
        "model": e.get("model"),
    }


def list_subagents() -> list[dict]:
    return rlm.list_subagents()


def delete_subagent(child) -> dict:
    return rlm.delete_subagent(child)


class _Harness:
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

    def create_skill(self, name: str, description: str = "", body: str = "") -> dict:
        from pathlib import Path as _P
        base = _P.home() / ".nexus" / "skills" / str(name)
        base.mkdir(parents=True, exist_ok=True)
        md = "---\nname: %s\ndescription: %s\n---\n\n%s\n" % (name, description.replace("\n", " "), body)
        (base / "SKILL.md").write_text(md, encoding="utf-8")
        return {"ok": True, "kind": "skill", "name": name, "path": str(base)}

    def update_skill(self, name: str, description: str | None = None, body: str | None = None) -> dict:
        from pathlib import Path as _P
        md_path = _P.home() / ".nexus" / "skills" / str(name) / "SKILL.md"
        if not md_path.exists():
            return {"ok": False, "error": "skill not found"}
        text = md_path.read_text(encoding="utf-8")
        front, sep, rest = text.partition("---\n\n")
        if sep:
            head = text[: text.index("---", 3)]
            tail = text[text.index("---", 3) + 3 :]
            if description is not None:
                new_lines = []
                for ln in head.split("\n"):
                    if ln.startswith("description:"):
                        new_lines.append("description: " + description.replace("\n", " "))
                    else:
                        new_lines.append(ln)
                head = "\n".join(new_lines)
            if body is not None:
                out = head + tail
                first_nl = out.find("\n", out.find("---"))
                out = out[: first_nl + 1] + "\n" + body + "\n"
                md_path.write_text(out, encoding="utf-8")
            else:
                md_path.write_text(head + tail, encoding="utf-8")
        elif body is not None:
            md_path.write_text(body, encoding="utf-8")
        return {"ok": True, "kind": "skill", "name": name}

    def delete_skill(self, name: str) -> dict:
        from pathlib import Path as _P
        import shutil
        target = _P.home() / ".nexus" / "skills" / str(name)
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
            return {"deleted": True, "kind": "skill", "name": name}
        return {"deleted": False, "kind": "skill", "name": name}

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
            "skills": sorted(h.get("skills", {}).keys()),
            "subagents": sorted(h.get("subagents", {}).keys()),
            "prompt_notes": sorted(h.get("prompt_notes", {}).keys()),
            "refinements": len(h.get("refinements", [])),
            "running_subagents": [
                e["id"] for e in _SUBAGENTS.values() if e["status"] in ("admitted", "running")
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
        with _SUBAGENT_LOCK:
            recent = [e for e in _SUBAGENTS.values() if e["status"] == "done"]
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