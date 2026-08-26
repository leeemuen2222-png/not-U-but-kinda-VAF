from __future__ import annotations

from datetime import datetime
from pathlib import Path
from threading import Lock

from PySide6.QtCore import QObject, Signal

from .app_paths import ensure_runtime_dirs, logs_dir


class LoggingService(QObject):
    """
    Single logging bridge shared by UI and future automation engines.

    Later, capture / recognition / action / workflow modules should log
    through this service instead of writing directly into UI widgets.
    """

    message_emitted = Signal(str, str, str)

    def __init__(self) -> None:
        super().__init__()
        ensure_runtime_dirs()
        self._lock = Lock()
        self._log_file = self._create_log_file()

    @property
    def log_file(self) -> Path:
        return self._log_file

    def log(self, message: str, level: str = "INFO", source: str = "core") -> None:
        level = level.upper()
        timestamp = datetime.now().strftime("%H:%M:%S")
        line = f"[{timestamp}] [{level}] [{source}] {message}"

        with self._lock:
            try:
                with self._log_file.open("a", encoding="utf-8") as handle:
                    handle.write(line + "\n")
            except OSError:
                pass

        self.message_emitted.emit(level, source, message)

    def info(self, message: str, source: str = "core") -> None:
        self.log(message, "INFO", source)

    def warning(self, message: str, source: str = "core") -> None:
        self.log(message, "WARN", source)

    def error(self, message: str, source: str = "core") -> None:
        self.log(message, "ERROR", source)

    @staticmethod
    def _create_log_file() -> Path:
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        return logs_dir() / f"uvaf_{stamp}.log"
