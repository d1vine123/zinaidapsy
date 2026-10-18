"""Prepare the private database, uploads and production settings for SCP.

Run locally with venv/bin/python. This does not change the source database.
"""

import argparse
import os
from pathlib import Path
import re
import secrets
import shutil
import sqlite3

from dotenv import dotenv_values


def env_value(value):
    value = str(value)
    if any(character in value for character in ("\n", "\r", "\x00")):
        raise ValueError("Multiline environment values are not supported")
    if re.fullmatch(r"[A-Za-z0-9_./:@,+?=&%-]*", value):
        return value
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def main():
    root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=root / "recovery" / "server-data")
    args = parser.parse_args()
    output = args.output.resolve()
    recovery = (root / "recovery").resolve()
    if output == recovery or not output.is_relative_to(recovery):
        raise SystemExit("Output must be a new directory inside recovery/")
    if output.exists():
        raise SystemExit(f"Existing data preserved: {output}. Use it or choose a new --output directory.")
    source_db = root / "db.sqlite3"
    if not source_db.is_file() or not (root / "media").is_dir():
        raise SystemExit("The original database and media directory are required")

    production = dict(dotenv_values(root / "deploy" / "production.env.example", interpolate=False))
    local = dotenv_values(root / ".env", interpolate=False)
    production["SECRET_KEY"] = secrets.token_urlsafe(64)
    for name in production:
        if name.startswith(("TELEGRAM_", "GOOGLE_", "FEEDBACK_")) and name in local:
            production[name] = local[name] or ""
    required = ("GOOGLE_FORM_ID", "GOOGLE_ENTRY_NAME", "GOOGLE_ENTRY_PHONE")
    missing = [name for name in required if not production.get(name)]
    if missing:
        raise SystemExit("Missing delivery settings in local .env: " + ", ".join(missing))
    env_text = "\n".join(f"{name}={env_value(value or '')}" for name, value in production.items()) + "\n"

    recovery.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(recovery, 0o700)
    output.mkdir(mode=0o700)
    with sqlite3.connect(source_db.as_uri() + "?mode=ro", uri=True) as source:
        with sqlite3.connect(output / "db.sqlite3") as target:
            source.backup(target)
            if target.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise SystemExit("SQLite integrity check failed")
            originals = list(target.execute("SELECT file FROM wagtailimages_image"))
    (output / "db.sqlite3").chmod(0o600)
    shutil.copytree(root / "media", output / "media", ignore=shutil.ignore_patterns("media", ".DS_Store"))
    for (relative,) in originals:
        target = output / "media" / relative
        if not target.resolve().is_relative_to((output / "media").resolve()):
            raise SystemExit("Unexpected image path in database")
        if not target.is_file():
            fallback = root / relative
            if not fallback.is_file() or not fallback.resolve().is_relative_to((root / "original_images").resolve()):
                raise SystemExit("An image original is missing; package preserved for inspection")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(fallback, target)
    env_path = output / "production.env"
    with open(env_path, "x", opener=lambda path, flags: os.open(path, flags, 0o600)) as stream:
        stream.write(env_text)
    print(f"Ready: {output}")
    print(f"Database verified; {len(originals)} image originals included; production.env is private.")


if __name__ == "__main__":
    main()
