#!/usr/bin/env python3
"""Create a minimal Android project for the Nexus Termux toolchain."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shutil
import stat
from xml.sax.saxutils import escape


PACKAGE_RE = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "android-app"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, help="New project directory")
    parser.add_argument("--name", required=True, help="User-visible application name")
    parser.add_argument("--package", dest="package_name", help="Java package name")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    app_name = args.name.strip()
    if not app_name:
        raise SystemExit("--name must not be empty")

    output = Path(args.output).expanduser().resolve()
    if output.exists():
        if not output.is_dir():
            raise SystemExit(f"Output exists and is not a directory: {output}")
        if any(output.iterdir()):
            raise SystemExit(f"Refusing to overwrite non-empty directory: {output}")

    slug = slugify(output.name or app_name)
    package_segment = slug.replace("-", "")
    if package_segment[0].isdigit():
        package_segment = f"app{package_segment}"
    package_name = (args.package_name or f"dev.nexus.{package_segment}").strip()
    if not PACKAGE_RE.fullmatch(package_name):
        raise SystemExit("--package must be lowercase Java segments such as dev.nexus.todo")

    template = Path(__file__).resolve().parent.parent / "assets" / "template"
    if not template.is_dir():
        raise SystemExit(f"Missing project template: {template}")

    output.mkdir(parents=True, exist_ok=True)
    shutil.copytree(template, output, dirs_exist_ok=True)

    replacements = {
        "__APP_NAME__": escape(app_name),
        "__PACKAGE__": package_name,
    }
    for path in output.rglob("*"):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for old, new in replacements.items():
            text = text.replace(old, new)
        path.write_text(text, encoding="utf-8", newline="\n")

    placeholder_java = output / "src" / "__PACKAGE_PATH__" / "MainActivity.java"
    package_dir = output / "src" / Path(*package_name.split("."))
    package_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(placeholder_java), str(package_dir / "MainActivity.java"))
    placeholder_java.parent.rmdir()

    build_script = output / "build-termux.sh"
    build_script.chmod(build_script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    result = {
        "ok": True,
        "project_path": str(output),
        "app_name": app_name,
        "package": package_name,
        "main_activity": f"{package_name}/.MainActivity",
        "next": f'android_build(project_path="{args.output}", deploy=True)',
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
