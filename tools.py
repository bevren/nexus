"""Predefined helper functions for code execution."""

from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import statistics
import subprocess
import sys
import difflib
import textwrap
import bisect
import hashlib
from datetime import datetime, timezone
from collections import Counter
from uuid import uuid4
from typing import Iterable
import harness
import skills_deps

WORKSPACE_ROOT = Path.cwd().resolve()
NEXUS_DIR = Path.home() / ".nexus"
MEMORY_STORE_FILE = NEXUS_DIR / "memory.jsonl"
PLAN_STORE_DIR = NEXUS_DIR / "plans"
SUMMARY_PREVIEW_CHARS = 2000
MAX_DIFF_LINES = 600
MAX_MEMORY_RESULTS = 5000
MAX_HISTORY_EXCLUDE_MATCHES = 5000
EDIT_EVENT_LOG: list[str] = []
EDIT_SUMMARY_LOG: list[str] = []
HISTORY_ACTION_LOG: list[dict[str, object]] = []
PLAN_UI_EVENT_LOG: list[dict[str, object]] = []


def _resolve_workspace_path(path: str) -> Path:
    if not isinstance(path, str) or not path.strip():
        raise ValueError("path must be a non-empty string")

    raw = Path(path.strip())
    candidate = (WORKSPACE_ROOT / raw).resolve() if not raw.is_absolute() else raw.resolve()

    try:
        candidate.relative_to(WORKSPACE_ROOT)
    except ValueError as exc:
        raise ValueError("path must stay inside the workspace") from exc

    return candidate


def _parse_regex_flags(flags: str) -> int:
    if not isinstance(flags, str):
        raise ValueError("regex_flags must be a string")

    flag_map = {
        "i": re.IGNORECASE,
        "m": re.MULTILINE,
        "s": re.DOTALL,
        "x": re.VERBOSE,
        "a": re.ASCII,
        "u": re.UNICODE,
    }

    parsed = 0
    for ch in flags:
        key = ch.lower()
        if key in {" ", "\t", "\n", "\r"}:
            continue
        if key not in flag_map:
            raise ValueError("regex_flags contains invalid flag; allowed: i,m,s,x,a,u")
        parsed |= flag_map[key]

    return parsed


def _build_unified_diff(old_text: str, new_text: str, display_path: str) -> tuple[str, int, int]:
    old_lines = old_text.splitlines()
    new_lines = new_text.splitlines()
    diff_lines = list(
        difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=f"a/{display_path}",
            tofile=f"b/{display_path}",
            lineterm="",
        )
    )

    added = sum(1 for line in diff_lines if line.startswith("+") and not line.startswith("+++"))
    removed = sum(1 for line in diff_lines if line.startswith("-") and not line.startswith("---"))

    if len(diff_lines) > MAX_DIFF_LINES:
        hidden = len(diff_lines) - MAX_DIFF_LINES
        diff_lines = diff_lines[:MAX_DIFF_LINES]
        diff_lines.append(f"... +{hidden} lines")

    return ("\n".join(diff_lines), added, removed)


def drain_edit_events() -> list[str]:
    events = list(EDIT_EVENT_LOG)
    EDIT_EVENT_LOG.clear()
    return events


def drain_edit_summaries() -> list[str]:
    summaries = list(EDIT_SUMMARY_LOG)
    EDIT_SUMMARY_LOG.clear()
    return summaries


def drain_history_actions() -> list[dict[str, object]]:
    actions = list(HISTORY_ACTION_LOG)
    HISTORY_ACTION_LOG.clear()
    return actions


def drain_plan_ui_events() -> list[dict[str, object]]:
    events = list(PLAN_UI_EVENT_LOG)
    PLAN_UI_EVENT_LOG.clear()
    return events


def _record_plan_ui_event(entries: list[dict[str, object]]) -> None:
    PLAN_UI_EVENT_LOG.append(
        {
            "type": "plan",
            "title": "Plan",
            "entries": [
                {
                    "text": str(entry.get("text", "")).strip(),
                    "completed": bool(entry.get("completed")),
                }
                for entry in entries
                if str(entry.get("text", "")).strip()
            ],
        }
    )


def _ensure_memory_store_ready() -> None:
    NEXUS_DIR.mkdir(parents=True, exist_ok=True)
    if not MEMORY_STORE_FILE.exists():
        MEMORY_STORE_FILE.write_text("", encoding="utf-8")


def _ensure_plan_store_ready() -> None:
    NEXUS_DIR.mkdir(parents=True, exist_ok=True)
    PLAN_STORE_DIR.mkdir(parents=True, exist_ok=True)


def _get_plan_store_file() -> Path:
    _ensure_plan_store_ready()
    workspace_key = hashlib.sha1(str(WORKSPACE_ROOT).encode("utf-8")).hexdigest()
    return PLAN_STORE_DIR / f"plan-{workspace_key}.json"


def _normalize_plan_entry_text(text: str) -> str:
    cleaned = str(text).strip()
    cleaned = re.sub(r"^\[(?:\s|x|X|✓)\]\s*[-–—]?\s*", "", cleaned)
    return cleaned.strip()


def _coerce_plan_entry_texts(value: object, field_name: str) -> list[str]:
    if isinstance(value, str):
        raw_items = value.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    elif isinstance(value, (list, tuple, set)):
        raw_items = list(value)
    else:
        raise ValueError(f"{field_name} must be a string or list of strings")

    texts: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        if not isinstance(item, str):
            raise ValueError(f"{field_name} must contain only strings")
        normalized = _normalize_plan_entry_text(item)
        if not normalized:
            continue
        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)
        texts.append(normalized)
    return texts


def _coerce_plan_identifiers(value: object, field_name: str) -> list[int | str]:
    if value is None:
        return []
    if isinstance(value, (str, int)):
        raw_items: list[object] = [value]
    elif isinstance(value, (list, tuple, set)):
        raw_items = list(value)
    else:
        raise ValueError(f"{field_name} must be an int, string, or list")

    out: list[int | str] = []
    for item in raw_items:
        if isinstance(item, int):
            out.append(item)
            continue
        if not isinstance(item, str):
            raise ValueError(f"{field_name} must contain only ints/strings")
        token = _normalize_plan_entry_text(item)
        if not token:
            continue
        if token.isdigit():
            out.append(int(token))
        else:
            out.append(token)
    return out


def _load_plan_entries() -> list[dict[str, object]]:
    store_file = _get_plan_store_file()
    if not store_file.exists():
        return []

    try:
        raw = json.loads(store_file.read_text(encoding="utf-8", errors="replace"))
    except json.JSONDecodeError:
        return []

    if isinstance(raw, dict):
        source = raw.get("entries")
    else:
        source = raw

    if not isinstance(source, list):
        return []

    entries: list[dict[str, object]] = []
    for item in source:
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if not isinstance(text, str):
            continue
        normalized = _normalize_plan_entry_text(text)
        if not normalized:
            continue
        entries.append(
            {
                "text": normalized,
                "completed": bool(item.get("completed")),
            }
        )
    return entries


def _save_plan_entries(entries: list[dict[str, object]]) -> None:
    store_file = _get_plan_store_file()
    payload = {
        "workspace": str(WORKSPACE_ROOT),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "entries": entries,
    }
    store_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _format_plan_entries(entries: list[dict[str, object]]) -> str:
    if not entries:
        return "(no plan)"
    lines: list[str] = []
    for entry in entries:
        mark = "✓" if bool(entry.get("completed")) else " "
        text = str(entry.get("text", "")).strip()
        lines.append(f"[{mark}] - {text}")
    return "\n".join(lines)


def _normalize_keywords_input(value: object) -> list[str]:
    if value is None:
        return []

    if isinstance(value, str):
        source_items: list[object] = [value]
    elif isinstance(value, (list, tuple, set)):
        source_items = list(value)
    else:
        raise ValueError("keywords must be a string or a list of strings")

    out: list[str] = []
    seen: set[str] = set()
    for item in source_items:
        if not isinstance(item, str):
            raise ValueError("keywords must contain only strings")
        for part in re.split(r"[,;\n]", item):
            keyword = part.strip().lower()
            if not keyword:
                continue
            if keyword in seen:
                continue
            seen.add(keyword)
            out.append(keyword)
    return out


def _iter_memory_records() -> list[dict[str, object]]:
    _ensure_memory_store_ready()
    text = MEMORY_STORE_FILE.read_text(encoding="utf-8", errors="replace")
    records: list[dict[str, object]] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(parsed, dict):
            continue
        memory = parsed.get("memory")
        if not isinstance(memory, str) or not memory.strip():
            continue
        record_id = parsed.get("id")
        if not isinstance(record_id, str) or not record_id:
            record_id = uuid4().hex
        created_at = parsed.get("created_at")
        if not isinstance(created_at, str) or not created_at:
            created_at = datetime.now(timezone.utc).isoformat()
        keywords = _normalize_keywords_input(parsed.get("keywords"))
        records.append(
            {
                "id": record_id,
                "memory": memory,
                "keywords": keywords,
                "created_at": created_at,
            }
        )
    return records


