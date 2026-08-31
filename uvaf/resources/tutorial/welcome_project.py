from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime
from pathlib import Path

from ...core.app_paths import app_data_dir, projects_dir


WELCOME_NAMES = {
    "欢迎使用UVAF",
    "欢迎使用 UVAF",
    "Welcome to UVAF",
}


def ensure_tutorial_welcome_project(project_manager, reset: bool = False):
    """Create a fresh tutorial welcome project from the user's current welcome project.

    The existing welcome project is used as the source so its current Arknights
    search example, templates and assets are preserved exactly.  The original
    project folder is archived outside the visible project library only after
    the clone has been written successfully.  A marker prevents repeated
    cloning on later launches.
    """
    tutorial_root = app_data_dir() / "tutorial"
    tutorial_root.mkdir(parents=True, exist_ok=True)
    marker = tutorial_root / "welcome_project.json"

    try:
        marker_data = json.loads(marker.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        marker_data = {}

    existing_id = str(marker_data.get("project_id", "")).strip()
    if existing_id:
        existing = project_manager.get_project(existing_id)
        if existing is not None:
            if reset:
                archived_value = str(marker_data.get("source_archive", "")).strip()
                archived = Path(archived_value) if archived_value else None
                if archived is not None and archived.is_dir():
                    current_path = existing.path
                    shutil.rmtree(current_path, ignore_errors=True)
                    shutil.copytree(archived, current_path)
                    manifest_path = current_path / "project.json"
                    data = json.loads(manifest_path.read_text(encoding="utf-8"))
                    stamp = datetime.now().isoformat(timespec="seconds")
                    data["project_id"] = existing_id
                    data["name"] = "欢迎使用UVAF"
                    data["updated_at"] = stamp
                    manifest_path.write_text(
                        json.dumps(data, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    return project_manager.get_project(existing_id)
            return existing

    projects = project_manager.list_projects()
    source = next((p for p in projects if p.name.strip() in WELCOME_NAMES), None)

    if source is None:
        created = project_manager.create_project("欢迎使用UVAF")
        marker.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "project_id": created.project_id,
                    "created_from": "blank",
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return created

    new_id = uuid.uuid4().hex[:12]
    destination = projects_dir() / new_id
    shutil.copytree(source.path, destination)

    manifest_path = destination / "project.json"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    stamp = datetime.now().isoformat(timespec="seconds")
    data["project_id"] = new_id
    data["name"] = "欢迎使用UVAF"
    data["created_at"] = stamp
    data["updated_at"] = stamp
    manifest_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # Archive the source only after the clone is complete and readable.
    cloned = project_manager.get_project(new_id)
    if cloned is None:
        shutil.rmtree(destination, ignore_errors=True)
        return source

    archive_root = tutorial_root / "welcome_source_archive"
    archive_root.mkdir(parents=True, exist_ok=True)
    archived = archive_root / source.project_id
    if archived.exists():
        shutil.rmtree(archived, ignore_errors=True)
    try:
        shutil.move(str(source.path), str(archived))
    except OSError:
        # Keeping the old source visible is safer than losing it.
        pass

    project_manager.set_current(new_id)
    marker.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "project_id": new_id,
                "created_from": source.project_id,
                "source_archive": str(archived),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return cloned
