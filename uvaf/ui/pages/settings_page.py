from __future__ import annotations

import os
import subprocess
import sys

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from ...core.app_paths import app_data_dir
from ...core.logging_service import LoggingService
from ...core.settings import SettingsStore
from ...core.i18n import LANGUAGES, translate_widget_tree



HOTKEY_MODIFIER_ORDER = (
    "CTRL",
    "ALT",
    "SHIFT",
    "META",
)


def hotkey_token_from_event(
    event,
) -> str:
    key = int(
        event.key()
    )

    special = {
        int(Qt.Key_Control): "CTRL",
        int(Qt.Key_Shift): "SHIFT",
        int(Qt.Key_Alt): "ALT",
        int(Qt.Key_Meta): "META",
        int(Qt.Key_Space): "SPACE",
        int(Qt.Key_Return): "ENTER",
        int(Qt.Key_Enter): "ENTER",
        int(Qt.Key_Escape): "ESC",
        int(Qt.Key_Tab): "TAB",
        int(Qt.Key_Backspace): "BACKSPACE",
        int(Qt.Key_Delete): "DELETE",
        int(Qt.Key_Insert): "INSERT",
        int(Qt.Key_Home): "HOME",
        int(Qt.Key_End): "END",
        int(Qt.Key_PageUp): "PAGEUP",
        int(Qt.Key_PageDown): "PAGEDOWN",
        int(Qt.Key_Left): "LEFT",
        int(Qt.Key_Right): "RIGHT",
        int(Qt.Key_Up): "UP",
        int(Qt.Key_Down): "DOWN",
        int(Qt.Key_CapsLock): "CAPSLOCK",
    }

    if key in special:
        return special[
            key
        ]

    if (
        int(Qt.Key_F1)
        <= key
        <= int(Qt.Key_F24)
    ):
        return (
            "F"
            + str(
                key
                - int(Qt.Key_F1)
                + 1
            )
        )

    if (
        int(Qt.Key_A)
        <= key
        <= int(Qt.Key_Z)
    ):
        return chr(
            ord("A")
            + key
            - int(Qt.Key_A)
        )

    if (
        int(Qt.Key_0)
        <= key
        <= int(Qt.Key_9)
    ):
        return chr(
            ord("0")
            + key
            - int(Qt.Key_0)
        )

    # PortableText gives stable names for punctuation and less-common keys.
    portable = (
        QKeySequence(
            key
        )
        .toString()
        .strip()
    )

    if portable:
        return portable.upper()

    value = (
        event.text()
        .strip()
    )

    return value.upper()


def normalize_hotkey_tokens(
    tokens,
) -> list[str]:
    seen = set()
    cleaned = []

    for token in tokens:
        token = str(
            token
        ).strip().upper()

        if (
            not token
            or token in seen
        ):
            continue

        seen.add(
            token
        )
        cleaned.append(
            token
        )

    result = [
        modifier
        for modifier in HOTKEY_MODIFIER_ORDER
        if modifier in seen
    ]

    result.extend(
        token
        for token in cleaned
        if token not in HOTKEY_MODIFIER_ORDER
    )

    return result


def normalize_hotkey_string(
    value: str,
) -> str:
    return "+".join(
        normalize_hotkey_tokens(
            str(value)
            .replace(
                " ",
                "",
            )
            .split("+")
        )
    )


def display_hotkey(
    value: str,
) -> str:
    normalized = (
        normalize_hotkey_string(
            value
        )
    )

    return (
        " + ".join(
            normalized.split("+")
        )
        if normalized
        else "未绑定"
    )


