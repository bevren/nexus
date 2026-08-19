"""Predefined helper functions for code execution."""

from __future__ import annotations

import json
import math
import os
import queue
import struct
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


def _build_wav_pcm(data: bytes, sample_rate: int = 16000) -> bytes:
    """Wrap raw 16-bit mono PCM into a RIFF/WAVE container."""
    block_align = 2
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + len(data),
        b"WAVE",
        b"fmt ",
        16,
        1,  # WAVE_FORMAT_PCM
        1,  # mono
        sample_rate,
        sample_rate * block_align,
        block_align,
        16,  # bits per sample
        b"data",
        len(data),
    )
    return header + data


_WINMM_RECORDER_CLASS = None


def _winmm_recorder_class():
    """Lazily build the WinMM-based WaveRecorder class (Windows only).

    Both the push-to-talk helper and the voice engine share one capture
    implementation; ctypes structures are built once and cached.
    """
    global _WINMM_RECORDER_CLASS
    if _WINMM_RECORDER_CLASS is not None:
        return _WINMM_RECORDER_CLASS

    import ctypes
    import math as _math

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

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    winmm = ctypes.WinDLL("winmm", use_last_error=True)
    kernel32.CreateEventW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_wchar_p]
    kernel32.CreateEventW.restype = ctypes.c_void_p
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_int
    kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    kernel32.WaitForSingleObject.restype = ctypes.c_uint

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
        ctypes.POINTER(ctypes.c_void_p), ctypes.c_uint,
        ctypes.POINTER(WAVEFORMATEX), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint,
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
                ctypes.byref(self.handle), WAVE_MAPPER, ctypes.byref(format_ex),
                self.event_handle, 0, CALLBACK_EVENT,
            )
            if error_code != MMSYSERR_NOERROR:
                raise RuntimeError(f"waveInOpen failed (0x{error_code:x})")
            for _ in range(BUFFER_COUNT):
                raw = ctypes.create_string_buffer(BUFFER_BYTES)
                header = WAVEHDR()
                header.lpData = ctypes.cast(raw, ctypes.POINTER(ctypes.c_char))
                header.dwBufferLength = BUFFER_BYTES
                error_code = winmm.waveInPrepareHeader(self.handle, ctypes.byref(header), ctypes.sizeof(WAVEHDR))
                if error_code != MMSYSERR_NOERROR:
                    raise RuntimeError(f"waveInPrepareHeader failed (0x{error_code:x})")
                error_code = winmm.waveInAddBuffer(self.handle, ctypes.byref(header), ctypes.sizeof(WAVEHDR))
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
                    pass

        def write_snapshot(self, path, start_byte: int = 0, end_byte: int = -1) -> int:
            with self.data_lock:
                data = bytes(self.data[start_byte:])
                total = len(self.data)
            if end_byte is not None and end_byte >= 0:
                data = data[: max(0, end_byte - start_byte)]
            Path(path).write_bytes(_build_wav_pcm(data))
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
            return _math.sqrt(sum(sample * sample for sample in samples) / count)

        def stop(self, path) -> int:
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
                    Path(path).write_bytes(_build_wav_pcm(data))
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

    _WINMM_RECORDER_CLASS = WaveRecorder
    return WaveRecorder


# ---------------------------------------------------------------------------
# Voice engine: continuous capture with an optional VAD / wake-word / TTS
# pipeline. Pure state-machine + audio helpers live at module level so the
# self-test can exercise them without a microphone or model files; the
# Windows-only capture loop (--voice-engine) drives them.
# ---------------------------------------------------------------------------

_VOICE_SAMPLE_RATE = 16000
_VOICE_FRAME_BYTES = 640  # 20ms of 16 kHz 16-bit mono
_VOICE_PRE_ROLL_MS = 300  # keep 300ms of audio before speech onset
_VOICE_SILENCE_FINALIZE_MS = 900
_VOICE_WAKE_DEBOUNCE_MS = 1500


_VOICE_SYMBOL_WORDS = [
    # Ordered longest-first so arrow/link operators win over single symbols.
    ("->", " to "),
    ("=>", " to "),
    ("\u2192", " to "),   # →
    ("\u2014", " "),      # em dash
    ("\u2013", " "),      # en dash
    ("&", " and "),
    ("%", " percent "),
    ("+", " plus "),
    ("#", " number "),
    ("@", " at "),
    ("\u00d7", " times "),   # ×
    ("\u00b7", " "),         # ·
    ("\u2026", " ..."),      # …
]


def _voice_clean_for_speech(text: str) -> str:
    """Convert assistant text into speaker-friendly prose.

    Reads text the way people speak it instead of the way espeak-ng would read
    raw syntax: expands symbols to words, drops code/URLs/email/paths, reads
    dotted identifiers as "dot", expands units and currency, strips bullets,
    quotes, emoji, and collapses whitespace. Parenthesized *content* is kept.
    """
    import re as _re

    source = str(text or "").strip()
    if not source:
        return ""
    # Remove fenced + inline code so we never read code aloud.
    source = _re.sub(r"```.*?```", " ", source, flags=_re.S)
    source = _re.sub(r"`[^`]*`", " ", source)
    # Markdown links: keep the label, drop the URL.
    source = _re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", source)
    # Bare URLs, emails, and www tokens.
    source = _re.sub(r"https?://\S+", " ", source, flags=_re.I)
    source = _re.sub(r"www\.\S+", " ", source, flags=_re.I)
    source = _re.sub(r"[\w.+-]+@[\w-]+\.[\w.-]+", " ", source)
    # Symbol -> word expansions (arrows first).
    for symbol, word in _VOICE_SYMBOL_WORDS:
        source = source.replace(symbol, word)
    # Comparison operators. Longest-first so "!=" is consumed before "=="
    # matches its "=", and ">=" before ">".
    source = source.replace("!=", " not equal to ")
    source = source.replace(">=", " greater than or equal to ")
    source = source.replace("<=", " less than or equal to ")
    source = source.replace("==", " equals ")
    source = source.replace(">", " greater than ")
    source = source.replace("<", " less than ")
    # Ranges read as "to": 3-4 -> "3 to 4".
    source = _re.sub(r"(\d)\s*-\s*(\d)", r"\1 to \2", source)
    # Currency: $5 / euro / pound -> "5 dollars/euros/pounds" (unit after
    # the number; the decimal is expanded later).
    source = _re.sub(r"[$]\s*(\d+(?:[.,]\d+)?)", r"\1 dollars ", source)
    source = _re.sub(r"[\u20ac]\s*(\d+(?:[.,]\d+)?)", r"\1 euros ", source)
    source = _re.sub(r"[\u00a3]\s*(\d+(?:[.,]\d+)?)", r"\1 pounds ", source)
    # Data-size units -> words.
    source = _re.sub(
    r"(?i)\b(\d+)\s*(MB|GB|KB|TB)\b",
    lambda m: f"{m.group(1)} "
              f"{ {'MB': 'megabytes', 'GB': 'gigabytes', 'KB': 'kilobytes', 'TB': 'terabytes'}[m.group(2).upper()] }",
        source,
    )
    source = _re.sub(r"(\d+)\s*ms\b", r"\1 milliseconds ", source, flags=_re.I)
    _FREQ_UNIT_WORDS = {"GHZ": "gigahertz", "MHZ": "megahertz"}
    source = _re.sub(
        r"(\d+(?:\.\d+)?)\s*(GHz|MHz)\b",
        lambda m: f"{m.group(1)} {_FREQ_UNIT_WORDS.get(m.group(2).upper(), m.group(2).lower())} ",
        source,
        flags=_re.I,
    )
    source = _re.sub(r"(\d+)\s*[\u00b0C]\b", r"\1 degrees celsius ", source)
    # Versions and decimals: 3.14 -> "3 point 1 4"; v1.2.3 -> "v 1 point 2 point 3".
    source = _re.sub(
        r"\b(\d+)\.(\d+)(?:\.(\d+))?\b",
        lambda m: f"{m.group(1)} point {m.group(2)}" + (f" point {m.group(3)}" if m.group(3) else ""),
        source,
    )
    # Dotted identifiers / file names: index.js -> "index dot js".
    source = _re.sub(r"\b([A-Za-z]\w*)\.([A-Za-z]\w*)\b", r"\1 dot \2", source)
    # Paths: C:\Users\x and C:/Users/x -> separators read as "slash".
    source = _re.sub(r"\b([A-Za-z]):(?=[\\/])", r"\1", source)  # drive letter colon
    source = source.replace("\\", " slash ")
    source = _re.sub(r"(?<=[A-Za-z0-9])/(?=[A-Za-z0-9])", " slash ", source)
    # Strip paren/bracket/brace markers (keep inner text), quotes.
    source = _re.sub(r"[()\[\]{}]", " ", source)
    source = _re.sub(
        r'["\'`\u2018\u2019\u201c\u201d]',
        " ",
        source,
    )
    # Markdown decorators and separators.
    source = _re.sub(r"[#>*_~|^]", " ", source)
    # Bullets and numbered-list markers at start of lines.
    source = _re.sub(r"(^|\n)\s*(?:[-*\u2022]|\d+[.)])\s+", r"\1", source)
    # Thousands separators: 1,000 -> 1000 (read as "one thousand").
    source = _re.sub(r"(?<=\d),(?=\d)", "", source)
    # Emoji and misc symbols.
    source = _re.sub(
        "[\U0001F300-\U0001FAFF\u2600-\u27BF\uFE0F\u2190-\u21FF\u2000-\u206F]",
        " ",
        source,
    )
    # Collapse whitespace.
    source = _re.sub(r"\s+", " ", source).strip()
    return source
