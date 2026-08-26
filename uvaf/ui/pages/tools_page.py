from __future__ import annotations

from pathlib import Path
import ctypes
from ctypes import wintypes
import os
import threading
import time

import numpy as np

_TOOLS_USER32 = (
    ctypes.WinDLL(
        "user32",
        use_last_error=True,
    )
    if os.name == "nt"
    else None
)


from PySide6.QtCore import QAbstractTableModel, QModelIndex, QObject, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...core.recognition_engine import TemplateScanOptions
from ...core.i18n import tr_text
from .workspace_page import capture_screen_region_with_image


class MouseAnchorSignals(QObject):
    result_ready = Signal(
        str,
        object,
        str,
    )


class ColorReportModel(QAbstractTableModel):
    HEADERS = (
        "颜色",
        "HEX",
        "RGB",
        "像素数",
        "占比",
    )

    def __init__(
        self,
        rows=None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.rows = rows or []

    def set_rows(
        self,
        rows,
    ) -> None:
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    def rowCount(
        self,
        _parent=QModelIndex(),
    ) -> int:
        return len(
            self.rows
        )

    def columnCount(
        self,
        _parent=QModelIndex(),
    ) -> int:
        return len(
            self.HEADERS
        )

    def headerData(
        self,
        section,
        orientation,
        role=Qt.DisplayRole,
    ):
        if (
            orientation == Qt.Horizontal
            and role == Qt.DisplayRole
            and 0 <= section < len(
                self.HEADERS
            )
        ):
            return tr_text(
                self.HEADERS[
                    section
                ]
            )

        return None

    def data(
        self,
        index,
        role=Qt.DisplayRole,
    ):
        if (
            not index.isValid()
            or not (
                0
                <= index.row()
                < len(
                    self.rows
                )
            )
        ):
            return None

        red, green, blue, count, ratio = (
            self.rows[
                index.row()
            ]
        )

        if (
            role == Qt.DecorationRole
            and index.column() == 0
        ):
            return QColor(
                int(red),
                int(green),
                int(blue),
            )

        if role != Qt.DisplayRole:
            return None

        if index.column() == 0:
            return "■"

        if index.column() == 1:
            return (
                f"#{int(red):02X}"
                f"{int(green):02X}"
                f"{int(blue):02X}"
            )

        if index.column() == 2:
            return (
                f"RGB({int(red)}, "
                f"{int(green)}, "
                f"{int(blue)})"
            )

        if index.column() == 3:
            return f"{int(count):,}"

        if index.column() == 4:
            return f"{ratio * 100:.4f}%"

        return None


class ToolsPage(QWidget):
    def __init__(
        self,
        workspace=None,
        parent=None,
    ) -> None:
        super().__init__(parent)

        self.workspace = workspace
        self.recognition_engine = getattr(
            workspace,
            "recognition_engine",
            None,
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(
            28,
            24,
            28,
            24,
        )
        root.setSpacing(14)

        title = QLabel(
            "小工具",
            objectName="pageTitle",
        )
        root.addWidget(title)

        subtitle = QLabel(
            "一些独立于自动化流程的辅助分析工具。",
            objectName="pageSubtitle",
        )
        root.addWidget(
            subtitle
        )

        # ----------------------------------------------------------
        # Mouse coordinate monitor
        # ----------------------------------------------------------
        self.mouse_monitor_active = False
        self.mouse_records: list[
            tuple[int, int, str, str]
        ] = []

        self._mouse_anchor_path = ""
        self._mouse_anchor_point: tuple[
            int,
            int,
        ] | None = None
        self._mouse_anchor_error = ""
        self._anchor_scan_inflight = False

        self._anchor_signals = MouseAnchorSignals()
        self._anchor_signals.result_ready.connect(
            self._apply_anchor_scan_result
        )

        self._global_k_down = False

        self.mouse_timer = QTimer(
            self
        )
        self.mouse_timer.setInterval(
            200
        )
        self.mouse_timer.timeout.connect(
            self._update_mouse_position
        )

        self.mouse_key_timer = QTimer(
            self
        )
        self.mouse_key_timer.setInterval(
            50
        )
        self.mouse_key_timer.timeout.connect(
            self._poll_global_record_key
        )

        self.mouse_shortcut = QShortcut(
            QKeySequence(
                "K"
            ),
            self,
        )
        self.mouse_shortcut.setContext(
            Qt.WidgetWithChildrenShortcut
        )
        self.mouse_shortcut.activated.connect(
            self._shortcut_record_mouse_position
        )

        self.setFocusPolicy(
            Qt.StrongFocus
        )

        mouse_card = QFrame(
            objectName="card"
        )
        mouse_layout = QVBoxLayout(
            mouse_card
        )
        mouse_layout.setContentsMargins(
            18,
            16,
            18,
            16,
        )
        mouse_layout.setSpacing(
            10
        )

        mouse_header = QHBoxLayout()
        mouse_header.addWidget(
            QLabel(
                "鼠标坐标监视器",
                objectName="sectionTitle",
            )
        )
        mouse_header.addStretch()

        self.mouse_toggle_button = QPushButton(
            "启动",
            objectName="primaryButton",
        )
        self.mouse_toggle_button.clicked.connect(
            self.toggle_mouse_monitor
        )
        mouse_header.addWidget(
            self.mouse_toggle_button
        )

        mouse_layout.addLayout(
            mouse_header
        )

        coordinate_row = QHBoxLayout()
        coordinate_row.addWidget(
            QLabel(
                "坐标系"
            )
        )

        self.mouse_anchor_combo = QComboBox()
        self.mouse_anchor_combo.addItem(
            "全屏坐标（默认）",
            "",
        )
        self.mouse_anchor_combo.currentIndexChanged.connect(
            self._mouse_anchor_changed
        )
        coordinate_row.addWidget(
            self.mouse_anchor_combo,
            1,
        )

        self.mouse_template_refresh_button = QPushButton(
            "刷新模板"
        )
        self.mouse_template_refresh_button.clicked.connect(
            self.refresh_mouse_anchor_templates
        )
        coordinate_row.addWidget(
            self.mouse_template_refresh_button
        )

        mouse_layout.addLayout(
            coordinate_row
        )

        self.mouse_template_status = QLabel(
            "默认使用 Windows 物理全局坐标。",
            objectName="muted",
        )
        self.mouse_template_status.setWordWrap(
            True
        )
        mouse_layout.addWidget(
            self.mouse_template_status
        )

        self.mouse_position_label = QLabel(
            "未启动 · 启动后每 0.2 秒刷新一次鼠标全局坐标。",
            objectName="muted",
        )
        self.mouse_position_label.setWordWrap(
            True
        )
        mouse_layout.addWidget(
            self.mouse_position_label
        )

        mouse_hint = QLabel(
            "监视器启动后按 K 记录当前坐标。默认记录全屏坐标；"
            "选择当前项目模板作为锚点后，记录相对于该锚点左上角的坐标。",
            objectName="muted",
        )
        mouse_hint.setWordWrap(
            True
        )
        mouse_layout.addWidget(
            mouse_hint
        )

        mouse_actions = QHBoxLayout()

        delete_last_button = QPushButton(
            "删除上一项"
        )
        delete_last_button.clicked.connect(
            self.delete_last_mouse_record
        )
        mouse_actions.addWidget(
            delete_last_button
        )

        clear_button = QPushButton(
            "清空"
        )
        clear_button.clicked.connect(
            self.clear_mouse_records
        )
        mouse_actions.addWidget(
            clear_button
        )

        copy_button = QPushButton(
            "复制表格（Excel）"
        )
        copy_button.clicked.connect(
            self.copy_mouse_table
        )
        mouse_actions.addWidget(
            copy_button
        )

        mouse_actions.addStretch()
        mouse_layout.addLayout(
            mouse_actions
        )

        self.mouse_table = QTableWidget(
            0,
            5,
        )
        self.mouse_table.setHorizontalHeaderLabels(
            (
                "序号",
                "X",
                "Y",
                "坐标系",
                "记录时间",
            )
        )
        self.mouse_table.setEditTriggers(
            QAbstractItemView.NoEditTriggers
        )
        self.mouse_table.setSelectionBehavior(
            QAbstractItemView.SelectRows
        )
        self.mouse_table.setAlternatingRowColors(
            True
        )
        self.mouse_table.verticalHeader().setDefaultSectionSize(
            25
        )
        self.mouse_table.horizontalHeader().setStretchLastSection(
            True
        )
        self.mouse_table.setColumnWidth(
            0,
            65,
        )
        self.mouse_table.setColumnWidth(
            1,
            100,
        )
        self.mouse_table.setColumnWidth(
            2,
            100,
        )
        self.mouse_table.setColumnWidth(
            3,
            170,
        )
        self.mouse_table.setMinimumHeight(
            170
        )
        mouse_layout.addWidget(
            self.mouse_table
        )

        root.addWidget(
            mouse_card
        )

        self.refresh_mouse_anchor_templates()

        card = QFrame(
            objectName="card"
        )
        card_layout = QVBoxLayout(
            card
        )
        card_layout.setContentsMargins(
            18,
            16,
            18,
            16,
        )
        card_layout.setSpacing(
            12
        )

        header = QHBoxLayout()

        header.addWidget(
            QLabel(
                "框选区域颜色报告",
                objectName="sectionTitle",
            )
        )
        header.addStretch()

        select_button = QPushButton(
            "框选",
            objectName="primaryButton",
        )
        select_button.clicked.connect(
            self.capture_colors
        )
        header.addWidget(
            select_button
        )

        card_layout.addLayout(
            header
        )

        self.summary_label = QLabel(
            "点击“框选”，然后拖动选择屏幕区域。"
            "报告会列出该区域出现的每一种精确 RGB 颜色。",
            objectName="muted",
        )
        self.summary_label.setWordWrap(
            True
        )
        card_layout.addWidget(
            self.summary_label
        )

        self.table = QTableView()
        self.model = ColorReportModel(
            parent=self.table
        )
        self.table.setModel(
            self.model
        )
        self.table.setAlternatingRowColors(
            True
        )
        self.table.setSortingEnabled(
            False
        )
        self.table.verticalHeader().setDefaultSectionSize(
            26
        )
        self.table.horizontalHeader().setStretchLastSection(
            True
        )
        self.table.setColumnWidth(
            0,
            70,
        )
        self.table.setColumnWidth(
            1,
            110,
        )
        self.table.setColumnWidth(
            2,
            180,
        )
        self.table.setColumnWidth(
            3,
            110,
        )

        card_layout.addWidget(
            self.table,
            1,
        )

        root.addWidget(
            card,
            1,
        )

    def showEvent(
        self,
        event,
    ) -> None:
        super().showEvent(
            event
        )
        self.refresh_mouse_anchor_templates()

    def _current_project_template_dir(
        self,
    ) -> Path | None:
        workspace = self.workspace

        if workspace is None:
            return None

        project_manager = getattr(
            workspace,
            "project_manager",
            None,
        )

        if project_manager is None:
            return None

        try:
            project = (
                project_manager
                .current_project()
            )
        except Exception:
            return None

        if project is None:
            return None

        directory = (
            Path(
                project.path
            )
            / "templates"
        )
        directory.mkdir(
            parents=True,
            exist_ok=True,
        )
        return directory

    def refresh_mouse_anchor_templates(
        self,
    ) -> None:
        previous = str(
            self.mouse_anchor_combo.currentData()
            or ""
        )

        self.mouse_anchor_combo.blockSignals(
            True
        )

        try:
            self.mouse_anchor_combo.clear()
            self.mouse_anchor_combo.addItem(
                "全屏坐标（默认）",
                "",
            )

            directory = (
                self._current_project_template_dir()
            )

            if directory is None:
                self.mouse_template_status.setText(
                    tr_text(
                        "当前没有打开项目；仅可使用全屏坐标。"
                    )
                )
                self._mouse_anchor_path = ""
                self._mouse_anchor_point = None
                return

            suffixes = {
                ".png",
                ".jpg",
                ".jpeg",
                ".bmp",
                ".webp",
            }

            templates = sorted(
                (
                    path
                    for path in directory.iterdir()
                    if (
                        path.is_file()
                        and path.suffix.lower()
                        in suffixes
                    )
                ),
                key=lambda path: (
                    path.name.casefold()
                ),
            )

            for path in templates:
                self.mouse_anchor_combo.addItem(
                    path.name,
                    str(path),
                )

            if previous:
                index = (
                    self.mouse_anchor_combo
                    .findData(
                        previous
                    )
                )

                if index >= 0:
                    self.mouse_anchor_combo.setCurrentIndex(
                        index
                    )
                else:
                    self.mouse_anchor_combo.setCurrentIndex(
                        0
                    )
            else:
                self.mouse_anchor_combo.setCurrentIndex(
                    0
                )

            if not templates:
                self.mouse_template_status.setText(
                    tr_text(
                        "当前项目模板库为空；默认使用全屏坐标。"
                    )
                )
            elif not previous:
                self.mouse_template_status.setText(
                    tr_text(
                        (
                            f"已加载当前项目模板库："
                            f"{len(templates)} 个模板。"
                            "默认使用全屏坐标。"
                        )
                    )
                )

        finally:
            self.mouse_anchor_combo.blockSignals(
                False
            )

        self._mouse_anchor_changed()

    def _mouse_anchor_changed(
        self,
        _index: int = 0,
    ) -> None:
        self._mouse_anchor_path = str(
            self.mouse_anchor_combo.currentData()
            or ""
        )
        self._mouse_anchor_point = None
        self._mouse_anchor_error = ""
        self._anchor_scan_inflight = False

        if self._mouse_anchor_path:
            self.mouse_template_status.setText(
                tr_text(
                    (
                        "锚点："
                        f"{Path(self._mouse_anchor_path).name}"
                        " · 正在等待识别。"
                    )
                )
            )

            if self.mouse_monitor_active:
                self._request_anchor_scan()
        else:
            self.mouse_template_status.setText(
                tr_text(
                    "坐标系：全屏全局坐标。"
                )
            )

        if self.mouse_monitor_active:
            self._update_mouse_position()

    def toggle_mouse_monitor(
        self,
    ) -> None:
        self.mouse_monitor_active = (
            not self.mouse_monitor_active
        )

        if self.mouse_monitor_active:
            self.refresh_mouse_anchor_templates()

            self.mouse_toggle_button.setText(
                tr_text(
                    "停止"
                )
            )
            self.mouse_timer.start()
            self.mouse_key_timer.start()
            self._global_k_down = False

            self._update_mouse_position()

            if self._mouse_anchor_path:
                self._request_anchor_scan()

            self.setFocus(
                Qt.ShortcutFocusReason
            )
        else:
            self.mouse_toggle_button.setText(
                tr_text(
                    "启动"
                )
            )
            self.mouse_timer.stop()
            self.mouse_key_timer.stop()
            self._global_k_down = False
            self.mouse_position_label.setText(
                tr_text(
                    "已停止 · 再次点击“启动”可继续监视。"
                )
            )

    def _shortcut_record_mouse_position(
        self,
    ) -> None:
        # On Windows, GetAsyncKeyState below provides a true global K hotkey,
        # including when another application owns focus. Keep the Qt shortcut
        # as a fallback on other platforms only.
        if os.name != "nt":
            self.record_mouse_position()

    def _poll_global_record_key(
        self,
    ) -> None:
        if (
            not self.mouse_monitor_active
            or os.name != "nt"
        ):
            return

        try:
            if _TOOLS_USER32 is None:
                return

            down = bool(
                _TOOLS_USER32
                .GetAsyncKeyState(
                    ord("K")
                )
                & 0x8000
            )
        except Exception:
            return

        # Record only on the key-down edge, not repeatedly while held.
        if (
            down
            and not self._global_k_down
        ):
            self.record_mouse_position()

        self._global_k_down = down

    def _request_anchor_scan(
        self,
    ) -> None:
        path = self._mouse_anchor_path

        if (
            not path
            or self._anchor_scan_inflight
        ):
            return

        engine = self.recognition_engine

        if engine is None:
            self._mouse_anchor_error = (
                "Recognition Engine 不可用。"
            )
            self._mouse_anchor_point = None
            return

        if not Path(path).is_file():
            self._mouse_anchor_error = (
                "锚点模板文件不存在。"
            )
            self._mouse_anchor_point = None
            return

        self._anchor_scan_inflight = True

        def worker() -> None:
            point = None
            error = ""

            try:
                result = (
                    engine.scan_template(
                        path,
                        roi=None,
                        options=TemplateScanOptions(
                            threshold=0.860,
                            methods=(
                                "ccoeff_color",
                                "grayscale",
                                "feature",
                            ),
                            scales=(
                                0.90,
                                1.0,
                                1.10,
                            ),
                            confirm_frames=1,
                        ),
                    )
                )

                if result is None:
                    error = "未找到锚点"
                else:
                    point = (
                        int(
                            result.global_x
                        ),
                        int(
                            result.global_y
                        ),
                    )

            except Exception as exc:
                error = str(
                    exc
                )

            self._anchor_signals.result_ready.emit(
                path,
                point,
                error,
            )

        threading.Thread(
            target=worker,
            daemon=True,
            name="UVAF-MouseAnchorMonitor",
        ).start()

    def _apply_anchor_scan_result(
        self,
        path: str,
        point,
        error: str,
    ) -> None:
        self._anchor_scan_inflight = False

        # Ignore a stale result if the user changed anchors while the worker
        # was running.
        if (
            path
            != self._mouse_anchor_path
        ):
            return

        if (
            isinstance(
                point,
                (tuple, list),
            )
            and len(point) == 2
        ):
            self._mouse_anchor_point = (
                int(
                    point[0]
                ),
                int(
                    point[1]
                ),
            )
            self._mouse_anchor_error = ""
        else:
            self._mouse_anchor_point = None
            self._mouse_anchor_error = (
                error
                or "未找到锚点"
            )

        if self.mouse_monitor_active:
            self._update_mouse_position()

    @staticmethod
    def _windows_virtual_screen() -> tuple[
        int,
        int,
        int,
        int,
    ]:
        """
        Read the Windows virtual desktop directly.

        Returns:
            (left, top, width, height)

        SM_X/YVIRTUALSCREEN may be negative in multi-monitor layouts.
        The call is made under a temporary per-monitor-DPI-aware thread
        context when Windows supports it, preventing Qt/logical-DPI
        virtualization from leaking into this utility.
        """
        if os.name != "nt":
            screen = QApplication.primaryScreen()

            if screen is None:
                return (
                    0,
                    0,
                    1,
                    1,
                )

            geometry = (
                screen.virtualGeometry()
            )

            return (
                int(
                    geometry.x()
                ),
                int(
                    geometry.y()
                ),
                max(
                    1,
                    int(
                        geometry.width()
                    ),
                ),
                max(
                    1,
                    int(
                        geometry.height()
                    ),
                ),
            )

        user32 = _TOOLS_USER32

        if user32 is None:
            raise RuntimeError(
                "Windows user32 后端不可用。"
            )

        previous_context = None

        try:
            set_context = getattr(
                user32,
                "SetThreadDpiAwarenessContext",
                None,
            )

            if set_context is not None:
                set_context.restype = ctypes.c_void_p
                set_context.argtypes = [
                    ctypes.c_void_p
                ]

                # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 == -4
                previous_context = set_context(
                    ctypes.c_void_p(
                        -4
                    )
                )

            left = int(
                user32.GetSystemMetrics(
                    76  # SM_XVIRTUALSCREEN
                )
            )
            top = int(
                user32.GetSystemMetrics(
                    77  # SM_YVIRTUALSCREEN
                )
            )
            width = int(
                user32.GetSystemMetrics(
                    78  # SM_CXVIRTUALSCREEN
                )
            )
            height = int(
                user32.GetSystemMetrics(
                    79  # SM_CYVIRTUALSCREEN
                )
            )

            return (
                left,
                top,
                max(
                    1,
                    width,
                ),
                max(
                    1,
                    height,
                ),
            )

        finally:
            if (
                previous_context
                and os.name == "nt"
            ):
                try:
                    set_context = getattr(
                        user32,
                        "SetThreadDpiAwarenessContext",
                        None,
                    )

                    if set_context is not None:
                        set_context(
                            ctypes.c_void_p(
                                previous_context
                            )
                        )
                except Exception:
                    pass

    @staticmethod
    def _windows_physical_cursor_pos() -> tuple[
        int,
        int,
    ]:
        """
        Return the actual Windows physical cursor position.

        GetPhysicalCursorPos is preferred because it explicitly bypasses
        logical-coordinate DPI virtualization. GetCursorPos is retained as a
        compatibility fallback.
        """
        if os.name != "nt":
            point = QCursor.pos()

            return (
                int(
                    point.x()
                ),
                int(
                    point.y()
                ),
            )

        user32 = _TOOLS_USER32

        if user32 is None:
            raise RuntimeError(
                "Windows user32 后端不可用。"
            )
        point = wintypes.POINT()

        get_physical = getattr(
            user32,
            "GetPhysicalCursorPos",
            None,
        )

        if get_physical is not None:
            get_physical.argtypes = [
                ctypes.POINTER(
                    wintypes.POINT
                )
            ]
            get_physical.restype = (
                wintypes.BOOL
            )

            if get_physical(
                ctypes.byref(
                    point
                )
            ):
                return (
                    int(
                        point.x
                    ),
                    int(
                        point.y
                    ),
                )

        user32.GetCursorPos.argtypes = [
            ctypes.POINTER(
                wintypes.POINT
            )
        ]
        user32.GetCursorPos.restype = (
            wintypes.BOOL
        )

        if not user32.GetCursorPos(
            ctypes.byref(
                point
            )
        ):
            raise RuntimeError(
                "Windows GetCursorPos 失败。"
            )

        return (
            int(
                point.x
            ),
            int(
                point.y
            ),
        )

    def _windows_coordinate_snapshot(
        self,
    ) -> tuple[
        int,
        int,
        int,
        int,
        int,
        int,
    ]:
        """
        One consistent Windows-coordinate snapshot:
        cursor_x, cursor_y, virtual_left, virtual_top, width, height.
        """
        cursor_x, cursor_y = (
            self._windows_physical_cursor_pos()
        )
        left, top, width, height = (
            self._windows_virtual_screen()
        )

        return (
            cursor_x,
            cursor_y,
            left,
            top,
            width,
            height,
        )

    def _current_mouse_coordinate(
        self,
    ) -> tuple[
        int,
        int,
        str,
    ] | None:
        (
            global_x,
            global_y,
            _left,
            _top,
            _width,
            _height,
        ) = self._windows_coordinate_snapshot()

        anchor_path = (
            self._mouse_anchor_path
        )

        if not anchor_path:
            return (
                global_x,
                global_y,
                tr_text(
                    "全屏(Windows)"
                ),
            )

        anchor = (
            self._mouse_anchor_point
        )

        if anchor is None:
            return None

        return (
            global_x
            - int(
                anchor[0]
            ),
            global_y
            - int(
                anchor[1]
            ),
            (
                tr_text("锚点:")
                + f"{Path(anchor_path).name}"
            ),
        )

    def _update_mouse_position(
        self,
    ) -> None:
        if not self.mouse_monitor_active:
            return

        if self._mouse_anchor_path:
            self._request_anchor_scan()

        try:
            (
                global_x,
                global_y,
                virtual_left,
                virtual_top,
                virtual_width,
                virtual_height,
            ) = self._windows_coordinate_snapshot()
        except Exception as exc:
            self.mouse_position_label.setText(
                tr_text(
                    f"Windows 坐标读取失败：{exc}"
                )
            )
            return

        virtual_right = (
            virtual_left
            + virtual_width
            - 1
        )
        virtual_bottom = (
            virtual_top
            + virtual_height
            - 1
        )

        inside_virtual_screen = (
            virtual_left
            <= global_x
            <= virtual_right
            and virtual_top
            <= global_y
            <= virtual_bottom
        )

        bounds_text = (
            f"Windows虚拟桌面 "
            f"{virtual_width}×{virtual_height} · "
            f"原点=({virtual_left},{virtual_top})"
        )

        if not inside_virtual_screen:
            self.mouse_position_label.setText(
                tr_text(
                    (
                        f"Windows物理坐标 X={global_x} Y={global_y} · "
                        f"{bounds_text} · "
                        "警告：鼠标坐标超出 Windows 返回的虚拟桌面范围"
                    )
                )
            )
            return

        anchor_path = (
            self._mouse_anchor_path
        )

        if not anchor_path:
            self.mouse_position_label.setText(
                tr_text(
                    (
                        f"全屏坐标 · X={global_x}  Y={global_y} · "
                        f"{bounds_text} · "
                        "每 0.2 秒刷新 · 按 K 记录"
                    )
                )
            )
            self.mouse_template_status.setText(
                tr_text(
                    (
                        "坐标系：Windows 物理全局坐标 · "
                        f"{bounds_text}"
                    )
                )
            )
            return

        anchor = (
            self._mouse_anchor_point
        )

        if anchor is None:
            anchor_name = Path(
                anchor_path
            ).name
            status = (
                self._mouse_anchor_error
                or "正在定位锚点…"
            )

            self.mouse_position_label.setText(
                tr_text(
                    (
                        f"全局 X={global_x}  Y={global_y} · "
                        f"{bounds_text} · "
                        f"锚点 {anchor_name}：{status} · "
                        "当前不可记录相对坐标"
                    )
                )
            )
            self.mouse_template_status.setText(
                tr_text(
                    (
                        f"锚点：{anchor_name} · "
                        f"{status}"
                    )
                )
            )
            return

        relative_x = (
            global_x
            - int(
                anchor[0]
            )
        )
        relative_y = (
            global_y
            - int(
                anchor[1]
            )
        )

        anchor_name = Path(
            anchor_path
        ).name

        self.mouse_position_label.setText(
            tr_text(
                (
                    f"相对 X={relative_x}  Y={relative_y} · "
                    f"Windows全局 X={global_x}  Y={global_y} · "
                    f"{bounds_text} · "
                    "每 0.2 秒刷新 · 按 K 记录"
                )
            )
        )

        self.mouse_template_status.setText(
            tr_text(
                (
                    f"锚点:{anchor_name} · "
                    f"锚点全局=({anchor[0]}, {anchor[1]}) · "
                    "鼠标与锚点均使用 Windows 物理坐标"
                )
            )
        )

    def record_mouse_position(
        self,
    ) -> None:
        if not self.mouse_monitor_active:
            return

        current = (
            self._current_mouse_coordinate()
        )

        if current is None:
            self.mouse_position_label.setText(
                tr_text(
                    (
                        "当前锚点尚未识别，"
                        "本次 K 不记录坐标。"
                    )
                )
            )
            return

        x, y, coordinate_system = (
            current
        )

        recorded_at = time.strftime(
            "%H:%M:%S"
        )

        record = (
            int(
                x
            ),
            int(
                y
            ),
            coordinate_system,
            recorded_at,
        )
        self.mouse_records.append(
            record
        )

        row = (
            self.mouse_table.rowCount()
        )
        self.mouse_table.insertRow(
            row
        )

        values = (
            str(
                row + 1
            ),
            str(
                record[0]
            ),
            str(
                record[1]
            ),
            record[2],
            record[3],
        )

        for column, value in enumerate(
            values
        ):
            item = QTableWidgetItem(
                value
            )
            item.setTextAlignment(
                Qt.AlignCenter
            )
            self.mouse_table.setItem(
                row,
                column,
                item,
            )

        self.mouse_table.scrollToBottom()

        self.mouse_position_label.setText(
            tr_text(
                (
                    f"已记录 #{row + 1} · "
                    f"X={record[0]}  Y={record[1]} · "
                    f"{record[2]} · 按 K 可继续记录"
                )
            )
        )

    def delete_last_mouse_record(
        self,
    ) -> None:
        if not self.mouse_records:
            return

        self.mouse_records.pop()

        last_row = (
            self.mouse_table.rowCount()
            - 1
        )

        if last_row >= 0:
            self.mouse_table.removeRow(
                last_row
            )

        if self.mouse_monitor_active:
            self._update_mouse_position()

    def clear_mouse_records(
        self,
    ) -> None:
        self.mouse_records.clear()
        self.mouse_table.setRowCount(
            0
        )

        if self.mouse_monitor_active:
            self._update_mouse_position()
        else:
            self.mouse_position_label.setText(
                tr_text(
                    "记录已清空。"
                )
            )

    def copy_mouse_table(
        self,
    ) -> None:
        """
        Copy TSV so Excel / Calc / Sheets can paste columns directly.
        """
        rows = [
            (
                "序号",
                "X",
                "Y",
                "坐标系",
                "记录时间",
            )
        ]

        for index, (
            x,
            y,
            coordinate_system,
            recorded_at,
        ) in enumerate(
            self.mouse_records,
            start=1,
        ):
            rows.append(
                (
                    str(index),
                    str(x),
                    str(y),
                    coordinate_system,
                    recorded_at,
                )
            )

        table_text = "\n".join(
            "\t".join(
                row
            )
            for row in rows
        )

        QApplication.clipboard().setText(
            table_text
        )

        self.mouse_position_label.setText(
            tr_text(
                (
                    f"已复制 {len(self.mouse_records)} 条记录，"
                    "可直接粘贴到 Excel。"
                )
            )
        )

    def capture_colors(
        self,
    ) -> None:
        result = (
            capture_screen_region_with_image(
                self.window()
            )
        )

        if result is None:
            return

        region, bgr = result

        if bgr.size == 0:
            return

        # BGR -> RGB, then exact unique colors. QAbstractTableModel keeps
        # even very large color reports lazy instead of creating thousands
        # of QWidget rows.
        rgb = bgr[
            :,
            :,
            ::-1
        ].reshape(
            -1,
            3,
        )

        colors, counts = np.unique(
            rgb,
            axis=0,
            return_counts=True,
        )

        total = int(
            counts.sum()
        )

        order = np.argsort(
            counts
        )[::-1]

        rows = []

        for index in order:
            red, green, blue = (
                colors[
                    index
                ]
            )
            count = int(
                counts[
                    index
                ]
            )

            rows.append(
                (
                    int(red),
                    int(green),
                    int(blue),
                    count,
                    (
                        count
                        / total
                        if total
                        else 0.0
                    ),
                )
            )

        self.model.set_rows(
            rows
        )

        x, y, width, height = (
            region
        )

        self.summary_label.setText(
            tr_text(
                (
                    f"区域：({x}, {y}) "
                    f"{width}×{height} · "
                    f"像素：{total:,} · "
                    f"不同颜色：{len(rows):,}"
                )
            )
        )
