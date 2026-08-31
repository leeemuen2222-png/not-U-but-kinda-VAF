from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..core.logging_service import LoggingService
from ..core.settings import SettingsStore
from ..version import __version__
from .pages.home_page import HomePage
from .pages.workspace_page import WorkspacePage
from .pages.tools_page import ToolsPage
from .pages.console_page import ConsolePage
from .pages.settings_page import SettingsPage
from .theme import build_stylesheet
from ..core.i18n import (
    install_i18n,
    set_language,
    tr_text,
    translate_widget_tree,
)
from ..resources.tutorial.controller import TutorialController


class MainWindow(QMainWindow):
    def __init__(self, settings: SettingsStore, logger: LoggingService) -> None:
        super().__init__()

        self.settings = settings
        self.logger = logger

        # Apply language before child pages are constructed.  ConsolePage
        # writes its first rich-text log line during construction; setting the
        # language here prevents that initial line from being permanently
        # stored in Chinese when the user's preference is another language.
        app = QApplication.instance()
        initial_language = str(
            self.settings.get(
                "ui.language",
                "zh_CN",
            )
        )

        if app is not None:
            install_i18n(
                app,
                initial_language,
            )
            app.setProperty(
                "uvaf_language",
                initial_language,
            )

        self.setWindowTitle(f"UVAF v{__version__}")
        self.setMinimumSize(960, 620)
        self.resize(1180, 760)

        self._build_ui()
        self._connect_signals()
        self.apply_preferences()

        self.tutorial_controller = TutorialController(self)

        self.switch_page("home")
        QTimer.singleShot(
            650,
            self.tutorial_controller.maybe_start,
        )
        self.logger.info(
            f"{tr_text('UVAF started')} v{__version__}.",
            source="app",
        )

    def _build_ui(self) -> None:
        root = QWidget(objectName="appRoot")
        self.setCentralWidget(root)

        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self._build_sidebar())

        self.pages = QStackedWidget()

        self.home_page = HomePage()
        self.workspace_page = WorkspacePage(self.settings, self.logger)
        self.tools_page = ToolsPage(self.workspace_page)
        self.console_page = ConsolePage(self.settings, self.logger)
        self.settings_page = SettingsPage(self.settings, self.logger)

        self.page_map = {
            "home": self.home_page,
            "workspace": self.workspace_page,
            "tools": self.tools_page,
            "console": self.console_page,
            "settings": self.settings_page,
        }

        self.pages.addWidget(self.home_page)
        self.pages.addWidget(self.workspace_page)
        self.pages.addWidget(self.tools_page)
        self.pages.addWidget(self.console_page)
        self.pages.addWidget(self.settings_page)

        layout.addWidget(self.pages, 1)

    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame(objectName="sidebar")
        sidebar.setFixedWidth(208)

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(14, 18, 14, 16)
        layout.setSpacing(8)

        brand_row = QHBoxLayout()
        brand_row.setSpacing(10)

        mark = QLabel(objectName="brandMark")
        mark.setAlignment(Qt.AlignCenter)
        mark.setText("")
        icon_path = (
            Path(__file__).resolve().parents[1]
            / "resources"
            / "icons"
            / "uvaf.png"
        )
        if icon_path.exists():
            pixmap = QPixmap(str(icon_path))
            if not pixmap.isNull():
                mark.setPixmap(
                    pixmap.scaled(
                        28,
                        28,
                        Qt.KeepAspectRatio,
                        Qt.SmoothTransformation,
                    )
                )
            else:
                mark.setText("UV")
        else:
            mark.setText("UV")

        brand_text = QVBoxLayout()
        brand_text.setSpacing(0)
        brand_text.addWidget(QLabel("UVAF", objectName="brandTitle"))
        brand_text.addWidget(
            QLabel(
                f"v{__version__}",
                objectName="brandVersion",
            )
        )

        brand_row.addWidget(mark)
        brand_row.addLayout(brand_text)
        brand_row.addStretch()

        layout.addLayout(brand_row)
        layout.addSpacing(20)

        self.nav_buttons: dict[str, QPushButton] = {}

        for page_id, text in (
            ("home", "主页"),
            ("workspace", "工作台"),
            ("tools", "小工具"),
            ("console", "控制台"),
            ("settings", "设置"),
        ):
            button = QPushButton(text, objectName="navButton")
            button.setCheckable(True)
            button.clicked.connect(
                lambda _checked=False, pid=page_id: self.switch_page(pid)
            )

            self.nav_buttons[page_id] = button
            layout.addWidget(button)

        layout.addStretch()

        footer = QLabel(
            "Universal Visual Automation Framework",
            objectName="brandVersion",
        )
        footer.setWordWrap(True)
        layout.addWidget(footer)

        return sidebar

    def _connect_signals(self) -> None:
        self.console_page.request_settings.connect(
            lambda: self.switch_page("settings")
        )

        self.console_page.settings_changed.connect(
            self.settings_page.load_from_store
        )

        self.settings_page.settings_changed.connect(
            self.console_page.reload_settings
        )
        self.settings_page.settings_changed.connect(
            self.workspace_page.reload_settings
        )
        self.settings_page.settings_changed.connect(
            self.apply_preferences
        )
        self.settings_page.tutorial_requested.connect(
            self.start_tutorial
        )
        self.settings_page.tutorial_reference_requested.connect(
            self.open_tutorial_reference
        )

    def start_tutorial(self) -> None:
        if not hasattr(self, "tutorial_controller"):
            self.tutorial_controller = TutorialController(self)
        self.tutorial_controller.start(force=True)

    def open_tutorial_reference(self) -> None:
        if not hasattr(self, "tutorial_controller"):
            self.tutorial_controller = TutorialController(self)
        self.tutorial_controller.open_reference()

    def apply_preferences(self) -> None:
        app = QApplication.instance()

        language = str(
            self.settings.get(
                "ui.language",
                "zh_CN",
            )
        )
        theme = str(
            self.settings.get(
                "ui.theme",
                "dark",
            )
        )

        if app is not None:
            app.setProperty(
                "uvaf_theme",
                theme,
            )
            app.setProperty(
                "uvaf_language",
                language,
            )
            app.setStyleSheet(
                build_stylesheet(theme)
            )
            install_i18n(
                app,
                language,
            )

        set_language(
            language,
            self,
        )
        translate_widget_tree(
            self
        )

        # QGraphics-based workbench surfaces are not ordinary widgets, so the
        # workbench refreshes their painted labels/backgrounds from settings.
        if hasattr(
            self,
            "workspace_page",
        ):
            self.workspace_page.reload_settings()

    def switch_page(self, page_id: str) -> None:
        page = self.page_map.get(page_id)
        if page is None:
            return

        self.pages.setCurrentWidget(page)

        for key, button in self.nav_buttons.items():
            button.setChecked(key == page_id)

        if page_id == "settings":
            self.settings_page.load_from_store()
