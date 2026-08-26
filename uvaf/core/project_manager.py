from __future__ import annotations

import json
import shutil
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .app_paths import active_project_file, projects_dir


PROJECT_EXTENSION = ".uvafproj"
PROJECT_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class ProjectInfo:
    project_id: str
    name: str
    path: Path
    created_at: str
    updated_at: str


class ProjectManager:
    """UVAF project library and portable project archive manager."""

    def __init__(self) -> None:
        projects_dir().mkdir(parents=True, exist_ok=True)

    def list_projects(self) -> list[ProjectInfo]:
        result: list[ProjectInfo] = []

        for folder in projects_dir().iterdir():
            if not folder.is_dir():
                continue

            manifest = folder / "project.json"

            try:
                data = json.loads(
                    manifest.read_text(encoding="utf-8")
                )
            except (OSError, json.JSONDecodeError):
                continue

            result.append(
                ProjectInfo(
                    project_id=str(
                        data.get(
                            "project_id",
                            folder.name,
                        )
                    ),
                    name=str(
                        data.get(
                            "name",
                            folder.name,
                        )
                    ),
                    path=folder,
                    created_at=str(
                        data.get("created_at", "")
                    ),
                    updated_at=str(
                        data.get("updated_at", "")
                    ),
                )
            )

        result.sort(
            key=lambda project: project.updated_at,
            reverse=True,
        )
        return result

    def current_project_id(self) -> str | None:
        try:
            data = json.loads(
                active_project_file().read_text(
                    encoding="utf-8"
                )
            )
        except (
            FileNotFoundError,
            OSError,
            json.JSONDecodeError,
        ):
            return None

        project_id = data.get("project_id")
        return str(project_id) if project_id else None

    def current_project(self) -> ProjectInfo | None:
        project_id = self.current_project_id()

        if not project_id:
            return None

        return self.get_project(project_id)

    def get_project(
        self,
        project_id: str,
    ) -> ProjectInfo | None:
        folder = projects_dir() / project_id
        manifest = folder / "project.json"

        if not manifest.exists():
            return None

        try:
            data = json.loads(
                manifest.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError):
            return None

        return ProjectInfo(
            project_id=project_id,
            name=str(
                data.get(
                    "name",
                    project_id,
                )
            ),
            path=folder,
            created_at=str(
                data.get("created_at", "")
            ),
            updated_at=str(
                data.get("updated_at", "")
            ),
        )

    def set_current(
        self,
        project_id: str | None,
    ) -> None:
        path = active_project_file()

        if project_id is None:
            path.unlink(missing_ok=True)
            return

        if self.get_project(project_id) is None:
            raise FileNotFoundError(
                f"Project does not exist: {project_id}"
            )

        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        path.write_text(
            json.dumps(
                {
                    "project_id": project_id,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def create_project(
        self,
        name: str,
    ) -> ProjectInfo:
        name = name.strip()

        if not name:
            raise ValueError("项目名称不能为空。")

        project_id = uuid.uuid4().hex[:12]
        folder = projects_dir() / project_id
        folder.mkdir(
            parents=True,
            exist_ok=False,
        )

        (folder / "templates").mkdir()
        (folder / "assets").mkdir()

        stamp = datetime.now().isoformat(
            timespec="seconds"
        )

        manifest = {
            "schema_version": PROJECT_SCHEMA_VERSION,
            "project_id": project_id,
            "name": name,
            "created_at": stamp,
            "updated_at": stamp,
        }

        (folder / "project.json").write_text(
            json.dumps(
                manifest,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        (folder / "workflow.json").write_text(
            json.dumps(
                {
                    "schema_version": PROJECT_SCHEMA_VERSION,
                    "workspace_mode": "simple",
                    "nodes": [],
                    "connections": [],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        self.set_current(project_id)

        project = self.get_project(project_id)

        if project is None:
            raise RuntimeError("项目创建失败。")

        return project

    def project_templates_dir(
        self,
        project_id: str | None = None,
    ) -> Path:
        project_id = (
            project_id
            or self.current_project_id()
        )

        if not project_id:
            raise RuntimeError("当前没有打开项目。")

        path = (
            projects_dir()
            / project_id
            / "templates"
        )
        path.mkdir(
            parents=True,
            exist_ok=True,
        )
        return path

    def workflow_file(
        self,
        project_id: str | None = None,
    ) -> Path:
        project_id = (
            project_id
            or self.current_project_id()
        )

        if not project_id:
            raise RuntimeError("当前没有打开项目。")

        return (
            projects_dir()
            / project_id
            / "workflow.json"
        )

    def load_workflow(
        self,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        path = self.workflow_file(project_id)

        try:
            data = json.loads(
                path.read_text(encoding="utf-8")
            )
        except (
            FileNotFoundError,
            OSError,
            json.JSONDecodeError,
        ):
            return {
                "schema_version": PROJECT_SCHEMA_VERSION,
                "workspace_mode": "simple",
                "nodes": [],
                "connections": [],
            }

        return data if isinstance(data, dict) else {}

    def save_workflow(
        self,
        state: dict[str, Any],
        project_id: str | None = None,
    ) -> None:
        project_id = (
            project_id
            or self.current_project_id()
        )

        if not project_id:
            raise RuntimeError("当前没有打开项目。")

        workflow = self.workflow_file(project_id)

        workflow.write_text(
            json.dumps(
                state,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        manifest_path = (
            projects_dir()
            / project_id
            / "project.json"
        )

        manifest = json.loads(
            manifest_path.read_text(
                encoding="utf-8"
            )
        )
        manifest["updated_at"] = (
            datetime.now().isoformat(
                timespec="seconds"
            )
        )

        manifest_path.write_text(
            json.dumps(
                manifest,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def delete_project(
        self,
        project_id: str,
    ) -> None:
        """
        Permanently delete one project from the local UVAF project library.

        If the project is currently active, clear the active-project marker
        before removing its directory.
        """
        project = self.get_project(project_id)

        if project is None:
            raise FileNotFoundError(
                "项目不存在或已经被删除。"
            )

        if (
            self.current_project_id()
            == project_id
        ):
            self.set_current(None)

        try:
            shutil.rmtree(
                project.path
            )
        except OSError as exc:
            raise RuntimeError(
                f"无法删除项目：{exc}"
            ) from exc

    def export_project(
        self,
        destination: Path,
        project_id: str | None = None,
    ) -> Path:
        project_id = (
            project_id
            or self.current_project_id()
        )

        if not project_id:
            raise RuntimeError("当前没有打开项目。")

        project = self.get_project(project_id)

        if project is None:
            raise FileNotFoundError("项目不存在。")

        destination = Path(destination)

        if destination.suffix.lower() != PROJECT_EXTENSION:
            destination = destination.with_suffix(
                PROJECT_EXTENSION
            )

        destination.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with zipfile.ZipFile(
            destination,
            "w",
            compression=zipfile.ZIP_DEFLATED,
        ) as archive:
            destination_resolved = destination.resolve()

            for file in project.path.rglob("*"):
                if not file.is_file():
                    continue

                # The default export path may be inside the project folder.
                # Never include the archive currently being created in itself.
                try:
                    if file.resolve() == destination_resolved:
                        continue
                except OSError:
                    pass

                archive.write(
                    file,
                    file.relative_to(
                        project.path
                    ),
                )

        return destination

    def import_project(
        self,
        archive_path: Path,
    ) -> ProjectInfo:
        archive_path = Path(archive_path)

        if (
            archive_path.suffix.lower()
            != PROJECT_EXTENSION
        ):
            raise ValueError(
                f"只支持 {PROJECT_EXTENSION} 项目文件。"
            )

        with zipfile.ZipFile(
            archive_path,
            "r",
        ) as archive:
            names = archive.namelist()

            if "project.json" not in names:
                raise ValueError(
                    "项目包缺少 project.json。"
                )

            manifest = json.loads(
                archive.read(
                    "project.json"
                ).decode("utf-8")
            )

            name = str(
                manifest.get(
                    "name",
                    archive_path.stem,
                )
            )

            new_id = uuid.uuid4().hex[:12]
            destination = (
                projects_dir()
                / new_id
            )
            destination.mkdir(
                parents=True,
                exist_ok=False,
            )

            for member in archive.infolist():
                member_path = Path(
                    member.filename
                )

                if (
                    member_path.is_absolute()
                    or ".." in member_path.parts
                ):
                    shutil.rmtree(
                        destination,
                        ignore_errors=True,
                    )
                    raise ValueError(
                        "项目包包含非法路径。"
                    )

                archive.extract(
                    member,
                    destination,
                )

        manifest_path = (
            destination
            / "project.json"
        )
        manifest["project_id"] = new_id
        manifest["name"] = name
        manifest["updated_at"] = (
            datetime.now().isoformat(
                timespec="seconds"
            )
        )

        manifest_path.write_text(
            json.dumps(
                manifest,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        (destination / "templates").mkdir(
            exist_ok=True
        )
        (destination / "assets").mkdir(
            exist_ok=True
        )

        self.set_current(new_id)

        project = self.get_project(new_id)

        if project is None:
            raise RuntimeError("项目导入失败。")

        return project
