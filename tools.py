"""Predefined helper functions for code execution."""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
import signal
import shutil
import statistics
import subprocess
import sys
import threading
import time
import tempfile
import difflib
import textwrap
import bisect
import hashlib
import errno
import inspect
import types as _types
import uuid
from datetime import datetime, timezone
from typing import Iterable
import typing as _typing
import harness
import skills_deps

WORKSPACE_ROOT = Path.cwd().resolve()
NEXUS_DIR = Path.home() / ".nexus"
PLAN_STORE_DIR = NEXUS_DIR / "plans"
SUMMARY_PREVIEW_CHARS = 2000
MAX_DIFF_LINES = 600
MAX_HISTORY_EXCLUDE_MATCHES = 5000
EDIT_EVENT_LOG: list[str] = []
EDIT_SUMMARY_LOG: list[str] = []
HISTORY_ACTION_LOG: list[dict[str, object]] = []
PLAN_UI_EVENT_LOG: list[dict[str, object]] = []
BACKGROUND_JOB_EVENT_LOG: list[dict[str, object]] = []
SHELL_STREAM_WRITER = None


def _emit_voice_capture_event(event: str, **payload) -> None:
    print(json.dumps({"event": event, **payload}, ensure_ascii=False), flush=True)


def _run_voice_capture_helper(temp_directory: str, parent_pid: int) -> int:
    """Hold-to-talk Alt dictation using the default Windows microphone.

    While Alt is held, audio is captured through the waveform API and every
    ~1.2s the partial recording is snapshotted to a WAV file. Each snapshot is
    emitted as an ``interim_snapshot`` event so the parent TUI can stream live
    transcripts into the input box. Releasing Alt saves the full WAV and emits
    ``recording_stopped``; a non-modifier chord while holding Alt cancels.
    """
    if os.name != "nt":
        _emit_voice_capture_event("unavailable", error="push-to-talk is currently supported on Windows")
        return 1

    import ctypes
    import math
    import struct

    WAVE_FORMAT_PCM = 1
    WAVE_MAPPER = 0xFFFFFFFF
    CALLBACK_EVENT = 0x00050000
    MMSYSERR_NOERROR = 0
    WHDR_DONE = 0x00000001
    SYNCHRONIZE = 0x00100000
    WAIT_TIMEOUT = 0x00000102
    SAMPLE_RATE = 16000
    BUFFER_BYTES = 8192
    BUFFER_COUNT = 4
    INTERIM_INTERVAL_S = 0.8
    MAX_RECORDING_S = 300.0
    SILENCE_RMS = 260
    SILENCE_FINALIZE_S = 0.9
    RMS_WINDOW_BYTES = 16000

    target_dir = Path(temp_directory).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    winmm = ctypes.WinDLL("winmm", use_last_error=True)
    user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    user32.GetAsyncKeyState.restype = ctypes.c_short
    kernel32.OpenProcess.argtypes = [ctypes.c_uint, ctypes.c_int, ctypes.c_uint]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    kernel32.WaitForSingleObject.restype = ctypes.c_uint
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_int
    kernel32.CreateEventW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_wchar_p]
    kernel32.CreateEventW.restype = ctypes.c_void_p

    class WAVEFORMATEX(ctypes.Structure):
        _fields_ = [
            ("wFormatTag", ctypes.c_uint16),
            ("nChannels", ctypes.c_uint16),
            ("nSamplesPerSec", ctypes.c_uint32),
            ("nAvgBytesPerSec", ctypes.c_uint32),
            ("nBlockAlign", ctypes.c_uint16),
            ("wBitsPerSample", ctypes.c_uint16),
            ("cbSize", ctypes.c_uint16),
        ]

    class WAVEHDR(ctypes.Structure):
        _fields_ = [
            ("lpData", ctypes.POINTER(ctypes.c_char)),
            ("dwBufferLength", ctypes.c_uint32),
            ("dwBytesRecorded", ctypes.c_uint32),
            ("dwUser", ctypes.c_size_t),
            ("dwFlags", ctypes.c_uint32),
            ("dwLoops", ctypes.c_uint32),
            ("lpNext", ctypes.c_void_p),
            ("reserved", ctypes.c_size_t),
        ]

    winmm.waveInOpen.argtypes = [
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.c_uint,
        ctypes.POINTER(WAVEFORMATEX),
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_uint,
    ]
    winmm.waveInOpen.restype = ctypes.c_uint
    winmm.waveInPrepareHeader.argtypes = [ctypes.c_void_p, ctypes.POINTER(WAVEHDR), ctypes.c_uint]
    winmm.waveInPrepareHeader.restype = ctypes.c_uint
    winmm.waveInUnprepareHeader.argtypes = [ctypes.c_void_p, ctypes.POINTER(WAVEHDR), ctypes.c_uint]
    winmm.waveInUnprepareHeader.restype = ctypes.c_uint
    winmm.waveInAddBuffer.argtypes = [ctypes.c_void_p, ctypes.POINTER(WAVEHDR), ctypes.c_uint]
    winmm.waveInAddBuffer.restype = ctypes.c_uint
    winmm.waveInStart.argtypes = [ctypes.c_void_p]
    winmm.waveInStart.restype = ctypes.c_uint
    winmm.waveInReset.argtypes = [ctypes.c_void_p]
    winmm.waveInReset.restype = ctypes.c_uint
    winmm.waveInClose.argtypes = [ctypes.c_void_p]
    winmm.waveInClose.restype = ctypes.c_uint

    def build_wav(data: bytes) -> bytes:
        block_align = 2
        header = struct.pack(
            "<4sI4s4sIHHIIHH4sI",
            b"RIFF",
            36 + len(data),
            b"WAVE",
            b"fmt ",
            16,
            WAVE_FORMAT_PCM,
            1,
            SAMPLE_RATE,
            SAMPLE_RATE * block_align,
            block_align,
            16,
            b"data",
            len(data),
        )
        return header + data

    class WaveRecorder:
        def __init__(self) -> None:
            self.data = bytearray()
            self.data_lock = threading.Lock()
            self.buffers = []
            self.handle = ctypes.c_void_p(0)
            self.event_handle = None
            self.stop_event = threading.Event()
            self.thread = None

            format_ex = WAVEFORMATEX()
            format_ex.wFormatTag = WAVE_FORMAT_PCM
            format_ex.nChannels = 1
            format_ex.nSamplesPerSec = SAMPLE_RATE
            format_ex.wBitsPerSample = 16
            format_ex.nBlockAlign = 2
            format_ex.nAvgBytesPerSec = SAMPLE_RATE * 2
            format_ex.cbSize = 0
            self.event_handle = kernel32.CreateEventW(None, False, False, None)
            if not self.event_handle:
                raise RuntimeError("CreateEventW failed")
            error_code = winmm.waveInOpen(
                ctypes.byref(self.handle),
                WAVE_MAPPER,
                ctypes.byref(format_ex),
                self.event_handle,
                0,
                CALLBACK_EVENT,
            )
            if error_code != MMSYSERR_NOERROR:
                raise RuntimeError(f"waveInOpen failed (0x{error_code:x})")
            for _ in range(BUFFER_COUNT):
                raw = ctypes.create_string_buffer(BUFFER_BYTES)
                header = WAVEHDR()
                header.lpData = ctypes.cast(raw, ctypes.POINTER(ctypes.c_char))
                header.dwBufferLength = BUFFER_BYTES
                error_code = winmm.waveInPrepareHeader(
                    self.handle, ctypes.byref(header), ctypes.sizeof(WAVEHDR)
                )
                if error_code != MMSYSERR_NOERROR:
                    raise RuntimeError(f"waveInPrepareHeader failed (0x{error_code:x})")
                error_code = winmm.waveInAddBuffer(
                    self.handle, ctypes.byref(header), ctypes.sizeof(WAVEHDR)
                )
                if error_code != MMSYSERR_NOERROR:
                    raise RuntimeError(f"waveInAddBuffer failed (0x{error_code:x})")
                self.buffers.append((raw, header))
            error_code = winmm.waveInStart(self.handle)
            if error_code != MMSYSERR_NOERROR:
                raise RuntimeError(f"waveInStart failed (0x{error_code:x})")
            self.thread = threading.Thread(target=self._capture_loop, daemon=True)
            self.thread.start()

        def _capture_loop(self) -> None:
            while not self.stop_event.is_set():
                if kernel32.WaitForSingleObject(self.event_handle, 200) == WAIT_TIMEOUT:
                    continue
                if self.stop_event.is_set():
                    break
                self._drain()

        def _drain(self) -> None:
            block_align = 2
            for _, header in self.buffers:
                try:
                    if not (header.dwFlags & WHDR_DONE):
                        continue
                    recorded = int(header.dwBytesRecorded)
                    recorded -= recorded % block_align
                    if recorded > 0:
                        chunk = ctypes.string_at(header.lpData, recorded)
                        with self.data_lock:
                            self.data.extend(chunk)
                    header.dwFlags = 0
                    header.dwBytesRecorded = 0
                    winmm.waveInUnprepareHeader(self.handle, ctypes.byref(header), ctypes.sizeof(WAVEHDR))
                    winmm.waveInPrepareHeader(self.handle, ctypes.byref(header), ctypes.sizeof(WAVEHDR))
                    winmm.waveInAddBuffer(self.handle, ctypes.byref(header), ctypes.sizeof(WAVEHDR))
                except Exception:
                    # A transient winmm/ctypes error on one buffer must not
                    # kill the capture thread; the next drain retries.
                    pass

        def write_snapshot(self, path, start_byte: int = 0) -> int:
            with self.data_lock:
                data = bytes(self.data[start_byte:])
                total = len(self.data)
            path = Path(path)
            if data:
                path.write_bytes(build_wav(data))
            else:
                # Emit empty WAV so the parent can validate path + plumbing
                # even when no audio arrived yet.
                path.write_bytes(build_wav(b""))
            return total

        def full_data(self) -> bytes:
            with self.data_lock:
                return bytes(self.data)

        def length(self) -> int:
            with self.data_lock:
                return len(self.data)

        def rms_last(self, window_bytes: int) -> float:
            block_align = 2
            window_bytes -= window_bytes % block_align
            with self.data_lock:
                data = bytes(self.data[-window_bytes:]) if self.data else b""
            if len(data) < block_align:
                return 0.0
            count = len(data) // block_align
            samples = struct.unpack(f"<{count}h", data)
            return math.sqrt(sum(sample * sample for sample in samples) / count)

        def stop(self, path) -> int:
            # Never raise: even if winmm teardown misbehaves, the recording
            # must be written so the parent can transcribe it.
            self.stop_event.set()
            if self.thread:
                self.thread.join(timeout=1.0)
            try:
                self._drain()
            except Exception:
                pass
            with self.data_lock:
                total = len(self.data)
                data = bytes(self.data)
            if path is not None:
                try:
                    Path(path).write_bytes(build_wav(data))
                except Exception:
                    pass
            try:
                winmm.waveInReset(self.handle)
            except Exception:
                pass
            for _, header in self.buffers:
                try:
                    winmm.waveInUnprepareHeader(self.handle, ctypes.byref(header), ctypes.sizeof(WAVEHDR))
                except Exception:
                    pass
            try:
                winmm.waveInClose(self.handle)
            except Exception:
                pass
            if self.event_handle:
                try:
                    kernel32.CloseHandle(self.event_handle)
                except Exception:
                    pass
            return total

    parent_handle = kernel32.OpenProcess(SYNCHRONIZE, False, int(parent_pid))
    control = {"enabled": False, "stop": False}
    control_lock = threading.Lock()

    def read_control() -> None:
        try:
            for line in sys.stdin:
                try:
                    message = json.loads(line)
                except Exception:
                    continue
                with control_lock:
                    if "enabled" in message:
                        control["enabled"] = bool(message["enabled"])
                    if message.get("stop") is True:
                        control["stop"] = True
                        return
        finally:
            with control_lock:
                control["stop"] = True

    threading.Thread(target=read_control, daemon=True).start()

    recorder = None
    recording = False
    recording_path = None
    recording_started_at = 0.0
    last_interim_at = 0.0
    interim_index = 0
    last_speech_at = 0.0
    committed_bytes = 0
    utterance_active = False
    silence_committed = False
    alt_was_down = False
    chorded = False

    def has_non_modifier_key_down() -> bool:
        ignored = {
            0x01, 0x02, 0x04, 0x05, 0x06,  # mouse buttons
            0x10, 0x11, 0x12,              # Shift, Ctrl, Alt
            0x14, 0x90, 0x91,              # lock keys
            0x5B, 0x5C,                    # Windows keys
            0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5,
        }
        return any(
            virtual_key not in ignored and bool(user32.GetAsyncKeyState(virtual_key) & 0x8000)
            for virtual_key in range(0x08, 0xFF)
        )

    def stop_recording(save: bool):
        nonlocal recorder, recording, recording_path, recording_started_at, last_interim_at
        recorder_ref = recorder
        recorder = None
        path_value = str(recording_path or "")
        duration_ms = max(0, int((time.monotonic() - recording_started_at) * 1000))
        write_ok = False
        final_total = 0
        if recorder_ref is not None:
            try:
                if save and recording_path is not None:
                    target = str(recording_path)
                    try:
                        final_total = recorder_ref.stop(target)
                    except Exception:
                        # winmm teardown failed; recover by writing the PCM we
                        # already collected so the recording is never lost.
                        data = recorder_ref.full_data()
                        Path(target).write_bytes(build_wav(data))
                        final_total = len(data)
                    write_ok = Path(target).is_file() and Path(target).stat().st_size > 44
                else:
                    recorder_ref.stop(None)
            except Exception:
                write_ok = False
        last_speech_bytes = committed_bytes
        if last_speech_at > 0 and final_total > 0:
            last_speech_bytes = min(
                final_total,
                max(
                    committed_bytes,
                    int((last_speech_at - recording_started_at) * SAMPLE_RATE * 2),
                ),
            )
        last_speech_bytes -= last_speech_bytes % 2
        recording = False
        recording_path = None
        recording_started_at = 0.0
        last_interim_at = 0.0
        if not save and path_value:
            try:
                Path(path_value).unlink(missing_ok=True)
            except Exception:
                pass
        return path_value, duration_ms, write_ok, final_total, committed_bytes, last_speech_bytes

    _emit_voice_capture_event("ready")
    try:
        while True:
            with control_lock:
                enabled = control["enabled"]
                should_stop = control["stop"]
            if should_stop:
                break
            if parent_handle and kernel32.WaitForSingleObject(parent_handle, 0) != WAIT_TIMEOUT:
                break

            try:
                alt_down = bool(user32.GetAsyncKeyState(0x12) & 0x8000)
            except Exception as exc:
                _emit_voice_capture_event("error", error=f"voice capture state: {exc}")
                time.sleep(0.02)
                continue
            if not enabled:
                if recording:
                    stop_recording(False)
                    _emit_voice_capture_event("recording_cancelled")
                alt_was_down = alt_down
                chorded = False
                time.sleep(0.012)
                continue

            if alt_down and not alt_was_down:
                chorded = False
                recording_path = target_dir / f"recording-{int(time.time() * 1000)}.wav"
                try:
                    recorder = WaveRecorder()
                    recording = True
                    recording_started_at = time.monotonic()
                    last_interim_at = recording_started_at
                    last_speech_at = 0.0
                    committed_bytes = 0
                    utterance_active = False
                    silence_committed = False
                    _emit_voice_capture_event("recording_started", path=str(recording_path))
                except Exception as exc:
                    recorder = None
                    recording = False
                    recording_path = None
                    _emit_voice_capture_event("error", error=str(exc))

            if alt_down and recording and recorder is not None and has_non_modifier_key_down():
                chorded = True
                stop_recording(False)
                _emit_voice_capture_event("recording_cancelled")
                continue

            if alt_down and recording and (time.monotonic() - recording_started_at) >= MAX_RECORDING_S:
                path_value, duration_ms, write_ok, final_total, committed_value, speech_value = stop_recording(True)
                if write_ok:
                    _emit_voice_capture_event(
                        "recording_stopped",
                        path=path_value,
                        duration_ms=duration_ms,
                        reason="maximum duration reached",
                        total_bytes=final_total,
                        committed_bytes=committed_value,
                        speech_bytes=speech_value,
                    )
                else:
                    _emit_voice_capture_event("error", error="recording could not be saved")
                chorded = True

            now_monotonic = time.monotonic()
            speaking = False
            try:
                speaking = (
                    recording
                    and recorder is not None
                    and recorder.rms_last(RMS_WINDOW_BYTES) >= SILENCE_RMS
                )
            except Exception as exc:
                _emit_voice_capture_event("error", error=f"voice level check: {exc}")
            if speaking:
                last_speech_at = now_monotonic
                if not utterance_active:
                    utterance_active = True
                    silence_committed = False

            if (
                recording
                and recorder is not None
                and utterance_active
                and not silence_committed
                and (now_monotonic - last_speech_at) >= SILENCE_FINALIZE_S
            ):
                # The user stopped talking: finalize this utterance so the UI
                # commits the displayed text and stops changing it. New speech
                # after this point starts a fresh utterance with a byte offset
                # so only the NEW audio gets uploaded/transcribed.
                try:
                    silence_committed = True
                    utterance_active = False
                    committed_bytes = recorder.length()
                    _emit_voice_capture_event("utterance_committed")
                except Exception as exc:
                    _emit_voice_capture_event("error", error=f"utterance commit: {exc}")

            audio_growth_ready = False
            try:
                audio_growth_ready = recorder is not None and recorder.length() > committed_bytes
            except Exception as exc:
                _emit_voice_capture_event("error", error=f"audio length check: {exc}")

            if (
                alt_down
                and recording
                and recorder is not None
                and utterance_active
                and (speaking or (now_monotonic - last_speech_at) < 0.15)
                and (now_monotonic - last_interim_at) >= INTERIM_INTERVAL_S
                and audio_growth_ready
            ):
                last_interim_at = now_monotonic
                interim_index += 1
                snapshot_path = target_dir / f"interim-{int(time.time() * 1000)}-{interim_index}.wav"
                try:
                    total_bytes = recorder.write_snapshot(snapshot_path, committed_bytes)
                    if (
                        total_bytes > committed_bytes
                        and snapshot_path.is_file()
                        and snapshot_path.stat().st_size > 44
                    ):
                        duration_ms = max(0, int((now_monotonic - recording_started_at) * 1000))
                        _emit_voice_capture_event(
                            "interim_snapshot",
                            path=str(snapshot_path),
                            duration_ms=duration_ms,
                        )
                    else:
                        snapshot_path.unlink(missing_ok=True)
                except Exception:
                    try:
                        snapshot_path.unlink(missing_ok=True)
                    except Exception:
                        pass

            if not alt_down and alt_was_down:
                if recording and not chorded:
                    path_value, duration_ms, write_ok, final_total, committed_value, speech_value = stop_recording(True)
                    if write_ok:
                        _emit_voice_capture_event(
                            "recording_stopped",
                            path=path_value,
                            duration_ms=duration_ms,
                            total_bytes=final_total,
                            committed_bytes=committed_value,
                            speech_bytes=speech_value,
                        )
                    else:
                        _emit_voice_capture_event("error", error="recording could not be saved")
                chorded = False

            alt_was_down = alt_down
            time.sleep(0.012)
    finally:
        if recording and recorder is not None:
            try:
                stop_recording(False)
            except Exception:
                pass
        if parent_handle:
            kernel32.CloseHandle(parent_handle)
    return 0