class HotkeyRecorderDialog(QDialog):
    """
    Record one simultaneous key chord.

    Recording starts on the first KeyPress. While ANY recorded key remains
    held, additional KeyPress events join the same chord. The chord is only
    committed after every key involved in that recording session has finally
    been released.

    Example:
        Ctrl down
        Shift down
        K down
        K up
        Shift up
        Ctrl up
        -> CTRL+SHIFT+K
    """

    def __init__(
        self,
        title: str,
        current: str,
        parent=None,
    ) -> None:
        super().__init__(
            parent
        )

        self.result_hotkey = ""
        self._pressed: set[
            str
        ] = set()
        self._recorded_order: list[
            str
        ] = []
        self._recording_started = False

        self.setWindowTitle(
            title
        )
        self.setModal(
            True
        )
        self.resize(
            440,
            220,
        )
        self.setFocusPolicy(
            Qt.StrongFocus
        )

        layout = QVBoxLayout(
            self
        )
        layout.setContentsMargins(
            20,
            20,
            20,
            20,
        )
        layout.setSpacing(
            14
        )

        heading = QLabel(
            "请按下要绑定的按键组合"
        )
        heading.setAlignment(
            Qt.AlignCenter
        )
        heading.setStyleSheet(
            "font-size:18px;"
            "font-weight:700;"
        )
        layout.addWidget(
            heading
        )

        self.preview = QLabel(
            display_hotkey(
                current
            )
        )
        self.preview.setAlignment(
            Qt.AlignCenter
        )
        self.preview.setStyleSheet(
            "font-size:22px;"
            "font-weight:700;"
            "padding:12px;"
        )
        layout.addWidget(
            self.preview
        )

        hint = QLabel(
            "从第一个键按下开始录制。只要其中还有按键没有松开，"
            "就会继续记录后续按下的键；当本次组合中的所有按键都松开后自动完成。",
            objectName="muted",
        )
        hint.setWordWrap(
            True
        )
        hint.setAlignment(
            Qt.AlignCenter
        )
        layout.addWidget(
            hint
        )

        layout.addStretch()

        cancel = QPushButton(
            "取消"
        )
        cancel.clicked.connect(
            self.reject
        )
        layout.addWidget(
            cancel,
            alignment=Qt.AlignRight,
        )

    def keyPressEvent(
        self,
        event,
    ) -> None:
        if event.isAutoRepeat():
            event.accept()
            return

        token = hotkey_token_from_event(
            event
        )

        if not token:
            event.accept()
            return

        self._recording_started = True
        self._pressed.add(
            token
        )

        if token not in self._recorded_order:
            self._recorded_order.append(
                token
            )

        tokens = normalize_hotkey_tokens(
            self._recorded_order
        )

        self.preview.setText(
            " + ".join(
                tokens
            )
        )

        event.accept()

    def keyReleaseEvent(
        self,
        event,
    ) -> None:
        if event.isAutoRepeat():
            event.accept()
            return

        token = hotkey_token_from_event(
            event
        )

        if token:
            self._pressed.discard(
                token
            )

        if (
            self._recording_started
            and not self._pressed
            and self._recorded_order
        ):
            self.result_hotkey = (
                "+".join(
                    normalize_hotkey_tokens(
                        self._recorded_order
                    )
                )
            )
            self.accept()

        event.accept()