def _compact_speech_text(text: str, max_chars: int) -> str:
    """Truncate spoken text at a sentence boundary.

    Keeps the reply short and natural ("no wall of text"): when the cleaned
    text exceeds ``max_chars`` it is cut at the last sentence ending before
    the limit and an ellipsis is appended. ``max_chars <= 0`` disables the cap.
    """
    source = str(text or "").strip()
    if not source or max_chars <= 0 or len(source) <= max_chars:
        return source
    head = source[:max_chars]
    boundary = max(head.rfind(". "), head.rfind("! "), head.rfind("? "))
    if boundary >= max_chars * 0.4:
        return head[: boundary + 1].rstrip() + " ..."
    return head.rstrip() + " ..."


def _split_voice_sentences(text: str, max_chars: int = 400, total_max_chars: int = 0) -> list[str]:
    """Split prose into sentence-sized chunks for streaming TTS.

    Cleans the text for speech (``_voice_clean_for_speech``), optionally
    compacts it to ``total_max_chars``, and keeps chunks under ``max_chars``.
    Used by both the Kokoro path and the provider fallback so chunking is
    tested once.
    """
    import re as _re

    source = _voice_clean_for_speech(text)
    if not source:
        return []
    if total_max_chars > 0:
        source = _compact_speech_text(source, total_max_chars)
    if not source:
        return []

    # Split on sentence boundaries, keeping short sentences grouped.
    parts = _re.split(r"(?<=[.!?])\s+", source)
    chunks: list[str] = []
    current = ""
    for part in parts:
        candidate = f"{current} {part}".strip() if current else part
        if len(candidate) > max_chars and current:
            chunks.append(current)
            current = part
        else:
            current = candidate
    if current:
        chunks.append(current)
    return [chunk for chunk in chunks if chunk]


def _frame_rms(frame: bytes) -> float:
    """RMS (linear) of one 16-bit mono PCM frame."""
    import math as _math

    if len(frame) < 2:
        return 0.0
    count = len(frame) // 2
    samples = struct.unpack(f"<{count}h", frame[: count * 2])
    return _math.sqrt(sum(sample * sample for sample in samples) / count) if count else 0.0


class _AdaptiveBargeDetector:
    """Adaptive speech detector used ONLY while TTS is playing.

    Fixed amplitude thresholds cannot work here: TTS playback through speakers
    reaches the mic at a level that varies with volume, distance, and room. So
    this detector tracks a rolling ambient floor (the TTS echo) and triggers a
    barge-in only when the incoming audio is sustained well above that floor -
    a person talking into the mic is typically 6-20dB louder than the echo.

    ``margin_ratio`` (default 2.2 ~ 7dB) and ``confirm_frames`` (default 8 =
    160ms of continuous speech) make it robust: brief TTS syllables near the
    floor cannot confirm, but real speech does.
    """

    def __init__(
        self,
        margin_ratio: float = 2.2,
        confirm_frames: int = 8,
        ambient_alpha: float = 0.05,
        min_ambient: float = 40.0,
    ) -> None:
        self.margin_ratio = max(1.2, margin_ratio)
        self.confirm_frames = max(2, confirm_frames)
        self.ambient_alpha = max(0.01, min(0.2, ambient_alpha))
        self.min_ambient = max(10.0, min_ambient)
        self.ambient = None
        self.loud_run = 0

    def reset(self) -> None:
        self.ambient = None
        self.loud_run = 0

    def feed(self, frame: bytes, ms: float) -> bool:
        rms = _frame_rms(frame)
        if self.ambient is None:
            self.ambient = max(rms, self.min_ambient)
        else:
            # Track the floor with a slow EMA. Cap each sample at 1.5x ambient
            # so a loud burst (user speech) cannot inflate the floor before it
            # triggers; the floor mostly follows the steady TTS echo.
            self.ambient = self.ambient * (1 - self.ambient_alpha) + (
                min(rms, self.ambient * 1.5) if rms > self.ambient else rms
            ) * self.ambient_alpha
        threshold = max(self.min_ambient * self.margin_ratio, self.ambient * self.margin_ratio)
        if rms >= threshold:
            self.loud_run += 1
            if self.loud_run >= self.confirm_frames:
                self.loud_run = 0
                return True
        else:
            # Tolerate brief dips inside a loud run.
            self.loud_run = max(0, self.loud_run - 1)
        return False


class _FrameVadGate:
    """RMS-based speech gate used by the voice engine.

    Silero (onnxruntime) is the preferred detector; when the model file is
    missing the engine falls back to this gate so hands-free capture still
    works. A ring buffer keeps the pre-roll audio before speech onset.
    """

    def __init__(
        self,
        rms_threshold: float = 200.0,
        silence_finalize_ms: int = _VOICE_SILENCE_FINALIZE_MS,
        onset_confirmation_frames: int = 2,
    ) -> None:
        self.rms_threshold = rms_threshold
        self.silence_finalize_ms = silence_finalize_ms
        self.onset_confirmation_frames = max(1, onset_confirmation_frames)
        self.speaking = False
        self.last_speech_ms = 0.0
        self.loud_frames = 0
        self.pre_roll_bytes = int(_VOICE_SAMPLE_RATE * 2 * (_VOICE_PRE_ROLL_MS / 1000))
        self._pre_roll = bytearray()

    def feed(self, frame: bytes, ms: float) -> tuple[bool, bool]:
        """Feed one 20ms audio frame; returns (speech_started, speech_ended).

        Speech onset requires a few consecutive loud frames (20ms each) so a
        single noise spike cannot false-start an utterance.
        """
        import math as _math

        self._pre_roll.extend(frame)
        if len(self._pre_roll) > self.pre_roll_bytes:
            del self._pre_roll[: len(self._pre_roll) - self.pre_roll_bytes]
        if len(frame) < 2:
            return False, False
        count = len(frame) // 2
        samples = struct.unpack(f"<{count}h", frame[: count * 2])
        rms = _math.sqrt(sum(sample * sample for sample in samples) / count) if count else 0.0
        is_speech = rms >= self.rms_threshold
        started = False
        ended = False
        if is_speech:
            self.last_speech_ms = ms
            self.loud_frames += 1
            if not self.speaking and self.loud_frames >= self.onset_confirmation_frames:
                self.speaking = True
                started = True
        else:
            # A brief dip is tolerated while speaking; long silence ends it.
            self.loud_frames = 0
            if self.speaking and (ms - self.last_speech_ms) >= self.silence_finalize_ms:
                self.speaking = False
                ended = True
        return started, ended

    def pre_roll(self) -> bytes:
        return bytes(self._pre_roll)