def _normalize_preference_topic(topic: str) -> str:
    cleaned = str(topic).strip().lower()
    cleaned = re.sub(r'^[\'"`]+|[\'"`]+$', "", cleaned)
    cleaned = re.sub(r"[.!?]+$", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned


def _extract_preference_signature(
    memory_text: str, keywords: list[str] | None = None
) -> tuple[str, str] | None:
    text = str(memory_text or "").strip()
    if not text:
        return None

    normalized_keywords = _normalize_keywords_input(keywords)
    has_preference_keyword = "preference" in set(normalized_keywords)

    patterns: list[tuple[str, str]] = [
        (
            "dislike",
            r"^\s*user\s+(?:now\s+)?(?:does\s+not\s+like|doesn't\s+like|dislikes?|hates?)\s+(.+?)\s*[.!?]*\s*$",
        ),
        (
            "dislike",
            r"^\s*i\s+(?:do\s+not\s+like|don't\s+like|dislike|hate)\s+(.+?)\s*[.!?]*\s*$",
        ),
        (
            "like",
            r"^\s*user\s+(?:now\s+)?(?:likes?|loves?|prefers?)\s+(.+?)\s*[.!?]*\s*$",
        ),
        ("like", r"^\s*i\s+(?:like|love|prefer)\s+(.+?)\s*[.!?]*\s*$"),
    ]

    for value, pattern in patterns:
        match = re.match(pattern, text, re.IGNORECASE)
        if not match:
            continue
        topic = _normalize_preference_topic(match.group(1))
        if not topic:
            return None
        return (f"preference:{topic}", value)

    if has_preference_keyword:
        return None

    return None


def word_count(text: str) -> int:
    """Count words in a string."""
    return len(re.findall(r"\b\w+\b", text))


def line_count(text: str) -> int:
    """Count lines in a string."""
    if not text:
        return 0
    return len(text.splitlines())


def unique_words(text: str) -> list[str]:
    """Return sorted unique lowercase words."""
    words = re.findall(r"\b\w+\b", text.lower())
    return sorted(set(words))


def average(values: Iterable[float]) -> float:
    """Return arithmetic mean of values."""
    vals = [float(v) for v in values]
    if not vals:
        raise ValueError("values must not be empty")
    return statistics.fmean(vals)


def title_case(text: str) -> str:
    """Convert text to title case."""
    return text.title()


def insert_memory(memory: str, keyword: str | list[str]) -> dict[str, object]:
    """Insert persistent memory with one or more keywords."""
    if not isinstance(memory, str) or not memory.strip():
        raise ValueError("memory must be a non-empty string")

    memory_text = memory.strip()
    keywords = _normalize_keywords_input(keyword)
    if not keywords:
        raise ValueError("keyword must include at least one non-empty keyword")

    record = {
        "id": uuid4().hex,
        "memory": memory_text,
        "keywords": keywords,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    # Preference statements (e.g., likes/dislikes) are upserted by topic
    # so we keep only one effective memory per preference key.
    preference_sig = _extract_preference_signature(memory_text, keywords)
    if preference_sig is not None:
        pref_key, pref_value = preference_sig
        existing_records = _iter_memory_records()
        kept_records: list[dict[str, object]] = []
        replaced_count = 0
        exact_duplicate = None

        for existing in existing_records:
            existing_keywords = _normalize_keywords_input(existing.get("keywords"))
            existing_sig = _extract_preference_signature(
                str(existing.get("memory", "")), existing_keywords
            )
            if existing_sig is None or existing_sig[0] != pref_key:
                kept_records.append(existing)
                continue

            same_text = str(existing.get("memory", "")).strip().casefold() == memory_text.casefold()
            same_keywords = set(existing_keywords) == set(keywords)
            same_value = existing_sig[1] == pref_value
            if same_text and same_keywords and same_value:
                exact_duplicate = existing
                kept_records.append(existing)
            else:
                replaced_count += 1

        if exact_duplicate is not None and replaced_count == 0:
            existing_memory = str(exact_duplicate.get("memory", ""))
            return {
                "ok": True,
                "id": str(exact_duplicate.get("id", "")),
                "keywords": _normalize_keywords_input(exact_duplicate.get("keywords")),
                "bytes_written": len(existing_memory.encode("utf-8")),
                "upserted_preference": True,
                "preference_key": pref_key,
                "preference_value": pref_value,
                "skipped": "already_exists",
            }

        _ensure_memory_store_ready()
        with MEMORY_STORE_FILE.open("w", encoding="utf-8") as fp:
            for existing in kept_records:
                fp.write(json.dumps(existing, ensure_ascii=False) + "\n")
            fp.write(json.dumps(record, ensure_ascii=False) + "\n")

        return {
            "ok": True,
            "id": record["id"],
            "keywords": keywords,
            "bytes_written": len(record["memory"].encode("utf-8")),
            "upserted_preference": True,
            "preference_key": pref_key,
            "preference_value": pref_value,
            "replaced_count": replaced_count,
        }

    _ensure_memory_store_ready()
    with MEMORY_STORE_FILE.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(record, ensure_ascii=False) + "\n")

    return {
        "ok": True,
        "id": record["id"],
        "keywords": keywords,
        "bytes_written": len(record["memory"].encode("utf-8")),
    }


def retrieve_memory(
    query: str = "",
    use_regex: bool = False,
    case_sensitive: bool = False,
    regex_flags: str = "",
    keywords: str | list[str] | None = None,
    max_results: int = 20,
) -> list[dict[str, object]]:
    """Retrieve persistent memory by string/regex query and optional keyword filtering."""
    if not isinstance(query, str):
        raise ValueError("query must be a string")
    if not isinstance(use_regex, bool):
        raise ValueError("use_regex must be a boolean")
    if not isinstance(case_sensitive, bool):
        raise ValueError("case_sensitive must be a boolean")
    if not isinstance(regex_flags, str):
        raise ValueError("regex_flags must be a string")
    if not isinstance(max_results, int) or max_results < 1:
        raise ValueError("max_results must be an integer >= 1")
    if max_results > MAX_MEMORY_RESULTS:
        raise ValueError(f"max_results must be <= {MAX_MEMORY_RESULTS}")

    query_text = query.strip()
    keyword_filter = _normalize_keywords_input(keywords)
    if not query_text and not keyword_filter:
        raise ValueError("provide query and/or keywords")

    records = _iter_memory_records()
    records = list(reversed(records))

    matcher = None
    if query_text:
        if use_regex:
            flags = _parse_regex_flags(regex_flags)
            if not case_sensitive:
                flags |= re.IGNORECASE
            try:
                matcher = re.compile(query_text, flags)
            except re.error as exc:
                raise ValueError(f"invalid regex pattern: {exc}") from exc
        else:
            matcher = query_text if case_sensitive else query_text.lower()

    def _collect_results(apply_query_match: bool) -> list[dict[str, object]]:
        collected: list[dict[str, object]] = []
        for record in records:
            record_keywords = _normalize_keywords_input(record.get("keywords"))
            if keyword_filter and not any(key in record_keywords for key in keyword_filter):
                continue

            memory_text = str(record.get("memory", ""))
            if apply_query_match and matcher is not None:
                if use_regex:
                    if not matcher.search(memory_text):
                        continue
                else:
                    haystack = memory_text if case_sensitive else memory_text.lower()
                    if matcher not in haystack:
                        continue

            collected.append(
                {
                    "id": record.get("id", ""),
                    "memory": memory_text,
                    "keywords": record_keywords,
                    "created_at": record.get("created_at", ""),
                }
            )
            if len(collected) >= max_results:
                break

        return collected

    results = _collect_results(apply_query_match=True)
    if results:
        return results

    # If a query produced no strict hits but keyword filters were provided,
    # fall back to keyword-only matches instead of returning empty.
    if query_text and keyword_filter:
        return _collect_results(apply_query_match=False)

    return results


def memory_keywords() -> list[dict[str, object]]:
    """Return all inserted memory keywords with usage counts."""
    records = _iter_memory_records()
    counter: Counter[str] = Counter()
    for record in records:
        counter.update(_normalize_keywords_input(record.get("keywords")))

    items = [{"keyword": key, "count": int(count)} for key, count in counter.items()]
    items.sort(key=lambda item: (-item["count"], item["keyword"]))
    return items


def remove_memory(id: str) -> dict[str, object]:
    """Remove a memory record by its id."""
    if not isinstance(id, str) or not id.strip():
        raise ValueError("id must be a non-empty string")

    target_id = id.strip()
    records = _iter_memory_records()
    kept_records: list[dict[str, object]] = []
    removed_record: dict[str, object] | None = None

    for record in records:
        record_id = str(record.get("id", ""))
        if removed_record is None and record_id == target_id:
            removed_record = record
            continue
        kept_records.append(record)

    if removed_record is None:
        return {
            "ok": False,
            "id": target_id,
            "removed": False,
            "message": "memory id not found",
        }

    _ensure_memory_store_ready()
    with MEMORY_STORE_FILE.open("w", encoding="utf-8") as fp:
        for record in kept_records:
            fp.write(json.dumps(record, ensure_ascii=False) + "\n")

    removed_memory = str(removed_record.get("memory", ""))
    return {
        "ok": True,
        "id": target_id,
        "removed": True,
        "bytes_removed": len(removed_memory.encode("utf-8")),
    }


def update_memory(
    id: str,
    memory: str | None = None,
    keyword: str | list[str] | None = None,
) -> dict[str, object]:
    """Update one memory record by id (memory text and/or keywords)."""
    if not isinstance(id, str) or not id.strip():
        raise ValueError("id must be a non-empty string")

    target_id = id.strip()
    has_memory_update = memory is not None
    has_keyword_update = keyword is not None
    if not has_memory_update and not has_keyword_update:
        raise ValueError("provide memory and/or keyword to update")

    next_memory = None
    if has_memory_update:
        if not isinstance(memory, str) or not memory.strip():
            raise ValueError("memory must be a non-empty string when provided")
        next_memory = memory.strip()

    next_keywords = None
    if has_keyword_update:
        next_keywords = _normalize_keywords_input(keyword)
        if not next_keywords:
            raise ValueError("keyword must include at least one non-empty keyword when provided")

    records = _iter_memory_records()
    updated = False
    bytes_written = 0

    for record in records:
        record_id = str(record.get("id", ""))
        if record_id != target_id:
            continue
        if next_memory is not None:
            record["memory"] = next_memory
        if next_keywords is not None:
            record["keywords"] = next_keywords
        bytes_written = len(str(record.get("memory", "")).encode("utf-8"))
        updated = True
        break

    if not updated:
        return {
            "ok": False,
            "id": target_id,
            "updated": False,
            "message": "memory id not found",
        }

    _ensure_memory_store_ready()
    with MEMORY_STORE_FILE.open("w", encoding="utf-8") as fp:
        for record in records:
            fp.write(json.dumps(record, ensure_ascii=False) + "\n")

    return {
        "ok": True,
        "id": target_id,
        "updated": True,
        "memory_updated": next_memory is not None,
        "keywords_updated": next_keywords is not None,
        "bytes_written": bytes_written,
    }


def exclude_history_messages(
    latest_n: int = 0,
    role: str = "",
    query: str = "",
    use_regex: bool = False,
    case_sensitive: bool = False,
    regex_flags: str = "",
    max_matches: int = 200,
    include_system: bool = False,
) -> dict[str, object]:
    """Queue a runtime action to exclude matching chat history from future LLM requests."""
    if not isinstance(latest_n, int) or latest_n < 0:
        raise ValueError("latest_n must be an integer >= 0")
    if not isinstance(role, str):
        raise ValueError("role must be a string")
    if not isinstance(query, str):
        raise ValueError("query must be a string")
    if not isinstance(use_regex, bool):
        raise ValueError("use_regex must be a boolean")
    if not isinstance(case_sensitive, bool):
        raise ValueError("case_sensitive must be a boolean")
    if not isinstance(regex_flags, str):
        raise ValueError("regex_flags must be a string")
    if not isinstance(max_matches, int) or max_matches < 1:
        raise ValueError("max_matches must be an integer >= 1")
    if max_matches > MAX_HISTORY_EXCLUDE_MATCHES:
        raise ValueError(f"max_matches must be <= {MAX_HISTORY_EXCLUDE_MATCHES}")
    if not isinstance(include_system, bool):
        raise ValueError("include_system must be a boolean")

    normalized_role = role.strip().lower()
    allowed_roles = {"", "system", "user", "assistant", "tool", "tool_result", "error"}
    if normalized_role not in allowed_roles:
        raise ValueError("role must be one of: system,user,assistant,tool,tool_result,error")

    query_text = query.strip()
    if use_regex and query_text:
        flags = _parse_regex_flags(regex_flags)
        if not case_sensitive:
            flags |= re.IGNORECASE
        try:
            re.compile(query_text, flags)
        except re.error as exc:
            raise ValueError(f"invalid regex pattern: {exc}") from exc

    if latest_n == 0 and not normalized_role and not query_text:
        raise ValueError("provide at least one filter: latest_n, role, or query")

    action = {
        "type": "exclude_history_messages",
        "latest_n": latest_n,
        "role": normalized_role,
        "query": query_text,
        "use_regex": use_regex,
        "case_sensitive": case_sensitive,
        "regex_flags": regex_flags,
        "max_matches": max_matches,
        "include_system": include_system,
    }
    HISTORY_ACTION_LOG.append(action)

    return {
        "ok": True,
        "queued": True,
        "action": action,
    }


def create_plan(entries: str | list[str]) -> dict[str, object]:
    """Create a new workspace plan and return the full plan."""
    plan_texts = _coerce_plan_entry_texts(entries, "entries")
    if not plan_texts:
        raise ValueError("entries must include at least one non-empty item")

    plan_entries = [{"text": text, "completed": False} for text in plan_texts]
    _save_plan_entries(plan_entries)
    _record_plan_ui_event(plan_entries)

    return {
        "created_count": len(plan_entries),
        "entries": plan_entries,
        "plan": _format_plan_entries(plan_entries),
    }


def update_plan(
    completed: int | str | list[int | str] | None = None,
    new_entries: str | list[str] | None = None,
) -> dict[str, object]:
    """Mark entries completed and/or add new entries to the current plan."""
    identifiers = _coerce_plan_identifiers(completed, "completed")
    additions = _coerce_plan_entry_texts(new_entries, "new_entries") if new_entries is not None else []
    if not identifiers and not additions:
        raise ValueError("provide completed and/or new_entries")

    entries = _load_plan_entries()

    existing_keys = {str(entry.get("text", "")).casefold() for entry in entries}
    added_entries: list[dict[str, object]] = []
    for text in additions:
        key = text.casefold()
        if key in existing_keys:
            continue
        new_entry = {"text": text, "completed": False}
        entries.append(new_entry)
        added_entries.append(new_entry)
        existing_keys.add(key)

    updated_indexes: set[int] = set()
    unmatched: list[int | str] = []
    for identifier in identifiers:
        if isinstance(identifier, int):
            idx = identifier - 1
            if idx < 0 or idx >= len(entries):
                unmatched.append(identifier)
                continue
            entries[idx]["completed"] = True
            updated_indexes.add(idx)
            continue

        needle = identifier.casefold()
        matched = False
        for idx, entry in enumerate(entries):
            text = str(entry.get("text", ""))
            if text.casefold() == needle:
                entries[idx]["completed"] = True
                updated_indexes.add(idx)
                matched = True
        if not matched:
            unmatched.append(identifier)

    _save_plan_entries(entries)
    _record_plan_ui_event(entries)
    updated_entries = [entries[idx] for idx in sorted(updated_indexes)]

    return {
        "updated_count": len(updated_entries),
        "updated_entries": updated_entries,
        "added_count": len(added_entries),
        "added_entries": added_entries,
        "unmatched": unmatched,
        "plan": _format_plan_entries(entries),
    }


def get_current_plan() -> dict[str, object]:
    """Return the current workspace plan."""
    entries = _load_plan_entries()
    completed_count = sum(1 for entry in entries if bool(entry.get("completed")))
    return {
        "entry_count": len(entries),
        "completed_count": completed_count,
        "entries": entries,
        "plan": _format_plan_entries(entries),
    }


def get_current_working_directory() -> str:
    """Return the absolute workspace directory path."""
    return str(WORKSPACE_ROOT)


def get_file_list(path: str = ".") -> list[str]:
    """List files/directories under a workspace path."""
    target = _resolve_workspace_path(path)
    if not target.exists():
        raise ValueError("path does not exist")
    if not target.is_dir():
        raise ValueError("path must point to a directory")

    items = []
    for child in sorted(target.iterdir(), key=lambda item: item.name.lower()):
        rel = child.relative_to(WORKSPACE_ROOT).as_posix()
        items.append(f"{rel}/" if child.is_dir() else rel)

    return items


def get_file_content(path: str, start_line: int = -1, end_line: int = -1) -> str:
    """Read full or partial file content by 1-based line range."""
    target = _resolve_workspace_path(path)
    if not target.exists() or not target.is_file():
        raise ValueError("path must point to an existing file")

    if not isinstance(start_line, int):
        raise ValueError("start_line must be an integer")
    if not isinstance(end_line, int):
        raise ValueError("end_line must be an integer")

    if start_line != -1 and start_line < 1:
        raise ValueError("start_line must be -1 or >= 1")
    if end_line != -1 and end_line < 1:
        raise ValueError("end_line must be -1 or >= 1")

    if start_line != -1 and end_line != -1 and start_line > end_line:
        raise ValueError("start_line must be less than or equal to end_line")

    text = target.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    total = len(lines)

    if total == 0:
        if start_line == -1 and end_line == -1:
            return ""
        raise ValueError("requested line range is out of bounds for empty file")

    effective_start = 1 if start_line == -1 else start_line
    effective_end = total if end_line == -1 else end_line

    if effective_start > total:
        raise ValueError("start_line is out of bounds")
    if effective_end > total:
        raise ValueError("end_line is out of bounds")

    selected = lines[effective_start - 1 : effective_end]
    return "\n".join(selected)


def find_files(query: str, path: str = ".", max_results: int = 200) -> list[str]:
    """Find files by name/path substring under a workspace directory."""
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must be a non-empty string")
    if not isinstance(max_results, int) or max_results < 1:
        raise ValueError("max_results must be an integer >= 1")
    if max_results > 5000:
        raise ValueError("max_results must be <= 5000")

    root = _resolve_workspace_path(path)
    if not root.exists() or not root.is_dir():
        raise ValueError("path must point to an existing directory")

    needle = query.lower()
    matches: list[str] = []
    for child in root.rglob("*"):
        if not child.is_file():
            continue
        rel = child.relative_to(WORKSPACE_ROOT).as_posix()
        if needle in child.name.lower() or needle in rel.lower():
            matches.append(rel)
            if len(matches) >= max_results:
                break

    return matches


def list_directory(
    path: str = ".",
    include_hidden: bool = False,
    max_results: int = 500,
) -> list[dict[str, object]]:
    """List direct children of a directory with basic metadata."""
    if not isinstance(include_hidden, bool):
        raise ValueError("include_hidden must be a boolean")
    if not isinstance(max_results, int) or max_results < 1:
        raise ValueError("max_results must be an integer >= 1")
    if max_results > 5000:
        raise ValueError("max_results must be <= 5000")

    root = _resolve_workspace_path(path)
    if not root.exists() or not root.is_dir():
        raise ValueError("path must point to an existing directory")

    items: list[dict[str, object]] = []
    for child in sorted(root.iterdir(), key=lambda item: item.name.lower()):
        if not include_hidden and child.name.startswith("."):
            continue

        rel = child.relative_to(WORKSPACE_ROOT).as_posix()
        entry: dict[str, object] = {
            "name": child.name,
            "path": rel,
            "type": "directory" if child.is_dir() else "file",
        }
        if child.is_file():
            try:
                entry["size"] = child.stat().st_size
            except OSError:
                entry["size"] = None
        items.append(entry)
        if len(items) >= max_results:
            break

    return items


def make_directory(path: str, parents: bool = True, exist_ok: bool = True) -> dict[str, object]:
    """Create a directory inside workspace."""
    if not isinstance(parents, bool):
        raise ValueError("parents must be a boolean")
    if not isinstance(exist_ok, bool):
        raise ValueError("exist_ok must be a boolean")

    target = _resolve_workspace_path(path)
    existed_before = target.exists()
    target.mkdir(parents=parents, exist_ok=exist_ok)

    return {
        "path": target.relative_to(WORKSPACE_ROOT).as_posix(),
        "existed_before": existed_before,
    }


def delete_path(path: str, recursive: bool = False) -> dict[str, object]:
    """Delete a file or directory in workspace."""
    if not isinstance(recursive, bool):
        raise ValueError("recursive must be a boolean")

    target = _resolve_workspace_path(path)
    if target == WORKSPACE_ROOT:
        raise ValueError("refusing to delete workspace root")
    if not target.exists():
        raise ValueError("path does not exist")

    if target.is_file() or target.is_symlink():
        target.unlink()
        deleted_type = "file"
    elif target.is_dir():
        if recursive:
            shutil.rmtree(target)
        else:
            target.rmdir()
        deleted_type = "directory"
    else:
        raise ValueError("unsupported path type")

    return {
        "path": target.relative_to(WORKSPACE_ROOT).as_posix(),
        "deleted_type": deleted_type,
    }


def move_path(src: str, dst: str, overwrite: bool = False) -> dict[str, object]:
    """Move/rename a file or directory within workspace."""
    if not isinstance(overwrite, bool):
        raise ValueError("overwrite must be a boolean")

    source = _resolve_workspace_path(src)
    destination = _resolve_workspace_path(dst)
    if source == WORKSPACE_ROOT:
        raise ValueError("refusing to move workspace root")
    if not source.exists():
        raise ValueError("src does not exist")

    if destination.exists():
        if not overwrite:
            raise ValueError("dst already exists (set overwrite=true to replace)")
        if destination.is_file() or destination.is_symlink():
            destination.unlink()
        elif destination.is_dir():
            shutil.rmtree(destination)

    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(destination))

    return {
        "src": source.relative_to(WORKSPACE_ROOT).as_posix(),
        "dst": destination.relative_to(WORKSPACE_ROOT).as_posix(),
    }


