from __future__ import annotations

import json
import os
import shlex
from dataclasses import dataclass
from typing import Callable

from .app_paths import app_data_dir
from .settings import SettingsStore
from ..version import __version__


@dataclass(slots=True)
class CommandResult:
    text: str = ""
    level: str = "INFO"
    action: str | None = None


class CommandDispatcher:
    """
    Handles UVAF's own console commands.

    Unknown commands are not silently passed to the OS shell.
    Shell commands must be explicit: !dir, !ping 127.0.0.1, ...
    """

    def __init__(self, settings: SettingsStore) -> None:
        self.settings = settings

    def execute(self, raw: str) -> CommandResult:
        raw = raw.strip()
        if not raw:
            return CommandResult()

        if raw.startswith("!"):
            if not self.settings.get("console.shell_enabled", True):
                return CommandResult(
                    "Shell commands are disabled in Settings.",
                    level="WARN",
                )
            command = raw[1:].strip()
            if not command:
                return CommandResult("Usage: !<shell command>", level="WARN")
            return CommandResult(command, action="shell")

        try:
            parts = shlex.split(raw, posix=False)
        except ValueError as exc:
            return CommandResult(f"Command parse error: {exc}", level="ERROR")

        command = parts[0].lower()
        args = parts[1:]

        handlers: dict[str, Callable[[list[str]], CommandResult]] = {
            "help": self._help,
            "?": self._help,
            "clear": lambda _: CommandResult(action="clear"),
            "cls": lambda _: CommandResult(action="clear"),
            "echo": self._echo,
            "version": self._version,
            "status": self._status,
            "settings": self._settings,
            "get": self._get,
            "set": self._set,
            "reset-settings": self._reset_settings,
        }

        handler = handlers.get(command)
        if handler is None:
            return CommandResult(
                f"Unknown UVAF command: {command}\n"
                f"Use 'help' for internal commands, or prefix an OS command with '!'.",
                level="WARN",
            )
        return handler(args)

    def _help(self, _: list[str]) -> CommandResult:
        return CommandResult(
            "\n".join(
                [
                    "UVAF Console commands",
                    "",
                    "  help / ?                 Show this help",
                    "  clear / cls              Clear console output",
                    "  version                  Show UVAF version",
                    "  status                   Show current runtime status",
                    "  echo <text>              Print text",
                    "  settings                 Open the Settings page",
                    "  get <key>                Read a setting",
                    "  set <key> <value>        Change a setting",
                    "  reset-settings           Restore default settings",
                    "  !<command>               Execute an OS shell command",
                    "",
                    "Examples:",
                    "  get console.timestamps",
                    "  set console.timestamps false",
                    "  !dir",
                ]
            )
        )

    def _echo(self, args: list[str]) -> CommandResult:
        return CommandResult(" ".join(args))

    def _version(self, _: list[str]) -> CommandResult:
        return CommandResult(f"UVAF v{__version__}")

    def _status(self, _: list[str]) -> CommandResult:
        return CommandResult(
            "\n".join(
                [
                    f"UVAF v{__version__}",
                    "Engine: idle",
                    "Workflow: none",
                    f"Data: {app_data_dir()}",
                    f"Shell: {'enabled' if self.settings.get('console.shell_enabled', True) else 'disabled'}",
                ]
            )
        )

    def _settings(self, _: list[str]) -> CommandResult:
        return CommandResult(action="settings")

    def _get(self, args: list[str]) -> CommandResult:
        if len(args) != 1:
            return CommandResult("Usage: get <setting.key>", level="WARN")

        key = args[0]
        value = self.settings.get(key, None)
        if value is None:
            return CommandResult(f"Setting not found: {key}", level="WARN")
        return CommandResult(f"{key} = {json.dumps(value, ensure_ascii=False)}")

    def _set(self, args: list[str]) -> CommandResult:
        if len(args) < 2:
            return CommandResult("Usage: set <setting.key> <value>", level="WARN")

        key = args[0]
        raw_value = " ".join(args[1:])
        value = self._parse_value(raw_value)
        self.settings.set(key, value)
        return CommandResult(
            f"{key} = {json.dumps(value, ensure_ascii=False)}",
            action="settings_changed",
        )

    def _reset_settings(self, _: list[str]) -> CommandResult:
        self.settings.reset()
        return CommandResult("Settings restored to defaults.", action="settings_changed")

    @staticmethod
    def _parse_value(raw: str):
        lowered = raw.lower()
        if lowered == "true":
            return True
        if lowered == "false":
            return False
        if lowered == "null":
            return None

        try:
            if "." in raw:
                return float(raw)
            return int(raw)
        except ValueError:
            return raw.strip('"')