class _SileroVadGate(_FrameVadGate):
    """Optional Silero VAD over onnxruntime; falls back to RMS when unavailable."""

    def __init__(self, model_path=None, rms_threshold: float = 260.0):
        super().__init__(rms_threshold=rms_threshold)
        self.model = None
        self.session = None
        if model_path:
            try:
                import onnxruntime as ort

                self.session = ort.InferenceSession(
                    str(model_path), providers=["CPUExecutionProvider"]
                )
                self.model = True
            except Exception:
                self.model = None

    def feed(self, frame: bytes, ms: float) -> tuple[bool, bool]:
        if self.session is None:
            return super().feed(frame, ms)
        try:
            import numpy as np

            samples = np.frombuffer(frame, dtype=np.int16).astype(np.float32) / 32768.0
            # Silero expects a single 16 kHz frame; model.onnx output is
            # [batch,1] probability.
            result = self.session.run(None, {self.session.get_inputs()[0].name: samples[None, :]})
            prob = float(result[0].flat[0]) if len(result) and result[0] is not None else 0.0
            is_speech = prob >= 0.5
            started = False
            ended = False
            if is_speech:
                self.last_speech_ms = ms
                if not self.speaking:
                    self.speaking = True
                    started = True
            elif self.speaking and (ms - self.last_speech_ms) >= self.silence_finalize_ms:
                self.speaking = False
                ended = True
            self._pre_roll.extend(frame)
            if len(self._pre_roll) > self.pre_roll_bytes:
                del self._pre_roll[: len(self._pre_roll) - self.pre_roll_bytes]
            return started, ended
        except Exception:
            return super().feed(frame, ms)


def _chunk_audio_for_vad(audio: bytes, frame_bytes: int = _VOICE_FRAME_BYTES):
    """Yield 20ms frames from raw PCM (test helper)."""
    frame_bytes = frame_bytes - (frame_bytes % 2)
    for i in range(0, len(audio) - frame_bytes + 1, frame_bytes):
        yield audio[i : i + frame_bytes]


_TTS_PLAY_LOCK = threading.Lock()
_TTS_PLAY_HANDLE = None  # winsound PlaySound handle; None when idle


# Global flag the play loop polls; set by _tts_stop_playback so a chunked
# play exits within ~50ms instead of finishing the whole file.
_TTS_STOP_FLAG = threading.Event()
_TTS_PLAY_HANDLE = None


def _tts_stop_playback() -> None:
    """Immediately stop any currently playing TTS audio.

    Sets the chunked-play stop flag and calls SND_PURGE (which reliably stops
    SND_ASYNC playback). The chunked player checks the flag between ~50ms
    chunks, so a barge-in stops the current sentence almost instantly.
    """
    _TTS_STOP_FLAG.set()
    try:
        import winsound

        winsound.PlaySound(None, winsound.SND_PURGE)
    except Exception:
        pass


def _tts_play_wav(path: str, timeout: float = 60.0) -> bool:
    """Play a WAV file on Windows via winsound, stopping promptly on demand.

    Plays the WHOLE file asynchronously with SND_FILENAME|SND_ASYNC (a complete
    WAV, so audio is always correct) and then waits its real duration while
    polling the stop flag every 30ms. On barge-in, _tts_stop_playback sets the
    flag and SND_PURGE stops the async playback immediately, so the current
    sentence cuts off within ~30ms instead of running to its end.
    """
    if os.name != "nt" or not path or not os.path.exists(path):
        return False
    try:
        import winsound
        import wave as _wave

        with _wave.open(path, "rb") as wav:
            duration_s = wav.getnframes() / max(1, wav.getframerate())
        _TTS_STOP_FLAG.clear()
        winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)
        deadline = time.monotonic() + max(0.1, min(float(timeout), duration_s + 1.0))
        while time.monotonic() < deadline:
            if _TTS_STOP_FLAG.is_set():
                winsound.PlaySound(None, winsound.SND_PURGE)
                _TTS_STOP_FLAG.clear()
                break
            time.sleep(0.03)
        return True
    except Exception:
        _TTS_STOP_FLAG.clear()
        return False


_TURKISH_VOICE = "tf_nisan"


def _voice_profile(voice: str) -> dict:
    """Resolve a voice id to (model, voices, vocab, espeak lang, voice id).

    tf_nisan is the Turkish Kokoro-82M fine-tune (duxx/kikiri_turkish_nisanONNX)
    stored under ~/.nexus/voice/kikiri/; it needs its own ONNX model, voicepack,
    character vocab (base 114 + '$'), and espeak-ng Turkish phonemization.
    Everything else uses the default English Kokoro model.
    """
    voice = str(voice or "af_heart").strip()
    if voice == _TURKISH_VOICE:
        kikiri = NEXUS_DIR / "voice" / "kikiri"
        return {
            "model": str(kikiri / "model.onnx"),
            # kokoro-onnx np.load expects an .npz dict of {voice: (510,1,256)};
            # the repo ships a raw float32 blob, so we convert it once.
            "voices": str(kikiri / "voices.npz"),
            "tokenizer": str(kikiri / "tokenizer.json"),
            "lang": "tr",
            "voice": "tf_nisan",
        }
    return {
        "model": str(NEXUS_DIR / "voice" / "kokoro-v1.0.onnx"),
        "voices": str(NEXUS_DIR / "voice" / "voices-v1.0.bin"),
        "tokenizer": "",
        "lang": "en-us",
        "voice": voice,
    }


def _load_kokoro(voice: str):
    """Load the Kokoro instance for a voice, applying the custom vocab + espeak
    lang when the voice needs them (Turkish fine-tune)."""
    from kokoro_onnx import Kokoro

    profile = _voice_profile(voice)
    if not os.path.exists(profile["model"]):
        raise FileNotFoundError(
            f"model files for voice {voice} missing. Run /voice-setup or download them into ~/.nexus/voice/."
        )
    if voice == _TURKISH_VOICE:
        # The Turkish repo ships the voice as a raw float32 blob (510*256);
        # convert it to the .npz dict kokoro-onnx expects, once.
        voices_npz = os.path.join(NEXUS_DIR, "voice", "kikiri", "voices.npz")
        raw_bin = os.path.join(NEXUS_DIR, "voice", "kikiri", "tf_nisan.bin")
        if not os.path.exists(voices_npz):
            if not os.path.exists(raw_bin):
                raise FileNotFoundError("Turkish voice tf_nisan.bin is missing")
            import numpy as _np

            arr = _np.frombuffer(open(raw_bin, "rb").read(), dtype=_np.float32)
            total = arr.size
            if total != 510 * 256:
                raise ValueError(f"tf_nisan.bin has {total} floats, expected 510*256")
            _np.savez(voices_npz, tf_nisan=arr.reshape(510, 1, 256))
        profile["voices"] = voices_npz
    if not os.path.exists(profile["voices"]):
        raise FileNotFoundError(
            f"voicepack for {voice} missing. Run /voice-setup or download it into ~/.nexus/voice/."
        )
    vocab_config = None
    if profile["tokenizer"] and os.path.exists(profile["tokenizer"]):
        import json as _json

        with open(profile["tokenizer"], encoding="utf-8") as fp:
            vocab_config = {"vocab": _json.load(fp)["model"]["vocab"]}
    return Kokoro(
        profile["model"],
        profile["voices"],
        vocab_config=vocab_config,
    )