def copy_path(
    src: str,
    dst: str,
    overwrite: bool = False,
    recursive: bool = False,
) -> dict[str, object]:
    """Copy a file or directory within workspace."""
    if not isinstance(overwrite, bool):
        raise ValueError("overwrite must be a boolean")
    if not isinstance(recursive, bool):
        raise ValueError("recursive must be a boolean")

    source = _resolve_workspace_path(src)
    destination = _resolve_workspace_path(dst)
    if not source.exists():
        raise ValueError("src does not exist")

    if source.is_dir() and not recursive:
        raise ValueError("src is a directory; set recursive=true to copy directories")

    if destination.exists():
        if not overwrite:
            raise ValueError("dst already exists (set overwrite=true to replace)")
        if destination.is_file() or destination.is_symlink():
            destination.unlink()
        elif destination.is_dir():
            shutil.rmtree(destination)

    destination.parent.mkdir(parents=True, exist_ok=True)

    if source.is_dir():
        shutil.copytree(source, destination, dirs_exist_ok=overwrite)
        copied_type = "directory"
    else:
        shutil.copy2(source, destination)
        copied_type = "file"

    return {
        "src": source.relative_to(WORKSPACE_ROOT).as_posix(),
        "dst": destination.relative_to(WORKSPACE_ROOT).as_posix(),
        "copied_type": copied_type,
    }