def set_shell_stream_writer(writer) -> None:
    """Set an execute-transport-only callback for live foreground shell output."""
    global SHELL_STREAM_WRITER
    SHELL_STREAM_WRITER = writer if callable(writer) else None


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


def drain_background_job_events() -> list[dict[str, object]]:
    events = list(BACKGROUND_JOB_EVENT_LOG)
    BACKGROUND_JOB_EVENT_LOG.clear()
    return events


def _record_plan_ui_event(entries: list[dict[str, object]], action: str = "plan") -> None:
    PLAN_UI_EVENT_LOG.append(
        {
            "type": "plan",
            "action": action,
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


def _ensure_plan_store_ready() -> None:
    NEXUS_DIR.mkdir(parents=True, exist_ok=True)
    PLAN_STORE_DIR.mkdir(parents=True, exist_ok=True)


def _get_plan_store_file() -> Path:
    _ensure_plan_store_ready()
    runtime_session_id = harness.get_agent_runtime_session_id().strip()
    scope = f"{WORKSPACE_ROOT}\0{runtime_session_id}" if runtime_session_id else str(WORKSPACE_ROOT)
    scope_key = hashlib.sha1(scope.encode("utf-8")).hexdigest()
    return PLAN_STORE_DIR / f"plan-{scope_key}.json"


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
    _record_plan_ui_event(plan_entries, "create_plan")

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
    _record_plan_ui_event(entries, "update_plan")
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


def _create_windows_kill_job(process: subprocess.Popen):
    """Assign a child to a kill-on-close Windows Job Object using only stdlib ctypes."""
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_ulonglong),
                ("WriteOperationCount", ctypes.c_ulonglong),
                ("OtherOperationCount", ctypes.c_ulonglong),
                ("ReadTransferCount", ctypes.c_ulonglong),
                ("WriteTransferCount", ctypes.c_ulonglong),
                ("OtherTransferCount", ctypes.c_ulonglong),
            ]

        class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            return None
        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = 0x00002000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        configured = kernel32.SetInformationJobObject(
            job, 9, ctypes.byref(info), ctypes.sizeof(info)
        )
        assigned = configured and kernel32.AssignProcessToJobObject(
            job, wintypes.HANDLE(int(process._handle))
        )
        if not assigned:
            kernel32.CloseHandle(job)
            return None
        return job
    except Exception:
        return None


