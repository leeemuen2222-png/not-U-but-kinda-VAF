from __future__ import annotations

from datetime import datetime
from html import escape
import sys

from PySide6.QtCore import QProcess, Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ...core.commands import CommandDispatcher, CommandResult
from ...core.logging_service import LoggingService
from ...core.settings import SettingsStore
from ...core.i18n import tr_text


class HistoryLineEdit(QLineEdit):
    history_up = Signal()
    history_down = Signal()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key_Up:
            self.history_up.emit()
            return
        if event.key() == Qt.Key_Down:
            self.history_down.emit()
            return
        super().keyPressEvent(event)


class ConsolePage(QWidget):
    request_settings = Signal()
    settings_changed = Signal()

    def __init__(
        self,
        settings: SettingsStore,
        logger: LoggingService,
    ) -> None:
        super().__init__(objectName="page")

        self.settings = settings
        self.logger = logger
        self.dispatcher = CommandDispatcher(settings)

        self.history: list[str] = []
        self.history_index = 0
        self.process: QProcess | None = None

        self._build_ui()
        self._connect_signals()
        self.reload_settings()

        self.append_system(
            "控制台 ready. Type 'help' for commands.",
            level="INFO",
        )

    def _build_ui(self) -> None:
        main = QVBoxLayout(self)
        main.setContentsMargins(28, 24, 28, 26)
        main.setSpacing(14)

        main.addWidget(QLabel("控制台", objectName="pageTitle"))
        main.addWidget(
            QLabel(
                "运行日志和命令输出会显示在这里。",
                objectName="pageSubtitle",
            )
        )

        card = QFrame(objectName="card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 14, 16, 14)
        card_layout.setSpacing(10)

        header = QHBoxLayout()
        header.addWidget(QLabel("控制台", objectName="sectionTitle"))
        header.addStretch()

        clear_button = QPushButton("清空", objectName="secondaryButton")
        clear_button.clicked.connect(self.clear_console)
        header.addWidget(clear_button)

        card_layout.addLayout(header)

        self.output = QTextEdit(objectName="consoleOutput")
        self.output.setReadOnly(True)
        self.output.document().setMaximumBlockCount(3000)
        card_layout.addWidget(self.output, 1)

        command_row = QHBoxLayout()
        command_row.setSpacing(8)

        command_row.addWidget(QLabel(">", objectName="prompt"))

        self.input = HistoryLineEdit(objectName="consoleInput")
        self.input.setPlaceholderText("输入 UVAF 指令；使用 !command 执行系统命令")
        self.input.returnPressed.connect(self.submit_command)
        self.input.history_up.connect(self.history_previous)
        self.input.history_down.connect(self.history_next)
        command_row.addWidget(self.input, 1)

        run_button = QPushButton("执行", objectName="primaryButton")
        run_button.clicked.connect(self.submit_command)
        command_row.addWidget(run_button)

        card_layout.addLayout(command_row)
        main.addWidget(card, 1)

    def _connect_signals(self) -> None:
        self.logger.message_emitted.connect(self.on_log_message)

    def reload_settings(self) -> None:
        max_blocks = int(self.settings.get("console.max_blocks", 3000))
        self.output.document().setMaximumBlockCount(max(100, max_blocks))

    def submit_command(self) -> None:
        raw = self.input.text().strip()
        if not raw:
            return

        self.append_command(raw)
        self._push_history(raw)
        self.input.clear()

        result = self.dispatcher.execute(raw)
        self._handle_result(result)

    def _handle_result(self, result: CommandResult) -> None:
        if result.action == "clear":
            self.clear_console()
            return

        if result.action == "settings":
            self.request_settings.emit()
            return

        if result.action == "settings_changed":
            self.settings_changed.emit()
            self.reload_settings()

        if result.action == "shell":
            self.start_shell_process(result.text)
            return

        if result.text:
            self.append_system(result.text, result.level)

    def start_shell_process(self, command: str) -> None:
        if self.process is not None and self.process.state() != QProcess.NotRunning:
            self.append_system(
                tr_text(
                    "A shell command is already running."
                ),
                level="WARN",
            )
            return

        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.MergedChannels)

        self.process.readyReadStandardOutput.connect(self._read_process_output)
        self.process.finished.connect(self._process_finished)
        self.process.errorOccurred.connect(self._process_error)

        self.append_system(f"shell> {command}", level="INFO")

        if sys.platform == "win32":
            self.process.start("cmd.exe", ["/d", "/s", "/c", command])
        else:
            self.process.start("/bin/sh", ["-lc", command])

    def _read_process_output(self) -> None:
        if self.process is None:
            return

        data = bytes(self.process.readAllStandardOutput())

        text = ""
        for encoding in ("utf-8", "gbk", "cp1252"):
            try:
                text = data.decode(encoding)
                break
            except UnicodeDecodeError:
                continue

        if not text:
            text = data.decode("utf-8", errors="replace")

        text = text.rstrip()
        if text:
            self.append_plain(text, css_class="shell")

    def _process_finished(self, exit_code: int, _exit_status) -> None:
        level = "INFO" if exit_code == 0 else "WARN"
        self.append_system(f"Process exited with code {exit_code}.", level=level)

    def _process_error(self, error) -> None:
        self.append_system(f"Shell process error: {error}", level="ERROR")

    def on_log_message(self, level: str, source: str, message: str) -> None:
        self.append_system(message, level=level, source=source)

    def append_command(self, command: str) -> None:
        stamp = self._timestamp_prefix()
        safe = escape(command)
        self.output.append(
            f'<span style="color:#747B88">{stamp}</span>'
            f'<span style="color:#7C87FF;font-weight:700">&gt;</span> '
            f'<span style="color:#F1F2F5">{safe}</span>'
        )
        self._scroll_to_bottom()

    def append_system(
        self,
        message: str,
        level: str = "INFO",
        source: str = "console",
    ) -> None:
        colors = {
            "INFO": "#B8BDC8",
            "WARN": "#E3B65B",
            "ERROR": "#F06C75",
            "DEBUG": "#8690A3",
        }
        level = level.upper()
        color = colors.get(level, colors["INFO"])
        stamp = self._timestamp_prefix()

        translated_message = tr_text(
            message
        )
        safe_message = escape(
            translated_message
        ).replace("\n", "<br>")
        safe_source = escape(source)

        self.output.append(
            f'<span style="color:#747B88">{stamp}</span>'
            f'<span style="color:{color}">[{escape(level)}]</span> '
            f'<span style="color:#737986">[{safe_source}]</span> '
            f'<span style="color:#D9DCE3">{safe_message}</span>'
        )
        self._scroll_to_bottom()

    def append_plain(self, text: str, css_class: str = "") -> None:
        stamp = self._timestamp_prefix()
        safe = escape(text).replace("\n", "<br>")
        self.output.append(
            f'<span style="color:#747B88">{stamp}</span>'
            f'<span style="color:#C9CDD6">{safe}</span>'
        )
        self._scroll_to_bottom()

    def clear_console(self) -> None:
        self.output.clear()

    def history_previous(self) -> None:
        if not self.history:
            return
        self.history_index = max(0, self.history_index - 1)
        self.input.setText(self.history[self.history_index])
        self.input.setCursorPosition(len(self.input.text()))

    def history_next(self) -> None:
        if not self.history:
            return
        self.history_index = min(len(self.history), self.history_index + 1)
        if self.history_index >= len(self.history):
            self.input.clear()
            return
        self.input.setText(self.history[self.history_index])
        self.input.setCursorPosition(len(self.input.text()))

    def _push_history(self, command: str) -> None:
        if not self.history or self.history[-1] != command:
            self.history.append(command)
        self.history = self.history[-100:]
        self.history_index = len(self.history)

    def _timestamp_prefix(self) -> str:
        if not self.settings.get("console.timestamps", True):
            return ""
        return f"[{datetime.now().strftime('%H:%M:%S')}] "

    def _scroll_to_bottom(self) -> None:
        bar = self.output.verticalScrollBar()
        bar.setValue(bar.maximum())