def path_exists(path: str) -> dict[str, object]:
    """Return existence/type info for a workspace path."""
    target = _resolve_workspace_path(path)
    exists = target.exists()
    return {
        "path": target.relative_to(WORKSPACE_ROOT).as_posix(),
        "exists": exists,
        "is_file": target.is_file() if exists else False,
        "is_dir": target.is_dir() if exists else False,
    }


def _run_git_command(args: list[str], timeout: int = 10) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(WORKSPACE_ROOT),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def get_git_status() -> dict[str, object]:
    """Return git status (short + branch)."""
    completed = _run_git_command(["status", "--short", "--branch"], timeout=10)
    output = (completed.stdout or "").strip()
    error = (completed.stderr or "").strip()
    return {
        "ok": completed.returncode == 0,
        "exit_code": int(completed.returncode),
        "output": output,
        "error": error,
    }


def get_git_diff(
    path: str = "",
    staged: bool = False,
    context_lines: int = 3,
    max_chars: int = 60000,
) -> dict[str, object]:
    """Return git diff text with optional path filtering and truncation."""
    if not isinstance(staged, bool):
        raise ValueError("staged must be a boolean")
    if not isinstance(context_lines, int) or context_lines < 0:
        raise ValueError("context_lines must be an integer >= 0")
    if context_lines > 100:
        raise ValueError("context_lines must be <= 100")
    if not isinstance(max_chars, int) or max_chars < 200:
        raise ValueError("max_chars must be an integer >= 200")
    if max_chars > 500000:
        raise ValueError("max_chars must be <= 500000")

    args = ["diff", f"--unified={context_lines}"]
    if staged:
        args.append("--staged")

    safe_path = ""
    if isinstance(path, str) and path.strip():
        resolved = _resolve_workspace_path(path.strip())
        safe_path = resolved.relative_to(WORKSPACE_ROOT).as_posix()
        args.extend(["--", safe_path])

    completed = _run_git_command(args, timeout=20)
    diff_text = (completed.stdout or "").rstrip("\n")
    truncated = False
    if len(diff_text) > max_chars:
        diff_text = diff_text[:max_chars]
        truncated = True

    return {
        "ok": completed.returncode == 0,
        "exit_code": int(completed.returncode),
        "path": safe_path,
        "staged": staged,
        "diff": diff_text,
        "truncated": truncated,
        "error": (completed.stderr or "").strip(),
    }


def get_git_log(max_count: int = 20) -> dict[str, object]:
    """Return recent git commits."""
    if not isinstance(max_count, int) or max_count < 1:
        raise ValueError("max_count must be an integer >= 1")
    if max_count > 500:
        raise ValueError("max_count must be <= 500")

    args = [
        "log",
        f"--max-count={max_count}",
        "--date=short",
        "--pretty=format:%h %ad %an %s",
    ]
    completed = _run_git_command(args, timeout=20)
    lines = [line for line in (completed.stdout or "").splitlines() if line.strip()]
    return {
        "ok": completed.returncode == 0,
        "exit_code": int(completed.returncode),
        "commits": lines,
        "error": (completed.stderr or "").strip(),
    }


def find_in_file(
    path: str,
    query: str,
    use_regex: bool = False,
    case_sensitive: bool = False,
    regex_flags: str = "",
    max_results: int = 200,
) -> list[dict[str, object]]:
    """Find string/regex matches in a single file with line/column positions."""
    if not isinstance(query, str) or not query:
        raise ValueError("query must be a non-empty string")
    if not isinstance(use_regex, bool):
        raise ValueError("use_regex must be a boolean")
    if not isinstance(case_sensitive, bool):
        raise ValueError("case_sensitive must be a boolean")
    if not isinstance(regex_flags, str):
        raise ValueError("regex_flags must be a string")
    if not isinstance(max_results, int) or max_results < 1:
        raise ValueError("max_results must be an integer >= 1")
    if max_results > 5000:
        raise ValueError("max_results must be <= 5000")

    target = _resolve_workspace_path(path)
    if not target.exists() or not target.is_file():
        raise ValueError("path must point to an existing file")

    text = target.read_text(encoding="utf-8", errors="replace")
    rel_path = target.relative_to(WORKSPACE_ROOT).as_posix()
    lines = text.splitlines()
    line_starts = [0]
    pos = 0
    while True:
        idx = text.find("\n", pos)
        if idx == -1:
            break
        line_starts.append(idx + 1)
        pos = idx + 1

    def _locate(offset: int) -> tuple[int, int, str]:
        if offset < 0:
            offset = 0
        if offset > len(text):
            offset = len(text)
        line_idx = bisect.bisect_right(line_starts, offset) - 1
        if line_idx < 0:
            line_idx = 0
        line_start = line_starts[line_idx] if line_idx < len(line_starts) else 0
        line_number = line_idx + 1
        column = (offset - line_start) + 1
        line_text = lines[line_idx] if line_idx < len(lines) else ""
        return line_number, column, line_text

    matches: list[dict[str, object]] = []

    if use_regex:
        flags = _parse_regex_flags(regex_flags)
        if not case_sensitive:
            flags |= re.IGNORECASE
        try:
            pattern = re.compile(query, flags)
        except re.error as exc:
            raise ValueError(f"invalid regex pattern: {exc}") from exc

        for match in pattern.finditer(text):
            start, end = match.span()
            if end <= start:
                continue
            line_number, column_start, line_text = _locate(start)
            _, column_end, _ = _locate(end - 1)
            matches.append(
                {
                    "path": rel_path,
                    "line_number": line_number,
                    "column_start": column_start,
                    "column_end": column_end,
                    "match": match.group(0),
                    "line": line_text,
                }
            )
            if len(matches) >= max_results:
                break
    else:
        haystack = text if case_sensitive else text.lower()
        needle = query if case_sensitive else query.lower()
        cursor = 0
        step = len(needle)
        while cursor <= len(haystack):
            start = haystack.find(needle, cursor)
            if start == -1:
                break
            end = start + step
            line_number, column_start, line_text = _locate(start)
            _, column_end, _ = _locate(end - 1)
            matches.append(
                {
                    "path": rel_path,
                    "line_number": line_number,
                    "column_start": column_start,
                    "column_end": column_end,
                    "match": text[start:end],
                    "line": line_text,
                }
            )
            if len(matches) >= max_results:
                break
            cursor = end

    return matches


