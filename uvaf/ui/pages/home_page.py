from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...core.app_paths import app_data_dir
from ...version import __version__


class HomePage(QWidget):
    def __init__(self) -> None:
        super().__init__(objectName="page")
        self._build_ui()

    def _build_ui(self) -> None:
        main = QVBoxLayout(self)
        main.setContentsMargins(28, 24, 28, 26)
        main.setSpacing(14)

        main.addWidget(QLabel("主页", objectName="pageTitle"))
        main.addWidget(
            QLabel(
                "UVAF 的运行状态和常用入口会显示在这里。",
                objectName="pageSubtitle",
            )
        )

        status_card = QFrame(objectName="card")
        status_layout = QVBoxLayout(status_card)
        status_layout.setContentsMargins(18, 16, 18, 16)
        status_layout.setSpacing(12)

        status_layout.addWidget(QLabel("当前状态", objectName="sectionTitle"))

        version_row = QHBoxLayout()
        version_row.addWidget(QLabel("版本"))
        version_row.addStretch()
        version_row.addWidget(QLabel(f"v{__version__}", objectName="statusValue"))
        status_layout.addLayout(version_row)

        engine_row = QHBoxLayout()
        engine_row.addWidget(QLabel("自动化引擎"))
        engine_row.addStretch()
        engine_row.addWidget(QLabel("未运行", objectName="statusValue"))
        status_layout.addLayout(engine_row)

        workflow_row = QHBoxLayout()
        workflow_row.addWidget(QLabel("当前流程"))
        workflow_row.addStretch()
        workflow_row.addWidget(QLabel("无", objectName="statusValue"))
        status_layout.addLayout(workflow_row)

        main.addWidget(status_card)

        info_card = QFrame(objectName="card")
        info_layout = QVBoxLayout(info_card)
        info_layout.setContentsMargins(18, 16, 18, 16)
        info_layout.setSpacing(10)

        info_layout.addWidget(QLabel("项目数据", objectName="sectionTitle"))
        path_label = QLabel(str(app_data_dir()), objectName="statusHint")
        path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        path_label.setWordWrap(True)
        info_layout.addWidget(path_label)

        main.addWidget(info_card)
        main.addStretch()