class SettingsPage(QWidget):
    settings_changed = Signal()
    tutorial_requested = Signal()
    tutorial_reference_requested = Signal()

    def __init__(
        self,
        settings: SettingsStore,
        logger: LoggingService,
    ) -> None:
        super().__init__(objectName="page")

        self.settings = settings
        self.logger = logger

        self._build_ui()
        self.load_from_store()

    def _build_ui(self) -> None:
        # The settings page must never vertically compress cards just to fit
        # the current window. A dedicated scroll viewport keeps every section
        # at its natural readable height and exposes a vertical scrollbar when
        # the viewport is shorter than the complete settings document.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(
            0,
            0,
            0,
            0,
        )
        outer.setSpacing(0)

        self.settings_scroll = QScrollArea(
            self
        )
        self.settings_scroll.setWidgetResizable(
            True
        )
        self.settings_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarAlwaysOff
        )
        self.settings_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarAsNeeded
        )
        self.settings_scroll.setFrameShape(
            QFrame.NoFrame
        )
        self.settings_scroll.setObjectName(
            "settingsScroll"
        )

        # Makes mouse-wheel scrolling feel natural while still allowing
        # sliders/comboboxes inside the document to operate normally.
        self.settings_scroll.setFocusPolicy(
            Qt.NoFocus
        )

        self.settings_content = QWidget(
            objectName="settingsContent"
        )
        self.settings_content.setSizePolicy(
            QSizePolicy.Expanding,
            QSizePolicy.Minimum,
        )

        main = QVBoxLayout(
            self.settings_content
        )
        main.setContentsMargins(
            28,
            24,
            28,
            26,
        )
        main.setSpacing(
            18
        )
        main.setSizeConstraint(
            QVBoxLayout.SetMinimumSize
        )

        self.settings_scroll.setWidget(
            self.settings_content
        )
        outer.addWidget(
            self.settings_scroll
        )

        main.addWidget(
            QLabel(
                "设置",
                objectName="pageTitle",
            )
        )
        main.addWidget(
            QLabel(
                "",
                objectName="pageSubtitle",
            )
        )

        # --------------------------------------------------------------
        # Appearance & language
        # --------------------------------------------------------------
        appearance_card = QFrame(objectName="card")
        appearance_card.setSizePolicy(
            QSizePolicy.Expanding,
            QSizePolicy.Minimum,
        )
        appearance_layout = QVBoxLayout(appearance_card)
        appearance_layout.setContentsMargins(18, 16, 18, 16)
        appearance_layout.setSpacing(12)

        appearance_layout.addWidget(
            QLabel(
                "外观与语言",
                objectName="sectionTitle",
            )
        )

        theme_row = QHBoxLayout()
        theme_row.addWidget(QLabel("主题"))
        theme_row.addStretch()

        self.theme_combo = QComboBox()
        self.theme_combo.addItem("深色", "dark")
        self.theme_combo.addItem("浅色", "light")
        self.theme_combo.setMinimumWidth(220)
        self.theme_combo.currentIndexChanged.connect(
            self.save_settings
        )
        theme_row.addWidget(self.theme_combo)
        appearance_layout.addLayout(theme_row)

        language_row = QHBoxLayout()
        language_row.addWidget(QLabel("语言"))
        language_row.addStretch()

        self.language_combo = QComboBox()
        for language_code, language_name in LANGUAGES:
            self.language_combo.addItem(
                language_name,
                language_code,
            )
        self.language_combo.setMinimumWidth(220)
        self.language_combo.currentIndexChanged.connect(
            self.save_settings
        )
        language_row.addWidget(self.language_combo)
        appearance_layout.addLayout(language_row)

        main.addWidget(appearance_card)

        # --------------------------------------------------------------
        # Workspace
        # --------------------------------------------------------------
        workspace_card = QFrame(objectName="card")
        workspace_card.setSizePolicy(
            QSizePolicy.Expanding,
            QSizePolicy.Minimum,
        )
        workspace_layout = QVBoxLayout(workspace_card)
        workspace_layout.setContentsMargins(18, 16, 18, 16)
        workspace_layout.setSpacing(12)

        workspace_layout.addWidget(
            QLabel(
                "工作台",
                objectName="sectionTitle",
            )
        )

        self.quick_template_check = QCheckBox(
            "显示快捷工具栏"
        )
        self.quick_template_check.toggled.connect(
            self.save_settings
        )
        workspace_layout.addWidget(
            self.quick_template_check
        )

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("工作台模式"))
        mode_row.addStretch()

        self.workspace_mode_combo = QComboBox()
        self.workspace_mode_combo.addItem(
            "简单模式（拼图模式）",
            "simple",
        )
        self.workspace_mode_combo.addItem(
            "复杂模式（节点与连线）",
            "complex",
        )
        self.workspace_mode_combo.setMinimumWidth(220)
        self.workspace_mode_combo.currentIndexChanged.connect(
            self.save_settings
        )
        mode_row.addWidget(
            self.workspace_mode_combo
        )

        workspace_layout.addLayout(mode_row)

        mode_hint = QLabel(
            "简单模式使用拼图磁吸；复杂模式采用类似 World Machine 的节点、端口和连线。",
            objectName="muted",
        )
        mode_hint.setWordWrap(True)
        workspace_layout.addWidget(mode_hint)

        main.addWidget(workspace_card)

        # --------------------------------------------------------------
        # Hotkeys
        # --------------------------------------------------------------
        hotkey_card = QFrame(
            objectName="card"
        )
        hotkey_layout = QVBoxLayout(
            hotkey_card
        )
        hotkey_layout.setContentsMargins(
            18,
            16,
            18,
            16,
        )
        hotkey_layout.setSpacing(
            12
        )

        hotkey_layout.addWidget(
            QLabel(
                "热键",
                objectName="sectionTitle",
            )
        )

        template_hotkey_row = QHBoxLayout()
        template_hotkey_row.addWidget(
            QLabel(
                "快捷建立模板"
            )
        )
        template_hotkey_row.addStretch()

        self.quick_template_hotkey_edit = QLineEdit()
        self.quick_template_hotkey_edit.setReadOnly(
            True
        )
        self.quick_template_hotkey_edit.setMinimumWidth(
            190
        )
        self.quick_template_hotkey_edit.setAlignment(
            Qt.AlignCenter
        )
        template_hotkey_row.addWidget(
            self.quick_template_hotkey_edit
        )

        template_record_button = QPushButton(
            "录制"
        )
        template_record_button.clicked.connect(
            lambda:
            self._record_hotkey(
                "quick_template"
            )
        )
        template_hotkey_row.addWidget(
            template_record_button
        )

        hotkey_layout.addLayout(
            template_hotkey_row
        )

        recognition_hotkey_row = QHBoxLayout()
        recognition_hotkey_row.addWidget(
            QLabel(
                "视觉识别系统视角"
            )
        )
        recognition_hotkey_row.addStretch()

        self.recognition_hotkey_edit = QLineEdit()
        self.recognition_hotkey_edit.setReadOnly(
            True
        )
        self.recognition_hotkey_edit.setMinimumWidth(
            190
        )
        self.recognition_hotkey_edit.setAlignment(
            Qt.AlignCenter
        )
        recognition_hotkey_row.addWidget(
            self.recognition_hotkey_edit
        )

        recognition_record_button = QPushButton(
            "录制"
        )
        recognition_record_button.clicked.connect(
            lambda:
            self._record_hotkey(
                "recognition_viewport"
            )
        )
        recognition_hotkey_row.addWidget(
            recognition_record_button
        )

        hotkey_layout.addLayout(
            recognition_hotkey_row
        )

        hotkey_hint = QLabel(
            "默认：快捷建立模板 Ctrl+S；视觉识别系统视角 Ctrl+L。"
            "录制支持 Ctrl+Shift+K 等组合；第一个键按下后会持续记录，"
            "直到本次组合的所有按键最终全部松开。",
            objectName="muted",
        )
        hotkey_hint.setWordWrap(
            True
        )
        hotkey_layout.addWidget(
            hotkey_hint
        )

        main.addWidget(
            hotkey_card
        )

        # --------------------------------------------------------------
        # Recognition
        # --------------------------------------------------------------
        recognition_card = QFrame(objectName="card")
        recognition_card.setSizePolicy(
            QSizePolicy.Expanding,
            QSizePolicy.Minimum,
        )
        recognition_layout = QVBoxLayout(recognition_card)
        recognition_layout.setContentsMargins(18, 16, 18, 16)
        recognition_layout.setSpacing(12)

        recognition_layout.addWidget(
            QLabel(
                "识别引擎",
                objectName="sectionTitle",
            )
        )

        recognition_row = QHBoxLayout()
        recognition_row.addWidget(
            QLabel("识别后端")
        )
        recognition_row.addStretch()

        self.recognition_backend_combo = QComboBox()
        self.recognition_backend_combo.addItem(
            "UVAF Native（推荐：DXCam 优先，MSS 回退）",
            "native",
        )
        self.recognition_backend_combo.addItem(
            "MSS 兼容后端",
            "mss",
        )
        self.recognition_backend_combo.addItem(
            "PyAutoGUI 兼容后端",
            "pyautogui",
        )
        self.recognition_backend_combo.setMinimumWidth(310)
        self.recognition_backend_combo.currentIndexChanged.connect(
            self.save_settings
        )
        recognition_row.addWidget(
            self.recognition_backend_combo
        )

        recognition_layout.addLayout(
            recognition_row
        )

        fps_row = QHBoxLayout()
        fps_row.setSpacing(12)

        fps_label = QLabel(
            "最大识别帧率"
        )
        fps_label.setMinimumWidth(
            120
        )
        fps_row.addWidget(
            fps_label
        )

        self.recognition_fps_slider = QSlider(
            Qt.Horizontal
        )
        self.recognition_fps_slider.setRange(
            1,
            240,
        )
        self.recognition_fps_slider.setSingleStep(
            1
        )
        self.recognition_fps_slider.setPageStep(
            10
        )
        self.recognition_fps_slider.setMinimumWidth(
            260
        )
        self.recognition_fps_slider.valueChanged.connect(
            self._update_fps_label
        )
        self.recognition_fps_slider.valueChanged.connect(
            self.save_settings
        )
        self.recognition_fps_slider.sliderReleased.connect(
            self.save_settings
        )
        fps_row.addWidget(
            self.recognition_fps_slider,
            1,
        )

        self.recognition_fps_value = QLabel(
            "60 FPS"
        )
        self.recognition_fps_value.setMinimumWidth(
            72
        )
        self.recognition_fps_value.setAlignment(
            Qt.AlignRight
            | Qt.AlignVCenter
        )
        fps_row.addWidget(
            self.recognition_fps_value
        )

        recognition_layout.addLayout(
            fps_row
        )

        self.exclude_viewport_check = QCheckBox(
            "排除视觉识别视角窗口"
        )
        self.exclude_viewport_check.toggled.connect(
            self.save_settings
        )
        recognition_layout.addWidget(
            self.exclude_viewport_check
        )

        exclude_hint = QLabel(
            "开启后会尽量让 Windows 截图和 Recognition Engine 忽略视觉识别视角窗口，"
            "避免递归套娃；关闭时可正常截取该调试窗口。",
            objectName="muted",
        )
        exclude_hint.setWordWrap(True)
        recognition_layout.addWidget(
            exclude_hint
        )

        recognition_hint = QLabel(
            "这里选择的是截图/识别执行后端，而不是模板算法。扫描模板自己的"
            "彩色、灰度、RGB、HSV、边缘、FeatureMatch 等算法在模块设置中独立选择；"
            "默认全部启用。最大识别帧率是抓取新画面的上限，实际速度仍取决于识别耗时。",
            objectName="muted",
        )
        recognition_hint.setWordWrap(True)
        recognition_layout.addWidget(
            recognition_hint
        )

        main.addWidget(recognition_card)

        # Console
        # --------------------------------------------------------------
        console_card = QFrame(objectName="card")
        console_card.setSizePolicy(
            QSizePolicy.Expanding,
            QSizePolicy.Minimum,
        )
        console_layout = QVBoxLayout(console_card)
        console_layout.setContentsMargins(18, 16, 18, 16)
        console_layout.setSpacing(12)

        console_layout.addWidget(
            QLabel(
                "控制台",
                objectName="sectionTitle",
            )
        )

        self.timestamps_check = QCheckBox(
            "显示时间戳"
        )
        self.timestamps_check.toggled.connect(
            self.save_settings
        )
        console_layout.addWidget(
            self.timestamps_check
        )

        self.shell_check = QCheckBox(
            "允许使用 !command 执行系统命令"
        )
        self.shell_check.toggled.connect(
            self.save_settings
        )
        console_layout.addWidget(
            self.shell_check
        )

        block_row = QHBoxLayout()
        block_row.setSpacing(12)

        block_label = QLabel(
            "最大控制台行数"
        )
        block_label.setMinimumWidth(
            120
        )
        block_row.addWidget(
            block_label
        )

        self.max_blocks_slider = QSlider(
            Qt.Horizontal
        )
        self.max_blocks_slider.setRange(
            1,
            200,
        )
        self.max_blocks_slider.setSingleStep(
            1
        )
        self.max_blocks_slider.setPageStep(
            10
        )
        self.max_blocks_slider.setMinimumWidth(
            260
        )
        self.max_blocks_slider.valueChanged.connect(
            self._update_max_blocks_label
        )
        self.max_blocks_slider.valueChanged.connect(
            self.save_settings
        )
        self.max_blocks_slider.sliderReleased.connect(
            self.save_settings
        )
        block_row.addWidget(
            self.max_blocks_slider,
            1,
        )

        self.max_blocks_value = QLabel(
            "3000"
        )
        self.max_blocks_value.setMinimumWidth(
            72
        )
        self.max_blocks_value.setAlignment(
            Qt.AlignRight
            | Qt.AlignVCenter
        )
        block_row.addWidget(
            self.max_blocks_value
        )

        console_layout.addLayout(
            block_row
        )
        main.addWidget(
            console_card
        )

        # --------------------------------------------------------------
        # Data
        # --------------------------------------------------------------
        data_card = QFrame(objectName="card")
        data_card.setSizePolicy(
            QSizePolicy.Expanding,
            QSizePolicy.Minimum,
        )
        data_layout = QVBoxLayout(data_card)
        data_layout.setContentsMargins(18, 16, 18, 16)
        data_layout.setSpacing(10)

        data_layout.addWidget(
            QLabel(
                "数据与配置",
                objectName="sectionTitle",
            )
        )

        self.data_path_label = QLabel(
            str(app_data_dir()),
            objectName="muted",
        )
        self.data_path_label.setTextInteractionFlags(
            Qt.TextSelectableByMouse
        )
        data_layout.addWidget(
            self.data_path_label
        )

        button_row = QHBoxLayout()

        open_button = QPushButton(
            "打开数据文件夹",
            objectName="secondaryButton",
        )
        open_button.clicked.connect(
            self.open_data_folder
        )
        button_row.addWidget(
            open_button
        )

        reset_button = QPushButton(
            "恢复默认设置",
            objectName="secondaryButton",
        )
        reset_button.clicked.connect(
            self.reset_settings
        )
        button_row.addWidget(
            reset_button
        )

        button_row.addStretch()
        data_layout.addLayout(
            button_row
        )

        main.addWidget(data_card)

        # --------------------------------------------------------------
        # Tutorial
        # --------------------------------------------------------------
        tutorial_card = QFrame(objectName="card")
        tutorial_card.setSizePolicy(
            QSizePolicy.Expanding,
            QSizePolicy.Minimum,
        )
        tutorial_layout = QVBoxLayout(tutorial_card)
        tutorial_layout.setContentsMargins(18, 16, 18, 16)
        tutorial_layout.setSpacing(10)

        tutorial_layout.addWidget(
            QLabel(
                "教程",
                objectName="sectionTitle",
            )
        )

        tutorial_hint = QLabel(
            "重新启动首次使用教程。教程会带你体验欢迎项目、清空示例并亲手制作一个简单的鼠标点击流程，最后可以打开完整模块手册。",
            objectName="muted",
        )
        tutorial_hint.setWordWrap(True)
        tutorial_layout.addWidget(tutorial_hint)

        tutorial_buttons = QHBoxLayout()
        tutorial_buttons.setSpacing(10)

        self.restart_tutorial_button = QPushButton(
            "再次开始教程",
            objectName="secondaryButton",
        )
        self.restart_tutorial_button.clicked.connect(
            self.tutorial_requested.emit
        )
        tutorial_buttons.addWidget(self.restart_tutorial_button)

        self.open_tutorial_reference_button = QPushButton(
            "打开完整模块手册",
            objectName="secondaryButton",
        )
        self.open_tutorial_reference_button.clicked.connect(
            self.tutorial_reference_requested.emit
        )
        tutorial_buttons.addWidget(self.open_tutorial_reference_button)
        tutorial_buttons.addStretch()
        tutorial_layout.addLayout(tutorial_buttons)

        main.addWidget(tutorial_card)
        main.addStretch()

    def _update_fps_label(
        self,
        value: int,
    ) -> None:
        self.recognition_fps_value.setText(
            f"{int(value)} FPS"
        )

    def _update_max_blocks_label(
        self,
        slider_value: int,
    ) -> None:
        actual_value = int(
            slider_value
            * 100
        )
        self.max_blocks_value.setText(
            f"{actual_value:,}"
        )

    def load_from_store(self) -> None:
        widgets = (
            self.theme_combo,
            self.language_combo,
            self.quick_template_check,
            self.workspace_mode_combo,
            self.recognition_backend_combo,
            self.recognition_fps_slider,
            self.exclude_viewport_check,
            self.timestamps_check,
            self.shell_check,
            self.max_blocks_slider,
        )

        for widget in widgets:
            widget.blockSignals(True)

        theme_value = str(
            self.settings.get(
                "ui.theme",
                "dark",
            )
        )
        theme_index = self.theme_combo.findData(
            theme_value
        )
        self.theme_combo.setCurrentIndex(
            max(0, theme_index)
        )

        language_value = str(
            self.settings.get(
                "ui.language",
                "zh_CN",
            )
        )
        language_index = self.language_combo.findData(
            language_value
        )
        self.language_combo.setCurrentIndex(
            max(0, language_index)
        )

        self.quick_template_check.setChecked(
            bool(
                self.settings.get(
                    "workspace.quick_toolbar",
                    self.settings.get(
                        "workspace.quick_template_capture",
                        False,
                    ),
                )
            )
        )

        quick_template_hotkey = (
            normalize_hotkey_string(
                str(
                    self.settings.get(
                        "hotkeys.quick_template",
                        "CTRL+S",
                    )
                )
            )
            or "CTRL+S"
        )
        recognition_hotkey = (
            normalize_hotkey_string(
                str(
                    self.settings.get(
                        "hotkeys.recognition_viewport",
                        "CTRL+L",
                    )
                )
            )
            or "CTRL+L"
        )

        self.quick_template_hotkey_edit.setProperty(
            "hotkey_value",
            quick_template_hotkey,
        )
        self.quick_template_hotkey_edit.setText(
            display_hotkey(
                quick_template_hotkey
            )
        )

        self.recognition_hotkey_edit.setProperty(
            "hotkey_value",
            recognition_hotkey,
        )
        self.recognition_hotkey_edit.setText(
            display_hotkey(
                recognition_hotkey
            )
        )

        workspace_mode = str(
            self.settings.get(
                "workspace.mode",
                "simple",
            )
        )
        workspace_index = self.workspace_mode_combo.findData(
            workspace_mode
        )
        self.workspace_mode_combo.setCurrentIndex(
            max(0, workspace_index)
        )

        recognition_backend = str(
            self.settings.get(
                "recognition.backend",
                "native",
            )
        )
        recognition_index = self.recognition_backend_combo.findData(
            recognition_backend
        )
        self.recognition_backend_combo.setCurrentIndex(
            max(0, recognition_index)
        )

        fps_value = int(
            self.settings.get(
                "recognition.max_fps",
                60,
            )
        )
        self.recognition_fps_slider.setValue(
            max(
                1,
                min(
                    240,
                    fps_value,
                ),
            )
        )
        self._update_fps_label(
            self.recognition_fps_slider.value()
        )

        self.exclude_viewport_check.setChecked(
            bool(
                self.settings.get(
                    "recognition.exclude_viewport_from_capture",
                    False,
                )
            )
        )

        self.timestamps_check.setChecked(
            bool(
                self.settings.get(
                    "console.timestamps",
                    True,
                )
            )
        )
        self.shell_check.setChecked(
            bool(
                self.settings.get(
                    "console.shell_enabled",
                    True,
                )
            )
        )
        max_blocks_value = int(
            self.settings.get(
                "console.max_blocks",
                3000,
            )
        )
        self.max_blocks_slider.setValue(
            max(
                1,
                min(
                    200,
                    int(
                        round(
                            max_blocks_value
                            / 100
                        )
                    ),
                ),
            )
        )
        self._update_max_blocks_label(
            self.max_blocks_slider.value()
        )

        for widget in widgets:
            widget.blockSignals(False)

    def _record_hotkey(
        self,
        action: str,
    ) -> None:
        if action == "quick_template":
            edit = (
                self.quick_template_hotkey_edit
            )
            other_edit = (
                self.recognition_hotkey_edit
            )
            title = (
                "录制：快捷建立模板"
            )
        else:
            edit = (
                self.recognition_hotkey_edit
            )
            other_edit = (
                self.quick_template_hotkey_edit
            )
            title = (
                "录制：视觉识别系统视角"
            )

        current = normalize_hotkey_string(
            edit.property(
                "hotkey_value"
            )
            or ""
        )

        dialog = HotkeyRecorderDialog(
            title,
            current,
            self,
        )

        if (
            dialog.exec()
            != QDialog.Accepted
        ):
            return

        value = normalize_hotkey_string(
            dialog.result_hotkey
        )

        if not value:
            return

        other = normalize_hotkey_string(
            other_edit.property(
                "hotkey_value"
            )
            or ""
        )

        if (
            other
            and value == other
        ):
            QMessageBox.warning(
                self,
                "热键冲突",
                (
                    f"{display_hotkey(value)} "
                    "已经绑定给另一个功能，请录制不同的组合。"
                ),
            )
            return

        edit.setProperty(
            "hotkey_value",
            value,
        )
        edit.setText(
            display_hotkey(
                value
            )
        )

        self.save_settings()

    def save_settings(self) -> None:
        self.settings.set(
            "ui.theme",
            self.theme_combo.currentData() or "dark",
        )
        self.settings.set(
            "ui.language",
            self.language_combo.currentData() or "zh_CN",
        )
        self.settings.set(
            "workspace.quick_toolbar",
            self.quick_template_check.isChecked(),
        )
        self.settings.set(
            "workspace.mode",
            self.workspace_mode_combo.currentData(),
        )
        self.settings.set(
            "hotkeys.quick_template",
            normalize_hotkey_string(
                self.quick_template_hotkey_edit.property(
                    "hotkey_value"
                )
                or "CTRL+S"
            ),
        )
        self.settings.set(
            "hotkeys.recognition_viewport",
            normalize_hotkey_string(
                self.recognition_hotkey_edit.property(
                    "hotkey_value"
                )
                or "CTRL+L"
            ),
        )
        self.settings.set(
            "recognition.backend",
            self.recognition_backend_combo.currentData(),
        )
        self.settings.set(
            "recognition.max_fps",
            self.recognition_fps_slider.value(),
        )
        self.settings.set(
            "recognition.exclude_viewport_from_capture",
            self.exclude_viewport_check.isChecked(),
        )
        self.settings.set(
            "console.timestamps",
            self.timestamps_check.isChecked(),
        )
        self.settings.set(
            "console.shell_enabled",
            self.shell_check.isChecked(),
        )
        self.settings.set(
            "console.max_blocks",
            self.max_blocks_slider.value() * 100,
        )

        self.settings_changed.emit()

    def reset_settings(self) -> None:
        result = QMessageBox.question(
            self,
            "恢复默认设置",
            "确定恢复 UVAF 的默认设置吗？",
        )

        if result != QMessageBox.Yes:
            return

        self.settings.reset()
        self.load_from_store()
        self.settings_changed.emit()

        self.logger.info(
            "Settings restored to defaults.",
            source="settings",
        )

    def open_data_folder(self) -> None:
        path = app_data_dir()
        path.mkdir(
            parents=True,
            exist_ok=True,
        )

        try:
            if os.name == "nt":
                os.startfile(path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(
                    ["open", str(path)]
                )
            else:
                subprocess.Popen(
                    ["xdg-open", str(path)]
                )
        except OSError as exc:
            QMessageBox.warning(
                self,
                "无法打开文件夹",
                str(exc),
            )