def write_file(path: str, content: str) -> dict[str, object]:
    """Write text content to a file inside the workspace (create/overwrite)."""
    if not isinstance(content, str):
        raise ValueError("content must be a string")

    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    normalized_lines = normalized.split("\n")
    while normalized_lines and normalized_lines[0].strip() == "":
        normalized_lines.pop(0)
    while normalized_lines and normalized_lines[-1].strip() == "":
        normalized_lines.pop()
    normalized = "\n".join(normalized_lines)

    # Auto-fix common LLM triple-quoted indentation issues for Python files.
    # We only rewrite when parsing fails specifically with IndentationError.
    target = _resolve_workspace_path(path)
    if target.suffix.lower() == ".py" and normalized:
        parse_ok = False
        try:
            compile(normalized, "<write_file>", "exec")
            parse_ok = True
        except IndentationError:
            parse_ok = False
        except SyntaxError:
            parse_ok = True

        if not parse_ok:
            dedent_candidates = []
            full_dedent = textwrap.dedent(normalized)
            if full_dedent != normalized:
                dedent_candidates.append(full_dedent)

            lines = normalized.split("\n")
            if len(lines) > 1:
                rest_dedent = textwrap.dedent("\n".join(lines[1:]))
                with_rest_dedent = f"{lines[0]}\n{rest_dedent}"
                if with_rest_dedent != normalized:
                    dedent_candidates.append(with_rest_dedent)

            for candidate in dedent_candidates:
                try:
                    compile(candidate, "<write_file>", "exec")
                    normalized = candidate
                    break
                except IndentationError:
                    continue
                except SyntaxError:
                    continue

    rel_path = target.relative_to(WORKSPACE_ROOT).as_posix()
    old_text = ""
    if target.exists() and target.is_file():
        old_text = target.read_text(encoding="utf-8", errors="replace")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(normalized, encoding="utf-8")

    changed = old_text != normalized
    added_lines = 0
    removed_lines = 0
    if changed:
        diff_text, added_lines, removed_lines = _build_unified_diff(old_text, normalized, rel_path)
        if diff_text:
            EDIT_EVENT_LOG.append(f"Edited {rel_path} (+{added_lines} -{removed_lines})\n{diff_text}")
        EDIT_SUMMARY_LOG.append(
            f"file written: {rel_path} ({len(normalized.encode('utf-8'))} bytes)"
        )

    return {
        "path": rel_path,
        "bytes_written": len(normalized.encode("utf-8")),
        "changed": changed,
        "added_lines": added_lines,
        "removed_lines": removed_lines,
    }


def replace_in_file(
    path: str,
    old: str,
    new: str,
    count: int = -1,
    use_regex: bool = False,
    regex_flags: str = "",
) -> dict[str, object]:
    """Replace text in a file. Use count=-1 to replace all occurrences.

    Set use_regex=True to treat old as a regular expression.
    regex_flags supports: i,m,s,x,a,u.
    """
    if not isinstance(old, str) or not old:
        raise ValueError("old must be a non-empty string")
    if not isinstance(new, str):
        raise ValueError("new must be a string")
    if not isinstance(count, int):
        raise ValueError("count must be an integer")
    if count == 0 or count < -1:
        raise ValueError("count must be -1 or a positive integer")
    if not isinstance(use_regex, bool):
        raise ValueError("use_regex must be a boolean")
    if not isinstance(regex_flags, str):
        raise ValueError("regex_flags must be a string")

    target = _resolve_workspace_path(path)
    if not target.exists() or not target.is_file():
        raise ValueError("path must point to an existing file")

    rel_path = target.relative_to(WORKSPACE_ROOT).as_posix()
    text = target.read_text(encoding="utf-8", errors="replace")

    if use_regex:
        flags = _parse_regex_flags(regex_flags)
        try:
            pattern = re.compile(old, flags)
        except re.error as exc:
            raise ValueError(f"invalid regex pattern: {exc}") from exc
        sub_count = 0 if count == -1 else count
        updated, replacements = pattern.subn(new, text, count=sub_count)
    else:
        occurrences = text.count(old)
        if count == -1:
            updated = text.replace(old, new)
            replacements = occurrences
        else:
            updated = text.replace(old, new, count)
            replacements = min(occurrences, count)

    if replacements == 0:
        EDIT_SUMMARY_LOG.append(f"file content replaced successfully: {rel_path} (0 replacements)")
        return {
            "path": rel_path,
            "replacements": 0,
            "changed": False,
        }

    changed = updated != text
    added_lines = 0
    removed_lines = 0
    if changed:
        target.write_text(updated, encoding="utf-8")
        diff_text, added_lines, removed_lines = _build_unified_diff(text, updated, rel_path)
        if diff_text:
            EDIT_EVENT_LOG.append(f"Edited {rel_path} (+{added_lines} -{removed_lines})\n{diff_text}")
        EDIT_SUMMARY_LOG.append(
            f"file content replaced successfully: {rel_path} ({replacements} replacements)"
        )

    return {
        "path": rel_path,
        "replacements": replacements,
        "changed": changed,
        "added_lines": added_lines,
        "removed_lines": removed_lines,
    }


