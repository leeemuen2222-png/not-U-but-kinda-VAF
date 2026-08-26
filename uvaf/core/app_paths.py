from __future__ import annotations

import json
import os
from pathlib import Path

APP_NAME = "UVAF"


def app_data_dir() -> Path:
    if os.name == "nt":
        base = Path(os.getenv("APPDATA", Path.home()))
        return base / APP_NAME
    return Path.home() / ".uvaf"


def preferences_file() -> Path:
    """Primary persistent user-preference file."""
    return app_data_dir() / "preferences.json"


def settings_file() -> Path:
    """
    Legacy settings path kept for migration/backward compatibility.

    New UVAF versions write user preferences to preferences.json.
    """
    return app_data_dir() / "settings.json"


def logs_dir() -> Path:
    return app_data_dir() / "logs"


def projects_dir() -> Path:
    return app_data_dir() / "projects"


def active_project_file() -> Path:
    return app_data_dir() / "active_project.json"


def legacy_templates_dir() -> Path:
    return app_data_dir() / "templates"


def templates_dir() -> Path:
    """
    Return the current project's isolated template directory.

    Before a project is opened, fall back to the old global template folder
    for backward compatibility.
    """
    try:
        data = json.loads(
            active_project_file().read_text(encoding="utf-8")
        )
        project_id = data.get("project_id")
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        project_id = None

    if project_id:
        path = projects_dir() / str(project_id) / "templates"
        path.mkdir(parents=True, exist_ok=True)
        return path

    path = legacy_templates_dir()
    path.mkdir(parents=True, exist_ok=True)
    return path


def modules_dir() -> Path:
    return app_data_dir() / "modules"


def ensure_runtime_dirs() -> None:
    for path in (
        app_data_dir(),
        logs_dir(),
        projects_dir(),
        legacy_templates_dir(),
        modules_dir(),
    ):
        path.mkdir(parents=True, exist_ok=True)
