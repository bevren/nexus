"""Skill dependency management: shared venv + requirements.txt installs."""
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

NEXUS_DIR = Path.home() / ".nexus"
SKILLS_VENV_DIR = NEXUS_DIR / "skills-venv"
REQ_NAME = "requirements.txt"
MARKER_NAME = ".deps.json"
LOCK_NAME = ".deps.lock"
ERR_NAME = ".deps.err"


def _get_config() -> dict:
    cfg = {}
    try:
        cfg = json.loads((NEXUS_DIR / "config.json").read_text(encoding="utf-8"))
    except Exception:
        pass
    return cfg if isinstance(cfg, dict) else {}


def auto_install_enabled() -> bool:
    val = _get_config().get("skills_auto_install_deps", True)
    return bool(val) if isinstance(val, bool) else True


def get_venv_python() -> str:
    """Return venv python path, creating the shared venv lazily if needed."""
    if sys.platform == "win32":
        py = SKILLS_VENV_DIR / "Scripts" / "python.exe"
        pip = SKILLS_VENV_DIR / "Scripts" / "pip.exe"
    else:
        py = SKILLS_VENV_DIR / "bin" / "python"
        pip = SKILLS_VENV_DIR / "bin" / "pip"
    if py.exists() and pip.exists():
        return str(py)
    base = sys.executable
    try:
        SKILLS_VENV_DIR.mkdir(parents=True, exist_ok=True)
        subprocess.run([base, "-m", "venv", str(SKILLS_VENV_DIR)], check=True, timeout=180, capture_output=True)
    except Exception:
        if sys.platform == "win32":
            try:
                subprocess.run(["py", "-3", "-m", "venv", str(SKILLS_VENV_DIR)], check=True, timeout=180, capture_output=True)
            except Exception:
                pass
    return str(py) if py.exists() else base


def _requirements_path(skill_dir):
    return Path(skill_dir) / REQ_NAME


def _marker_path(skill_dir):
    return Path(skill_dir) / MARKER_NAME


def _lock_path(skill_dir):
    return Path(skill_dir) / LOCK_NAME


def _err_path(skill_dir):
    return Path(skill_dir) / ERR_NAME


def _req_hash(skill_dir):
    p = _requirements_path(skill_dir)
    if not p.exists():
        return ""
    try:
        return hashlib.sha256(p.read_bytes()).hexdigest()[:16]
    except Exception:
        return ""


def _read_marker(skill_dir):
    try:
        if _marker_path(skill_dir).exists():
            return json.loads(_marker_path(skill_dir).read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def requirements_satisfied(skill_dir) -> dict:
    """Report dependency state WITHOUT installing or blocking."""
    req = _requirements_path(skill_dir)
    if not req.exists():
        return {"present": False, "installed": True, "installing": False, "needs_install": False, "requirements": [], "error": ""}
    reqs = []
    try:
        reqs = [ln.strip() for ln in req.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.strip().startswith("#")]
    except Exception:
        reqs = []
    marker = _read_marker(skill_dir)
    installed = marker.get("req_hash") == _req_hash(skill_dir)
    err = ""
    try:
        if _err_path(skill_dir).exists():
            err = _err_path(skill_dir).read_text(encoding="utf-8")[-800:]
    except Exception:
        pass
    lock = _lock_path(skill_dir)
    installing = lock.exists()
    return {
        "present": True,
        "installed": bool(installed),
        "installing": bool(installing),
        "needs_install": bool(not installed and not installing),
        "requirements": reqs,
        "error": err,
    }

_WRAPPER = """import subprocess, sys, json, hashlib, time, os
s, r, py = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    p = subprocess.run([py, "-m", "pip", "install", "--disable-pip-version-check", "-r", r], capture_output=True, text=True, timeout=600)
    ok = p.returncode == 0
    err = (p.stderr or "")[-2000:]
    out = (p.stdout or "")[-2000:]
except Exception as e:
    ok, err, out = False, str(e), ""
if ok:
    try:
        req_text = open(r, "rb").read()
        h = hashlib.sha256(req_text).hexdigest()[:16]
        reqs = [ln.strip() for ln in open(r, encoding="utf-8").read().splitlines() if ln.strip() and not ln.strip().startswith("#")]
        json.dump({"req_hash": h, "installed_at": time.time(), "packages": reqs}, open(os.path.join(s, ".deps.json"), "w", encoding="utf-8"), indent=2)
    except Exception:
        pass
else:
    try:
        open(os.path.join(s, ".deps.err"), "w", encoding="utf-8").write(err or out or "pip install failed")
    except Exception:
        pass
try:
    os.remove(os.path.join(s, ".deps.lock"))
except Exception:
    pass
"""


def _install_background(skill_dir, py) -> None:
    req = _requirements_path(skill_dir)
    lock = _lock_path(skill_dir)
    try:
        lock.write_text(str(os.getpid()), encoding="utf-8")
    except Exception:
        pass
    try:
        if _err_path(skill_dir).exists():
            _err_path(skill_dir).unlink()
    except Exception:
        pass
    kwargs = {}
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    try:
        subprocess.Popen([sys.executable, "-c", _WRAPPER, str(skill_dir), str(req), py], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kwargs)
    except Exception:
        try:
            lock.unlink(missing_ok=True)
        except Exception:
            pass


def ensure_skill_dependencies(skill_dir) -> dict:
    """Ensure skill requirements are installed. Non-blocking: kicks off pip in the background."""
    info = requirements_satisfied(skill_dir)
    if not info["present"]:
        return {"status": "no_requirements", "installed": True, "installing": False, "error": ""}
    if not auto_install_enabled():
        return {"status": "skipped", "installed": False, "installing": False, "error": "skills_auto_install_deps is false in config"}
    if info["installed"]:
        return {"status": "satisfied", "installed": True, "installing": False, "packages": info["requirements"], "error": ""}
    if info["installing"]:
        return {"status": "installing", "installed": False, "installing": True, "packages": info["requirements"], "error": ""}
    py = get_venv_python()
    _install_background(skill_dir, py)
    return {"status": "installing", "installed": False, "installing": True, "packages": info["requirements"], "error": ""}