def run_shell(command: str, timeout: int | float = 10) -> dict[str, object]:
    """Run a shell command in workspace with timeout (seconds)."""
    if not isinstance(command, str) or not command.strip():
        raise ValueError("command must be a non-empty string")

    try:
        timeout_seconds = float(timeout)
    except (TypeError, ValueError) as exc:
        raise ValueError("timeout must be a number") from exc

    if timeout_seconds <= 0:
        raise ValueError("timeout must be greater than 0")
    if timeout_seconds > 600:
        raise ValueError("timeout must be <= 600 seconds")

    try:
        completed = subprocess.run(
            command,
            shell=True,
            cwd=str(WORKSPACE_ROOT),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        return {
            "ok": completed.returncode == 0,
            "exit_code": int(completed.returncode),
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "timed_out": False,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "exit_code": None,
            "stdout": (exc.stdout or ""),
            "stderr": (exc.stderr or ""),
            "timed_out": True,
            "error": f"Command timed out after {timeout_seconds:g}s",
        }


def android_build(
    project_path: str = "android-smoke",
    deploy: bool = True,
    timeout: int | float = 300,
) -> dict[str, object]:
    """Build an on-phone Android project and optionally install/relaunch it over ADB."""
    if not isinstance(deploy, bool):
        raise ValueError("deploy must be a boolean")
    try:
        timeout_seconds = float(timeout)
    except (TypeError, ValueError) as exc:
        raise ValueError("timeout must be a number") from exc
    if timeout_seconds <= 0 or timeout_seconds > 600:
        raise ValueError("timeout must be > 0 and <= 600 seconds")

    project_dir = _resolve_workspace_path(project_path)
    if not project_dir.is_dir():
        raise ValueError("project_path must point to a project directory")
    build_script = project_dir / "build-termux.sh"
    if not build_script.is_file():
        raise ValueError("project_path must contain build-termux.sh")

    command = ["sh", str(build_script)]
    if deploy:
        command.append("--deploy")
    try:
        completed = subprocess.run(
            command,
            cwd=str(WORKSPACE_ROOT),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        return {
            "ok": completed.returncode == 0,
            "exit_code": int(completed.returncode),
            "project_path": project_dir.relative_to(WORKSPACE_ROOT).as_posix(),
            "deployed": deploy and completed.returncode == 0,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "timed_out": False,
        }
    except FileNotFoundError:
        return {
            "ok": False,
            "exit_code": None,
            "project_path": project_dir.relative_to(WORKSPACE_ROOT).as_posix(),
            "deployed": False,
            "stdout": "",
            "stderr": "The sh command is unavailable; android_build must run inside Termux.",
            "timed_out": False,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "exit_code": None,
            "project_path": project_dir.relative_to(WORKSPACE_ROOT).as_posix(),
            "deployed": False,
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or "",
            "timed_out": True,
            "error": f"Android build timed out after {timeout_seconds:g}s",
        }


async def get_file_info(path: str) -> dict[str, object]:
    """Return basic metadata for a file or directory."""
    target = _resolve_workspace_path(path)
    exists = target.exists()
    if not exists:
        return {
            "path": str(target.relative_to(WORKSPACE_ROOT)),
            "exists": False,
            "is_file": False,
            "is_dir": False,
            "size": 0,
        }

    stat = target.stat()
    return {
        "path": str(target.relative_to(WORKSPACE_ROOT)),
        "exists": True,
        "is_file": target.is_file(),
        "is_dir": target.is_dir(),
        "size": stat.st_size,
        "modified_unix": stat.st_mtime,
    }


async def read_file_summary(path: str) -> dict[str, object]:
    """Read a compact summary of a text file."""
    target = _resolve_workspace_path(path)
    if not target.exists() or not target.is_file():
        raise ValueError("path must point to an existing file")

    text = target.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    return {
        "path": str(target.relative_to(WORKSPACE_ROOT)),
        "line_count": len(lines),
        "char_count": len(text),
        "preview": text[:SUMMARY_PREVIEW_CHARS],
    }


from html.parser import HTMLParser


class _DuckDuckGoParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.results = []
        self.current = None
        self.in_link = False
        self.in_snippet = False
        self.buf = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = attrs.get("class", "").split()
        if tag == "a" and "result-link" in classes:
            self.current = {"title": "", "snippet": "", "href": attrs.get("href", "")}
            self.in_link = True
            self.buf = []
        elif tag == "td" and "result-snippet" in classes:
            self.in_snippet = True
            self.buf = []

    def handle_data(self, data):
        if self.in_link or self.in_snippet:
            self.buf.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self.in_link and self.current:
            self.current["title"] = " ".join("".join(self.buf).split())
            self.in_link = False
        elif tag == "td" and self.in_snippet and self.current:
            self.current["snippet"] = " ".join("".join(self.buf).split())
            self.in_snippet = False
            if self.current["title"] and self.current.get("href"):
                self.results.append(self.current)
            self.current = None


import gzip
import re
from html.parser import HTMLParser


class _PageTextExtractor(HTMLParser):
    VOID = {
        "meta", "link", "br", "img", "hr", "input", "source", "track",
        "wbr", "area", "base", "col", "embed", "param",
    }
    SKIP = {
        "script", "style", "noscript", "svg", "canvas", "iframe", "template",
        "head", "select", "textarea", "audio", "video", "object",
    }
    BLOCK = {
        "p", "div", "li", "tr", "section", "article", "header", "footer",
        "ul", "ol", "table", "blockquote", "pre", "h1", "h2", "h3", "h4", "h5", "h6",
        "main", "aside", "nav", "form", "fieldset", "figure", "figcaption", "dl", "dd", "dt",
    }

    def __init__(self):
        super().__init__()
        self.out = []
        self.title = ""
        self._skip = 0
        self._in_title = False
        self._titlebuf = []

    def handle_starttag(self, tag, attrs):
        t = tag.lower()
        if t == "title":
            self._in_title = True
            self._titlebuf = []
            return
        if t in self.VOID:
            return
        if t in self.SKIP:
            self._skip += 1
            return
        if t in self.BLOCK:
            self.out.append("\n")

    def handle_endtag(self, tag):
        t = tag.lower()
        if t == "title":
            self.title = " ".join("".join(self._titlebuf).split())
            self._in_title = False
            return
        if t in self.VOID:
            return
        if t in self.SKIP:
            self._skip = max(0, self._skip - 1)
            return
        if t in self.BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self._titlebuf.append(data)
            return
        if self._skip > 0:
            return
        if data.strip():
            self.out.append(data)


def _normalize_page_text(out):
    lines = "".join(out).split("\n")
    cleaned = []
    for line in lines:
        line = " ".join(line.split())
        if line:
            cleaned.append(line)
    return "\n".join(cleaned)


def _guess_charset(raw):
    head = raw[:4096].lower()
    m = re.search(rb"charset=[\'\"]?([a-z0-9_\-]+)", head)
    if m:
        return m.group(1).decode("ascii", errors="ignore")
    if raw.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    if raw.startswith(b"\xfe\xff"):
        return "utf-16"
    return "utf-8"


def fetch_url(url: str, max_chars: int = 20000) -> dict[str, object]:
    """Fetch a URL and extract visible text content (HTML stripped).

    Returns a dict with:
      - url: the requested url
      - title: the page <title> text if present
      - text: the extracted visible text (newline separated)
      - truncated: True if the text was cut to max_chars
      - error: error message if the fetch/parse failed
    """
    import urllib.parse
    import urllib.request
    import urllib.error

    if not isinstance(url, str) or not url.strip():
        raise ValueError("url must be a non-empty string")
    if not isinstance(max_chars, int):
        raise ValueError("max_chars must be an integer")
    max_chars = max(500, min(max_chars, 100000))

    url = url.strip()
    if not url.startswith(("http://", "https://")):
        return {"url": url, "title": "", "text": "", "truncated": False, "error": "url must start with http:// or https://"}

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, identity",
    }
    MAX_READ = 2_000_000

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            ctype = (resp.headers.get("Content-Type") or "").lower()
            if ctype.startswith(("image/", "video/", "audio/", "application/octet-stream")):
                return {"url": url, "title": "", "text": "", "truncated": False, "error": "unsupported content type: " + ctype}

            raw = resp.read(MAX_READ + 1)
            raw = raw[:MAX_READ]

            encoding = (resp.headers.get("Content-Encoding") or "").lower()
            if "gzip" in encoding:
                try:
                    raw = gzip.decompress(raw)
                except (OSError, EOFError):
                    pass

            charset = resp.headers.get_content_charset()
            if not charset:
                charset = _guess_charset(raw)

            html_text = raw.decode(charset, errors="replace")
    except urllib.error.HTTPError as exc:
        return {"url": url, "title": "", "text": "", "truncated": False, "error": "HTTP " + str(exc.code) + ": " + str(exc.reason)}
    except urllib.error.URLError as exc:
        return {"url": url, "title": "", "text": "", "truncated": False, "error": "request failed: " + str(exc.reason)}
    except Exception as exc:
        return {"url": url, "title": "", "text": "", "truncated": False, "error": "fetch failed: " + str(exc)}

    extractor = _PageTextExtractor()
    extractor.feed(html_text)
    text = _normalize_page_text(extractor.out).strip()
    title = extractor.title

    truncated = len(text) > max_chars
    if truncated:
        text = text[:max_chars].rsplit("\n", 1)[0]

    return {"url": url, "title": title, "text": text, "truncated": truncated, "error": ""}


def web_search(query: str, max_results: int = 5) -> dict[str, object]:
    """Search the web using DuckDuckGo Lite HTML, falling back to the
    Instant Answer API when the Lite endpoint is unavailable.

    Returns a dict with:
      - query: the original query
      - results: list of {title, snippet, url} dicts
      - error: error message if the request failed
    """
    import urllib.parse
    import urllib.request

    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must be a non-empty string")
    if not isinstance(max_results, int):
        raise ValueError("max_results must be an integer")
    max_results = max(1, min(max_results, 20))

    lite = _web_search_lite(query, max_results)
    if lite["results"]:
        return {"query": query.strip(), "results": lite["results"], "error": ""}

    ia = _web_search_instant_answer(query, max_results)
    if ia["results"]:
        return {"query": query.strip(), "results": ia["results"], "error": lite["error"] or ""}

    return {
        "query": query.strip(),
        "results": [],
        "error": lite["error"] or ia["error"] or "no results",
    }


def _web_search_lite(query: str, max_results: int) -> dict[str, object]:
    import time
    import urllib.parse
    import urllib.request

    params = urllib.parse.urlencode({"q": query.strip()})
    url = "https://lite.duckduckgo.com/lite/?" + params
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    }

    last_error = ""
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=12) as resp:
                html_text = resp.read().decode("utf-8", errors="replace")
        except Exception as exc:
            last_error = "web search failed: " + str(exc)
            if attempt < 2:
                time.sleep(1.2)
            continue

        if "anomaly" in html_text.lower() and "result-link" not in html_text:
            last_error = "web search blocked by DuckDuckGo anomaly check"
            if attempt < 2:
                time.sleep(1.2)
            continue

        parser = _DuckDuckGoParser()
        parser.feed(html_text)

        results = []
        seen = set()
        for item in parser.results:
            if len(results) >= max_results:
                break
            href = item.get("href") or ""
            decoded = _decode_ddg_href(href)
            if not decoded or decoded in seen:
                continue
            seen.add(decoded)
            results.append(
                {
                    "title": item.get("title") or "",
                    "snippet": item.get("snippet") or "",
                    "url": decoded,
                }
            )

        return {"results": results, "error": ""}

    return {"results": [], "error": last_error}


def _decode_ddg_href(href: str) -> str:
    import urllib.parse

    if not href:
        return ""
    if "uddg=" in href:
        try:
            parts = urllib.parse.urlparse(href)
            qs = urllib.parse.parse_qs(parts.query)
            decoded = qs.get("uddg", [""])[0]
            return decoded if decoded.startswith("http") else ""
        except Exception:
            return ""
    if href.startswith("http"):
        return href
    return ""


def _web_search_instant_answer(query: str, max_results: int) -> dict[str, object]:
    import urllib.parse
    import urllib.request
    import json as _json

    params = urllib.parse.urlencode(
        {"q": query.strip(), "format": "json", "no_html": "1", "skip_disambig": "1"}
    )
    url = "https://api.duckduckgo.com/?" + params

    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (NexusTUI/1.0)",
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            payload = _json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception as exc:
        return {"results": [], "error": "instant answer search failed: " + str(exc)}

    results = []
    seen = set()
    related = payload.get("RelatedTopics") or []
    for topic in related:
        if not isinstance(topic, dict):
            continue
        subtopics = topic.get("Topics")
        if isinstance(subtopics, list):
            for sub in subtopics:
                if not isinstance(sub, dict):
                    continue
                _append_ia_result(results, seen, sub, max_results)
        else:
            _append_ia_result(results, seen, topic, max_results)
        if len(results) >= max_results:
            break

    return {"results": results[:max_results], "error": ""}


def _append_ia_result(results, seen, item, max_results):
    if len(results) >= max_results:
        return
    title = str(item.get("Text") or item.get("Name") or "").strip()
    url = str(item.get("FirstURL") or item.get("Url") or "").strip()
    if not url or url in seen:
        return
    seen.add(url)
    snippet = str(item.get("Text") or item.get("Abstract") or "").strip()
    results.append({"title": title, "snippet": snippet, "url": url})


from pathlib import Path

SKILLS_DIRS = [
    Path.home() / ".nexus" / "skills",
    WORKSPACE_ROOT / "skills",
    Path(__file__).resolve().parent / "skills",
]


def _parse_skill_frontmatter(text):
    import re

    name = ""
    description = ""
    frontmatter = ""
    body = text
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            frontmatter = text[3:end].strip()
            body = text[end + 4 :].lstrip("\n")
            for line in frontmatter.splitlines():
                stripped = line.strip()
                if stripped.startswith("name:"):
                    name = stripped[len("name:") :].strip().strip("\"'")
                elif stripped.startswith("description:"):
                    description = stripped[len("description:") :].strip().strip("\"'")
    return name, description, frontmatter, body


def _skill_deps_status(skill_dir):
    # Attach dependency status to a skill entry (non-blocking).
    try:
        info = skills_deps.requirements_satisfied(skill_dir)
        return {
            "present": info["present"],
            "installed": info["installed"],
            "installing": info["installing"],
            "needs_install": info["needs_install"],
            "error": info["error"],
        }
    except Exception as exc:
        return {"present": False, "installed": False, "error": str(exc)}

def _skill_entry_from_file(skill_dir):
    md = skill_dir / "SKILL.md"
    if not md.exists():
        return None
    try:
        raw = md.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None
    name, description, _fm, body = _parse_skill_frontmatter(raw)
    if not name:
        name = skill_dir.name
    return {
        "name": name,
        "description": description or "",
        "path": str(skill_dir),
        "body": body[:8000] if body else "",
    }


