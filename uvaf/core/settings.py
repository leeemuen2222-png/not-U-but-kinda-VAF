from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from .app_paths import ensure_runtime_dirs, preferences_file, settings_file


DEFAULT_SETTINGS: dict[str, Any] = {
    "ui": {
        "start_page": "home",
        "theme": "dark",
        "language": "zh_CN",
    },
    "console": {
        "timestamps": True,
        "shell_enabled": True,
        "max_blocks": 3000,
    },
    "workspace": {
        "quick_toolbar": False,
        "quick_template_capture": False,
        "mode": "simple",
    },
    "recognition": {
        "backend": "native",
        "max_fps": 60,
        "exclude_viewport_from_capture": False,
    },
    "hotkeys": {
        "quick_template": "CTRL+S",
        "recognition_viewport": "CTRL+L",
    },
    "runtime": {
        "debug_logging": False,
    },
}


class SettingsStore:
    """
    Persistent UVAF user-preference store.

    The public class name is intentionally kept as SettingsStore so existing
    pages do not need a large migration. New data is stored in
    preferences.json. An existing legacy settings.json is imported once when
    preferences.json does not yet exist.
    """

    def __init__(self, path: Path | None = None) -> None:
        ensure_runtime_dirs()

        self.path = path or preferences_file()
        self.legacy_path = settings_file()

        self.data: dict[str, Any] = deepcopy(DEFAULT_SETTINGS)

        self._migrate_legacy_preferences()
        self.load()

    def _migrate_legacy_preferences(self) -> None:
        """
        Import old settings.json once.

        The legacy file is deliberately left untouched so upgrading UVAF can
        never destroy a user's previous configuration.
        """
        if (
            self.path.exists()
            or not self.legacy_path.exists()
        ):
            return

        try:
            legacy_data = json.loads(
                self.legacy_path.read_text(
                    encoding="utf-8"
                )
            )
        except (
            OSError,
            json.JSONDecodeError,
        ):
            return

        if not isinstance(
            legacy_data,
            dict,
        ):
            return

        migrated = deepcopy(
            DEFAULT_SETTINGS
        )
        self._deep_merge(
            migrated,
            legacy_data,
        )

        self.path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        temp_path = self.path.with_suffix(
            ".tmp"
        )
        temp_path.write_text(
            json.dumps(
                migrated,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        temp_path.replace(
            self.path
        )

    def as_dict(self) -> dict[str, Any]:
        """Return a detached snapshot useful for diagnostics/export."""
        return deepcopy(
            self.data
        )

    def load(self) -> None:
        loaded: dict[str, Any] = {}

        try:
            loaded = json.loads(
                self.path.read_text(encoding="utf-8")
            )
            if not isinstance(loaded, dict):
                loaded = {}
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            loaded = {}

        self.data = deepcopy(DEFAULT_SETTINGS)
        self._deep_merge(self.data, loaded)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(".tmp")
        temp_path.write_text(
            json.dumps(
                self.data,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        temp_path.replace(self.path)

    def get(self, dotted_key: str, default: Any = None) -> Any:
        node: Any = self.data

        for part in dotted_key.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]

        return node

    def set(self, dotted_key: str, value: Any) -> None:
        parts = dotted_key.split(".")
        node = self.data

        for part in parts[:-1]:
            child = node.get(part)

            if not isinstance(child, dict):
                child = {}
                node[part] = child

            node = child

        node[parts[-1]] = value
        self.save()

    def reset(self) -> None:
        self.data = deepcopy(DEFAULT_SETTINGS)
        self.save()

    @staticmethod
    def _deep_merge(
        target: dict[str, Any],
        source: dict[str, Any],
    ) -> None:
        for key, value in source.items():
            if (
                key in target
                and isinstance(target[key], dict)
                and isinstance(value, dict)
            ):
                SettingsStore._deep_merge(
                    target[key],
                    value,
                )
            else:
                target[key] = value



# Preferred name for new code. Existing imports of SettingsStore continue to
# work without modification.
PreferencesStore = SettingsStore