def _tts_synthesize_kikiri(text: str, voice: str = "tf_nisan", speed: float = 1.0, out_path: str = "") -> dict:
    """Synthesize Turkish text with the fine-tuned Kokoro model.

    The Turkish ONNX export (duxx/kikiri_turkish_nisanONNX) uses an
    ``input_ids``/``style``/``speed`` signature and a custom character
    tokenizer, which kokoro-onnx's standard create() does not feed correctly
    (it passes int32 speed and expects its own layout). Run the session
    directly here.
    """
    if not text or not text.strip():
        return {"ok": False, "error": "empty text"}
    import tempfile as _tempfile
    import json as _json

    out_path = out_path or os.path.join(_tempfile.gettempdir(), f"nexus-tts-{int(time.time() * 1000)}.wav")
    try:
        import numpy as np
        import onnxruntime as ort

        kikiri = NEXUS_DIR / "voice" / "kikiri"
        model_path = kikiri / "model.onnx"
        tokenizer_path = kikiri / "tokenizer.json"
        raw_voice = kikiri / "tf_nisan.bin"
        if not (model_path.exists() and tokenizer_path.exists() and raw_voice.exists()):
            return {"ok": False, "error": "Turkish voice files missing under ~/.nexus/voice/kikiri/"}
        session = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])

        vocab = _json.load(open(tokenizer_path, encoding="utf-8"))["model"]["vocab"]

        # Defensive: strip markdown/emoji/symbols before phonemizing so raw
        # assistant text (e.g. **bold**, emoji, code) can never reach the
        # model as literal characters (espeak-ng would spell them out).
        text = _voice_clean_for_speech(text)

        # Phonemize Turkish text with espeak-ng to IPA, exactly like the
        # reference (node_kokoro_turkish_transformers): the model's vocab is
        # IPA phonemes, NOT raw Turkish characters - so ö/ü/ı must become
        # their IPA equivalents (ø/y/ɯ) or they are silently dropped.
        def _phonemize_turkish(text_in: str) -> str:
            # Force UTF-8 I/O: the engine can run under a non-UTF-8 locale
            # (e.g. cp1254 on Windows), and phonemizer/espeak's IPA output
            # (ɪ, ʊ, ø, ...) would otherwise fail to encode or get mangled.
            try:
                sys.stdout.reconfigure(encoding="utf-8", errors="replace")
                sys.stderr.reconfigure(encoding="utf-8", errors="replace")
                os.environ["PYTHONIOENCODING"] = "utf-8"
            except Exception:
                pass
            # Wire the bundled espeak-ng (shipped with kokoro-onnx) into
            # phonemizer so "tr" works without a system-wide install.
            try:
                import espeakng_loader

                from phonemizer.backend.espeak.wrapper import EspeakWrapper

                data_path = espeakng_loader.get_data_path()
                lib_path = espeakng_loader.get_library_path()
                os.environ.setdefault("PHONEMIZER_ESPEAK_LIBRARY", lib_path)
                os.environ.setdefault("PHONEMIZER_ESPEAK_PATH", data_path)
                EspeakWrapper.set_data_path(data_path)
                EspeakWrapper.set_library(lib_path)
            except Exception:
                pass
            from phonemizer import phonemize

            ipa = phonemize(
                str(text_in),
                "tr",
                preserve_punctuation=True,
                with_stress=False,
            )
            # Reference post-processing (node_kokoro_turkish_transformers):
            # drop espeak's '_', map dark-l and palatal-j, collapse spaces.
            ipa = ipa.replace("_", "").replace("\u026b", "l").replace("\u02b2", "j")
            ipa = "".join(ch for ch in ipa if ch in vocab)
            return " ".join(ipa.split()).strip()

        phonemes = _phonemize_turkish(text)
        if not phonemes:
            return {"ok": False, "error": "phonemization produced no tokens"}
        ids = [int(vocab[ch]) for ch in phonemes]
        tokens = np.array([[0, *ids, 0]], dtype=np.int64)

        # Voice: the fine-tune ships a raw float32 blob of 510*256 = the
        # per-token style table; pick the row for the token count (reference:
        # voiceRow = min(tokenCount, 509)).
        voice_arr = np.frombuffer(raw_voice.read_bytes(), dtype=np.float32)
        if voice_arr.size != 510 * 256:
            return {"ok": False, "error": f"tf_nisan.bin size {voice_arr.size} != 510*256"}
        voice_table = voice_arr.reshape(510, 256)
        token_count = len(ids)
        row = min(token_count, 509)
        style = np.array(voice_table[row], dtype=np.float32).reshape(1, 256)

        outputs = session.run(
            None,
            {
                "input_ids": tokens,
                "style": style,
                "speed": np.array([float(speed)], dtype=np.float32),
            },
        )
        audio = np.asarray(outputs[0], dtype=np.float32).flatten()
        sample_rate = 24000
        pcm = (np.clip(audio, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
        Path(out_path).write_bytes(_build_wav_pcm(pcm, sample_rate))
        return {"ok": True, "path": out_path, "sample_rate": sample_rate}
    except ImportError:
        return {"ok": False, "error": "onnxruntime is not installed"}
    except Exception as exc:
        return {"ok": False, "error": f"kikiri tts failed: {exc}"}


def _tts_synthesize_kokoro(
    text: str,
    voice: str = "af_heart",
    speed: float = 1.0,
    out_path: str = "",
    kokoro=None,
) -> dict:
    """Synthesize text with kokoro-onnx into a WAV file.

    Accepts an optional prebuilt ``Kokoro`` instance so the voice engine can
    cache the 325MB model instead of re-loading it per sentence.

    Returns {"ok": True, "path": ...} or {"ok": False, "error": ...}.
    """
    if not text or not text.strip():
        return {"ok": False, "error": "empty text"}
    import tempfile as _tempfile

    out_path = out_path or os.path.join(_tempfile.gettempdir(), f"nexus-tts-{int(time.time() * 1000)}.wav")
    try:
        if voice == _TURKISH_VOICE:
            # Turkish fine-tune has a different ONNX signature; use the
            # dedicated inference path (ignores any preloaded English kokoro).
            return _tts_synthesize_kikiri(text, voice=voice, speed=speed, out_path=out_path)
        if kokoro is None:
            kokoro = _load_kokoro(voice)
        profile = _voice_profile(voice)
        samples, sample_rate = kokoro.create(text, voice=profile["voice"], speed=speed, lang=profile["lang"])
        try:
            import numpy as np

            pcm = (np.asarray(samples) * 32767.0).astype("<i2").tobytes()
        except Exception:
            import array as _array

            pcm = _array.array("h", [int(max(-1, min(1, s)) * 32767) for s in samples]).tobytes()
        Path(out_path).write_bytes(_build_wav_pcm(pcm, int(sample_rate)))
        return {"ok": True, "path": out_path, "sample_rate": int(sample_rate)}
    except ImportError:
        return {"ok": False, "error": "kokoro-onnx is not installed. pip install kokoro-onnx"}
    except Exception as exc:
        return {"ok": False, "error": f"kokoro tts failed: {exc}"}


def _tts_synthesize(text: str, voice: str = "", out_path: str = "") -> dict:
    """TTS entry point: Kokoro first, then the provider fallback (provider is
    invoked by the TUI via the media bridge when the helper reports no local
    model). This function only implements the local path + chunking so the
    engine can stream sentence-by-sentence."""
    result = _tts_synthesize_kokoro(text, voice=voice, out_path=out_path)
    if result.get("ok"):
        return result
    # Local model missing: return the actionable error; the TUI decides
    # whether to fall back to a provider TTS model.
    return result


def _run_voice_engine_self_test() -> int:
    """Offline checks for the voice engine's pure logic (no mic, no models)."""
    out = print
    try:
        # Sentence splitting strips markdown and groups short sentences.
        chunks = _split_voice_sentences(
            "Hello **world**. Check ```python\nprint(1)\n``` now. [link](https://x) and done."
        )
        if not chunks or any("```" in c or "**" in c or "http" in c for c in chunks):
            out("VOICE_FAIL: sentence splitter kept markdown")
            return 1
        if any(len(c) > 400 for c in chunks):
            out("VOICE_FAIL: sentence chunk exceeded max_chars")
            return 1
        if _split_voice_sentences("```python\ncode only\n```") != []:
            out("VOICE_FAIL: code-only text should produce no speech chunks")
            return 1

        # Speaker-friendly cleaning: symbols become words, parens/brackets/
        # quotes/emoji are stripped, code and links are removed.
        cleaned = _voice_clean_for_speech(
            "Open (file) 1,000 times: 3-4 & 5% -> done! Path C:\\x \u2192 ok, "
            "\u201cquoted\u201d #2 @ 3pm \u2705 use `os.path.join` 100%"
        )
        if any(symbol in cleaned for symbol in "()[]{}%&@#\u2192\u2705`"):
            out(f"VOICE_FAIL: cleaner kept special characters: {cleaned!r}")
            return 1
        if "1000" not in cleaned or "3 to 4" not in cleaned or "and 5 percent" not in cleaned:
            out(f"VOICE_FAIL: cleaner did not expand symbols: {cleaned!r}")
            return 1
        if "quoted" not in cleaned or "number 2" not in cleaned:
            out(f"VOICE_FAIL: cleaner lost quoted content: {cleaned!r}")
            return 1
        # Units, currency, decimals, dotted identifiers, comparisons.
        unit_clean = _voice_clean_for_speech(
            "1.5GB and 200ms and 3.5GHz and 22C. Costs $5.99. "
            "x != y and a >= b. index.js and C:/Users/x."
        )
        for expected in (
            "gigabytes", "milliseconds", "gigahertz", "degrees celsius",
            "5 point 99 dollars", "not equal to", "greater than or equal to",
            "index dot js", "slash Users",
        ):
            if expected not in unit_clean:
                out(f"VOICE_FAIL: cleaner unit/currency handling missing {expected!r}: {unit_clean!r}")
                return 1
        if "ghzhertz" in unit_clean or "ghz" in unit_clean:
            out(f"VOICE_FAIL: cleaner produced a double unit: {unit_clean!r}")
            return 1
        # Barge-in: _tts_stop_playback must be callable without crashing.
        _tts_stop_playback()
        # Compaction: long text truncates at a sentence boundary with "...".
        long_text = (
            "This is a very long first sentence that keeps going and going "
            "and going and going and going and going and going. Short second."
        )
        compacted = _compact_speech_text(long_text, 60)
        if len(compacted) > 66 or not compacted.endswith("..."):
            out(f"VOICE_FAIL: compaction did not cap at a sentence boundary: {compacted!r}")
            return 1
        if "Short second" in compacted:
            out(f"VOICE_FAIL: compaction kept text past the cap: {compacted!r}")
            return 1
        if _compact_speech_text("Short text.", 0) != "Short text.":
            out("VOICE_FAIL: max_chars=0 should disable compaction")
            return 1

        # VAD gate: silence frames stay silent, loud frames start speech,
        # then a trailing silence window finalizes the utterance.
        gate = _FrameVadGate(rms_threshold=260.0, silence_finalize_ms=900)
        import math as _math

        loud = struct.pack("<320h", *([3000] * 320))
        quiet = struct.pack("<320h", *([0] * 320))
        started = False
        ended = False
        for ms in range(0, 2000, 20):
            s1, e1 = gate.feed(loud, float(ms))
            started = started or s1
            ended = ended or e1
        if not started:
            out("VOICE_FAIL: VAD gate did not detect speech onset")
            return 1
        for ms in range(2000, 3200, 20):
            s2, e2 = gate.feed(quiet, float(ms))
            ended = ended or e2
        if not ended:
            out("VOICE_FAIL: VAD gate did not finalize the utterance")
            return 1
        if not gate.speaking:
            pass  # speaking flag resets after finalize; acceptable
        # Onset confirmation: one loud frame must not false-start (noise
        # spike), two consecutive loud frames must start speech.
        confirm_gate = _FrameVadGate(rms_threshold=200.0, silence_finalize_ms=900, onset_confirmation_frames=2)
        single_loud = confirm_gate.feed(loud, 10.0)
        if single_loud[0]:
            out("VOICE_FAIL: a single loud frame must not start speech")
            return 1
        second_loud = confirm_gate.feed(loud, 30.0)
        if not second_loud[0]:
            out("VOICE_FAIL: two loud frames should confirm speech onset")
            return 1
        # Adaptive barge detector (used while TTS plays): steady TTS echo at
        # the mic must never trigger, but speech well above that floor
        # (6-20dB louder, sustained 160ms) must.
        echo = struct.pack("<320h", *([300] * 320))      # TTS echo at mic
        speech = struct.pack("<320h", *([1000] * 320))   # ~10dB above echo
        faint_speech = struct.pack("<320h", *([450] * 320))  # ~3.5dB above echo
        barge = _AdaptiveBargeDetector()
        barge_started = False
        for ms in range(0, 3000, 20):
            if barge.feed(echo, float(ms)):
                barge_started = True
                break
        if barge_started:
            out("VOICE_FAIL: steady TTS echo should never trigger the barge detector")
            return 1
        # A brief faint burst (a TTS syllable) must not confirm either.
        barge2 = _AdaptiveBargeDetector()
        barge_started2 = False
        for ms in range(0, 300, 20):  # 300ms of faint burst
            if barge2.feed(faint_speech, float(ms)):
                barge_started2 = True
                break
        if barge_started2:
            out("VOICE_FAIL: a faint brief burst should not trigger the barge detector")
            return 1
        # Real speech sustained above the echo triggers.
        barge3 = _AdaptiveBargeDetector()
        barge_started3 = False
        for ms in range(0, 3000, 20):
            frame = echo if ms < 600 else speech  # echo floor, then real speech
            if barge3.feed(frame, float(ms)):
                barge_started3 = True
                break
        if not barge_started3:
            out("VOICE_FAIL: sustained speech above the echo should trigger the barge detector")
            return 1
        # Adaptivity: after the floor rises (louder TTS), the old speech level
        # no longer triggers until speech exceeds the new floor.
        barge4 = _AdaptiveBargeDetector()
        for ms in range(0, 2000, 20):
            barge4.feed(echo, float(ms))
        barge_started4 = False
        for ms in range(0, 1000, 20):
            if barge4.feed(faint_speech, float(ms)):
                barge_started4 = True
                break
        if barge_started4:
            out("VOICE_FAIL: barge detector must adapt to a louder ambient floor")
            return 1
        pre_roll = gate.pre_roll()
        if len(pre_roll) > _VOICE_SAMPLE_RATE * 2 * 2:
            out("VOICE_FAIL: pre-roll ring buffer exceeded its cap")
            return 1

        # Wake-word scoring degrades to disabled without the lib.
        if _wake_word_score(b"\x00" * 640, None) != 0.0:
            out("VOICE_FAIL: wake-word scoring should be disabled without the lib")
            return 1

        # Frame chunker yields 20ms frames exactly.
        frames = list(_chunk_audio_for_vad(b"\x00" * 6400))
        if len(frames) != 10 or any(len(f) != 640 for f in frames):
            out("VOICE_FAIL: VAD frame chunking is incorrect")
            return 1

        # Kokoro result contract: with models present a valid voice synthesizes
        # a WAV; without them (or with a bad voice) the call returns an
        # actionable error dict and never crashes.
        model_present = (
            (NEXUS_DIR / "voice" / "kokoro-v1.0.onnx").exists()
            and (NEXUS_DIR / "voice" / "voices-v1.0.bin").exists()
        )
        if model_present:
            good = _tts_synthesize("hello from the voice test", voice="af_heart")
            if not good.get("ok") or not good.get("path") or not os.path.exists(good.get("path")):
                out(f"VOICE_FAIL: kokoro synthesis failed with models present: {good}")
                return 1
            bad = _tts_synthesize("hello", voice="nope_none")
            if bad.get("ok") or "error" not in bad:
                out("VOICE_FAIL: invalid voice should return an error")
                return 1
        else:
            result = _tts_synthesize("hello")
            if result.get("ok"):
                out("VOICE_FAIL: TTS should fail without model files")
                return 1
            if "error" not in result:
                out("VOICE_FAIL: TTS missing-model result lacks an error")
                return 1

        # Voice-setup URL resolution: the fallback tag produces the expected
        # model-files-v1.0 URLs without any network access.
        urls = _voice_setup_download_urls()
        if not urls.get("kokoro-v1.0.onnx") or "model-files-v1.0" not in urls["kokoro-v1.0.onnx"]:
            out("VOICE_FAIL: voice-setup URL resolution is incorrect")
            return 1
        if not urls.get("voices-v1.0.bin"):
            out("VOICE_FAIL: voice-setup missing voices URL")
            return 1

        out("VOICE_OK")
        return 0
    except Exception as exc:
        out(f"VOICE_FAIL: {exc}")
        return 1


_VOICE_SETUP_MANIFEST = [
    {
        "name": "kokoro-v1.0.onnx",
        "file": "kokoro-v1.0.onnx",
        "size": 325_000_000,
        "required": False,
    },
    {
        "name": "voices-v1.0.bin",
        "file": "voices-v1.0.bin",
        "size": 2_100_000,
        "required": False,
    },
]


def _voice_setup_download_urls() -> dict:
    """Resolve the latest Kokoro model-file release URLs from the GitHub API.

    Falls back to the pinned ``model-files-v1.0`` tag when the API is
    unreachable so the downloader never hard-fails on a transient network
    error.
    """
    import urllib.error as _url_err
    import urllib.request as _url_req

    fallback_tag = "model-files-v1.0"
    try:
        req = _url_req.Request(
            "https://api.github.com/repos/thewh1teagle/kokoro-onnx/releases/latest",
            headers={"User-Agent": "nexus-voice-setup/1.0"},
        )
        with _url_req.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        tag = str(data.get("tag_name") or fallback_tag)
        urls = {
            str(asset.get("name")): str(asset.get("browser_download_url"))
            for asset in data.get("assets", [])
            if asset.get("name") and asset.get("browser_download_url")
        }
        if urls:
            return urls
        tag = fallback_tag
    except Exception:
        tag = fallback_tag
    return {
        "kokoro-v1.0.onnx": (
            f"https://github.com/thewh1teagle/kokoro-onnx/releases/download/{tag}/kokoro-v1.0.onnx"
        ),
        "voices-v1.0.bin": (
            f"https://github.com/thewh1teagle/kokoro-onnx/releases/download/{tag}/voices-v1.0.bin"
        ),
    }


def _download_voice_file(url: str, dest: Path, expected_bytes: int = 0, timeout: float = 600.0) -> dict:
    """Download one model file to ~/.nexus/voice with a streaming write."""
    import urllib.request as _urlreq

    dest.parent.mkdir(parents=True, exist_ok=True)
    temporary = dest.with_name(f".{dest.name}.{os.getpid()}.tmp")
    try:
        req = _urlreq.Request(url, headers={"User-Agent": "nexus-voice-setup/1.0"})
        with _urlreq.urlopen(req, timeout=timeout) as resp:
            with open(temporary, "wb") as handle:
                total = 0
                while True:
                    chunk = resp.read(1 << 16)
                    if not chunk:
                        break
                    handle.write(chunk)
                    total += len(chunk)
        if expected_bytes and total < expected_bytes * 0.95:
            temporary.unlink(missing_ok=True)
            return {"ok": False, "name": dest.name, "error": f"download too small: {total} bytes"}
        os.replace(temporary, dest)
        return {"ok": True, "name": dest.name, "bytes": total}
    except Exception as exc:
        try:
            temporary.unlink(missing_ok=True)
        except Exception:
            pass
        return {"ok": False, "name": dest.name, "error": str(exc)}


def _run_voice_setup(force: bool = False, progress: bool = True) -> int:
    """Download optional voice models (Kokoro TTS) into ~/.nexus/voice.

    This step is optional: without it the voice engine still runs with RMS VAD
    and no local TTS. Returns 0 when all downloads succeeded (or were skipped
    because present), 1 when at least one required download failed.
    """
    def log(message: str) -> None:
        if progress:
            print(message, flush=True)

    voice_dir = NEXUS_DIR / "voice"
    voice_dir.mkdir(parents=True, exist_ok=True)
    urls = _voice_setup_download_urls()
    failed = False
    for entry in _VOICE_SETUP_MANIFEST:
        dest = voice_dir / entry["name"]
        if dest.exists() and dest.stat().st_size > 1000 and not force:
            log(f"present: {entry['name']}")
            continue
        url = urls.get(entry["file"]) or urls.get(entry["name"])
        if not url:
            log(f"failed: {entry['name']}: release asset not found")
            if entry["required"]:
                failed = True
            continue
        log(f"downloading {entry['name']} ...")
        result = _download_voice_file(url, dest, entry["size"])
        if result.get("ok"):
            log(f"ok: {entry['name']} ({result.get('bytes')} bytes)")
        else:
            log(f"failed: {entry['name']}: {result.get('error')}")
            if entry["required"]:
                failed = True
    if not failed:
        log("voice models ready")
    return 1 if failed else 0


def _wake_word_score(frame: bytes, porcupine=None) -> float:
    """Score one 20ms frame with Porcupine; returns 0..1 keyword likelihood.

    ``porcupine`` is the pvporcupine.create() instance; when None (lib or
    keyword file missing) the function returns 0.0 so wake gating degrades to
    disabled rather than crashing.
    """
    if porcupine is None:
        return 0.0
    try:
        import numpy as np

        samples = np.frombuffer(frame, dtype=np.int16)
        index = porcupine.process(samples)
        return 1.0 if index >= 0 else 0.0
    except Exception:
        return 0.0


def _run_voice_capture_helper(temp_directory: str, parent_pid: int) -> int:
    """Hold-to-talk Alt dictation using the default Windows microphone.

    While Alt is held, audio is captured through the waveform API and every
    ~1.2s the partial recording is snapshotted to a WAV file. Each snapshot is
    emitted as an ``interim_snapshot`` event so the parent TUI can stream live"""
    import ctypes
    import math

    WAVE_MAPPER = 0xFFFFFFFF
    SYNCHRONIZE = 0x00100000
    WAIT_TIMEOUT = 0x00000102
    SAMPLE_RATE = 16000
    INTERIM_INTERVAL_S = 0.8
    MAX_RECORDING_S = 300.0
    SILENCE_RMS = 260
    SILENCE_FINALIZE_S = 0.9
    RMS_WINDOW_BYTES = 16000
    WaveRecorder = _winmm_recorder_class()

    target_dir = Path(temp_directory).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    user32.GetAsyncKeyState.restype = ctypes.c_short
    kernel32.OpenProcess.argtypes = [ctypes.c_uint, ctypes.c_int, ctypes.c_uint]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    kernel32.WaitForSingleObject.restype = ctypes.c_uint
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_int

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


def _run_voice_engine_helper(temp_directory: str, parent_pid: int) -> int:
    """Persistent voice engine: continuous capture with mode switching.

    Unlike the push-to-talk helper, this process captures audio the whole time
    and applies a mode gate:
      - "ptt"       : Alt held = recording (same as the dictation helper)
      - "hands-free": VAD starts/ends utterances automatically
      - "wake-word" : a keyword arms VAD; the following utterance is captured
    Utterances are written to WAV files and emitted as ``vad_utterance``
    events (path + start/end offsets) so the TUI can transcribe and insert
    them exactly like dictation recordings. A ``synthesize`` command renders
    text with the local Kokoro model when available.

    Commands arrive on stdin as JSON lines:
      {"cmd": "mode", "mode": "hands-free"}
      {"cmd": "synthesize", "text": "...", "voice": "af_heart", "speed": 1.0}
      {"cmd": "stop"}
    """
    if os.name != "nt":
        _emit_voice_capture_event("unavailable", error="voice engine is currently supported on Windows")
        return 1

    import ctypes
    import math

    SYNCHRONIZE = 0x00100000
    WAIT_TIMEOUT = 0x00000102
    SAMPLE_RATE = 16000
    FRAME_MS = 20
    WaveRecorder = _winmm_recorder_class()

    target_dir = Path(temp_directory).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [ctypes.c_uint, ctypes.c_int, ctypes.c_uint]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    kernel32.WaitForSingleObject.restype = ctypes.c_uint
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_int
    parent_handle = kernel32.OpenProcess(SYNCHRONIZE, False, int(parent_pid))

    state = {
        "mode": "hands-free",
        "enabled": True,
        "stop": False,
        "wake_phrase": "",
        "wake_armed": False,   # wake-word heard, listening for the utterance
        "recording": False,
        "recording_path": "",
        "started_at": 0.0,
        "last_speech_at": 0.0,
        "last_wake_at": 0.0,
        "tts_busy": False,
        # Texts waiting to be spoken. Appends merge into the active pipeline so
        # the next sentence is synthesized WHILE the current one plays (no
        # dead air between sentences). tts_gen identifies the active worker so
        # a replace can retire the old worker without it clobbering state.
        "tts_pending_texts": [],
        "tts_gen": 0,
    }
    state_lock = threading.Lock()
    porcupine = None
    kokoro = None
    models_ready = threading.Event()

    def load_optional_models() -> None:
        nonlocal porcupine, kokoro
        voice_dir = NEXUS_DIR / "voice"
        try:
            porcupine_path = voice_dir / "porcupine_params.pv"
            keyword_path = voice_dir / "hey-nexus.ppn"
            if porcupine_path.exists() and keyword_path.exists():
                import pvporcupine

                porcupine = pvporcupine.create(
                    access_key="",
                    library_path=None,
                    model_path=str(porcupine_path),
                    keyword_paths=[str(keyword_path)],
                )
        except Exception:
            porcupine = None
        try:
            from kokoro_onnx import Kokoro

            model_path = voice_dir / "kokoro-v1.0.onnx"
            voices_path = voice_dir / "voices-v1.0.bin"
            if model_path.exists() and voices_path.exists():
                kokoro = Kokoro(str(model_path), str(voices_path))
        except Exception:
            kokoro = None
        finally:
            models_ready.set()
            _emit_voice_capture_event("models_loaded")

    def read_commands() -> None:
        try:
            for line in sys.stdin:
                try:
                    message = json.loads(line)
                except Exception:
                    continue
                cmd = str(message.get("cmd") or "")
                if cmd == "mode":
                    with state_lock:
                        mode = str(message.get("mode") or "hands-free")
                        if mode in {"ptt", "hands-free", "wake-word"}:
                            state["mode"] = mode
                            state["wake_armed"] = False
                    _emit_voice_capture_event("mode_changed", mode=mode)
                elif cmd == "synthesize":
                    text = str(message.get("text") or "")
                    voice = str(message.get("voice") or "af_heart")
                    speed = float(message.get("speed") or 1.0)
                    try:
                        max_chars = max(0, int(message.get("max_chars") or 0))
                    except (TypeError, ValueError):
                        max_chars = 0
                    append = bool(message.get("append"))
                    if text.strip():
                        with state_lock:
                            was_busy = bool(state.get("tts_busy"))
                            start_new = not was_busy or not append
                            if was_busy and not append:
                                # Replace: retire the old worker, drop pending
                                # speech, and start over with this reply.
                                state["tts_cancel"] = True
                                _tts_stop_playback()
                                state["tts_pending_texts"].clear()
                                state["tts_gen"] += 1
                                state["tts_cancel"] = False
                            state["tts_pending_texts"].append(
                                {"text": text, "voice": voice, "speed": speed, "max_chars": max_chars}
                            )
                            state["tts_busy"] = True
                            state["tts_started_at"] = time.monotonic() * 1000.0
                        if start_new:
                            _emit_voice_capture_event("tts_started")
                            threading.Thread(
                                target=_tts_worker,
                                args=(state["tts_gen"],),
                                name="nexus-tts-worker",
                                daemon=True,
                            ).start()
                elif cmd == "warmup":
                    # Force the model to finish loading and warm onnxruntime
                    # without audible output. Used by the TUI at startup so
                    # the first real reply speaks instantly.
                    if not models_ready.wait(timeout=20.0):
                        _emit_voice_capture_event("tts_error", error="Kokoro model failed to load")
                        continue
                    if kokoro is not None:
                        try:
                            _tts_synthesize_kokoro(" ", voice="af_bella", speed=1.0, kokoro=kokoro)
                        except Exception:
                            pass
                    _emit_voice_capture_event("warmup_done")
                elif cmd == "barge_in":
                    with state_lock:
                        # User pressed push-to-talk while TTS was playing:
                        # cancel the current sentence, drop pending speech, and
                        # stop playback. Only act when busy so a stale cancel
                        # can never kill the NEXT speak.
                        if state.get("tts_busy"):
                            state["tts_cancel"] = True
                            state["tts_pending_texts"].clear()
                            state["tts_gen"] += 1
                            _tts_stop_playback()
                            _emit_voice_capture_event("tts_cancelled")
                elif cmd == "stop":
                    with state_lock:
                        state["stop"] = True
                    return
        finally:
            with state_lock:
                state["stop"] = True

    def _tts_worker(gen: int) -> None:
        """Pipelined speech worker.

        A producer thread synthesizes sentences AHEAD of playback into a small
        buffer while the main loop plays them, so consecutive sentences (and
        appended compacted text) flow with no dead air. Appends merge into the
        active pipeline; barge_in/replace bump ``gen`` which retires this
        worker without it clobbering a newer worker's state.
        """
        if not models_ready.wait(timeout=20.0):
            _emit_voice_capture_event("tts_error", error="Kokoro model failed to load")
            return
        if kokoro is None:
            _emit_voice_capture_event("tts_error", error="Kokoro model is unavailable")
            return
        synth_buffer: queue.Queue = queue.Queue(maxsize=3)
        producer_active = [True]
        last_activity = [time.monotonic()]

        def _current() -> bool:
            """True while this worker is still the active generation."""
            with state_lock:
                return (
                    not state["stop"]
                    and not state.get("tts_cancel")
                    and state.get("tts_gen") == gen
                )

        def producer() -> None:
            try:
                while True:
                    if not _current():
                        return
                    with state_lock:
                        job = state["tts_pending_texts"][0] if state["tts_pending_texts"] else None
                    if job is None:
                        time.sleep(0.05)
                        continue
                    producer_active[0] = True
                    last_activity[0] = time.monotonic()
                    # Small chunks (~60 chars, sentence-aligned) so each
                    # synthesizes in ~1s and pipelines behind the previous
                    # playback; a single large chunk costs ~25ms/char of dead
                    # air before the first word of the rest plays.
                    chunks = _split_voice_sentences(
                        job["text"],
                        max_chars=60,
                        total_max_chars=job.get("max_chars", 0),
                    )
                    with state_lock:
                        if state["tts_pending_texts"] and state["tts_pending_texts"][0] is job:
                            state["tts_pending_texts"].pop(0)
                    for chunk in chunks:
                        if not _current():
                            return
                        # Turkish voice uses the dedicated inference path; the
                        # English model is irrelevant (and unloaded) for it.
                        if job["voice"] == _TURKISH_VOICE:
                            result = _tts_synthesize_kokoro(
                                chunk, voice=job["voice"], speed=job["speed"]
                            )
                        else:
                            result = _tts_synthesize_kokoro(
                                chunk, voice=job["voice"], speed=job["speed"], kokoro=kokoro
                            )
                        if not _current():
                            return
                        if result.get("ok") and result.get("path"):
                            last_activity[0] = time.monotonic()
                            with state_lock:
                                state["tts_started_at"] = time.monotonic() * 1000.0
                            _emit_voice_capture_event("tts_chunk", path=result["path"])
                            synth_buffer.put(result["path"])
                        elif not result.get("ok"):
                            _emit_voice_capture_event(
                                "tts_error",
                                error=result.get("error") or "synth failed",
                                voice=job["voice"],
                            )
                    with state_lock:
                        no_more = not state["tts_pending_texts"]
                    if no_more:
                        producer_active[0] = False
                        last_activity[0] = time.monotonic()
            finally:
                producer_active[0] = False
                synth_buffer.put(None)

        threading.Thread(target=producer, name="nexus-tts-producer", daemon=True).start()
        try:
            while True:
                if not _current():
                    with state_lock:
                        is_active = state.get("tts_gen") == gen
                    if is_active:
                        _emit_voice_capture_event("tts_cancelled")
                    break
                try:
                    path = synth_buffer.get(timeout=0.05)
                except queue.Empty:
                    with state_lock:
                        pending = bool(state["tts_pending_texts"])
                        gen_ok = state.get("tts_gen") == gen
                    idle_for = time.monotonic() - last_activity[0]
                    # Stay alive while the producer is working OR while a
                    # possible append (the TUI streams first-sentence then the
                    # rest) may still land. The app can take >0.5s between the
                    # first speak and the append (JS async), so use a 4s grace
                    # window after the last audio before going idle.
                    if not pending and gen_ok and not producer_active[0] and idle_for > 4.0:
                        break
                    continue
                if path is None:
                    break
                _tts_play_wav(path)
                time.sleep(0.15)
        finally:
            while True:
                try:
                    synth_buffer.get_nowait()
                except queue.Empty:
                    break
            with state_lock:
                still_active = state.get("tts_gen") == gen
                if still_active:
                    state["tts_cancel"] = False
                    state["tts_busy"] = False
            # Only the ACTIVE generation reports completion; a replaced
            # worker's tts_done would tell the TUI speech finished while the
            # new worker is still playing.
            if still_active:
                _emit_voice_capture_event("tts_done")

    # Emit ready immediately (the TUI keeps the engine alive), then LOAD the
    # Kokoro model SYNCHRONOUSLY in this thread before starting the capture
    # loop. This is a one-time ~2s startup cost but guarantees the first
    # synthesize never blocks on the model - the 2s delay we were seeing was
    # the background load racing the first reply. Commands still work during
    # the load (they queue); only VAD capture starts after it.
    _emit_voice_capture_event("ready", engine=True, mode=state["mode"])
    # Start the model load on its own thread FIRST so it runs before the
    # command reader contends; then the main thread waits on it before the
    # capture loop, guaranteeing TTS is instant once capture starts.
    load_thread = threading.Thread(target=load_optional_models, name="nexus-voice-models", daemon=True)
    load_thread.start()
    threading.Thread(target=read_commands, daemon=True).start()
    models_ready.wait(timeout=20.0)

    recorder = None
    vad = _SileroVadGate()
    frame_ms = FRAME_MS
    utterance_index = 0

    # The engine keeps ONE continuous capture recorder alive for the whole
    # session in hands-free / wake-word modes so the VAD always has audio to
    # inspect. "recording" is a logical utterance state: speech onset sets it
    # and snapshots from the pre-roll; silence finalization closes the
    # utterance. Byte accounting is monotonic: last_processed never resets so
    # each frame is fed to the VAD exactly once.
    continuous_recorder = None
    utterance_start_byte = 0  # recorder byte offset where the utterance begins
    utterance_start_ms = 0.0

    def ensure_continuous_capture() -> None:
        nonlocal continuous_recorder
        if continuous_recorder is not None:
            return
        try:
            continuous_recorder = WaveRecorder()
            _emit_voice_capture_event("capture_ready")
        except Exception as exc:
            _emit_voice_capture_event("error", error=f"voice engine capture: {exc}")
            continuous_recorder = None

    def begin_utterance() -> None:
        nonlocal utterance_start_byte, utterance_start_ms, utterance_index
        if state["recording"]:
            return
        try:
            utterance_index += 1
            path_value = target_dir / f"vad-{int(time.time() * 1000)}-{utterance_index}.wav"
            with state_lock:
                state["recording"] = True
                state["recording_path"] = str(path_value)
                state["started_at"] = time.monotonic()
            # Snapshot starts a short pre-roll before speech onset. Do NOT
            # reset processed_bytes: the VAD keeps consuming the live stream.
            if continuous_recorder is not None:
                utterance_start_byte = max(
                    0, continuous_recorder.length() - vad.pre_roll_bytes
                )
            else:
                utterance_start_byte = 0
            utterance_start_ms = time.monotonic() * 1000.0
            _emit_voice_capture_event("recording_started", path=str(path_value), source="vad")
        except Exception as exc:
            _emit_voice_capture_event("error", error=f"voice engine begin: {exc}")

    def finish_utterance(save: bool) -> None:
        nonlocal utterance_start_byte
        with state_lock:
            if not state["recording"]:
                return
            state["recording"] = False
            path_value = state["recording_path"]
            state["recording_path"] = ""
            duration_ms = max(0, int((time.monotonic() - state["started_at"]) * 1000))
        if save and path_value and continuous_recorder is not None:
            try:
                continuous_recorder.write_snapshot(path_value, utterance_start_byte)
            except Exception:
                pass
            try:
                ok_size = Path(path_value).stat().st_size > 44
            except Exception:
                ok_size = False
            if ok_size:
                _emit_voice_capture_event(
                    "vad_utterance",
                    path=path_value,
                    duration_ms=duration_ms,
                    mode=state["mode"],
                )
            else:
                try:
                    Path(path_value).unlink(missing_ok=True)
                except Exception:
                    pass
        elif path_value:
            try:
                Path(path_value).unlink(missing_ok=True)
            except Exception:
                pass

    try:
        while True:
            with state_lock:
                if state["stop"]:
                    break
                mode = state["mode"]
            if parent_handle and kernel32.WaitForSingleObject(parent_handle, 0) != WAIT_TIMEOUT:
                break

            now_ms = time.monotonic() * 1000.0
            if mode in {"hands-free", "wake-word"}:
                ensure_continuous_capture()
            elif continuous_recorder is not None:
                # ptt mode: the dictation helper owns the mic; stop capturing.
                try:
                    continuous_recorder.stop(None)
                except Exception:
                    pass
                continuous_recorder = None
                if state["recording"]:
                    finish_utterance(False)

            # While TTS is synthesizing/playing, skip mic frame processing
            # entirely: the Python-heavy VAD loop would contend for the GIL
            # and slow Kokoro ~5x (observed 0.6s -> 3.9s). Barge-in is
            # explicit (Alt press -> barge_in command), so the mic is not
            # needed during speech output.
            tts_busy_now = bool(state.get("tts_busy"))
            if continuous_recorder is not None and not tts_busy_now:
                total = continuous_recorder.length()
                with state_lock:
                    last_processed = state.get("processed_bytes", 0)
                new_bytes = total - last_processed
                if new_bytes > 0:
                    audio = continuous_recorder.full_data()[last_processed:total]
                    with state_lock:
                        state["processed_bytes"] = total
                    frame_ms_now = now_ms
                    for frame in _chunk_audio_for_vad(audio, _VOICE_FRAME_BYTES):
                        frame_ms_now += FRAME_MS
                        started, ended = vad.feed(frame, frame_ms_now)
                        if started and mode in {"hands-free", "wake-word"}:
                            if mode == "wake-word" and not state["wake_armed"]:
                                continue
                            if state["wake_armed"]:
                                state["wake_armed"] = False
                            # Skip the TTS tail right after a barge-in cancel
                            # (speaker feedback winds down for ~400ms), then
                            # the user's continued speech starts an utterance.
                            if (now_ms - state.get("tts_last_cancel_at", 0)) < 400:
                                continue
                            begin_utterance()
                        if ended and state["recording"]:
                            finish_utterance(True)

            # Wake-word detection when armed in wake-word mode and idle.
            if mode == "wake-word" and not state["recording"] and porcupine is not None and continuous_recorder is not None:
                if (now_ms - state["last_wake_at"]) >= _VOICE_WAKE_DEBOUNCE_MS:
                    audio = continuous_recorder.full_data()
                    hit = False
                    for frame in _chunk_audio_for_vad(audio[-_VOICE_FRAME_BYTES * 50:], _VOICE_FRAME_BYTES):
                        if _wake_word_score(frame, porcupine) >= 1.0:
                            hit = True
                            break
                    if hit:
                        state["last_wake_at"] = now_ms
                        state["wake_armed"] = True
                        _emit_voice_capture_event("wake_detected")

            time.sleep(0.005)
    finally:
        if state["recording"]:
            try:
                finish_utterance(False)
            except Exception:
                pass
        if continuous_recorder is not None:
            try:
                continuous_recorder.stop(None)
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
    if "--voice-engine" in args:
        index = args.index("--voice-engine")
        if index + 2 >= len(args):
            return 2
        try:
            parent_pid = int(args[index + 2])
        except ValueError:
            return 2
        return _run_voice_engine_helper(args[index + 1], parent_pid)
    if "--voice-engine-self-test" in args:
        return _run_voice_engine_self_test()
    if "--voice-setup" in args:
        force = any(token == "--force" for token in args)
        silent = any(token == "--quiet" for token in args)
        return _run_voice_setup(force=force, progress=not silent)
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