def list_skills() -> dict[str, object]:
    """List available skills. Skills are directories containing a SKILL.md file.

    Returns a dict with:
      - skills: list of {name, description} dicts (body excluded)
      - error: error message if scanning failed
    """
    found = []
    seen = set()
    for base in SKILLS_DIRS:
        try:
            if not base.exists():
                continue
            for child in sorted(base.iterdir()):
                if not child.is_dir():
                    continue
                if child.name in seen:
                    continue
                entry = _skill_entry_from_file(child)
                if entry:
                    seen.add(child.name)
                    found.append(entry)
        except Exception:
            continue
    found.sort(key=lambda e: e["name"].lower())
    return {
        "skills": [
            {
                "name": s["name"],
                "description": s["description"],
                "has_deps": _skill_deps_status(s["path"])["present"],
                "deps_installed": _skill_deps_status(s["path"])["installed"],
            }
            for s in found
        ],
        "error": "",
    }


def get_skill(name: str) -> dict[str, object]:
    """Get a skill by name. Returns its full markdown body plus metadata.

    Args:
        name: skill name (directory name or frontmatter name).

    Returns:
        dict with name, description, path, body; error field on failure.
    """
    if not isinstance(name, str) or not name.strip():
        raise ValueError("name must be a non-empty string")
    key = name.strip()

    for base in SKILLS_DIRS:
        try:
            if not base.exists():
                continue
            candidates = [base / key]
            for child in sorted(base.iterdir()):
                if child.is_dir():
                    entries = _skill_entry_from_file(child)
                    if entries and entries["name"].lower() == key.lower():
                        candidates.append(child)
            for candidate in candidates:
                entry = _skill_entry_from_file(candidate)
                if entry and entry["name"].lower() == key.lower():
                    entry["deps"] = _skill_deps_status(entry["path"])
                    if entry["deps"].get("needs_install"):
                        entry["deps"] = skills_deps.ensure_skill_dependencies(entry["path"])
                    return entry
        except Exception:
            continue

    # Fall back to listing so the agent knows what exists.
    try:
        listing = list_skills()
        names = [s["name"] for s in listing.get("skills", [])]
    except Exception:
        names = []
    return {
        "name": key,
        "description": "",
        "path": "",
        "body": "",
        "error": f"skill not found: {key}" + (f" (available: {', '.join(names)})" if names else ""),
    }



# --- RLM subagents + continual harness (Prime Agent-style interfaces) ---

def rlm_spawn(
    prompt: str,
    model: str = "",
    system: str = "",
    timeout: int = 300,
    max_tokens: int = 2048,
    template: str = "",
) -> dict:
    """Spawn a child sub-agent. Returns an admission handle (id, status) immediately.
    Poll with list_subagents() or delete with delete_subagent(handle_id)."""
    try:
        if template:
            handle = harness.rlm(prompt, template=template, timeout=timeout, max_tokens=max_tokens)
        else:
            handle = harness.rlm(
                prompt,
                model=model or None,
                system=system or None,
                timeout=timeout,
                max_tokens=max_tokens,
            )
        return handle.to_dict()
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def list_subagents() -> list[dict]:
    """List spawned child sub-agents with status, prompt, result, error."""
    try:
        return harness.rlm.list_subagents()
    except Exception as exc:
        return [{"ok": False, "error": str(exc)}]


def delete_subagent(handle_id: str) -> dict:
    """Delete a spawned child sub-agent by handle id."""
    try:
        return harness.rlm.delete_subagent(handle_id)
    except Exception as exc:
        return {"deleted": False, "error": str(exc)}


def harness_overview() -> dict:
    """Continual harness overview: memories, skills, subagent templates, prompt notes, refinements."""
    try:
        return harness.rlm.harness.overview()
    except Exception as exc:
        return {"error": str(exc)}


def harness_memory(key: str, content: str = "", delete: bool = False) -> dict:
    """Create/update/delete a persistent harness memory by key."""
    try:
        h = harness.rlm.harness
        if delete:
            return h.delete_memory(key)
        return h.create_memory(key, content)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def harness_prompt_note(name: str, content: str = "", delete: bool = False) -> dict:
    """Create/update/delete a persistent harness prompt note by name."""
    try:
        h = harness.rlm.harness
        if delete:
            return h.delete_prompt_note(name)
        return h.create_prompt_note(name, content)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def harness_subagent(name: str, prompt: str = "", model: str = "", system: str = "", delete: bool = False) -> dict:
    """Persist a reusable subagent template (create/update/delete by name)."""
    try:
        h = harness.rlm.harness
        if delete:
            return h.delete_subagent(name)
        if prompt:
            return h.update_subagent(name, prompt=prompt, model=model or None, system=system or None)
        return h.create_subagent(name, prompt or name, model=model or None, system=system or None)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def harness_skill(name: str, description: str = "", body: str = "", delete: bool = False) -> dict:
    """Create/update/delete a skill in the continual harness (writes ~/.nexus/skills/<name>/SKILL.md)."""
    try:
        h = harness.rlm.harness
        if delete:
            return h.delete_skill(name)
        if body:
            return h.create_skill(name, description, body)
        return h.update_skill(name, description=description or None, body=None)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def record_refinement(summary: str, evidence: str = "") -> dict:
    """Persist a reusable pattern into the continual harness with supporting evidence."""
    try:
        return harness.rlm.harness.record_refinement(summary, evidence)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def refine_reflection(auto: bool = True) -> dict:
    """Auto-synthesize a refinement from recent subagent results and prompt notes."""
    try:
        return harness.refine.run(auto=auto)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def skill_python_path() -> str:
    # Return the shared skill venv python executable (creates venv if needed).
    try:
        return skills_deps.get_venv_python()
    except Exception as exc:
        return "error: " + str(exc)