def _close_windows_job(job, terminate: bool = False) -> None:
    if not job or os.name != "nt":
        return
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        if terminate:
            kernel32.TerminateJobObject(job, 1)
        kernel32.CloseHandle(job)
    except Exception:
        pass


def _terminate_process_tree(process: subprocess.Popen, windows_job=None) -> None:
    """Terminate a shell and all descendants without waiting indefinitely on inherited pipes."""
    if os.name == "nt":
        if windows_job:
            _close_windows_job(windows_job, terminate=True)
            return
        try:
            process.send_signal(signal.CTRL_BREAK_EVENT)
            process.wait(timeout=1)
            return
        except Exception:
            pass
        try:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                timeout=2,
                check=False,
            )
            return
        except Exception:
            pass
    else:
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            return
        except Exception:
            pass
    try:
        process.kill()
    except Exception:
        pass


def run_shell(
    command: str,
    timeout: int | float = 10,
    background: bool = False,
) -> dict[str, object]:
    """Run synchronously with a timeout, or launch a TUI-owned background job capped at 10 minutes."""
    if not isinstance(command, str) or not command.strip():
        raise ValueError("command must be a non-empty string")
    if not isinstance(background, bool):
        raise ValueError("background must be a boolean")

    if background:
        result = _bridge_request(
            "background_shell",
            {"command": command.strip()},
        )
        if result.get("ok") and result.get("job_id"):
            BACKGROUND_JOB_EVENT_LOG.append({"job_id": str(result["job_id"])})
        return result

    try:
        timeout_seconds = float(timeout)
    except (TypeError, ValueError) as exc:
        raise ValueError("timeout must be a number") from exc

    if timeout_seconds <= 0:
        raise ValueError("timeout must be greater than 0")
    if timeout_seconds > 600:
        raise ValueError("timeout must be <= 600 seconds")

    popen_options: dict[str, object] = {}
    if os.name == "nt":
        popen_options["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        popen_options["start_new_session"] = True
    process = subprocess.Popen(
        command,
        shell=True,
        cwd=str(WORKSPACE_ROOT),
        # Python otherwise block-buffers stdout when it is connected to the
        # execute transport pipe, so normal print() calls would only appear
        # after the command exits. Other programs simply ignore this variable.
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        **popen_options,
    )
    windows_job = _create_windows_kill_job(process)
    stdout_chunks: list[str] = []
    stderr_chunks: list[str] = []

    def pump_stream(pipe, stream_name: str, chunks: list[str]) -> None:
        if pipe is None:
            return
        try:
            for value in iter(pipe.readline, ""):
                chunks.append(value)
                writer = SHELL_STREAM_WRITER
                if writer is not None:
                    try:
                        writer(stream_name, value)
                    except Exception:
                        pass
        finally:
            try:
                pipe.close()
            except Exception:
                pass

    stdout_thread = threading.Thread(
        target=pump_stream,
        args=(process.stdout, "stdout", stdout_chunks),
        daemon=True,
    )
    stderr_thread = threading.Thread(
        target=pump_stream,
        args=(process.stderr, "stderr", stderr_chunks),
        daemon=True,
    )
    stdout_thread.start()
    stderr_thread.start()

    timed_out = False
    try:
        process.wait(timeout=timeout_seconds)
        _close_windows_job(windows_job)
    except subprocess.TimeoutExpired:
        timed_out = True
        _terminate_process_tree(process, windows_job)
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
            except Exception:
                pass
    finally:
        for thread in (stdout_thread, stderr_thread):
            thread.join(timeout=1)
        for pipe in (process.stdout, process.stderr):
            if pipe is not None:
                try:
                    pipe.close()
                except Exception:
                    pass

    result = {
        "ok": not timed_out and process.returncode == 0,
        "exit_code": None if timed_out else int(process.returncode),
        "stdout": "".join(stdout_chunks),
        "stderr": "".join(stderr_chunks),
        "timed_out": timed_out,
    }
    if timed_out:
        result["error"] = f"Command timed out after {timeout_seconds:g}s"
    return result


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


_SKILL_INDEX_CACHE: dict = {"url": "", "data": None, "fetched_at": 0.0}
SKILL_INDEX_TTL_SECONDS = 600
DEFAULT_SKILLS_REPO = "bevren/nexus-skills"


def search_skill(
    query: str,
    max_results: int = 10,
    repo: str = "",
) -> dict[str, object]:
    """Search the public nexus-skills registry for installable skills.

    Fetches the registry index (index.json) from a GitHub repo and matches the
    query against each skill's name and description. The default registry is
    bevren/nexus-skills on the main branch; override with the repo parameter
    ("owner/name") or the NEXUS_SKILLS_REPO environment variable.

    Returns a dict with:
      - ok: True if the registry was fetched and searched successfully
      - query: the original query
      - repo: the registry repo actually used
      - skills: list of {name, description, raw_url} matches (raw_url points at
        the skill's SKILL.md for direct install with manage_skill)
      - error: error message if the registry could not be reached/parsed
    """
    import urllib.error
    import urllib.request

    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must be a non-empty string")
    if not isinstance(max_results, int):
        raise ValueError("max_results must be an integer")
    max_results = max(1, min(max_results, 50))

    repo_key = str(repo or os.environ.get("NEXUS_SKILLS_REPO") or DEFAULT_SKILLS_REPO).strip().rstrip("/")
    index_url = f"https://raw.githubusercontent.com/{repo_key}/main/index.json"

    now = time.time()
    cache = _SKILL_INDEX_CACHE
    if cache.get("url") == index_url and cache.get("data") is not None and now - cache.get("fetched_at", 0.0) < SKILL_INDEX_TTL_SECONDS:
        payload = cache["data"]
    else:
        try:
            req = urllib.request.Request(
                index_url,
                headers={"User-Agent": "Mozilla/5.0 nexus-skills-search"},
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read(1_000_000)
            payload = json.loads(raw.decode("utf-8", errors="replace"))
            if not isinstance(payload, dict) or not isinstance(payload.get("skills"), list):
                return {"ok": False, "query": query.strip(), "repo": repo_key, "skills": [], "error": "registry index has no skills list"}
            cache["url"] = index_url
            cache["data"] = payload
            cache["fetched_at"] = now
        except urllib.error.HTTPError as exc:
            return {"ok": False, "query": query.strip(), "repo": repo_key, "skills": [], "error": "HTTP " + str(exc.code) + ": " + str(exc.reason)}
        except urllib.error.URLError as exc:
            return {"ok": False, "query": query.strip(), "repo": repo_key, "skills": [], "error": "request failed: " + str(exc.reason)}
        except Exception as exc:
            return {"ok": False, "query": query.strip(), "repo": repo_key, "skills": [], "error": "search failed: " + str(exc)}

    q = query.strip().lower()
    q_tokens = set(re.findall(r"[a-z0-9]+", q))
    scored = []
    for skill in payload["skills"]:
        if not isinstance(skill, dict):
            continue
        name = str(skill.get("name") or "")
        description = str(skill.get("description") or "")
        haystack = (name + " " + description).lower()
        score = 0
        if name.lower() == q:
            score += 500
        if q in name.lower():
            score += 200
        if q in haystack:
            score += 100
        score += len(q_tokens & set(re.findall(r"[a-z0-9]+", haystack))) * 10
        if score > 0:
            scored.append((score, name, description))
    scored.sort(key=lambda t: (-t[0], t[1].lower()))
    skills = [
        {
            "name": name,
            "description": description,
            "raw_url": f"https://raw.githubusercontent.com/{repo_key}/main/{name}/SKILL.md",
        }
        for _score, name, description in scored[:max_results]
    ]
    return {"ok": True, "query": query.strip(), "repo": repo_key, "skills": skills, "error": ""}


def manage_skill(
    name: str,
    description: str = "",
    body: str = "",
    delete: bool = False,
) -> dict[str, object]:
    """Create, update, or delete a personal skill in ~/.nexus/skills."""
    key = str(name or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", key) or key in {".", ".."}:
        return {"ok": False, "error": "skill name must use only letters, numbers, dot, underscore, or hyphen"}

    personal_root = SKILLS_DIRS[0].resolve()
    target = (personal_root / key).resolve()
    try:
        target.relative_to(personal_root)
    except ValueError:
        return {"ok": False, "error": "skill path must stay inside ~/.nexus/skills"}

    if delete:
        if not target.exists():
            return {"ok": True, "deleted": False, "name": key, "scope": "personal"}
        shutil.rmtree(target)
        return {"ok": True, "deleted": True, "name": key, "scope": "personal"}

    skill_file = target / "SKILL.md"
    existing_description = ""
    existing_body = ""
    existing_frontmatter = ""
    if skill_file.exists():
        raw = skill_file.read_text(encoding="utf-8", errors="replace")
        _old_name, existing_description, existing_frontmatter, existing_body = _parse_skill_frontmatter(raw)
    elif not str(body or "").strip():
        return {"ok": False, "error": "body is required when creating a skill", "name": key}

    next_description = str(description).strip() if str(description).strip() else existing_description
    next_body = str(body).strip() if str(body).strip() else existing_body.strip()
    frontmatter_lines = []
    saw_name = False
    saw_description = False
    for line in existing_frontmatter.splitlines():
        stripped = line.strip()
        if stripped.startswith("name:"):
            frontmatter_lines.append(f"name: {key}")
            saw_name = True
        elif stripped.startswith("description:"):
            frontmatter_lines.append(f"description: {next_description.replace(chr(10), ' ')}")
            saw_description = True
        else:
            frontmatter_lines.append(line)
    if not saw_name:
        frontmatter_lines.insert(0, f"name: {key}")
    if not saw_description:
        frontmatter_lines.append(f"description: {next_description.replace(chr(10), ' ')}")

    target.mkdir(parents=True, exist_ok=True)
    rendered = "---\n" + "\n".join(frontmatter_lines) + "\n---\n\n" + next_body + "\n"
    skill_file.write_text(rendered, encoding="utf-8")
    return {
        "ok": True,
        "created": not bool(existing_frontmatter or existing_body),
        "name": key,
        "scope": "personal",
        "path": str(target),
    }



# --- RLM subagents + continual harness (Prime Agent-style interfaces) ---

def configure_subagent_runtime(
    system_prompt: str,
    model: str = "",
    reasoning_enabled: bool = False,
    reasoning_effort: str = "low",
    session_id: str = "",
    collaboration_mode: str = "build",
    runtime_settings: dict | None = None,
) -> None:
    """Internal bridge: make child agents inherit the active Nexus runtime."""
    harness.configure_agent_runtime(
        system_prompt=system_prompt,
        model=model,
        reasoning_enabled=reasoning_enabled,
        reasoning_effort=reasoning_effort,
        session_id=session_id,
        collaboration_mode=collaboration_mode,
        runtime_settings=runtime_settings,
    )


def _normalize_named_agent_name(value: str) -> str:
    name = str(value or "").strip()
    if not name or len(name) > 48 or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name):
        raise ValueError("agent name must use letters, numbers, dot, dash, or underscore (max 48 characters)")
    return name


def _named_agent_record_path(name: str) -> Path:
    workspace_scope = hashlib.sha256(str(WORKSPACE_ROOT).encode("utf-8")).hexdigest()[:16]
    key = name.lower()
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]
    prefix = re.sub(r"[^a-z0-9._-]+", "-", key)[:24] or "agent"
    return NEXUS_DIR / "agents" / workspace_scope / f"{prefix}-{digest}.json"


def _read_named_agent_record(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, ValueError, TypeError):
        return None


def _write_named_agent_record(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        for attempt in range(10):
            try:
                os.replace(temporary, path)
                return
            except OSError as exc:
                transient = (
                    exc.errno in {errno.EACCES, errno.EPERM, errno.EBUSY}
                    or getattr(exc, "winerror", None) in {5, 32, 33}
                )
                if not transient or attempt == 9:
                    raise
                time.sleep(min(0.4, 0.02 * (2 ** attempt)))
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _new_named_agent_record(name: str, task: str) -> dict:
    runtime = harness.get_agent_runtime()
    now = time.time()
    session_uid = uuid.uuid4().hex
    model = str(runtime.get("model") or "")
    settings = dict(runtime.get("settings") or {})
    request_timeout_ms = settings.get("request_timeout_ms", 300_000)
    try:
        request_timeout = max(1, round(float(request_timeout_ms) / 1000))
    except (TypeError, ValueError):
        request_timeout = 300
    reasoning_enabled = bool(runtime.get("reasoning_enabled"))
    reasoning_effort = str(runtime.get("reasoning_effort") or "low")
    collaboration_mode = "plan" if runtime.get("collaboration_mode") == "plan" else "build"
    system_prompt = str(runtime.get("system_prompt") or "")
    return {
        "kind": "named-agent",
        "id": "agent-" + hashlib.sha256(f"{WORKSPACE_ROOT}:{name.lower()}".encode("utf-8")).hexdigest()[:16],
        "name": name,
        "session_uid": session_uid,
        "session_title": task,
        "workspace": str(WORKSPACE_ROOT),
        "model": model,
        "timeout": request_timeout,
        "max_tokens": 0,
        "reasoning_enabled": reasoning_enabled,
        "reasoning_effort": reasoning_effort,
        "messages": [{"role": "system", "content": system_prompt}],
        "status": "idle",
        "result": None,
        "error": None,
        "created_at": now,
        "updated_at": now,
        "turn": 0,
        "runtime": {
            "system_prompt": system_prompt,
            "model": model,
            "reasoning_enabled": reasoning_enabled,
            "reasoning_effort": reasoning_effort,
            "collaboration_mode": collaboration_mode,
            "session_id": f"named-{name.lower()}-{session_uid}",
        },
        "session_runtime": {
            "model": model,
            "collaboration_mode": collaboration_mode,
            "reasoning_by_model": {model: reasoning_enabled} if model else {},
            "settings": settings,
            "context_left_by_model": {},
            "cache_telemetry_by_model": {},
        },
    }


def _admit_named_agent(name: str, task: str) -> dict:
    normalized_name = _normalize_named_agent_name(name)
    normalized_task = str(task or "").strip()
    if not normalized_task:
        return {"ok": False, "agent": normalized_name, "error": "task must be non-empty"}
    if normalized_name.lower() == "main":
        return {"ok": False, "agent": normalized_name, "error": "main must be targeted through the Nexus session router"}
    runtime_session_id = str(harness.get_agent_runtime().get("session_id") or "").lower()
    if runtime_session_id.startswith(f"named-{normalized_name.lower()}-"):
        return {"ok": False, "agent": normalized_name, "error": "an agent cannot delegate a task to itself"}

    record_path = _named_agent_record_path(normalized_name)
    record = _read_named_agent_record(record_path)
    if not record:
        record = _new_named_agent_record(normalized_name, normalized_task)
    status = str(record.get("status") or "idle").lower()
    if status in {"admitted", "running"}:
        return {"ok": False, "agent": str(record.get("name") or normalized_name), "status": status, "error": f"Agent {record.get('name') or normalized_name} is already working"}

    call_id = uuid.uuid4().hex
    record["messages"] = list(record.get("messages") or [])
    record["messages"].append({"role": "user", "content": normalized_task})
    if not str(record.get("session_title") or "").strip():
        record["session_title"] = normalized_task
    record["prompt"] = normalized_task
    record["status"] = "admitted"
    record["result"] = None
    record["error"] = None
    record["pid"] = None
    record["task_started_at"] = time.time()
    record["active_loop_id"] = ""
    record["main_handoff_id"] = ""
    record["agent_tool_call_id"] = call_id
    record["updated_at"] = time.time()
    _write_named_agent_record(record_path, record)
    try:
        pid = harness.launch_subagent_job(str(record_path))
    except Exception as exc:
        latest = _read_named_agent_record(record_path) or record
        if latest.get("agent_tool_call_id") == call_id:
            latest["status"] = "stopped"
            latest["error"] = f"failed to launch agent: {exc}"
            latest["updated_at"] = time.time()
            _write_named_agent_record(record_path, latest)
        return {"ok": False, "agent": str(record.get("name") or normalized_name), "status": "stopped", "error": str(exc)}
    return {
        "ok": True,
        "agent": str(record.get("name") or normalized_name),
        "status": "admitted",
        "pid": pid,
        "call_id": call_id,
        "record_path": str(record_path),
    }


def notify_agent(name: str, task: str) -> dict:
    """Start a named Nexus agent and return as soon as its task is admitted."""
    admitted = _admit_named_agent(name, task)
    admitted.pop("record_path", None)
    admitted.pop("call_id", None)
    return admitted


def delegate_agent(
    name: str,
    task: str,
    timeout: int | float = 240,
    poll_interval: int | float = 0.25,
) -> dict:
    """Run a task in a named Nexus agent and wait for its terminal result."""
    admitted = _admit_named_agent(name, task)
    if not admitted.get("ok"):
        admitted.pop("record_path", None)
        admitted.pop("call_id", None)
        return admitted
    try:
        timeout_seconds = max(0.1, min(3600.0, float(timeout)))
        interval_seconds = max(0.05, min(2.0, float(poll_interval)))
    except (TypeError, ValueError):
        return {"ok": False, "agent": admitted["agent"], "status": "admitted", "error": "timeout and poll_interval must be numbers"}
    deadline = time.monotonic() + timeout_seconds
    record_path = Path(admitted["record_path"])
    call_id = admitted["call_id"]
    while time.monotonic() < deadline:
        record = _read_named_agent_record(record_path)
        if record and record.get("agent_tool_call_id") != call_id:
            return {"ok": False, "agent": admitted["agent"], "status": "stopped", "error": "agent session changed while waiting for its result"}
        status = str((record or {}).get("status") or "admitted").lower()
        if status in {"done", "error", "stopped"}:
            result = str((record or {}).get("result") or "").strip()
            error = str((record or {}).get("error") or "").strip()
            if status == "done":
                return {"ok": True, "agent": str((record or {}).get("name") or admitted["agent"]), "status": status, "result": result}
            return {"ok": False, "agent": str((record or {}).get("name") or admitted["agent"]), "status": status, "error": error or "agent stopped before completing the task"}
        time.sleep(interval_seconds)
    return {
        "ok": False,
        "agent": admitted["agent"],
        "status": "running",
        "error": f"timed out after {timeout_seconds:g}s while waiting; the named agent is still running",
    }


def _run_named_agent_tool_self_test() -> dict:
    """Exercise named-agent admission/result behavior without a live provider."""
    global NEXUS_DIR
    temporary_root = Path(tempfile.mkdtemp(prefix="nexus-agent-tools-"))
    original_nexus_dir = NEXUS_DIR
    original_launcher = harness.launch_subagent_job
    try:
        NEXUS_DIR = temporary_root
        configure_subagent_runtime(
            system_prompt="named agent tool self-test",
            model="self-test/model",
            reasoning_enabled=True,
            reasoning_effort="high",
            session_id="main-self-test",
            collaboration_mode="build",
            runtime_settings={"context_window": 1_000_000, "request_timeout_ms": 600_000},
        )

        def complete_agent(job_path: str) -> int:
            path = Path(job_path)
            record = _read_named_agent_record(path)
            if not record:
                raise AssertionError("delegated agent record was not written")
            record["status"] = "done"
            record["result"] = "delegated answer"
            _write_named_agent_record(path, record)
            return 321

        harness.launch_subagent_job = complete_agent
        delegated = delegate_agent("Kral", "check weather", timeout=1)
        if delegated != {
            "ok": True,
            "agent": "Kral",
            "status": "done",
            "result": "delegated answer",
        }:
            raise AssertionError(f"delegate_agent returned an unexpected result: {delegated}")

        harness.launch_subagent_job = lambda _job_path: 654
        notified = notify_agent("Price", "check gold")
        if notified != {
            "ok": True,
            "agent": "Price",
            "status": "admitted",
            "pid": 654,
        }:
            raise AssertionError(f"notify_agent returned an unexpected result: {notified}")
        price_record = _read_named_agent_record(_named_agent_record_path("Price")) or {}
        context_window = ((price_record.get("session_runtime") or {}).get("settings") or {}).get("context_window")
        if context_window != 1_000_000:
            raise AssertionError("named agent did not inherit the source session runtime settings")
        listed_agents = {
            item.get("name"): item
            for item in list_subagents()
            if item.get("kind") == "named-agent"
        }
        if listed_agents.get("Kral", {}).get("status") != "idle":
            raise AssertionError("completed named agent was not listed as idle")
        if listed_agents.get("Kral", {}).get("task_status") != "done":
            raise AssertionError("completed named agent lost its raw task status")
        if listed_agents.get("Price", {}).get("status") != "running":
            raise AssertionError("admitted named agent was not listed as running")

        price_record["status"] = "stopped"
        price_record["error"] = "Stopped by user"
        _write_named_agent_record(_named_agent_record_path("Price"), price_record)
        stopped_agents = {
            item.get("name"): item
            for item in list_subagents()
            if item.get("kind") == "named-agent"
        }
        if stopped_agents.get("Price", {}).get("status") != "stopped":
            raise AssertionError("stopped named agent was not listed as stopped")
        kral_id = str(listed_agents.get("Kral", {}).get("id") or "")
        waited = wait_subagents([kral_id], timeout=1, poll_interval=0.05)
        if (
            len(waited) != 1
            or waited[0].get("name") != "Kral"
            or waited[0].get("status") != "idle"
            or waited[0].get("result") != "delegated answer"
        ):
            raise AssertionError(f"wait_subagents did not return completed named agent: {waited}")
        missing_started = time.monotonic()
        missing = wait_subagents(["agent-does-not-exist"], timeout=10, poll_interval=0.05)
        if (
            time.monotonic() - missing_started >= 1
            or missing != [{
                "ok": False,
                "id": "agent-does-not-exist",
                "status": "stopped",
                "task_status": "missing",
                "error": "agent not found",
            }]
        ):
            raise AssertionError(f"wait_subagents did not reject an unknown agent immediately: {missing}")
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    finally:
        harness.launch_subagent_job = original_launcher
        NEXUS_DIR = original_nexus_dir
        shutil.rmtree(temporary_root, ignore_errors=True)

def rlm_spawn(
    prompt: str,
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
                system=system or None,
                timeout=timeout,
                max_tokens=max_tokens,
            )
        return handle.to_dict()
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _agent_activity_status(value: object) -> str:
    """Normalize persisted task states into the statuses shown by Nexus."""
    raw = str(value or "idle").strip().lower()
    if raw in {"admitted", "running"}:
        return "running"
    if raw in {"error", "stopped", "cancelled", "killed"}:
        return "stopped"
    return "idle"


def _list_named_agent_records() -> list[dict]:
    """Read every named agent belonging to the current workspace."""
    workspace_scope = hashlib.sha256(str(WORKSPACE_ROOT).encode("utf-8")).hexdigest()[:16]
    directory = NEXUS_DIR / "agents" / workspace_scope
    if not directory.exists():
        return []

    expected_workspace = os.path.normcase(str(WORKSPACE_ROOT))
    agents = []
    for record_path in directory.glob("*.json"):
        record = _read_named_agent_record(record_path)
        if not record or record.get("kind") != "named-agent":
            continue
        record_workspace = os.path.normcase(str(record.get("workspace") or ""))
        if record_workspace and record_workspace != expected_workspace:
            continue
        raw_status = str(record.get("status") or "idle").strip().lower()
        agents.append({
            "kind": "named-agent",
            "id": record.get("id"),
            "name": record.get("name"),
            "status": _agent_activity_status(raw_status),
            "task_status": raw_status,
            "prompt": str(record.get("prompt") or record.get("session_title") or "")[:200],
            "result": record.get("result"),
            "error": record.get("error"),
            "model": record.get("model"),
            "turn": record.get("turn", 0),
            "pid": record.get("pid"),
            "created_at": record.get("created_at"),
            "updated_at": record.get("updated_at"),
        })
    return agents


def list_subagents() -> list[dict]:
    """List all workspace named agents and session-spawned child agents."""
    try:
        agents = _list_named_agent_records()
        for record in harness.rlm.list_subagents():
            raw_status = str(record.get("status") or "idle").strip().lower()
            agents.append({
                **record,
                "kind": "spawned-agent",
                "status": _agent_activity_status(raw_status),
                "task_status": raw_status,
            })
        return sorted(agents, key=lambda item: float(item.get("created_at") or 0))
    except Exception as exc:
        return [{"ok": False, "error": str(exc)}]


def wait_subagents(
    handle_ids: list[str] | None = None,
    timeout: int | float = 300,
    poll_interval: int | float = 0.5,
) -> list[dict]:
    """Wait for selected named or spawned agents to become idle/stopped.

    Workers and status survive across tool executions. A running status is
    progress, not a failure.
    """
    requested = [handle_ids] if isinstance(handle_ids, str) else (handle_ids or [])
    selected = {str(value).strip() for value in requested if str(value).strip()}
    selected_keys = {value.casefold() for value in selected}
    timeout_seconds = max(0.0, min(float(timeout), 3600.0))
    interval_seconds = max(0.05, min(float(poll_interval), 5.0))
    deadline = time.monotonic() + timeout_seconds

    while True:
        records = list_subagents()
        if any(record.get("ok") is False for record in records):
            return records
        if selected:
            records = [
                record
                for record in records
                if str(record.get("id") or "").casefold() in selected_keys
                or str(record.get("name") or "").casefold() in selected_keys
            ]
            found = {
                key
                for record in records
                for key in (
                    str(record.get("id") or "").casefold(),
                    str(record.get("name") or "").casefold(),
                )
                if key in selected_keys
            }
            missing = sorted(selected_keys - found)
            if missing:
                return records + [
                    {
                        "ok": False,
                        "id": value,
                        "status": "stopped",
                        "task_status": "missing",
                        "error": "agent not found",
                    }
                    for value in missing
                ]
        if not records:
            return []
        terminal = {"idle", "stopped"}
        if all(str(record.get("status") or "").lower() in terminal for record in records):
            return records
        if time.monotonic() >= deadline:
            return records
        time.sleep(min(interval_seconds, max(0.0, deadline - time.monotonic())))


def delete_subagent(handle_id: str) -> dict:
    """Delete a spawned child sub-agent by handle id."""
    try:
        return harness.rlm.delete_subagent(handle_id)
    except Exception as exc:
        return {"deleted": False, "error": str(exc)}


def harness_overview() -> dict:
    """Continual harness overview: memories, skills, subagent templates, prompt notes, refinements."""
    try:
        overview = harness.rlm.harness.overview()
        catalog = list_skills()
        overview["skills"] = [item["name"] for item in catalog.get("skills", [])]
        return overview
    except Exception as exc:
        return {"error": str(exc)}


def harness_memory(key: str, content: str = "", delete: bool = False) -> dict:
    """Read a memory by key, or create/update/delete it when requested."""
    try:
        h = harness.rlm.harness
        if delete:
            return h.delete_memory(key)
        if content == "":
            return h.get_memory(key)
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
        {
            "method": "reminder",
            "when": when.strip(),
            "prompt": prompt.strip(),
            "session_id": harness.get_agent_runtime_session_id(),
        }
    ).encode("utf-8")
    try:
        req = urllib.request.Request(
            url, data=payload, headers={"Content-Type": "application/json"}, method="POST"
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        return {"ok": False, "error": f"set_reminder: bridge request failed: {exc}"}


def _bridge_request(method: str, payload: dict, timeout: float = 180) -> dict:
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
        with urllib.request.urlopen(req, timeout=max(1.0, float(timeout))) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        return {"ok": False, "error": f"bridge request failed: {exc}"}


def _expand_workspace_media_paths(value, extensions: set[str], tool_name: str) -> list[str]:
    if isinstance(value, (str, os.PathLike)):
        requested = [str(value)]
    elif isinstance(value, (list, tuple, set)):
        requested = [str(item) for item in value]
    else:
        raise ValueError(f"{tool_name}: expected a path or list of paths")

    resolved: list[Path] = []
    for item in requested:
        candidate = _resolve_workspace_path(item)
        if not candidate.exists():
            raise ValueError(f"{tool_name}: path does not exist: {item}")
        if candidate.is_dir():
            resolved.extend(
                child.resolve()
                for child in sorted(candidate.rglob("*"), key=lambda path_value: str(path_value).lower())
                if child.is_file() and child.suffix.lower() in extensions
            )
        elif candidate.is_file():
            if candidate.suffix.lower() not in extensions:
                raise ValueError(f"{tool_name}: unsupported file format: {candidate.suffix or 'none'}")
            resolved.append(candidate)
        else:
            raise ValueError(f"{tool_name}: path is not a file or directory: {item}")

    unique: list[str] = []
    seen: set[str] = set()
    for candidate in resolved:
        checked = _resolve_workspace_path(str(candidate))
        key = str(checked).casefold() if os.name == "nt" else str(checked)
        if key in seen:
            continue
        seen.add(key)
        unique.append(checked.relative_to(WORKSPACE_ROOT).as_posix())
    if not unique:
        supported = ", ".join(sorted(extensions))
        raise ValueError(f"{tool_name}: no supported files found ({supported})")
    if len(unique) > 20:
        raise ValueError(f"{tool_name}: at most 20 files can be processed per call")
    return unique


def _media_runtime_payload(setting_key: str) -> tuple[str, str, int]:
    runtime = harness.get_agent_runtime()
    settings = runtime.get("settings") if isinstance(runtime.get("settings"), dict) else {}
    profile = str(settings.get(setting_key) or "").strip()
    session_id = str(runtime.get("session_id") or "")
    try:
        timeout_ms = max(1_000, int(settings.get("request_timeout_ms") or 600_000))
    except (TypeError, ValueError):
        timeout_ms = 600_000
    return profile, session_id, timeout_ms


def transcribe_audio(audios, language: str = "") -> dict:
    """Transcribe workspace audio using the Speech to text profile selected in /settings."""
    try:
        paths = _expand_workspace_media_paths(
            audios,
            {".wav", ".mp3", ".flac", ".m4a", ".ogg", ".webm", ".aac"},
            "transcribe_audio",
        )
        profile, session_id, timeout_ms = _media_runtime_payload("speech_to_text_model")
        bridge_timeout = min(3_600.0, max(180.0, timeout_ms / 1000 * len(paths) + 30))
        return _bridge_request(
            "media",
            {
                "action": "transcribe_audio",
                "paths": paths,
                "profile": profile,
                "session_id": session_id,
                "timeout_ms": timeout_ms,
                "language": str(language or "").strip(),
            },
            timeout=bridge_timeout,
        )
    except Exception as exc:
        return {"ok": False, "error": f"transcribe_audio: {exc}"}


def describe_image(images, prompt: str = "Describe this image accurately and concisely.") -> dict:
    """Describe workspace images using the Vision model profile selected in /settings."""
    try:
        paths = _expand_workspace_media_paths(
            images,
            {".png", ".jpg", ".jpeg", ".webp", ".gif"},
            "describe_image",
        )
        clean_prompt = str(prompt or "").strip()
        if not clean_prompt:
            raise ValueError("prompt must be non-empty")
        profile, session_id, timeout_ms = _media_runtime_payload("vision_model")
        bridge_timeout = min(3_600.0, max(180.0, timeout_ms / 1000 * len(paths) + 30))
        return _bridge_request(
            "media",
            {
                "action": "describe_image",
                "paths": paths,
                "profile": profile,
                "session_id": session_id,
                "timeout_ms": timeout_ms,
                "prompt": clean_prompt,
            },
            timeout=bridge_timeout,
        )
    except Exception as exc:
        return {"ok": False, "error": f"describe_image: {exc}"}


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
    env_port = os.environ.get("NEXUS_TUI_BRIDGE_PORT", "").strip()
    if env_port:
        try:
            port = int(env_port)
            if port > 0:
                return {"port": port, "pid": os.environ.get("NEXUS_TUI_BRIDGE_PID", "")}
        except ValueError:
            pass
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
    payload = json.dumps({
        "method": "list",
        "session_id": harness.get_agent_runtime_session_id(),
    }).encode("utf-8")
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
    payload = json.dumps({
        "method": "call",
        "server": server,
        "tool": tool,
        "arguments": args,
        "session_id": harness.get_agent_runtime_session_id(),
    }).encode("utf-8")
    try:
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        return {"ok": False, "error": f"MCP bridge request failed: {exc}"}


def mcp_search(
    query: str = "",
    action: str = "search",
    server: str = "",
    tool: str = "",
    args: dict | None = None,
    limit: int = 5,
) -> dict:
    """Search, describe, list, or call tools in the TUI's deferred MCP catalog."""
    import urllib.request

    info = _read_mcp_bridge_info()
    if not info:
        return {
            "ok": False,
            "error": "MCP bridge not available. Is the TUI running with MCP enabled, and are servers configured in ~/.nexus/mcp_config.json?",
        }
    action = str(action or "search").strip().lower()
    if action not in {"list", "search", "describe", "call"}:
        return {"ok": False, "error": "mcp_search: action must be list, search, describe, or call"}
    if action == "search" and not str(query or "").strip():
        return {"ok": False, "error": "mcp_search: query must be non-empty for search"}
    if action in {"describe", "call"} and (not str(server or "").strip() or not str(tool or "").strip()):
        return {"ok": False, "error": f"mcp_search: server and tool are required for {action}"}
    if args is None:
        args = {}
    if not isinstance(args, dict):
        return {"ok": False, "error": "mcp_search: args must be a dict"}

    payload = json.dumps({
        "method": "search",
        "action": action,
        "query": str(query or ""),
        "server": str(server or ""),
        "tool": str(tool or ""),
        "arguments": args,
        "limit": limit,
        "session_id": harness.get_agent_runtime_session_id(),
    }).encode("utf-8")
    url = f"http://127.0.0.1:{info['port']}/"
    try:
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
        timeout = 60 if action == "call" else 15
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        return {"ok": False, "error": f"MCP bridge request failed: {exc}"}


def _tool_search_tokens(value: object) -> list[str]:
    return re.findall(r"[a-z0-9]+", str(value or "").lower())


def tool_search(query: str, limit: int = 5) -> dict:
    """Search deferred built-in helpers without placing every signature in the system prompt."""
    query_text = str(query or "").strip().lower()
    if not query_text:
        return {"ok": False, "error": "tool_search: query must be non-empty"}
    try:
        result_limit = max(1, min(20, int(limit)))
    except (TypeError, ValueError):
        result_limit = 5

    query_tokens = set(_tool_search_tokens(query_text))
    documents = []
    document_frequency: dict[str, int] = {}
    for name, description in FUNCTION_DESCRIPTIONS.items():
        if name == "tool_search":
            continue
        tokens = _tool_search_tokens(f"{name} {description}")
        token_set = set(tokens)
        documents.append((name, description, tokens, token_set))
        for token in token_set:
            document_frequency[token] = document_frequency.get(token, 0) + 1

    count = max(1, len(documents))
    average_length = max(1.0, sum(len(item[2]) for item in documents) / count)
    ranked = []
    for name, description, tokens, _token_set in documents:
        raw_name = name.lower()
        score = 0.0
        if query_text == raw_name:
            score += 1000.0
        if query_text in raw_name:
            score += 120.0
        for token in query_tokens:
            frequency = tokens.count(token)
            if frequency <= 0:
                continue
            df = document_frequency.get(token, 0)
            inverse_frequency = math.log(1.0 + (count - df + 0.5) / (df + 0.5))
            normalized_length = 0.6 + 0.4 * (len(tokens) / average_length)
            score += inverse_frequency * ((frequency * 1.9) / (frequency + 0.9 * normalized_length))
            if token in raw_name:
                score += 20.0
        if score > 0:
            ranked.append((score, name, description))

    ranked.sort(key=lambda item: (-item[0], item[1]))
    return {
        "ok": True,
        "query": query_text,
        "matches": [
            {"name": name, "description": description}
            for _score, name, description in ranked[:result_limit]
        ],
        "totalCatalogTools": len(documents),
    }


def deep_think(thought: str) -> dict:
    """Acknowledge a deliberate external reasoning step without echoing it."""
    value = str(thought or "").strip()
    if not value:
        return {"ok": False, "error": "deep_think: thought must be non-empty"}
    return {"ok": True, "acknowledged": True, "message": "Thought recorded. Continue solving."}


FUNCTIONS = {
    "deep_think": deep_think,
    "delegate_agent": delegate_agent,
    "notify_agent": notify_agent,
    "tool_search": tool_search,
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
    "transcribe_audio": transcribe_audio,
    "describe_image": describe_image,
    "list_skills": list_skills,
    "get_skill": get_skill,
    "search_skill": search_skill,
    "manage_skill": manage_skill,
    "rlm_spawn": rlm_spawn,
    "list_subagents": list_subagents,
    "wait_subagents": wait_subagents,
    "delete_subagent": delete_subagent,
    "harness_overview": harness_overview,
    "harness_memory": harness_memory,
    "harness_prompt_note": harness_prompt_note,
    "harness_subagent": harness_subagent,
    "record_refinement": record_refinement,
    "refine_reflection": refine_reflection,
    "skill_python_path": skill_python_path,
    "web_search": web_search,
    "mcp_list": mcp_list,
    "mcp_call": mcp_call,
    "mcp_search": mcp_search,
    "set_reminder": set_reminder,
    "kernel_exec": kernel_exec,
    "kernel_reset": kernel_reset,
}

FUNCTION_DESCRIPTIONS = {
    "deep_think": "deep_think(thought: str) -> dict: Record a private deliberate reasoning step, then continue solving with the returned acknowledgement. When External thinking is enabled and native thinking is disabled, call it once at the start of every assistant turn.",
    "delegate_agent": "delegate_agent(name: str, task: str, timeout: int|float = 240, poll_interval: int|float = 0.25) -> dict: Send a task to an idle named Nexus agent and wait for its final result. The target inherits its own persistent session, tools, MCP, skills, runtime settings, and shared workspace. Returns {ok, agent, status, result|error}.",
    "notify_agent": "notify_agent(name: str, task: str) -> dict: Start a task in an idle named Nexus agent and return immediately after admission. This is fire-and-forget: do not wait or poll unless the user later asks. Returns {ok, agent, status, pid|error}.",
    "tool_search": "tool_search(query: str, limit: int = 5) -> dict: Search deferred built-in helper names and descriptions. Returns the most relevant exact helper signatures; call a discovered helper in a later code_execution call.",
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
    "run_shell": "run_shell(command: str, timeout: int|float = 10, background: bool = False) -> dict: Run synchronously with a process-tree timeout. With background=True, use a fixed 600-second process-tree timeout, return {ok, job_id, pid, status, timeout} immediately, and add completion to chat later.",
    "android_build": "android_build(project_path: str = 'android-smoke', deploy: bool = True, timeout: int|float = 300) -> dict: Build an Android project locally in Termux. With deploy=true, install the APK over paired on-phone ADB, stop the old app, and launch the updated activity.",
    "get_git_status": "get_git_status() -> dict: Return git status summary.",
    "get_git_diff": "get_git_diff(path: str = '', staged: bool = False, context_lines: int = 3, max_chars: int = 60000) -> dict: Return git diff text.",
    "get_git_log": "get_git_log(max_count: int = 20) -> dict: Return recent git commits.",
    "read_file_summary": "async read_file_summary(path: str) -> dict: Return summary/preview for large files.",
    "fetch_url": "fetch_url(url: str, max_chars: int = 20000) -> dict: Fetch a URL and extract visible text content (HTML stripped). Returns {url, title, text, truncated, error}.",
    "transcribe_audio": "transcribe_audio(audios: str|list[str], language: str = '') -> dict: Transcribe one audio file, multiple files, or every supported audio file in a workspace directory using the Speech to text profile selected in /settings. Supported formats: wav, mp3, flac, m4a, ogg, webm, aac. Returns {ok, profile, model, results: [{ok, path, transcript|error}]}.",
    "describe_image": "describe_image(images: str|list[str], prompt: str = 'Describe this image accurately and concisely.') -> dict: Describe one image, multiple images, or every supported image in a workspace directory using the Vision model profile selected in /settings. Supported formats: png, jpg, jpeg, webp, gif. Returns {ok, profile, model, results: [{ok, path, description|error}]}.",
    "skill_python_path": "skill_python_path() -> str: Return the shared skill venv python executable (creates venv if needed). Use with run_shell to run skill scripts that depend on requirements.txt packages.",
    "list_skills": "list_skills() -> dict: List available skills. Returns {skills: [{name, description}], error}.",
    "get_skill": "get_skill(name: str) -> dict: Get a skill by name. Returns {name, description, path, body, error}. Load the body only when using the skill.",
    "search_skill": "search_skill(query: str, max_results: int = 10, repo: str = '') -> dict: Search the public nexus-skills registry on GitHub (default bevren/nexus-skills) for installable skills matching the query against name/description. Override with repo='owner/name' or the NEXUS_SKILLS_REPO env var. Returns {ok, query, repo, skills: [{name, description, raw_url}], error}. Use it before web_search when a needed skill is not installed; fall back to web_search only when it returns no match.",
    "manage_skill": "manage_skill(name: str, description: str = '', body: str = '', delete: bool = False) -> dict: Create, update, or delete a personal skill under ~/.nexus/skills. Workspace and bundled skills are read-only.",
    "web_search": "web_search(query: str, max_results: int = 5) -> dict: Search the web via DuckDuckGo (Lite HTML with Instant Answer fallback). Returns {query, results: [{title, snippet, url}], error}.",
    "rlm_spawn": "rlm_spawn(prompt: str, system: str = '', timeout: int = 300, max_tokens: int = 2048, template: str = '') -> dict: Non-blocking spawn of a persistent concurrent Nexus child process using the active provider/model, parent system prompt, unlimited tool turns, shared workspace, and tools. timeout is a hard wall-clock limit for each provider request and code_execution call. Returns an admitted handle immediately; end the current code_execution call after spawning so the child continues in the background.",
    "list_subagents": "list_subagents() -> list[dict]: Non-blocking workspace-wide list of named agents plus session-spawned child agents. status is normalized to idle, running, or stopped; task_status preserves the raw last-task state such as done or error. Returns kind, id, name, status, task_status, prompt, result, error, turn, and pid.",
    "wait_subagents": "wait_subagents(handle_ids: list[str] | None = None, timeout: int|float = 300, poll_interval: int|float = 0.5) -> list[dict]: Block until selected named or spawned Nexus agents become idle/stopped or timeout. Accepts agent IDs or names, returns already-finished agents immediately, and rejects unknown IDs immediately. Use only in a later code_execution call, never in the call that starts an agent.",
    "delete_subagent": "delete_subagent(handle_id: str) -> dict: Delete a spawned child sub-agent by handle id.",
    "harness_overview": "harness_overview() -> dict: Continual harness overview: memories, skills, subagent templates, prompt notes, refinements.",
    "harness_memory": "harness_memory(key: str, content: str = '', delete: bool = False) -> dict: Read a persistent memory when content is omitted; create/update it when content is supplied; delete it with delete=True.",
    "harness_prompt_note": "harness_prompt_note(name: str, content: str = '', delete: bool = False) -> dict: Create/update/delete a persistent harness prompt note by name.",
    "harness_subagent": "harness_subagent(name: str, prompt: str = '', model: str = '', system: str = '', delete: bool = False) -> dict: Persist a reusable subagent template.",
    "record_refinement": "record_refinement(summary: str, evidence: str = '') -> dict: Persist a reusable pattern into the continual harness with evidence.",
    "refine_reflection": "refine_reflection(auto: bool = True) -> dict: Auto-synthesize a refinement from recent subagent results and prompt notes.",
    "mcp_list": "mcp_list() -> dict: List all configured MCP servers and the tool names each exposes. Returns {ok: bool, servers?: {name: {status, error?, tools: [name]}}, error?: str}.",
    "mcp_call": "mcp_call(server: str, tool: str, args: dict | None = None) -> dict: Call a tool exposed by an MCP server (configured in ~/.nexus/mcp_config.json). Returns the server's result as {ok: bool, result?: object, text?: str, error?: str}.",
    "mcp_search": "mcp_search(query: str = '', action: str = 'search', server: str = '', tool: str = '', args: dict | None = None, limit: int = 5) -> dict: Search the deferred MCP catalog without loading every schema into context. Actions: list returns server counts; search returns matching schemas; describe returns one exact schema; call invokes an exact discovered tool.",
    "set_reminder": "set_reminder(when: str, prompt: str) -> dict: Schedule a one-shot session reminder via the TUI bridge. when is a human phrase like 'in 5 minutes', 'in 2 hours', 'at 3pm', 'tomorrow 9am'. prompt is the exact action/message to run when it fires. Fires once as a normal user turn. Use whenever the user asks to be reminded or to remember something later.",
    "kernel_exec": "kernel_exec(code: str) -> dict: Execute Python in the session's persistent kernel. State persists across calls (variables/functions defined here are usable in later kernel_exec calls). Returns {ok, output, error, traceback}; print() surfaces results. Use for iterative/stateful computation where recomputing from scratch would be wasteful.",
    "kernel_reset": "kernel_reset() -> dict: Kill the persistent kernel so the next kernel_exec starts with a clean scope. Returns {ok, error}.",
}




def get_functions() -> dict[str, object]:
    return dict(FUNCTIONS)


def _annotation_schema_type(annotation) -> str:
    if annotation is inspect.Parameter.empty or annotation is None:
        return "string"
    origin = _typing.get_origin(annotation)
    args = _typing.get_args(annotation)
    if origin is _typing.Union or (_types.UnionType is not None and origin is _types.UnionType):
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1:
            return _annotation_schema_type(non_none[0])
        if non_none and all(a in (int, float) for a in non_none):
            return "number"
        return "string"
    if origin is list:
        return "array"
    if origin is dict:
        return "object"
    if annotation in (str, bytes):
        return "string"
    if annotation is int:
        return "integer"
    if annotation is float:
        return "number"
    if annotation is bool:
        return "boolean"
    if annotation is list:
        return "array"
    if annotation is dict:
        return "object"
    if annotation is _typing.List:
        return "array"
    if annotation is _typing.Dict:
        return "object"
    return "string"


def _build_function_schema(name: str, func, description: str) -> dict:
    parameters: dict = {"type": "object", "properties": {}}
    required: list[str] = []
    try:
        hints = _typing.get_type_hints(func)
    except Exception:
        hints = {}
    try:
        signature = inspect.signature(func)
    except (TypeError, ValueError):
        signature = None
    if signature is not None:
        for param_name, param in signature.parameters.items():
            if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
                continue
            prop: dict = {}
            annotation = hints.get(param_name)
            if annotation is None and param.annotation is not inspect.Parameter.empty:
                annotation = param.annotation
            prop["type"] = _annotation_schema_type(annotation)
            if (
                param.default is not inspect.Parameter.empty
                and param.default is not None
                and isinstance(param.default, (str, int, float, bool))
            ):
                prop["default"] = param.default
            if param.default is inspect.Parameter.empty:
                required.append(param_name)
            parameters["properties"][param_name] = prop
    if required:
        parameters["required"] = required
    return {
        "type": "function",
        "function": {"name": name, "description": description, "parameters": parameters},
    }


TOOL_SCHEMAS = [
    _build_function_schema(name, fn, FUNCTION_DESCRIPTIONS[name])
    for name, fn in FUNCTIONS.items()
    if name in FUNCTION_DESCRIPTIONS
]


def get_descriptions() -> dict[str, str]:
    return dict(FUNCTION_DESCRIPTIONS)


def main() -> int:
    args = sys.argv[1:]
    if "--voice-capture" in args:
        index = args.index("--voice-capture")
        if index + 2 >= len(args):
            return 2
        try:
            parent_pid = int(args[index + 2])
        except ValueError:
            return 2
        return _run_voice_capture_helper(args[index + 1], parent_pid)
    if "--run-subagent" in args:
        index = args.index("--run-subagent")
        if index + 1 >= len(args):
            return 2
        return harness.run_subagent_job(args[index + 1])
    if "--launch-subagent" in args:
        index = args.index("--launch-subagent")
        if index + 1 >= len(args):
            return 2
        print(harness.launch_subagent_job(args[index + 1]))
        return 0
    if "--launch-subagent-test" in args:
        index = args.index("--launch-subagent-test")
        if index + 1 >= len(args):
            return 2
        print(harness.launch_subagent_job(args[index + 1], self_test=True))
        return 0
    if len(sys.argv) > 1 and sys.argv[1] == "--self-test-subagents":
        result = harness.run_subagent_self_test()
        if result.get("ok"):
            result = _run_named_agent_tool_self_test()
        print("SUBAGENT_OK" if result.get("ok") else "SUBAGENT_FAIL")
        return 0 if result.get("ok") else 1
    if len(sys.argv) > 1 and sys.argv[1] == "--list-skills-json":
        print(json.dumps(list_skills()))
        return 0
    if len(sys.argv) > 1 and sys.argv[1] == "--describe-json":
        print(json.dumps({"descriptions": FUNCTION_DESCRIPTIONS, "schemas": TOOL_SCHEMAS}))
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