def set_reminder(when: str, prompt: str) -> dict:
    """Schedule a one-shot session reminder via the TUI bridge.

    when:    a human time phrase, e.g. "in 5 minutes", "in 2 hours", "at 3pm",
             "tomorrow 9am".
    prompt:  the exact action/message to run when the reminder fires.
    Returns: {ok: true, text: "...", result: {...}} or {ok: false, error: "..."}.
    """
    import urllib.request

    if not isinstance(when, str) or not when.strip():
        return {"ok": False, "error": "set_reminder: 'when' must be a non-empty string"}
    if not isinstance(prompt, str) or not prompt.strip():
        return {"ok": False, "error": "set_reminder: 'prompt' must be a non-empty string"}

    info = _read_mcp_bridge_info()
    if not info:
        return {
            "ok": False,
            "error": "set_reminder: TUI bridge not available. Is the TUI running?",
        }

    url = f"http://127.0.0.1:{info['port']}/"
    payload = json.dumps(
        {"method": "reminder", "when": when.strip(), "prompt": prompt.strip()}
    ).encode("utf-8")
    try:
        req = urllib.request.Request(
            url, data=payload, headers={"Content-Type": "application/json"}, method="POST"
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        return {"ok": False, "error": f"set_reminder: bridge request failed: {exc}"}


def _bridge_request(method: str, payload: dict) -> dict:
    """POST a raw request to the TUI bridge and return the parsed JSON."""
    import urllib.request

    info = _read_mcp_bridge_info()
    if not info:
        return {
            "ok": False,
            "error": "bridge not available. Is the TUI running?",
        }
    url = f"http://127.0.0.1:{info['port']}/"
    body = json.dumps({"method": method, **payload}).encode("utf-8")
    try:
        req = urllib.request.Request(
            url, data=body, headers={"Content-Type": "application/json"}, method="POST"
        )
        with urllib.request.urlopen(req, timeout=180) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        return {"ok": False, "error": f"bridge request failed: {exc}"}


def kernel_exec(code: str) -> dict:
    """Execute Python in the session's persistent kernel (state persists).

    code: a Python program. Variables/functions defined here are available in
    later kernel_exec calls in the same session, so multi-step computation can
    build state incrementally instead of recomputing from scratch.

    Returns: {ok, output, error, traceback} where output is everything printed
    to stdout during the call. Use print() to surface results.
    """
    if not isinstance(code, str) or not code.strip():
        return {"ok": False, "error": "kernel_exec: 'code' must be a non-empty string"}
    resp = _bridge_request("kernel", {"action": "exec", "code": code})
    if not resp.get("ok"):
        error = resp.get("error") or "kernel_exec failed"
        if isinstance(resp.get("result"), dict):
            result = resp["result"]
            return {
                "ok": False,
                "output": result.get("output", ""),
                "error": result.get("error", error),
                "traceback": result.get("traceback", ""),
            }
        return {"ok": False, "error": error}
    result = resp.get("result") or {}
    return {
        "ok": True,
        "output": result.get("output", ""),
        "error": result.get("error", ""),
        "traceback": result.get("traceback", ""),
    }


def kernel_reset() -> dict:
    """Kill the persistent kernel so the next kernel_exec starts with a clean scope."""
    resp = _bridge_request("kernel", {"action": "reset"})
    return {"ok": bool(resp.get("ok")), "error": resp.get("error", "")}


def _read_mcp_bridge_info() -> dict:
    bridge_file = NEXUS_DIR / "mcp_bridge.json"
    try:
        if not bridge_file.exists():
            return {}
        data = json.loads(bridge_file.read_text(encoding="utf-8"))
        port = int(data.get("port") or 0)
        if port <= 0:
            return {}
        return {"port": port, "pid": data.get("pid")}
    except Exception:
        return {}


def mcp_list() -> dict:
    """List MCP servers and their tools from the TUI bridge."""
    import urllib.request

    info = _read_mcp_bridge_info()
    if not info:
        return {
            "ok": False,
            "error": "MCP bridge not available. Is the TUI running with MCP enabled, and are servers configured in ~/.nexus/mcp_config.json?",
        }
    url = f"http://127.0.0.1:{info['port']}/"
    payload = json.dumps({"method": "list"}).encode("utf-8")
    try:
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        return {"ok": False, "error": f"MCP bridge request failed: {exc}"}


def mcp_call(server: str, tool: str, args: dict | None = None) -> dict:
    """
    Call a tool exposed by an MCP server through the TUI bridge.

    server:  the MCP server name as configured in ~/.nexus/mcp_config.json
    tool:    the tool name exposed by that server
    args:    a dict of arguments the tool accepts (matching its inputSchema)
    Returns: the bridge reply, normally {ok: true, result: {...}, text: "..."}.
    """
    import urllib.request

    info = _read_mcp_bridge_info()
    if not info:
        return {
            "ok": False,
            "error": "MCP bridge not available. Is the TUI running with MCP enabled, and are servers configured in ~/.nexus/mcp_config.json?",
        }
    if not isinstance(server, str) or not server.strip():
        return {"ok": False, "error": "mcp_call: 'server' must be a non-empty string"}
    if not isinstance(tool, str) or not tool.strip():
        return {"ok": False, "error": "mcp_call: 'tool' must be a non-empty string"}
    if args is None:
        args = {}
    if not isinstance(args, dict):
        return {"ok": False, "error": "mcp_call: 'args' must be a dict"}

    url = f"http://127.0.0.1:{info['port']}/"
    payload = json.dumps({"method": "call", "server": server, "tool": tool, "arguments": args}).encode("utf-8")
    try:
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        return {"ok": False, "error": f"MCP bridge request failed: {exc}"}


FUNCTIONS = {
    "create_plan": create_plan,
    "update_plan": update_plan,
    "get_current_plan": get_current_plan,
    "get_current_working_directory": get_current_working_directory,
    "get_file_list": get_file_list,
    "get_file_content": get_file_content,
    "find_files": find_files,
    "list_directory": list_directory,
    "make_directory": make_directory,
    "delete_path": delete_path,
    "move_path": move_path,
    "copy_path": copy_path,
    "path_exists": path_exists,
    "find_in_file": find_in_file,
    "write_file": write_file,
    "replace_in_file": replace_in_file,
    "run_shell": run_shell,
    "android_build": android_build,
    "get_git_status": get_git_status,
    "get_git_diff": get_git_diff,
    "get_git_log": get_git_log,
    "read_file_summary": read_file_summary,
    "fetch_url": fetch_url,
    "list_skills": list_skills,
    "get_skill": get_skill,
    "rlm_spawn": rlm_spawn,
    "list_subagents": list_subagents,
    "delete_subagent": delete_subagent,
    "harness_overview": harness_overview,
    "harness_memory": harness_memory,
    "harness_prompt_note": harness_prompt_note,
    "harness_subagent": harness_subagent,
    "harness_skill": harness_skill,
    "record_refinement": record_refinement,
    "refine_reflection": refine_reflection,
    "skill_python_path": skill_python_path,
    "web_search": web_search,
    "mcp_list": mcp_list,
    "mcp_call": mcp_call,
    "set_reminder": set_reminder,
    "kernel_exec": kernel_exec,
    "kernel_reset": kernel_reset,
}

FUNCTION_DESCRIPTIONS = {
    "create_plan": "create_plan(entries: str|list[str]) -> dict: Create a new workspace to-do plan and return the full plan.",
    "update_plan": "update_plan(completed: int|str|list[int|str]|None = None, new_entries: str|list[str]|None = None) -> dict: Mark plan entries completed and/or add new plan entries, then return updated entries and current plan.",
    "get_current_plan": "get_current_plan() -> dict: Get current workspace plan with [ ]/[✓] style formatted output.",
    "get_current_working_directory": "get_current_working_directory() -> str: Return absolute workspace path.",
    "get_file_list": "get_file_list(path: str = '.') -> list[str]: List files/directories under a workspace path.",
    "get_file_content": "get_file_content(path: str, start_line: int = -1, end_line: int = -1) -> str: Read full or partial file content by 1-based line range.",
    "find_files": "find_files(query: str, path: str = '.', max_results: int = 200) -> list[str]: Find files by name/path substring.",
    "list_directory": "list_directory(path: str = '.', include_hidden: bool = False, max_results: int = 500) -> list[dict]: List direct children of a directory.",
    "make_directory": "make_directory(path: str, parents: bool = True, exist_ok: bool = True) -> dict: Create directory in workspace.",
    "delete_path": "delete_path(path: str, recursive: bool = False) -> dict: Delete file/directory in workspace.",
    "move_path": "move_path(src: str, dst: str, overwrite: bool = False) -> dict: Move or rename path in workspace.",
    "copy_path": "copy_path(src: str, dst: str, overwrite: bool = False, recursive: bool = False) -> dict: Copy file/directory in workspace.",
    "path_exists": "path_exists(path: str) -> dict: Return existence/type info for a workspace path.",
    "find_in_file": "find_in_file(path: str, query: str, use_regex: bool = False, case_sensitive: bool = False, regex_flags: str = '', max_results: int = 200) -> list[dict]: Find matches in one file (literal or regex) with line/column locations.",
    "write_file": "write_file(path: str, content: str) -> dict: Write text file (create/overwrite) in workspace.",
    "replace_in_file": "replace_in_file(path: str, old: str, new: str, count: int = -1, use_regex: bool = False, regex_flags: str = '') -> dict: Replace text in a file (literal or regex).",
    "run_shell": "run_shell(command: str, timeout: int|float = 10) -> dict: Run shell command with timeout seconds.",
    "android_build": "android_build(project_path: str = 'android-smoke', deploy: bool = True, timeout: int|float = 300) -> dict: Build an Android project locally in Termux. With deploy=true, install the APK over paired on-phone ADB, stop the old app, and launch the updated activity.",
    "get_git_status": "get_git_status() -> dict: Return git status summary.",
    "get_git_diff": "get_git_diff(path: str = '', staged: bool = False, context_lines: int = 3, max_chars: int = 60000) -> dict: Return git diff text.",
    "get_git_log": "get_git_log(max_count: int = 20) -> dict: Return recent git commits.",
    "read_file_summary": "async read_file_summary(path: str) -> dict: Return summary/preview for large files.",
    "fetch_url": "fetch_url(url: str, max_chars: int = 20000) -> dict: Fetch a URL and extract visible text content (HTML stripped). Returns {url, title, text, truncated, error}.",
    "skill_python_path": "skill_python_path() -> str: Return the shared skill venv python executable (creates venv if needed). Use with run_shell to run skill scripts that depend on requirements.txt packages.",
    "list_skills": "list_skills() -> dict: List available skills. Returns {skills: [{name, description}], error}.",
    "get_skill": "get_skill(name: str) -> dict: Get a skill by name. Returns {name, description, path, body, error}. Load the body only when using the skill.",
    "web_search": "web_search(query: str, max_results: int = 5) -> dict: Search the web via DuckDuckGo (Lite HTML with Instant Answer fallback). Returns {query, results: [{title, snippet, url}], error}.",
    "rlm_spawn": "rlm_spawn(prompt: str, model: str = '', system: str = '', timeout: int = 300, max_tokens: int = 2048, template: str = '') -> dict: Spawn a child sub-agent. Returns an admission handle {id, status, prompt} immediately; poll list_subagents() or delete_subagent(id).",
    "list_subagents": "list_subagents() -> list[dict]: List spawned child sub-agents with status, prompt, result, error.",
    "delete_subagent": "delete_subagent(handle_id: str) -> dict: Delete a spawned child sub-agent by handle id.",
    "harness_overview": "harness_overview() -> dict: Continual harness overview: memories, skills, subagent templates, prompt notes, refinements.",
    "harness_memory": "harness_memory(key: str, content: str = '', delete: bool = False) -> dict: Create/update/delete a persistent harness memory by key.",
    "harness_prompt_note": "harness_prompt_note(name: str, content: str = '', delete: bool = False) -> dict: Create/update/delete a persistent harness prompt note by name.",
    "harness_subagent": "harness_subagent(name: str, prompt: str = '', model: str = '', system: str = '', delete: bool = False) -> dict: Persist a reusable subagent template.",
    "harness_skill": "harness_skill(name: str, description: str = '', body: str = '', delete: bool = False) -> dict: Create/update/delete a skill in the continual harness.",
    "record_refinement": "record_refinement(summary: str, evidence: str = '') -> dict: Persist a reusable pattern into the continual harness with evidence.",
    "refine_reflection": "refine_reflection(auto: bool = True) -> dict: Auto-synthesize a refinement from recent subagent results and prompt notes.",
    "mcp_list": "mcp_list() -> dict: List all configured MCP servers and the tool names each exposes. Returns {ok: bool, servers?: {name: {status, error?, tools: [name]}}, error?: str}.",
    "mcp_call": "mcp_call(server: str, tool: str, args: dict | None = None) -> dict: Call a tool exposed by an MCP server (configured in ~/.nexus/mcp_config.json). Returns the server's result as {ok: bool, result?: object, text?: str, error?: str}.",
    "set_reminder": "set_reminder(when: str, prompt: str) -> dict: Schedule a one-shot session reminder via the TUI bridge. when is a human phrase like 'in 5 minutes', 'in 2 hours', 'at 3pm', 'tomorrow 9am'. prompt is the exact action/message to run when it fires. Fires once as a normal user turn. Use whenever the user asks to be reminded or to remember something later.",
    "kernel_exec": "kernel_exec(code: str) -> dict: Execute Python in the session's persistent kernel. State persists across calls (variables/functions defined here are usable in later kernel_exec calls). Returns {ok, output, error, traceback}; print() surfaces results. Use for iterative/stateful computation where recomputing from scratch would be wasteful.",
    "kernel_reset": "kernel_reset() -> dict: Kill the persistent kernel so the next kernel_exec starts with a clean scope. Returns {ok, error}.",
}




def get_functions() -> dict[str, object]:
    return dict(FUNCTIONS)


def get_descriptions() -> dict[str, str]:
    return dict(FUNCTION_DESCRIPTIONS)


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--list-skills-json":
        print(json.dumps(list_skills()))
        return 0
    if len(sys.argv) > 1 and sys.argv[1] == "--describe-json":
        print(json.dumps(FUNCTION_DESCRIPTIONS))
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
