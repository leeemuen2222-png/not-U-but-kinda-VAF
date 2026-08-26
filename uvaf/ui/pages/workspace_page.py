from __future__ import annotations

from pathlib import Path
import base64
import ctypes
import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid

import cv2
import mss
import numpy as np

from PySide6.QtCore import QByteArray, QEvent, QMimeData, QObject, QPoint, QPointF, QRect, QRectF, QRegularExpression, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QCursor,
    QIcon,
    QImage,
    QGuiApplication,
    QDrag,
    QFont,
    QDoubleValidator,
    QIntValidator,
    QKeyEvent,
    QKeySequence,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QRegularExpressionValidator,
    QPixmap,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QGraphicsEllipseItem,
    QGraphicsLineItem,
    QGraphicsPathItem,
    QFileDialog,
    QFrame,
    QGraphicsItem,
    QGraphicsProxyWidget,
    QGraphicsScene,
    QGraphicsView,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QRubberBand,
    QSpinBox,
    QStackedWidget,
    QToolButton,
    QToolTip,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ...core.app_paths import templates_dir
from ...core.logging_service import LoggingService
from ...core.mouse_action_engine import ClickOptions, MouseActionEngine, MoveOptions
from ...core.keyboard_action_engine import KeyboardActionEngine, KeyboardOptions
from ...core.project_manager import PROJECT_EXTENSION, ProjectManager
from ...core.recognition_engine import DEFAULT_METHODS, RecognitionEngine, TemplateScanOptions
from ...core.settings import SettingsStore
from ...core.i18n import tr_text, current_language
from ...resources.modules import (
    ACTION_MODULE_TYPES,
    BlockCategory,
    CATEGORIES,
    CONDITION_LOGIC_TYPES,
    EVENT_ROOT_MODULE_TYPES,
    GLOBAL_MODULE_TYPES,
    LOGIC_CONTAINER_TYPES,
    ModuleSpec,
    VISUAL_MODULE_TYPES,
    category_by_key,
    complex_ports_for,
    condition_slots_for,
    data_types_compatible,
    get_module_definition,
    logic_slots_for,
    module_input_type,
    module_output_type,
    module_specs_for_category,
    settings_key_for,
    simple_controls_for,
    simple_width_for,
)
from ...resources.modules.module_ui import (
    IMAGE_FILTER,
    ComplexRoiDialog,
    DelaySettingsDialog,
    SimpleRoiSettingsDialog,
    capture_screen_region,
    capture_screen_region_with_image,
    choose_template_with_search,
    create_anchor_template_from_selection,
    find_template_once,
    library_templates,
    open_module_settings_dialog,
    parse_coord_text,
    parse_size_text,
    unique_library_path,
)
from ...resources.modules.runtime import (
    ExecutionStep,
    ModuleRuntimeMixin,
    WorkspaceRuntimeSignals,
    intersect_roi,
)
from ...resources.modules.runtime_guard import (
    validate_workspace_runtime_contract,
)


MIME_BLOCK = "application/x-uvaf-block"
CUSTOM_MODULE_EXTENSION = ".uvafmodule"
CUSTOM_MODULE_FORMAT = "UVAF_CUSTOM_MODULE"

# Every two executable modules are separated by at least 5 ms.


HOTKEY_MODIFIER_ORDER = (
    "CTRL",
    "ALT",
    "SHIFT",
    "META",
)


def workspace_hotkey_token(
    event: QKeyEvent,
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

    portable = (
        QKeySequence(
            key
        )
        .toString()
        .strip()
    )

    if portable:
        return portable.upper()

    return (
        event.text()
        .strip()
        .upper()
    )


def workspace_hotkey_set(
    value: str,
) -> frozenset[str]:
    tokens = {
        token.strip().upper()
        for token in str(
            value
        ).replace(
            " ",
            "",
        ).split("+")
        if token.strip()
    }

    return frozenset(
        tokens
    )





class RecognitionViewportSignals(QObject):
    frame_ready = Signal(object, str)
    status_ready = Signal(str)
    worker_finished = Signal()


class RecognitionViewportDialog(QDialog):
    WDA_EXCLUDEFROMCAPTURE = 0x00000011

    """
    Workspace-level Recognition Engine viewport.

    It is deliberately non-modal so users can keep it open while pressing
    Run / Stop and editing the workflow.

    The worker asks WorkspacePage for the currently effective visual ROI and
    the latest sensing-module detection box. Recognition/capture work never
    runs in the Qt GUI thread.
    """

    def __init__(
        self,
        workspace: "WorkspacePage",
        parent=None,
    ) -> None:
        super().__init__(parent)

        self.workspace = workspace
        self.engine = workspace.recognition_engine

        self._stop_event = threading.Event()
        self._worker: threading.Thread | None = None

        self._close_requested = False
        self._allow_final_close = False
        self._capture_exclusion_applied = False

        self._signals = RecognitionViewportSignals()
        self._signals.frame_ready.connect(
            self._apply_frame
        )
        self._signals.status_ready.connect(
            self._set_status
        )
        self._signals.worker_finished.connect(
            self._worker_has_finished
        )

        self.setWindowTitle(
            "视觉识别系统视角"
        )
        self.resize(
            960,
            650,
        )
        self.setModal(False)

        self.setAttribute(
            Qt.WA_DeleteOnClose,
            False,
        )

        layout = QVBoxLayout(self)

        self.status_label = QLabel(
            "正在启动视觉识别系统视角…",
            objectName="muted",
        )
        self.status_label.setWordWrap(
            True
        )
        layout.addWidget(
            self.status_label
        )

        self.image_label = QLabel()
        self.image_label.setAlignment(
            Qt.AlignCenter
        )
        self.image_label.setMinimumSize(
            640,
            420,
        )
        self.image_label.setStyleSheet(
            "background:#111;"
            "border:1px solid #333;"
        )
        layout.addWidget(
            self.image_label,
            1,
        )

        self._latest_image: QImage | None = None

        self._worker = threading.Thread(
            target=self._worker_loop,
            daemon=True,
            name="UVAF-RecognitionViewport",
        )
        self._worker.start()

    # --------------------------------------------------------------
    # Exclude this debug window from Desktop Duplication capture.
    # --------------------------------------------------------------
    def showEvent(
        self,
        event,
    ) -> None:
        super().showEvent(event)
        self._apply_capture_exclusion_setting()

    def _apply_capture_exclusion_setting(
        self,
    ) -> None:
        """
        Apply the current preference immediately.

        Disabled: WDA_NONE, so Windows screenshots can capture this window.
        Enabled: WDA_EXCLUDEFROMCAPTURE, avoiding recursive capture where
        supported by Windows.
        """
        if os.name != "nt":
            return

        try:
            enabled = bool(
                self.workspace.settings.get(
                    "recognition.exclude_viewport_from_capture",
                    False,
                )
            )

            hwnd = int(
                self.winId()
            )

            affinity = (
                self.WDA_EXCLUDEFROMCAPTURE
                if enabled
                else 0x00000000
            )

            result = (
                ctypes.windll.user32
                .SetWindowDisplayAffinity(
                    hwnd,
                    affinity,
                )
            )

            self._capture_exclusion_applied = bool(
                result
                and enabled
            )

            if enabled and not result:
                self.status_label.setText(
                    tr_text(
                        "视觉识别视角已启动；当前 Windows 环境无法启用截图排除。"
                    )
                )

        except Exception:
            self._capture_exclusion_applied = False

    # --------------------------------------------------------------
    # Safe worker shutdown.
    # --------------------------------------------------------------
    def closeEvent(
        self,
        event,
    ) -> None:
        if self._allow_final_close:
            event.accept()
            return

        self._close_requested = True
        self._stop_event.set()
        self.hide()
        event.ignore()

        if (
            self._worker is None
            or not self._worker.is_alive()
        ):
            self._worker_has_finished()

    def reject(self) -> None:
        if self._allow_final_close:
            super().reject()
            return

        self._close_requested = True
        self._stop_event.set()
        self.hide()

        if (
            self._worker is None
            or not self._worker.is_alive()
        ):
            self._worker_has_finished()

    def _worker_has_finished(
        self,
    ) -> None:
        if not self._close_requested:
            return

        self._allow_final_close = True

        try:
            self._signals.frame_ready.disconnect(
                self._apply_frame
            )
        except (RuntimeError, TypeError):
            pass

        try:
            self._signals.status_ready.disconnect(
                self._set_status
            )
        except (RuntimeError, TypeError):
            pass

        super().reject()

    # --------------------------------------------------------------
    # GUI slots.
    # --------------------------------------------------------------
    def _set_status(
        self,
        text_value: str,
    ) -> None:
        if self._close_requested:
            return

        self.status_label.setText(
            text_value
        )

    def _apply_frame(
        self,
        image,
        status: str,
    ) -> None:
        if (
            self._close_requested
            or not isinstance(
                image,
                QImage,
            )
        ):
            return

        self._latest_image = image

        pixmap = QPixmap.fromImage(
            image
        ).scaled(
            self.image_label.size(),
            Qt.KeepAspectRatio,
            Qt.FastTransformation,
        )

        self.image_label.setPixmap(
            pixmap
        )
        self.status_label.setText(
            status
        )

    def resizeEvent(
        self,
        event,
    ) -> None:
        super().resizeEvent(event)

        if self._latest_image is None:
            return

        pixmap = QPixmap.fromImage(
            self._latest_image
        ).scaled(
            self.image_label.size(),
            Qt.KeepAspectRatio,
            Qt.FastTransformation,
        )

        self.image_label.setPixmap(
            pixmap
        )

    # --------------------------------------------------------------
    # Background viewport worker.
    # --------------------------------------------------------------
    @staticmethod
    def _normalize_debug_roi(
        value,
    ) -> tuple[int, int, int, int] | None:
        """
        Recognition viewport is diagnostic UI. A malformed/stale ROI should
        never kill the worker; fall back to full-screen view instead.
        """
        if value is None:
            return None

        if (
            not isinstance(
                value,
                (tuple, list),
            )
            or len(value) != 4
        ):
            return None

        try:
            x, y, width, height = (
                int(round(float(item)))
                for item in value
            )
        except (
            TypeError,
            ValueError,
            OverflowError,
        ):
            return None

        if (
            width <= 0
            or height <= 0
        ):
            return None

        return (
            x,
            y,
            width,
            height,
        )

    @staticmethod
    def _normalize_detection_boxes(
        detection,
    ) -> list[
        tuple[int, int, int, int]
    ]:
        """
        Accept one box, a list of boxes, [], or None.

        The previous worker treated [] as one empty box and then attempted
        `box_x, box_y, box_w, box_h = []`, producing:
        "not enough values to unpack (expected 4, got 0)".
        """
        if detection is None:
            return []

        # One ordinary box.
        if (
            isinstance(
                detection,
                (tuple, list),
            )
            and len(detection) == 4
            and not isinstance(
                detection[0],
                (tuple, list),
            )
        ):
            candidates = [
                detection
            ]
        elif isinstance(
            detection,
            (tuple, list),
        ):
            candidates = list(
                detection
            )
        else:
            return []

        result = []

        for candidate in candidates:
            if (
                not isinstance(
                    candidate,
                    (tuple, list),
                )
                or len(candidate) != 4
            ):
                continue

            try:
                x, y, width, height = (
                    int(round(float(item)))
                    for item in candidate
                )
            except (
                TypeError,
                ValueError,
                OverflowError,
            ):
                continue

            if (
                width <= 0
                or height <= 0
            ):
                continue

            result.append(
                (
                    x,
                    y,
                    width,
                    height,
                )
            )

        return result

    def _worker_loop(
        self,
    ) -> None:
        frame_counter = 0
        fps_window_start = time.perf_counter()
        displayed_fps = 0.0

        try:
            while not self._stop_event.is_set():
                try:
                    snapshot = (
                        self.workspace
                        ._vision_debug_snapshot()
                    )

                    raw_roi = snapshot.get(
                        "roi"
                    )
                    requested_roi = (
                        self._normalize_debug_roi(
                            raw_roi
                        )
                    )

                    capture_result = (
                        self.engine.capture(
                            requested_roi
                        )
                    )

                    if (
                        not isinstance(
                            capture_result,
                            tuple,
                        )
                        or len(capture_result) != 3
                    ):
                        raise RuntimeError(
                            "Recognition Engine 返回了无效截图结果。"
                        )

                    frame, left, top = (
                        capture_result
                    )

                    if self._stop_event.is_set():
                        break

                    if (
                        frame is None
                        or not isinstance(
                            frame,
                            np.ndarray,
                        )
                        or frame.size == 0
                        or frame.ndim < 2
                    ):
                        self._signals.status_ready.emit(
                            "视觉识别视角：等待有效截图帧…"
                        )
                        self._stop_event.wait(
                            0.03
                        )
                        continue

                    # Draw debug overlays on a private copy; never mutate a
                    # backend-owned image buffer.
                    frame = frame.copy()
                    h, w = frame.shape[:2]

                    detection = snapshot.get(
                        "detection"
                    )
                    detection_boxes = (
                        self._normalize_detection_boxes(
                            detection
                        )
                    )

                    for box in detection_boxes:
                        box_x, box_y, box_w, box_h = (
                            box
                        )

                        x1 = int(
                            round(
                                box_x - left
                            )
                        )
                        y1 = int(
                            round(
                                box_y - top
                            )
                        )
                        x2 = int(
                            round(
                                box_x
                                + box_w
                                - left
                            )
                        )
                        y2 = int(
                            round(
                                box_y
                                + box_h
                                - top
                            )
                        )

                        draw_x1 = max(
                            0,
                            min(
                                w - 1,
                                x1,
                            ),
                        )
                        draw_y1 = max(
                            0,
                            min(
                                h - 1,
                                y1,
                            ),
                        )
                        draw_x2 = max(
                            0,
                            min(
                                w - 1,
                                x2,
                            ),
                        )
                        draw_y2 = max(
                            0,
                            min(
                                h - 1,
                                y2,
                            ),
                        )

                        if (
                            draw_x2 > draw_x1
                            and draw_y2 > draw_y1
                        ):
                            cv2.rectangle(
                                frame,
                                (
                                    draw_x1,
                                    draw_y1,
                                ),
                                (
                                    draw_x2,
                                    draw_y2,
                                ),
                                (
                                    0,
                                    0,
                                    255,
                                ),
                                3,
                                cv2.LINE_AA,
                            )

                    rgb = cv2.cvtColor(
                        frame,
                        cv2.COLOR_BGR2RGB,
                    )
                    channels = rgb.shape[2]

                    image = QImage(
                        rgb.data,
                        w,
                        h,
                        channels * w,
                        QImage.Format_RGB888,
                    ).copy()

                    frame_counter += 1

                    elapsed_window = (
                        time.perf_counter()
                        - fps_window_start
                    )

                    if elapsed_window >= 0.75:
                        displayed_fps = (
                            frame_counter
                            / elapsed_window
                        )
                        frame_counter = 0
                        fps_window_start = (
                            time.perf_counter()
                        )

                    actual_roi = (
                        left,
                        top,
                        w,
                        h,
                    )

                    module_name = snapshot.get(
                        "module"
                    )

                    if module_name:
                        sensing_text = (
                            f"感知={module_name}"
                        )
                    else:
                        sensing_text = (
                            "感知=未激活"
                        )

                    box_text = (
                        f" · 红框={detection_boxes}"
                        if detection_boxes
                        else ""
                    )

                    roi_note = (
                        " · ROI已回退全屏"
                        if (
                            raw_roi is not None
                            and requested_roi is None
                        )
                        else ""
                    )

                    status = (
                        f"实际视角={actual_roi}{roi_note} · "
                        f"{sensing_text}"
                        f"{box_text} · "
                        f"{displayed_fps:.1f} FPS"
                    )

                    if not self._close_requested:
                        self._signals.frame_ready.emit(
                            image,
                            status,
                        )

                except Exception as exc:
                    if self._stop_event.is_set():
                        break

                    self._signals.status_ready.emit(
                        f"视觉识别视角错误：{exc}"
                    )
                    self._stop_event.wait(
                        0.12
                    )

        finally:
            try:
                self._signals.worker_finished.emit()
            except RuntimeError:
                pass














































def block_path(width: float, height: float) -> QPainterPath:
    """
    Scratch-style stack block silhouette.

    The upper notch is an inward socket.
    The lower tab is an outward matching plug.
    """
    radius = 6.0

    notch_x = 34.0
    notch_w = 34.0
    notch_d = 6.0

    path = QPainterPath()

    path.moveTo(radius, 0)

    # Top inward notch.
    path.lineTo(notch_x, 0)
    path.lineTo(notch_x + 6, notch_d)
    path.lineTo(notch_x + notch_w - 6, notch_d)
    path.lineTo(notch_x + notch_w, 0)

    path.lineTo(width - radius, 0)
    path.quadTo(width, 0, width, radius)

    path.lineTo(width, height - radius)
    path.quadTo(width, height, width - radius, height)

    # Bottom outward tab.
    path.lineTo(notch_x + notch_w, height)
    path.lineTo(notch_x + notch_w - 6, height + notch_d)
    path.lineTo(notch_x + 6, height + notch_d)
    path.lineTo(notch_x, height)

    path.lineTo(radius, height)
    path.quadTo(0, height, 0, height - radius)

    path.lineTo(0, radius)
    path.quadTo(0, 0, radius, 0)

    path.closeSubpath()
    return path


def paint_block(
    painter: QPainter,
    category: BlockCategory,
    width: float,
    height: float,
    selected: bool = False,
) -> None:
    """
    Opaque Scratch-style block with contour-following 3D shading.

    The highlight and shadow are clipped to the actual puzzle silhouette,
    so rounded corners and both puzzle connectors share the same depth effect.
    """
    base = QColor(category.color)
    outline = QColor(base.darker(150))

    shape = block_path(width, height)

    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)

    painter.setPen(
        QPen(QColor("#F2F2F2"), 2.0)
        if selected
        else QPen(outline, 1.0)
    )
    painter.setBrush(base)
    painter.drawPath(shape)

    # Restrict all 3D shading to the real puzzle silhouette.
    painter.setClipPath(shape)

    # Upper-left inner highlight, following the real block contour.
    painter.save()
    painter.translate(0.9, 1.0)
    highlight_pen = QPen(QColor(255, 255, 255, 82), 1.45)
    highlight_pen.setJoinStyle(Qt.RoundJoin)
    highlight_pen.setCapStyle(Qt.RoundCap)
    painter.setPen(highlight_pen)
    painter.setBrush(Qt.NoBrush)
    painter.drawPath(shape)
    painter.restore()

    # Lower-right inner shadow, following every notch and curved corner.
    painter.save()
    painter.translate(-0.9, -1.0)
    shadow_pen = QPen(QColor(0, 0, 0, 95), 1.55)
    shadow_pen.setJoinStyle(Qt.RoundJoin)
    shadow_pen.setCapStyle(Qt.RoundCap)
    painter.setPen(shadow_pen)
    painter.setBrush(Qt.NoBrush)
    painter.drawPath(shape)
    painter.restore()

    # Slight soft center lift so the block reads as one raised object rather
    # than two separate contour strokes.
    inner = QColor(base.lighter(108))
    inner.setAlpha(42)
    painter.setPen(Qt.NoPen)
    painter.setBrush(inner)

    inner_shape = block_path(
        max(8.0, width - 5.0),
        max(8.0, height - 5.0),
    )
    painter.save()
    painter.translate(2.5, 2.0)
    painter.drawPath(inner_shape)
    painter.restore()

    painter.restore()


def roi_frame_path(
    width: float,
    height: float,
) -> QPainterPath:
    """
    One continuous Scratch-style C block.

    The INTERNAL connector uses exactly the same notch geometry as a normal
    block. It is merely shifted right by INNER_INDENT, so an ordinary block
    placed at x + INNER_INDENT interlocks perfectly with it.
    """
    r = 6.0

    # Must remain identical to block_path().
    notch_x = 34.0
    notch_w = 34.0
    notch_d = 6.0

    inner_indent = 26.0

    top_h = 42.0
    bottom_h = 36.0
    left_w = 18.0

    inner_top = top_h
    inner_bottom = height - bottom_h

    internal_notch_x = inner_indent + notch_x

    path = QPainterPath()
    path.setFillRule(Qt.WindingFill)

    # --------------------------------------------------------------
    # Outer top edge + normal Scratch input notch
    # --------------------------------------------------------------
    path.moveTo(r, 0)

    path.lineTo(notch_x, 0)
    path.lineTo(notch_x + 6, notch_d)
    path.lineTo(notch_x + notch_w - 6, notch_d)
    path.lineTo(notch_x + notch_w, 0)

    path.lineTo(width - r, 0)
    path.quadTo(width, 0, width, r)

    # --------------------------------------------------------------
    # Right edge of top cap
    # --------------------------------------------------------------
    path.lineTo(width, top_h - r)
    path.quadTo(width, top_h, width - r, top_h)

    # --------------------------------------------------------------
    # INTERNAL Scratch output tooth
    #
    # This is exactly the normal bottom connector geometry shifted by
    # inner_indent. A child block positioned at x + inner_indent has its
    # normal top notch directly underneath this tooth.
    # --------------------------------------------------------------
    path.lineTo(internal_notch_x + notch_w, inner_top)

    path.lineTo(
        internal_notch_x + notch_w - 6,
        inner_top + notch_d,
    )
    path.lineTo(
        internal_notch_x + 6,
        inner_top + notch_d,
    )
    path.lineTo(
        internal_notch_x,
        inner_top,
    )

    # Continue to the inner left wall.
    path.lineTo(inner_indent + r, inner_top)
    path.quadTo(
        inner_indent,
        inner_top,
        inner_indent,
        inner_top + r,
    )

    # --------------------------------------------------------------
    # Inner left wall
    # --------------------------------------------------------------
    path.lineTo(
        inner_indent,
        inner_bottom - r,
    )
    path.quadTo(
        inner_indent,
        inner_bottom,
        inner_indent + r,
        inner_bottom,
    )

    # --------------------------------------------------------------
    # Inner bottom edge opens to the right
    # --------------------------------------------------------------
    path.lineTo(width - r, inner_bottom)
    path.quadTo(
        width,
        inner_bottom,
        width,
        inner_bottom + r,
    )

    # --------------------------------------------------------------
    # Outer lower cap
    # --------------------------------------------------------------
    path.lineTo(width, height - r)
    path.quadTo(
        width,
        height,
        width - r,
        height,
    )

    # Normal outer bottom Scratch output tooth.
    path.lineTo(notch_x + notch_w, height)
    path.lineTo(
        notch_x + notch_w - 6,
        height + notch_d,
    )
    path.lineTo(
        notch_x + 6,
        height + notch_d,
    )
    path.lineTo(notch_x, height)

    path.lineTo(r, height)
    path.quadTo(
        0,
        height,
        0,
        height - r,
    )

    path.lineTo(0, r)
    path.quadTo(0, 0, r, 0)

    path.closeSubpath()
    return path


def paint_roi_frame(
    painter: QPainter,
    category: BlockCategory,
    width: float,
    height: float,
    selected: bool = False,
) -> None:
    base = QColor(category.color)
    outline = QColor(base.darker(150))

    shape = roi_frame_path(width, height)

    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)

    painter.setPen(
        QPen(QColor("#F2F2F2"), 2.0)
        if selected
        else QPen(outline, 1.0)
    )
    painter.setBrush(base)
    painter.drawPath(shape)

    painter.setClipPath(shape)

    painter.save()
    painter.translate(0.9, 1.0)
    highlight = QPen(QColor(255, 255, 255, 78), 1.35)
    highlight.setJoinStyle(Qt.RoundJoin)
    painter.setPen(highlight)
    painter.setBrush(Qt.NoBrush)
    painter.drawPath(shape)
    painter.restore()

    painter.save()
    painter.translate(-0.9, -1.0)
    shadow = QPen(QColor(0, 0, 0, 90), 1.45)
    shadow.setJoinStyle(Qt.RoundJoin)
    painter.setPen(shadow)
    painter.setBrush(Qt.NoBrush)
    painter.drawPath(shape)
    painter.restore()

    painter.restore()


class PaletteBlock(QWidget):
    def __init__(
        self,
        category: BlockCategory,
        module_type: str,
        text: str,
        parent=None,
        payload_extra: str = "",
        context_callback=None,
    ) -> None:
        super().__init__(parent)

        self.category = category
        self.module_type = module_type
        self.block_text = text
        self.payload_extra = str(payload_extra)
        self.context_callback = context_callback
        self._press_pos: QPoint | None = None

        self.setFixedHeight(48)
        self.setMinimumWidth(170)
        self.setCursor(Qt.OpenHandCursor)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        painter.translate(0.5, 3.5)

        paint_block(
            painter,
            self.category,
            self.width() - 1,
            36,
        )

        painter.setPen(QColor("#FFFFFF"))
        font = QFont("Segoe UI", 10)
        font.setWeight(QFont.DemiBold)
        painter.setFont(font)

        label = (
            self.block_text
            if self.module_type == "custom_module"
            else tr_text(self.block_text)
        )
        if self.module_type == "findtemplate":
            label += "  ▼"

        painter.drawText(
            QRectF(15, 4, self.width() - 28, 27),
            Qt.AlignVCenter | Qt.AlignLeft,
            label,
        )

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self._press_pos = event.position().toPoint()
            self.setCursor(Qt.ClosedHandCursor)

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if (
            self._press_pos is None
            or not (event.buttons() & Qt.LeftButton)
        ):
            return

        if (
            event.position().toPoint() - self._press_pos
        ).manhattanLength() < 6:
            return

        drag = QDrag(self)
        mime = QMimeData()

        payload = (
            f"{self.category.key}\n"
            f"{self.module_type}\n"
            f"{self.block_text}\n"
            f"{self.payload_extra}"
        ).encode("utf-8")

        mime.setData(MIME_BLOCK, QByteArray(payload))
        drag.setMimeData(mime)

        pixmap = QPixmap(self.size())
        pixmap.fill(Qt.transparent)
        self.render(pixmap)

        drag.setPixmap(pixmap)
        drag.setHotSpot(self._press_pos)

        self.setCursor(Qt.OpenHandCursor)
        drag.exec(Qt.CopyAction)
        self._press_pos = None

    def contextMenuEvent(
        self,
        event,
    ) -> None:
        if (
            self.module_type
            == "custom_module"
            and callable(
                self.context_callback
            )
        ):
            self.context_callback(
                self.payload_extra,
                event.globalPos(),
            )
            event.accept()
            return

        super().contextMenuEvent(
            event
        )

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._press_pos = None
        self.setCursor(Qt.OpenHandCursor)
        super().mouseReleaseEvent(event)


class CustomModuleAddBlock(QWidget):
    """Dashed puzzle silhouette used to import/open the custom-module folder."""

    def __init__(
        self,
        category: BlockCategory,
        callback=None,
        parent=None,
    ) -> None:
        super().__init__(parent)

        self.category = category
        self.callback = callback
        self.setFixedHeight(48)
        self.setMinimumWidth(170)
        self.setCursor(
            Qt.PointingHandCursor
        )

    def paintEvent(
        self,
        _event,
    ) -> None:
        painter = QPainter(self)
        painter.setRenderHint(
            QPainter.Antialiasing,
            True,
        )
        painter.translate(
            0.5,
            3.5,
        )

        shape = block_path(
            self.width() - 1,
            36,
        )

        pen = QPen(
            QColor(
                self.category.color
            ).lighter(145),
            1.8,
        )
        pen.setStyle(
            Qt.DashLine
        )
        pen.setJoinStyle(
            Qt.RoundJoin
        )
        painter.setPen(
            pen
        )

        fill = QColor(
            self.category.color
        )
        fill.setAlpha(
            18
        )
        painter.setBrush(
            fill
        )
        painter.drawPath(
            shape
        )

        painter.setPen(
            QPen(
                QColor("#EEEEEE"),
                2.0,
            )
        )

        center_x = (
            self.width()
            / 2.0
        )
        center_y = 18.0

        painter.drawLine(
            QPointF(
                center_x - 7,
                center_y,
            ),
            QPointF(
                center_x + 7,
                center_y,
            ),
        )
        painter.drawLine(
            QPointF(
                center_x,
                center_y - 7,
            ),
            QPointF(
                center_x,
                center_y + 7,
            ),
        )

    def mouseReleaseEvent(
        self,
        event: QMouseEvent,
    ) -> None:
        if (
            event.button()
            == Qt.LeftButton
            and callable(
                self.callback
            )
        ):
            self.callback(
                self.mapToGlobal(
                    event.position()
                    .toPoint()
                )
            )
            event.accept()
            return

        super().mouseReleaseEvent(
            event
        )


class CategorySection(QWidget):
    def __init__(
        self,
        category: BlockCategory,
        parent=None,
        event_specs: tuple[ModuleSpec, ...] = (),
        custom_specs: tuple[ModuleSpec, ...] = (),
        custom_add_callback=None,
        custom_context_callback=None,
    ) -> None:
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 9)
        layout.setSpacing(6)

        title_row = QHBoxLayout()
        title_row.setSpacing(7)

        dot = QLabel()
        dot.setFixedSize(10, 10)
        dot.setStyleSheet(
            f"background-color:{category.color};"
            "border-radius:5px;"
        )

        title = QLabel(tr_text(category.title))
        title.setStyleSheet(
            "font-size:13px;"
            "font-weight:600;"
        )

        title_row.addWidget(dot)
        title_row.addWidget(title)
        title_row.addStretch()
        layout.addLayout(title_row)

        if category.key == "custom":
            specs = tuple(custom_specs)
        elif category.key == "event":
            specs = (
                *module_specs_for_category("event"),
                *event_specs,
            )
        else:
            specs = module_specs_for_category(
                category.key
            )

        for spec in specs:
            layout.addWidget(
                PaletteBlock(
                    category,
                    spec.module_type,
                    spec.label,
                    payload_extra=spec.payload_extra,
                    context_callback=(
                        custom_context_callback
                        if category.key == "custom"
                        else None
                    ),
                )
            )

        if category.key == "custom":
            layout.addWidget(
                CustomModuleAddBlock(
                    category,
                    custom_add_callback,
                )
            )


class CanvasBlock(QGraphicsItem):
    DEFAULT_WIDTH = 178.0
    FIND_TEMPLATE_WIDTH = 600.0
    GLOBAL_ANCHOR_WIDTH = 690.0
    HEIGHT = 38.0
    STACK_STEP = HEIGHT

    def __init__(
        self,
        category: BlockCategory,
        module_type: str,
        text: str,
    ) -> None:
        super().__init__()

        self.node_id = uuid.uuid4().hex
        self.category = category
        self.module_type = module_type
        self.text = text

        # A custom-module instance is one visible opaque block. Its original
        # component nodes remain hidden in the scene only as executable state.
        self.custom_member_ids: list[str] = []
        self.custom_source_path: str = ""
        self._custom_hidden = False

        # Presentation metadata comes from uvaf.resources.modules.
        self.block_width = simple_width_for(
            module_type,
            self.DEFAULT_WIDTH,
        )

        self.selected_template_path: str | None = None
        self.match_threshold = 0.860
        self.recognition_methods = tuple(DEFAULT_METHODS)
        self.multi_scale = True
        self.confirm_frames = 1
        self.feature_detector = "SIFT"
        self.wait_for_match = True
        self.wait_timeout_ms = 1000
        self.global_anchor_template_path: str | None = None
        self.global_anchor_roi = (0, 0, 1280, 720)
        self.global_roi_edit: QLineEdit | None = None
        self.global_roi_proxy: QGraphicsProxyWidget | None = None
        self.global_roi_button_proxy: QGraphicsProxyWidget | None = None

        # Action-module configuration.
        self.move_advanced = False
        self.move_offset_up = 0.0
        self.move_offset_down = 0.0
        self.move_offset_left = 0.0
        self.move_offset_right = 0.0
        self.move_speed_mode = "duration"
        self.move_speed_value = 0.0
        self.move_speed_variance = 0.0
        self.move_random_route = False

        self.click_count = 1
        self.click_advanced = False
        self.click_press_duration = 0.025
        self.click_interval = 0.100

        self.drag_start_x=0.0; self.drag_start_y=0.0; self.drag_end_x=0.0; self.drag_end_y=0.0; self.drag_press_duration=0.025
        self.key_name="SPACE"; self.key_mode="press"; self.key_count=1; self.key_interval=0.0; self.key_hold_duration=0.5
        self.key_advanced=False; self.key_duration_variance=0.0; self.key_interval_variance=0.0; self.key_humanized=False
        self.key_text_mode=False; self.key_text=""
        self.executable_path=""; self.delay_value=1.0; self.delay_unit="seconds"
        self.clock_value=60.0; self.clock_unit="seconds"; self.clock_behavior="stop"
        self.clock_event_slot=0; self.clock_event_claimed=False

        self.fixed_coordinate_x=0
        self.fixed_coordinate_y=0
        self.fixed_coordinate_anchor_path: str | None = None

        self.coordinate_modify_x=0
        self.coordinate_modify_y=0
        self.coordinate_modify_x_edit: QLineEdit | None = None
        self.coordinate_modify_y_edit: QLineEdit | None = None
        self.coordinate_modify_x_proxy: QGraphicsProxyWidget | None = None
        self.coordinate_modify_y_proxy: QGraphicsProxyWidget | None = None

        self.inline_path_edit=None; self.inline_delay_spin=None; self.inline_delay_unit=None

        self.type_warning_message = ""
        self.condition_warning_message = ""

        self.loop_count = 1
        self.loop_infinite = False

        self.stack_parent: CanvasBlock | None = None
        self.stack_child: CanvasBlock | None = None

        # When this is the first block inside an ROI, its container is
        # separate from normal Scratch stack_parent.
        self.container_parent = None

        self._press_scene_pos = QPointF()
        self._moved_during_press = False
        self._stack_move_guard = False

        self.threshold_proxy: QGraphicsProxyWidget | None = None
        self.threshold_edit: QLineEdit | None = None

        self.template_button: QPushButton | None = None
        self.template_button_proxy: QGraphicsProxyWidget | None = None

        self.setFlags(
            QGraphicsItem.ItemIsMovable
            | QGraphicsItem.ItemIsSelectable
            | QGraphicsItem.ItemSendsGeometryChanges
        )

        self.setCursor(Qt.OpenHandCursor)
        self.setZValue(10)

        control_kind = simple_controls_for(
            self.module_type
        )
        if control_kind == "visual":
            self._build_visual_controls()
        elif control_kind == "global_anchor":
            self._build_global_anchor_controls()
        elif control_kind == "launch_exe":
            self._build_inline_exe_controls()
        elif control_kind == "delay_wait":
            self._build_inline_delay_controls()
        elif control_kind == "coordinate_modify":
            self._build_coordinate_modify_controls()

    @staticmethod
    def _format_signed_offset(
        value: int,
    ) -> str:
        return f"{int(value):+d}"

    def _make_coordinate_modify_edit(
        self,
        axis: str,
        value: int,
    ) -> QLineEdit:
        edit = QLineEdit(
            self._format_signed_offset(
                value
            )
        )
        edit.setFixedSize(
            76,
            24,
        )
        edit.setAlignment(
            Qt.AlignCenter
        )
        edit.setPlaceholderText(
            "+0"
        )
        edit.setToolTip(
            f"{axis} 必须带 + 或 -，例如 +20、-15"
        )
        edit.setValidator(
            QRegularExpressionValidator(
                QRegularExpression(
                    r"^[+-]\d{0,9}$"
                ),
                edit,
            )
        )
        edit.editingFinished.connect(
            lambda checked_axis=axis, target=edit:
                self._commit_coordinate_modify_edit(
                    checked_axis,
                    target,
                )
        )
        return edit

    def _build_coordinate_modify_controls(
        self,
    ) -> None:
        x_edit = self._make_coordinate_modify_edit(
            "X",
            self.coordinate_modify_x,
        )
        y_edit = self._make_coordinate_modify_edit(
            "Y",
            self.coordinate_modify_y,
        )

        x_proxy = QGraphicsProxyWidget(
            self
        )
        x_proxy.setWidget(
            x_edit
        )
        x_proxy.setPos(
            218,
            7,
        )
        x_proxy.setZValue(
            31
        )

        y_proxy = QGraphicsProxyWidget(
            self
        )
        y_proxy.setWidget(
            y_edit
        )
        y_proxy.setPos(
            326,
            7,
        )
        y_proxy.setZValue(
            31
        )

        self.coordinate_modify_x_edit = (
            x_edit
        )
        self.coordinate_modify_y_edit = (
            y_edit
        )
        self.coordinate_modify_x_proxy = (
            x_proxy
        )
        self.coordinate_modify_y_proxy = (
            y_proxy
        )

    def _commit_coordinate_modify_edit(
        self,
        axis: str,
        edit: QLineEdit,
    ) -> None:
        value = (
            edit.text()
            .strip()
        )

        if not re.fullmatch(
            r"[+-]\d+",
            value,
        ):
            current = (
                self.coordinate_modify_x
                if axis == "X"
                else self.coordinate_modify_y
            )
            edit.setText(
                self._format_signed_offset(
                    current
                )
            )
            QToolTip.showText(
                QCursor.pos(),
                (
                    f"{axis} 必须带正负号，"
                    "例如 +20 或 -15"
                ),
                edit,
            )
            return

        parsed = int(
            value
        )

        if axis == "X":
            self.coordinate_modify_x = (
                parsed
            )
        else:
            self.coordinate_modify_y = (
                parsed
            )

        edit.setText(
            self._format_signed_offset(
                parsed
            )
        )
        self.update()

    def sync_coordinate_modify_controls(
        self,
    ) -> None:
        if self.coordinate_modify_x_edit is not None:
            self.coordinate_modify_x_edit.setText(
                self._format_signed_offset(
                    self.coordinate_modify_x
                )
            )

        if self.coordinate_modify_y_edit is not None:
            self.coordinate_modify_y_edit.setText(
                self._format_signed_offset(
                    self.coordinate_modify_y
                )
            )

    def _build_inline_exe_controls(self) -> None:
        edit=QLineEdit(); edit.setPlaceholderText("程序路径"); edit.setFixedSize(330,24)
        edit.editingFinished.connect(lambda:setattr(self,"executable_path",edit.text().strip()))
        p=QGraphicsProxyWidget(self); p.setWidget(edit); p.setPos(100,7); p.setZValue(31)
        btn=QPushButton("…"); btn.setFixedSize(32,24)
        def browse():
            path,_=QFileDialog.getOpenFileName(None,"选择程序",edit.text(),"Programs (*.exe);;All files (*.*)")
            if path: edit.setText(path); self.executable_path=path
        btn.clicked.connect(browse); q=QGraphicsProxyWidget(self); q.setWidget(btn); q.setPos(438,7); q.setZValue(31)
        self.inline_path_edit=edit

    def _build_inline_delay_controls(self) -> None:
        spin=QDoubleSpinBox(); spin.setRange(0,100000000); spin.setDecimals(3); spin.setFixedSize(120,24); spin.setValue(self.delay_value)
        combo=QComboBox(); [combo.addItem(label,data) for label,data in DelaySettingsDialog.UNITS]; combo.setFixedSize(90,24)
        spin.valueChanged.connect(lambda v:setattr(self,"delay_value",float(v))); combo.currentIndexChanged.connect(lambda _i:setattr(self,"delay_unit",str(combo.currentData())))
        p=QGraphicsProxyWidget(self); p.setWidget(spin); p.setPos(90,7); p.setZValue(31); q=QGraphicsProxyWidget(self); q.setWidget(combo); q.setPos(215,7); q.setZValue(31)
        self.inline_delay_spin=spin; self.inline_delay_unit=combo

    def sync_inline_action_controls(self) -> None:
        if self.inline_path_edit is not None:self.inline_path_edit.setText(str(self.executable_path))
        if self.inline_delay_spin is not None:self.inline_delay_spin.setValue(float(self.delay_value))
        if self.inline_delay_unit is not None:
            idx=self.inline_delay_unit.findData(str(self.delay_unit)); self.inline_delay_unit.setCurrentIndex(max(0,idx))

    def _build_global_anchor_controls(self) -> None:
        edit=QLineEdit('0,0,1280*720'); edit.setFixedSize(174,24); edit.setAlignment(Qt.AlignCenter)
        edit.setStyleSheet('QLineEdit{background:rgba(20,20,20,155);border:1px solid rgba(255,255,255,90);border-radius:5px;padding:0 5px;color:white;font-size:10px;}')
        edit.editingFinished.connect(self._commit_global_roi_text)
        proxy=QGraphicsProxyWidget(self); proxy.setWidget(edit); proxy.setPos(427,7); proxy.setZValue(31)
        button=QPushButton('框选'); button.setFixedSize(52,24); button.clicked.connect(self.select_global_roi)
        button.setStyleSheet('QPushButton{background:rgba(20,20,20,120);border:1px solid rgba(255,255,255,90);border-radius:5px;color:white;}')
        bp=QGraphicsProxyWidget(self); bp.setWidget(button); bp.setPos(608,7); bp.setZValue(31)
        self.global_roi_edit=edit; self.global_roi_proxy=proxy; self.global_roi_button_proxy=bp

    def sync_global_controls(self) -> None:
        if self.global_roi_edit is None: return
        x,y,w,h=self.global_anchor_roi; self.global_roi_edit.setText(f'{x},{y},{w}*{h}')

    def _commit_global_roi_text(self) -> None:
        if self.global_roi_edit is None: return
        m=re.match(r'^\s*(-?\d+)\s*[,，]\s*(-?\d+)\s*[,，]\s*(\d+)\s*[xX×*\\]\\?\s*(\d+)\s*$',self.global_roi_edit.text().strip())
        if m is None:
            # Common form: x,y,w*h
            m=re.match(r'^\s*(-?\d+)\s*[,，]\s*(-?\d+)\s*[,，]\s*(\d+)\s*[xX×*]\\?\s*(\d+)\s*$',self.global_roi_edit.text().strip())
        if m is None:
            self.sync_global_controls(); return
        self.global_anchor_roi=(int(m.group(1)),int(m.group(2)),max(1,int(m.group(3))),max(1,int(m.group(4))))
        self.sync_global_controls()

    def global_template_box_rect(self) -> QRectF:
        return QRectF(112,6,238,25)

    def global_template_name(self) -> str:
        if not self.global_anchor_template_path: return '选择锚点模板'
        name=Path(self.global_anchor_template_path).name
        return name if len(name)<=22 else name[:21]+'…'

    def choose_global_anchor_template(self) -> None:
        parent=None; scene=self.scene()
        if scene is not None:
            for view in scene.views(): parent=view.window(); break
        selected,_=choose_template_with_search(parent,'选择锚点模板',allow_external=False)
        if selected:
            self.global_anchor_template_path=selected; self.update()

    def _workspace_recognition_engine(self) -> RecognitionEngine | None:
        scene=self.scene()
        if scene is None: return None
        for view in scene.views():
            page=view
            while page is not None:
                engine=getattr(page,'recognition_engine',None)
                if engine is not None: return engine
                page=page.parent()
        return None

    def select_global_roi(self) -> None:
        if not self.global_anchor_template_path:
            QMessageBox.information(None,'尚未选择锚点','请先选择锚点模板。'); return
        engine=self._workspace_recognition_engine()
        if engine is None:
            QMessageBox.warning(None,'识别引擎不可用','当前无法访问 Recognition Engine。'); return
        anchor=engine.scan_template(self.global_anchor_template_path,roi=None,options=TemplateScanOptions(threshold=0.860,methods=('ccoeff_color','grayscale','feature'),scales=(0.90,1.0,1.10)))
        if anchor is None:
            QMessageBox.warning(None,'未找到锚点','当前屏幕中没有找到所选锚点模板。'); return
        region=capture_screen_region(None)
        if region is None: return
        x,y,w,h=region; self.global_anchor_roi=(x-anchor.x,y-anchor.y,w,h); self.sync_global_controls(); self.update()

    def _build_visual_controls(self) -> None:
        """
        Use a real QPushButton for the template dropdown.

        The old dropdown was only painted onto the QGraphicsItem and depended
        on CanvasBlock.mousePressEvent manually detecting the rectangle. That
        code remained hard-coded to findtemplate, so Template Count and Lock
        Template could never open the picker. A proxy widget also prevents
        block-drag handling from stealing the click.
        """
        button = QPushButton(
            "选择模板  ▼"
        )
        button.setFixedSize(
            int(
                self.template_box_rect()
                .width()
            ),
            25,
        )
        button.setCursor(
            Qt.PointingHandCursor
        )
        button.setStyleSheet(
            "QPushButton{"
            "background:rgba(25,110,75,90);"
            "border:1px solid rgba(255,255,255,90);"
            "border-radius:5px;"
            "padding:0 8px;"
            "color:white;"
            "font-size:10px;"
            "text-align:left;"
            "}"
            "QPushButton:hover{"
            "background:rgba(35,135,92,140);"
            "border:1px solid rgba(255,255,255,155);"
            "}"
            "QPushButton:pressed{"
            "background:rgba(20,90,62,180);"
            "}"
        )
        button.clicked.connect(
            self.open_template_menu
        )

        proxy = QGraphicsProxyWidget(
            self
        )
        proxy.setWidget(
            button
        )
        proxy.setPos(
            self.template_box_rect().x(),
            self.template_box_rect().y(),
        )
        proxy.setZValue(
            32
        )

        self.template_button = button
        self.template_button_proxy = (
            proxy
        )

        self._build_threshold_editor()
        self.sync_template_button()

    def open_template_menu(self) -> None:
        """
        Open the shared searchable template picker for every visual module.

        This method was accidentally dropped during the large workspace merge,
        while _build_visual_controls() still connected the button to it.
        """
        parent = None
        scene = self.scene()

        if scene is not None:
            for view in scene.views():
                parent = view.window()
                break

        selected, choose_external = (
            choose_template_with_search(
                parent,
                "选择模板",
                allow_external=True,
            )
        )

        if choose_external:
            self.choose_external_template(
                parent
            )
            return

        if selected:
            self.selected_template_path = str(
                selected
            )
            self.sync_template_button()
            self.update()

    def choose_external_template(
        self,
        parent=None,
    ) -> None:
        file_path, _filter = (
            QFileDialog.getOpenFileName(
                parent,
                "选择模板图片",
                "",
                IMAGE_FILTER,
            )
        )

        if not file_path:
            return

        source = Path(
            file_path
        )

        answer = QMessageBox.question(
            parent,
            "加入模板库",
            "是否将这个模板加入当前项目的模板库？",
            QMessageBox.Yes
            | QMessageBox.No,
            QMessageBox.Yes,
        )

        if answer == QMessageBox.Yes:
            destination = (
                unique_library_path(
                    source
                )
            )

            try:
                shutil.copy2(
                    source,
                    destination,
                )
            except OSError as exc:
                QMessageBox.warning(
                    parent,
                    "复制失败",
                    str(exc),
                )
                return

            self.selected_template_path = str(
                destination
            )
        else:
            self.selected_template_path = str(
                source
            )

        self.sync_template_button()
        self.update()

    def sync_template_button(self) -> None:
        if self.template_button is None:
            return

        name = self.template_display_name()

        self.template_button.setText(
            f"{name}  ▼"
        )

    def _build_threshold_editor(self) -> None:
        edit = QLineEdit("0.860")
        edit.setFixedSize(56, 24)
        edit.setAlignment(Qt.AlignCenter)
        edit.setMaxLength(5)

        validator = QDoubleValidator(0.0, 1.0, 3, edit)
        validator.setNotation(QDoubleValidator.StandardNotation)
        edit.setValidator(validator)

        edit.setStyleSheet(
            "QLineEdit{"
            "background:rgba(20,20,20,155);"
            "border:1px solid rgba(255,255,255,90);"
            "border-radius:5px;"
            "padding:0 4px;"
            "color:white;"
            "font-size:11px;"
            "}"
            "QLineEdit:focus{"
            "border:1px solid rgba(255,255,255,180);"
            "}"
        )

        edit.editingFinished.connect(
            self._commit_threshold
        )

        proxy = QGraphicsProxyWidget(self)
        proxy.setWidget(edit)
        proxy.setPos(
            self.block_width - 66,
            7,
        )
        proxy.setZValue(30)

        self.threshold_edit = edit
        self.threshold_proxy = proxy

    def _commit_threshold(self) -> None:
        if self.threshold_edit is None:
            return

        raw = self.threshold_edit.text().strip()

        try:
            value = float(raw)
        except ValueError:
            value = self.match_threshold

        value = max(0.0, min(1.0, value))
        self.match_threshold = value

        self.threshold_edit.setText(
            f"{value:.3f}"
        )

    def descendants(
        self,
    ) -> list["CanvasBlock"]:
        """
        Return the downstream simple-mode stack below this block.

        Used by magnetic snapping to prevent a dragged stack from being
        attached beneath one of its own descendants, which would create a
        cycle. The method is iterative and cycle-safe so damaged legacy
        project data cannot recurse forever.
        """
        result: list[
            CanvasBlock
        ] = []
        seen: set[int] = {
            id(self)
        }

        current = self.stack_child

        while current is not None:
            marker = id(
                current
            )

            if marker in seen:
                break

            seen.add(
                marker
            )
            result.append(
                current
            )
            current = (
                current.stack_child
            )

        return result

    def attach_under(
        self,
        parent: "CanvasBlock",
    ) -> bool:
        """
        Attach this block/stack directly below `parent` in simple mode.

        Event modules are roots and cannot themselves be attached below another
        block. Every other module type, including global modules such as Clock,
        can be powered by becoming reachable from an event root.
        """
        if parent is self:
            return False

        if self.module_type in EVENT_ROOT_MODULE_TYPES:
            return False

        # Do not create a cycle by attaching a stack under one of its own
        # descendants.
        current: CanvasBlock | None = parent

        while current is not None:
            if current is self:
                return False
            current = current.stack_parent

        if parent.stack_child is not None:
            return False

        # If this stack is currently attached somewhere else, detach only its
        # upper edge; descendants remain connected to this block.
        self.detach_from_parent()

        parent.stack_child = self
        self.stack_parent = parent

        # A normal external stack connection takes the block out of any ROI
        # container relationship inherited from a previous placement.
        current = self

        while current is not None:
            current.container_parent = None
            current = current.stack_child

        expected = QPointF(
            parent.scenePos().x(),
            parent.scenePos().y()
            + parent.stack_step(),
        )

        self._stack_move_guard = True

        try:
            self.setPos(
                expected
            )
        finally:
            self._stack_move_guard = False

        self.realign_descendants()

        if isinstance(
            parent,
            RoiBlock,
        ):
            parent.update_dynamic_height()

        scene = self.scene()

        if isinstance(
            scene,
            WorkflowScene,
        ):
            scene.request_overview_update()

        return True

    def detach_from_parent(
        self,
    ) -> None:
        """
        Detach this block and its downstream stack from its current simple-mode
        parent/container before dragging.

        The downstream stack stays attached to this block. If the block was
        inside an ROI, the entire detached sub-stack leaves that ROI so the
        container can shrink correctly.
        """
        parent = self.stack_parent
        container = self.container_parent

        if parent is not None:
            if parent.stack_child is self:
                parent.stack_child = None

            self.stack_parent = None

        # Structural containers own internal roots separately from the
        # ordinary Scratch stack.
        if container is not None:
            detach_root = getattr(container, "detach_internal_root", None)
            if callable(detach_root):
                detach_root(self)
            elif getattr(container, "inner_child", None) is self:
                container.inner_child = None

        # The dragged block and every descendant are no longer container-bound.
        current: CanvasBlock | None = self

        while current is not None:
            current.container_parent = None
            current = current.stack_child

        if container is not None:
            container.update_dynamic_height()

        if parent is not None:
            parent.realign_descendants()

        scene = self.scene()

        if isinstance(
            scene,
            WorkflowScene,
        ):
            scene.request_overview_update()

    def realign_descendants(
        self,
    ) -> None:
        """
        Re-align every block connected below this block in simple mode.

        This belongs on CanvasBlock, not RoiBlock, because ROI resizing calls
        it on ordinary blocks inside and below the ROI as well.
        """
        child = self.stack_child

        if child is None:
            return

        expected = QPointF(
            self.scenePos().x(),
            self.scenePos().y()
            + self.stack_step(),
        )

        child._stack_move_guard = True

        try:
            child.setPos(
                expected
            )
        finally:
            child._stack_move_guard = False

        child.realign_descendants()

    def stack_step(self) -> float:
        return self.HEIGHT

    def scene_stack_top(self) -> QPointF:
        return self.mapToScene(
            QPointF(0, 0)
        )

    def scene_stack_bottom(self) -> QPointF:
        return self.mapToScene(
            QPointF(
                0,
                self.stack_step(),
            )
        )

    def move_stack_by(
        self,
        delta: QPointF,
    ) -> None:
        current = self.stack_child
        descendants: list[
            CanvasBlock
        ] = []

        while current is not None:
            descendants.append(current)
            current = current.stack_child

        for descendant in descendants:
            descendant._stack_move_guard = True

            try:
                descendant.setPos(
                    descendant.pos() + delta
                )
            finally:
                descendant._stack_move_guard = False

    def itemChange(
        self,
        change,
        value,
    ):
        if (
            change
            == QGraphicsItem.ItemPositionChange
        ):
            new_pos = value

            if (
                isinstance(
                    new_pos,
                    QPointF,
                )
                and not self._stack_move_guard
            ):
                delta = new_pos - self.pos()

                if not delta.isNull():
                    self.move_stack_by(delta)

        if (
            change
            == QGraphicsItem.ItemPositionHasChanged
        ):
            scene = self.scene()

            if isinstance(
                scene,
                WorkflowScene,
            ):
                scene.request_overview_update()

                for view in scene.views():
                    view.viewport().update()

        return super().itemChange(
            change,
            value,
        )

    def boundingRect(self) -> QRectF:
        return QRectF(
            -3,
            -3,
            self.block_width + 6,
            self.HEIGHT + 12,
        )

    def shape(self) -> QPainterPath:
        return block_path(
            self.block_width,
            self.HEIGHT,
        )

    def template_box_rect(self) -> QRectF:
        return QRectF(
            190,
            6,
            self.block_width - 327,
            25,
        )

    def template_display_name(self) -> str:
        if not self.selected_template_path:
            return "选择模板"

        name = Path(
            self.selected_template_path
        ).name

        max_chars = 18

        if len(name) > max_chars:
            return name[: max_chars - 1] + "…"

        return name

    def paint(
        self,
        painter: QPainter,
        _option,
        _widget=None,
    ) -> None:
        painter.setRenderHint(
            QPainter.Antialiasing,
            True,
        )

        paint_block(
            painter,
            self.category,
            self.block_width,
            self.HEIGHT,
            selected=self.isSelected(),
        )

        if self.type_warning_message:
            painter.setPen(
                QPen(
                    QColor("#FF4D4F"),
                    3.0,
                )
            )
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(self.shape())
        elif self.condition_warning_message:
            painter.setPen(
                QPen(
                    QColor("#FFD54A"),
                    3.0,
                )
            )
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(self.shape())

        painter.setPen(QColor("#FFFFFF"))
        font = QFont("Segoe UI", 10)
        font.setWeight(QFont.DemiBold)
        painter.setFont(font)

        if self.module_type == "global_anchor_roi":
            painter.drawText(
                QRectF(15,5,92,27),
                Qt.AlignVCenter | Qt.AlignLeft,
                tr_text("仅识别锚点"),
            )
            box=self.global_template_box_rect()
            painter.setPen(QPen(QColor(255,255,255,95),1.0))
            painter.setBrush(QColor(0,0,0,55))
            painter.drawRoundedRect(box,5,5)
            painter.setPen(QColor("#FFFFFF")); painter.setFont(QFont("Segoe UI",9))
            painter.drawText(box.adjusted(8,0,-22,0),Qt.AlignVCenter|Qt.AlignLeft,self.global_template_name())
            painter.drawText(box.adjusted(0,0,-7,0),Qt.AlignVCenter|Qt.AlignRight,"▼")
            painter.setFont(QFont("Segoe UI",10))
            painter.drawText(
                QRectF(358,5,58,27),
                Qt.AlignVCenter|Qt.AlignCenter,
                tr_text("__anchor_roi_join__"),
            )

        elif self.module_type in VISUAL_MODULE_TYPES:
            definition = get_module_definition(
                self.module_type
            )
            visual_label = (
                definition.label
                if definition is not None
                else self.text
            )

            painter.drawText(
                QRectF(
                    15,
                    5,
                    168,
                    27,
                ),
                Qt.AlignVCenter
                | Qt.AlignLeft,
                tr_text(visual_label),
            )

            painter.setPen(
                QColor("#FFFFFF")
            )
            painter.setFont(
                QFont(
                    "Segoe UI",
                    8,
                )
            )
            painter.drawText(
                QRectF(
                    self.block_width - 132,
                    5,
                    58,
                    27,
                ),
                Qt.AlignVCenter
                | Qt.AlignRight,
                tr_text("匹配度"),
            )

        elif self.module_type == "coordinate_modify":
            painter.drawText(
                QRectF(
                    15,
                    5,
                    185,
                    27,
                ),
                Qt.AlignVCenter
                | Qt.AlignLeft,
                tr_text("坐标修改（坐标输出）"),
            )
            painter.drawText(
                QRectF(
                    198,
                    5,
                    20,
                    27,
                ),
                Qt.AlignVCenter
                | Qt.AlignRight,
                "X",
            )
            painter.drawText(
                QRectF(
                    306,
                    5,
                    20,
                    27,
                ),
                Qt.AlignVCenter
                | Qt.AlignRight,
                "Y",
            )
        elif self.module_type == "fixed_coordinate":
            anchor_name = (
                Path(
                    self.fixed_coordinate_anchor_path
                ).name
                if self.fixed_coordinate_anchor_path
                else tr_text("空")
            )
            painter.drawText(
                QRectF(
                    15,
                    5,
                    self.block_width - 30,
                    27,
                ),
                Qt.AlignVCenter
                | Qt.AlignLeft,
                tr_text(
                    (
                        f"固定坐标（坐标输出）  "
                        f"锚点:{anchor_name}  "
                        f"({self.fixed_coordinate_x}, "
                        f"{self.fixed_coordinate_y})"
                    )
                ),
            )
        elif self.module_type == "drag":
            painter.drawText(
                QRectF(15,5,self.block_width-30,27),
                Qt.AlignVCenter|Qt.AlignLeft,
                tr_text(
                    f"拖动  ({self.drag_start_x:.0f},{self.drag_start_y:.0f}) → "
                    f"({self.drag_end_x:.0f},{self.drag_end_y:.0f})"
                ),
            )
        elif self.module_type == "keyboard_input":
            if self.key_text_mode:
                preview = self.key_text.replace(
                    "\n",
                    "↵",
                )
                if len(preview) > 22:
                    preview = preview[:22] + "…"
                label = tr_text(
                    f"键盘输入  文本：{preview}"
                )
            else:
                label = tr_text(
                    (
                        f"键盘输入  "
                        f"{self.key_name}  ×{self.key_count}"
                    )
                )
            painter.drawText(
                QRectF(
                    15,
                    5,
                    self.block_width - 30,
                    27,
                ),
                Qt.AlignVCenter
                | Qt.AlignLeft,
                label,
            )
        elif self.module_type == "clock":
            painter.drawText(
                QRectF(15,5,self.block_width-30,27),
                Qt.AlignVCenter|Qt.AlignLeft,
                tr_text(
                    f"时钟  {self.clock_value:g} {self.clock_unit} → {self.clock_behavior}"
                ),
            )
        elif self.module_type == "launch_exe":
            painter.drawText(QRectF(15,5,80,27),Qt.AlignVCenter|Qt.AlignLeft,tr_text("启动程序"))
        elif self.module_type == "delay_wait":
            painter.drawText(QRectF(15,5,75,27),Qt.AlignVCenter|Qt.AlignLeft,tr_text("延时等待"))
        else:
            painter.drawText(
                QRectF(
                    15,
                    5,
                    self.block_width - 30,
                    27,
                ),
                Qt.AlignVCenter
                | Qt.AlignLeft,
                (
                    self.text
                    if self.module_type == "custom_module_instance"
                    else tr_text(self.text)
                ),
            )

    def mousePressEvent(
        self,
        event,
    ) -> None:
        if event.button() == Qt.LeftButton:
            if (
                self.module_type == "global_anchor_roi"
                and self.global_template_box_rect().contains(
                    event.pos()
                )
            ):
                self.choose_global_anchor_template()
                event.accept()
                return

            if (
                self.module_type in VISUAL_MODULE_TYPES
                and self.template_box_rect().contains(
                    event.pos()
                )
            ):
                self.open_template_menu()
                event.accept()
                return

            self._press_scene_pos = event.scenePos()
            self._moved_during_press = False

            self.setCursor(
                Qt.ClosedHandCursor
            )

        # IMPORTANT:
        # Do not detach here. A plain click / double-click must not change
        # workflow wiring. Actual detachment starts in mouseMoveEvent only
        # after the drag threshold has been crossed.
        super().mousePressEvent(event)


    def mouseMoveEvent(
        self,
        event,
    ) -> None:
        distance = (
            event.scenePos()
            - self._press_scene_pos
        ).manhattanLength()

        if (
            distance > 5
            and not self._moved_during_press
        ):
            self._moved_during_press = True

            # Event roots have no parent edge to detach.
            if self.module_type not in {
                "start",
                "clock_end_start",
            }:
                self.detach_from_parent()

        super().mouseMoveEvent(event)


    def mouseReleaseEvent(
        self,
        event,
    ) -> None:
        self.setCursor(
            Qt.OpenHandCursor
        )

        super().mouseReleaseEvent(event)

        if event.button() != Qt.LeftButton:
            return

        # A click or double-click is not a drag and must never cause
        # accidental magnetic rewiring.
        if not self._moved_during_press:
            return

        scene = self.scene()

        if isinstance(
            scene,
            WorkflowScene,
        ):
            scene.try_snap_stack(
                self
            )



    def mouseDoubleClickEvent(
        self,
        event,
    ) -> None:
        if event.button() == Qt.LeftButton:
            parent = None
            scene = self.scene()

            if scene is not None:
                for view in scene.views():
                    parent = view.window()
                    break

            engine = None
            if settings_key_for(self.module_type) == "global_anchor":
                engine = self._workspace_recognition_engine()

            if open_module_settings_dialog(
                self,
                parent,
                recognition_engine=engine,
            ):
                event.accept()
                return

        super().mouseDoubleClickEvent(
            event
        )





class RoiBlock(CanvasBlock):
    DEFAULT_WIDTH = 620.0
    EMPTY_HEIGHT = 116.0
    HEADER_HEIGHT = 42.0
    FOOTER_HEIGHT = 36.0
    INNER_BOTTOM_PADDING = 8.0
    INNER_X_OFFSET = 26.0

    def __init__(self, category: BlockCategory, text: str) -> None:
        super().__init__(category, "roi", text)
        self.block_width = self.DEFAULT_WIDTH
        self.roi_height = self.EMPTY_HEIGHT
        self.inner_child: CanvasBlock | None = None
        self._moving_contents_guard = False
        self.roi_values_data = (0, 0, 1280, 720)
        self.anchor_template_path: str | None = None
        self.roi_proxies: list[QGraphicsProxyWidget] = []
        self._build_roi_controls()

    def _build_roi_controls(self) -> None:
        # Only fast actions remain on the surface. Coordinate editing and
        # anchor-template creation are kept in the double-click dialog.
        select_button=QPushButton("ROI框选",objectName="secondaryButton")
        select_button.setFixedSize(78,24)
        select_button.clicked.connect(self.select_screen_roi)
        select_proxy=QGraphicsProxyWidget(self)
        select_proxy.setWidget(select_button); select_proxy.setPos(400,8); select_proxy.setZValue(31)

        choose_button=QPushButton("选择锚点",objectName="secondaryButton")
        choose_button.setFixedSize(86,24)
        choose_button.clicked.connect(self.choose_anchor_template)
        choose_proxy=QGraphicsProxyWidget(self)
        choose_proxy.setWidget(choose_button); choose_proxy.setPos(486,8); choose_proxy.setZValue(31)
        self.roi_proxies.extend([select_proxy,choose_proxy])

    def stack_step(self) -> float:
        return self.roi_height

    def boundingRect(self) -> QRectF:
        return QRectF(-4,-4,self.block_width+8,self.roi_height+14)

    def shape(self) -> QPainterPath:
        return roi_frame_path(self.block_width,self.roi_height)

    def inner_root_scene_pos(self) -> QPointF:
        return self.mapToScene(QPointF(self.INNER_X_OFFSET,self.HEADER_HEIGHT))

    def inner_tail(self) -> CanvasBlock | None:
        current=self.inner_child
        if current is None: return None
        seen=set()
        while current.stack_child is not None and id(current) not in seen:
            seen.add(id(current)); current=current.stack_child
        return current

    def internal_chain(self) -> list[CanvasBlock]:
        result=[]; current=self.inner_child; seen=set()
        while current is not None and id(current) not in seen:
            seen.add(id(current)); result.append(current); current=current.stack_child
        return result

    def required_height(self) -> float:
        chain=self.internal_chain()
        if not chain: return self.EMPTY_HEIGHT
        return self.HEADER_HEIGHT + sum(block.stack_step() for block in chain) + self.FOOTER_HEIGHT + self.INNER_BOTTOM_PADDING

    def realign_descendants(self) -> None:
        super().realign_descendants()

    def update_dynamic_height(self) -> None:
        new_height=self.required_height()
        if abs(new_height-self.roi_height)>=0.5:
            self.prepareGeometryChange(); self.roi_height=new_height

        if self.inner_child is not None:
            root=self.inner_child; root._stack_move_guard=True
            try: root.setPos(self.inner_root_scene_pos())
            finally: root._stack_move_guard=False
            root.realign_descendants()

        if self.stack_child is not None:
            child=self.stack_child; child._stack_move_guard=True
            try: child.setPos(QPointF(self.pos().x(),self.pos().y()+self.stack_step()))
            finally: child._stack_move_guard=False
            child.realign_descendants()

        self.update()
        outer=getattr(self,"container_parent",None)
        if outer is not None and outer is not self and hasattr(outer,"update_dynamic_height"):
            outer.update_dynamic_height()

        scene=self.scene()
        if isinstance(scene,WorkflowScene):
            scene.request_overview_update()
            for view in scene.views(): view.viewport().update()

    def attach_inner(self, block: CanvasBlock) -> bool:
        if block is self or block.module_type in EVENT_ROOT_MODULE_TYPES: return False
        block.detach_from_parent()
        tail=self.inner_tail()
        if tail is None:
            self.inner_child=block; block.stack_parent=None; block.container_parent=self
            block.setPos(self.inner_root_scene_pos())
        else:
            if tail.stack_child is not None: return False
            tail.stack_child=block; block.stack_parent=tail; block.container_parent=self
            block.setPos(QPointF(tail.pos().x(),tail.pos().y()+tail.stack_step()))
        current=block
        while current is not None:
            current.container_parent=self; current=current.stack_child
        block.realign_descendants(); self.update_dynamic_height(); return True

    def detach_inner_root(self, block: CanvasBlock) -> None:
        if self.inner_child is block:
            self.inner_child=None
            self.update_dynamic_height()

    def detach_internal_root(self, block: CanvasBlock) -> None:
        self.detach_inner_root(block)

    def roi_values(self) -> tuple[int,int,int,int]:
        x,y,w,h=self.roi_values_data
        return int(x),int(y),max(1,int(w)),max(1,int(h))

    def set_roi_values(self, values: tuple[int,int,int,int]) -> None:
        x,y,w,h=values
        self.roi_values_data=(int(x),int(y),max(1,int(w)),max(1,int(h)))
        self.update()

    def workflow_view(self) -> "WorkflowView | None":
        scene=self.scene()
        if scene is None: return None
        for view in scene.views():
            if isinstance(view,WorkflowView): return view
        return None

    def select_screen_roi(self) -> None:
        view=self.workflow_view()
        if view is None: return
        values=capture_screen_region(view.window())
        if values is None: return
        x,y,w,h=values

        if self.anchor_template_path:
            try:
                engine=self._workspace_recognition_engine()
                if engine is not None:
                    anchor=engine.scan_template(
                        self.anchor_template_path,
                        roi=None,
                        options=TemplateScanOptions(
                            threshold=0.860,
                            methods=("ccoeff_color","grayscale","rgb_count","hsv_count"),
                            scales=(1.0,),
                            confirm_frames=1,
                        ),
                    )
                    if anchor is None: raise RuntimeError("当前屏幕中没有找到所选锚点。")
                    self.set_roi_values((x-anchor.global_x,y-anchor.global_y,w,h)); return

                legacy=find_template_once(self.anchor_template_path,threshold=0.860,roi=None)
                if legacy is None: raise RuntimeError("当前屏幕中没有找到所选锚点。")
                ax,ay,_=legacy
                self.set_roi_values((x-ax,y-ay,w,h)); return
            except Exception as exc:
                QMessageBox.warning(view.window(),"锚点识别失败",str(exc)); return

        self.set_roi_values((x,y,w,h))

    def choose_anchor_template(self) -> None:
        view=self.workflow_view()
        if view is None: return
        selected,_=choose_template_with_search(view.window(),"选择锚点模板",allow_external=False)
        if selected:
            self.anchor_template_path=selected; self.update()

    def paint(self,painter:QPainter,_option,_widget=None) -> None:
        painter.setRenderHint(QPainter.Antialiasing,True)
        paint_roi_frame(painter,self.category,self.block_width,self.roi_height,selected=self.isSelected())
        painter.setPen(QColor("#FFFFFF"))
        font=QFont("Segoe UI",10); font.setWeight(QFont.DemiBold); painter.setFont(font)
        title="ROI" + (" · 锚点" if self.anchor_template_path else "")
        painter.drawText(QRectF(15,5,170,28),Qt.AlignVCenter|Qt.AlignLeft,title)
        x,y,w,h=self.roi_values()
        painter.setPen(QColor(255,255,255,150)); painter.setFont(QFont("Segoe UI",8))
        painter.drawText(QRectF(180,5,205,28),Qt.AlignVCenter|Qt.AlignRight,f"{x},{y} · {w}×{h}")

    def itemChange(self,change,value):
        if change==QGraphicsItem.ItemPositionChange and not self._moving_contents_guard:
            if isinstance(value,QPointF):
                delta=value-self.pos()
                if not delta.isNull():
                    self._moving_contents_guard=True
                    try:
                        for block in self.internal_chain():
                            block._stack_move_guard=True
                            try: block.setPos(block.pos()+delta)
                            finally: block._stack_move_guard=False
                    finally:
                        self._moving_contents_guard=False
        return super().itemChange(change,value)

    def mouseDoubleClickEvent(self,event) -> None:
        if event.button()==Qt.LeftButton:
            parent=None; scene=self.scene()
            if scene is not None:
                for view in scene.views(): parent=view.window(); break
            SimpleRoiSettingsDialog(self,parent).exec(); event.accept(); return
        super().mouseDoubleClickEvent(event)




class LogicContainerBlock(CanvasBlock):
    DEFAULT_WIDTH=620.0
    HEADER_HEIGHT=46.0
    SLOT_LABEL_HEIGHT=22.0
    SLOT_EMPTY_HEIGHT=48.0
    SLOT_GAP=10.0
    FOOTER_HEIGHT=34.0
    INNER_X_OFFSET=26.0



    def __init__(self,category:BlockCategory,module_type:str,text:str)->None:
        super().__init__(category,module_type,text)
        self.block_width=self.DEFAULT_WIDTH
        self.logic_height=150.0
        self.logic_slots = logic_slots_for(
            module_type
        )
        if not self.logic_slots:
            raise ValueError(
                f"Module {module_type!r} is not configured as a logic container."
            )
        self.slot_roots=[None for _ in self.logic_slots]
        self._moving_contents_guard=False
        self._warned_blocks=set()
        self.loop_count=max(1,int(getattr(self,"loop_count",1)))
        self.loop_infinite=bool(getattr(self,"loop_infinite",False))
        self.loop_count_edit=None
        self.loop_count_proxy=None
        if self.module_type=="loop":
            self._build_loop_control()
        self.logic_height=self.required_height()

    def _build_loop_control(self)->None:
        edit=QLineEdit()
        edit.setFixedSize(92,24); edit.setAlignment(Qt.AlignCenter)
        edit.setToolTip("输入正整数，或输入 ∞ / 无限")
        edit.setValidator(QRegularExpressionValidator(QRegularExpression(r"^(?:∞|无限|[1-9]\d{0,7})$"),edit))
        edit.editingFinished.connect(self._commit_loop_control)
        proxy=QGraphicsProxyWidget(self); proxy.setWidget(edit); proxy.setPos(76,9); proxy.setZValue(31)
        self.loop_count_edit=edit; self.loop_count_proxy=proxy; self.sync_loop_control()

    def sync_loop_control(self)->None:
        if self.loop_count_edit is not None:
            self.loop_count_edit.setText("∞" if self.loop_infinite else str(max(1,int(self.loop_count))))

    def _commit_loop_control(self)->None:
        if self.loop_count_edit is None: return
        value=self.loop_count_edit.text().strip()
        if value in {"∞","无限"}:
            self.loop_infinite=True
        else:
            try: count=int(value)
            except ValueError: count=1
            self.loop_infinite=False; self.loop_count=max(1,count)
        self.sync_loop_control(); self.update()

    def stack_step(self)->float:
        return self.logic_height

    def boundingRect(self)->QRectF:
        return QRectF(-4,-4,self.block_width+8,self.logic_height+14)

    def shape(self)->QPainterPath:
        return roi_frame_path(self.block_width,self.logic_height)

    def slot_count(self)->int:
        return len(self.slot_roots)

    def slot_chain(self,slot_index:int)->list[CanvasBlock]:
        if not 0<=slot_index<len(self.slot_roots): return []
        result=[]; current=self.slot_roots[slot_index]; seen=set()
        while current is not None and id(current) not in seen:
            seen.add(id(current)); result.append(current); current=current.stack_child
        return result

    def slot_tail(self,slot_index:int)->CanvasBlock|None:
        chain=self.slot_chain(slot_index)
        return chain[-1] if chain else None

    def all_internal_blocks(self)->list[CanvasBlock]:
        result=[]
        for index in range(self.slot_count()):
            result.extend(self.slot_chain(index))
        return result

    def slot_content_height(self,slot_index:int)->float:
        chain=self.slot_chain(slot_index)
        if not chain: return self.SLOT_EMPTY_HEIGHT
        return max(self.SLOT_EMPTY_HEIGHT,sum(block.stack_step() for block in chain))

    def slot_top(self,slot_index:int)->float:
        y=self.HEADER_HEIGHT
        for index in range(slot_index):
            y += self.SLOT_LABEL_HEIGHT+self.slot_content_height(index)+self.SLOT_GAP
        return y

    def slot_content_rect_local(self,slot_index:int)->QRectF:
        y=self.slot_top(slot_index)+self.SLOT_LABEL_HEIGHT
        return QRectF(self.INNER_X_OFFSET,y,self.block_width-self.INNER_X_OFFSET-18,self.slot_content_height(slot_index))

    def slot_root_scene_pos(self,slot_index:int)->QPointF:
        rect=self.slot_content_rect_local(slot_index)
        return self.mapToScene(QPointF(rect.left(),rect.top()))

    def required_height(self)->float:
        total=self.HEADER_HEIGHT+self.FOOTER_HEIGHT
        for index in range(self.slot_count()):
            total += self.SLOT_LABEL_HEIGHT+self.slot_content_height(index)
            if index<self.slot_count()-1: total += self.SLOT_GAP
        return max(150.0,total)

    def update_dynamic_height(self)->None:
        new_height=self.required_height()
        if abs(new_height-self.logic_height)>=0.5:
            self.prepareGeometryChange(); self.logic_height=new_height
        for index,root in enumerate(self.slot_roots):
            if root is None: continue
            root._stack_move_guard=True
            try: root.setPos(self.slot_root_scene_pos(index))
            finally: root._stack_move_guard=False
            root.realign_descendants()
        if self.stack_child is not None:
            child=self.stack_child; child._stack_move_guard=True
            try: child.setPos(QPointF(self.pos().x(),self.pos().y()+self.stack_step()))
            finally: child._stack_move_guard=False
            child.realign_descendants()
        self.refresh_condition_warnings(); self.update()
        outer=getattr(self,"container_parent",None)
        if outer is not None and outer is not self and hasattr(outer,"update_dynamic_height"):
            outer.update_dynamic_height()
        scene=self.scene()
        if isinstance(scene,WorkflowScene):
            scene.request_overview_update()
            for view in scene.views(): view.viewport().update()

    def attach_to_slot(self,block:CanvasBlock,slot_index:int)->bool:
        if block is self or block.module_type in EVENT_ROOT_MODULE_TYPES or not 0<=slot_index<self.slot_count():
            return False
        block.detach_from_parent()
        tail=self.slot_tail(slot_index)
        if tail is None:
            self.slot_roots[slot_index]=block; block.stack_parent=None; block.container_parent=self
            block.setPos(self.slot_root_scene_pos(slot_index))
        else:
            if tail.stack_child is not None: return False
            tail.stack_child=block; block.stack_parent=tail; block.container_parent=self
            block.setPos(QPointF(tail.pos().x(),tail.pos().y()+tail.stack_step()))
        current=block
        while current is not None:
            current.container_parent=self; current=current.stack_child
        block.realign_descendants(); self.update_dynamic_height(); return True

    def detach_internal_root(self,block:CanvasBlock)->None:
        for index,root in enumerate(self.slot_roots):
            if root is block:
                self.slot_roots[index]=None; break
        self.update_dynamic_height()

    def condition_slot_indices(self)->tuple[int,...]:
        return condition_slots_for(
            self.module_type
        )

    def _nested_blocks(self, block:CanvasBlock):
        yield block

        if isinstance(block,RoiBlock):
            for child in block.internal_chain():
                yield from self._nested_blocks(child)

        elif isinstance(block,LogicContainerBlock):
            for child in block.all_internal_blocks():
                yield from self._nested_blocks(child)

    def refresh_condition_warnings(self)->None:
        for block in tuple(self._warned_blocks):
            block.condition_warning_message=""; block.update()
        self._warned_blocks.clear()

        for slot_index in self.condition_slot_indices():
            for root_block in self.slot_chain(slot_index):
                for block in self._nested_blocks(root_block):
                    if block.module_type in ACTION_MODULE_TYPES:
                        block.condition_warning_message="该动作会在判定时执行，但不直接提供判定值。"
                        self._warned_blocks.add(block)
                        block.update()

    def has_condition_action(self)->bool:
        return bool(self._warned_blocks)

    def itemChange(self,change,value):
        if change==QGraphicsItem.ItemPositionChange and not self._moving_contents_guard and isinstance(value,QPointF):
            delta=value-self.pos()
            if not delta.isNull():
                self._moving_contents_guard=True
                try:
                    for block in self.all_internal_blocks():
                        block._stack_move_guard=True
                        try: block.setPos(block.pos()+delta)
                        finally: block._stack_move_guard=False
                finally:
                    self._moving_contents_guard=False
        return super().itemChange(change,value)

    def paint(self,painter:QPainter,_option,_widget=None)->None:
        painter.setRenderHint(QPainter.Antialiasing,True)
        paint_roi_frame(painter,self.category,self.block_width,self.logic_height,selected=self.isSelected())
        painter.setPen(QColor("#FFFFFF"))
        f=QFont("Segoe UI",10); f.setWeight(QFont.DemiBold); painter.setFont(f)
        definition = get_module_definition(
            self.module_type
        )
        title = tr_text(
            definition.label
            if definition is not None
            else self.text
        )
        painter.drawText(QRectF(15,5,260 if self.module_type!="loop" else 62,30),Qt.AlignVCenter|Qt.AlignLeft,title)
        if self.module_type=="loop" and not self.loop_infinite:
            painter.drawText(
                QRectF(174,5,44,30),
                Qt.AlignVCenter|Qt.AlignLeft,
                tr_text("次"),
            )
        for index,label in enumerate(self.logic_slots):
            top=self.slot_top(index); content=self.slot_content_rect_local(index)
            painter.setPen(QColor(255,255,255,165)); painter.setFont(QFont("Segoe UI",8))
            painter.drawText(
                QRectF(
                    self.INNER_X_OFFSET,
                    top,
                    self.block_width-self.INNER_X_OFFSET-18,
                    self.SLOT_LABEL_HEIGHT,
                ),
                Qt.AlignLeft|Qt.AlignVCenter,
                tr_text(label),
            )
            painter.setPen(QPen(QColor(255,255,255,75),1.0)); painter.setBrush(QColor(16,16,16,155))
            painter.drawRoundedRect(content,6,6)
        if self.has_condition_action():
            painter.setPen(QColor("#FFE45C")); wf=QFont("Segoe UI",8); wf.setWeight(QFont.DemiBold); painter.setFont(wf)
            painter.drawText(
                QRectF(280,5,self.block_width-295,30),
                Qt.AlignRight|Qt.AlignVCenter,
                tr_text("⚠ 判定框含动作：会执行，但不直接参与判定"),
            )

    def mouseDoubleClickEvent(self,event)->None:
        if event.button()==Qt.LeftButton:
            parent=None; scene=self.scene()
            if scene is not None:
                for view in scene.views():
                    parent=view.window(); break
            if open_module_settings_dialog(
                self,
                parent,
            ):
                event.accept(); return
        super().mouseDoubleClickEvent(event)




class WorkflowScene(QGraphicsScene):
    MINOR_GRID = 24
    MAJOR_GRID = 120

    SNAP_X = 92.0
    SNAP_Y = 42.0

    def __init__(
        self,
        parent=None,
    ) -> None:
        super().__init__(parent)

        self.setSceneRect(
            -5000,
            -5000,
            10000,
            10000,
        )

        self._overview_callback = None
        self.theme_name = "dark"

        self._overview_timer = QTimer()
        self._overview_timer.setSingleShot(True)
        self._overview_timer.setInterval(20)
        self._overview_timer.timeout.connect(
            self._emit_overview_update
        )

    def set_overview_callback(
        self,
        callback,
    ) -> None:
        self._overview_callback = callback

    def request_overview_update(self) -> None:
        self._overview_timer.start()

    def _emit_overview_update(self) -> None:
        if self._overview_callback is not None:
            self._overview_callback()

    def add_block(
        self,
        block: CanvasBlock,
        pos: QPointF,
    ) -> None:
        block.setPos(pos)
        self.addItem(block)

        self.clearSelection()
        block.setSelected(True)

        self.request_overview_update()

    def remove_selected_blocks(self) -> None:
        blocks = [
            item
            for item in self.selectedItems()
            if isinstance(
                item,
                CanvasBlock,
            )
            and item.isVisible()
        ]

        if not blocks:
            return

        member_ids: set[str] = set()
        for block in blocks:
            if block.module_type == "custom_module_instance":
                member_ids.update(
                    block.custom_member_ids
                )

        if member_ids:
            blocks.extend(
                item
                for item in self.items()
                if isinstance(item, CanvasBlock)
                and item.node_id in member_ids
                and item not in blocks
            )

        selected = set(blocks)
        affected_rois: set[RoiBlock] = set()

        for block in blocks:
            if block.container_parent is not None:
                affected_rois.add(
                    block.container_parent
                )

            if isinstance(
                block,
                RoiBlock,
            ):
                root = block.inner_child
                if root is not None:
                    current=root
                    while current is not None:
                        current.container_parent=None
                        current=current.stack_child
                    block.inner_child=None

            if isinstance(
                block,
                LogicContainerBlock,
            ):
                for root in block.slot_roots:
                    current=root
                    while current is not None:
                        current.container_parent=None
                        current=current.stack_child
                block.slot_roots=[None for _ in block.slot_roots]

            parent = block.stack_parent
            child = block.stack_child

            if (
                parent is not None
                and parent not in selected
            ):
                parent.stack_child = None

            if (
                child is not None
                and child not in selected
            ):
                child.stack_parent = None

            block.stack_parent = None
            block.stack_child = None

            if block.container_parent is not None:
                container=block.container_parent
                detach_root=getattr(container,"detach_internal_root",None)
                if callable(detach_root):
                    detach_root(block)
                elif getattr(container,"inner_child",None) is block:
                    container.inner_child=None
                block.container_parent=None

        for block in blocks:
            if block.scene() is self:
                self.removeItem(block)

        for roi in affected_rois:
            if roi.scene() is self:
                roi.update_dynamic_height()

        self.request_overview_update()


    def try_snap_stack(
        self,
        moved: CanvasBlock,
    ) -> bool:
        """
        Scratch magnetic snapping.

        Priority:
        1. ROI internal stack connector.
        2. Normal block bottom connector.
        """
        if moved.module_type in {
            "start",
            "clock_end_start",
        }:
            return False

        if moved.stack_parent is not None:
            return False

        moved_rect = moved.sceneBoundingRect()

        moved_chain = {
            moved,
            *moved.descendants(),
        }

        # A corrupted legacy stack must never be allowed to break the whole
        # mouse-release event. descendants() is cycle-safe, so this set is now
        # always finite.

        # -------------------------------------------------------------
        # Logic-container internal slots
        # -------------------------------------------------------------
        best_logic=None
        best_logic_slot=-1
        best_logic_score=float("inf")

        for item in self.items():
            if (
                not isinstance(item,LogicContainerBlock)
                or item is moved
                or not item.isVisible()
            ):
                continue
            for slot_index in range(item.slot_count()):
                tail=item.slot_tail(slot_index)
                target=item.slot_root_scene_pos(slot_index) if tail is None else tail.scene_stack_bottom()
                dx=abs(moved.scene_stack_top().x()-target.x())
                dy=abs(moved.scene_stack_top().y()-target.y())
                cavity=item.mapRectToScene(item.slot_content_rect_local(slot_index)).adjusted(-18,-18,18,18)
                if not cavity.intersects(moved_rect):
                    continue

                # A logic frame is an explicit drop zone: dropping anywhere
                # inside the intended cavity attaches to that branch. X still
                # has a generous guard so a neighbouring frame is not chosen.
                if dx<=110:
                    score=dx+min(dy,30.0)
                    if score<best_logic_score:
                        best_logic_score=score
                        best_logic=item
                        best_logic_slot=slot_index

        if best_logic is not None and best_logic_slot>=0:
            attached=best_logic.attach_to_slot(moved,best_logic_slot)
            self.request_overview_update()
            return attached

        # -------------------------------------------------------------
        # ROI internal snap
        # -------------------------------------------------------------
        best_roi: RoiBlock | None = None
        best_roi_score = float("inf")

        for item in self.items():
            if not isinstance(
                item,
                RoiBlock,
            ):
                continue

            if item is moved or not item.isVisible():
                continue

            tail = item.inner_tail()

            if tail is None:
                # Target is the exact child-origin position whose top notch
                # interlocks with the ROI internal tooth.
                target = item.inner_root_scene_pos()
            else:
                # Once the ROI contains a stack, continuation is ordinary
                # Scratch stacking from the last child's bottom tooth.
                target = tail.scene_stack_bottom()

            dx = abs(
                moved.scene_stack_top().x()
                - target.x()
            )
            dy = abs(
                moved.scene_stack_top().y()
                - target.y()
            )

            roi_body = item.sceneBoundingRect()

            cavity_left = (
                item.scenePos().x()
                + item.INNER_X_OFFSET
                - 28
            )
            cavity_right = (
                item.scenePos().x()
                + item.block_width
                - 12
            )

            moved_center_x = moved_rect.center().x()

            inside_cavity = (
                cavity_left
                <= moved_center_x
                <= cavity_right
            )

            overlaps_roi = (
                roi_body.adjusted(
                    -18,
                    -18,
                    18,
                    18,
                )
                .intersects(moved_rect)
            )

            if (
                overlaps_roi
                and inside_cavity
                and dx <= 72
                and dy <= 34
            ):
                score = dx + dy

                if score < best_roi_score:
                    best_roi_score = score
                    best_roi = item

        if best_roi is not None:
            attached = best_roi.attach_inner(
                moved
            )

            self.request_overview_update()
            return attached

        # -------------------------------------------------------------
        # Normal Scratch snap
        # -------------------------------------------------------------
        top = moved.scene_stack_top()

        best_parent: CanvasBlock | None = None
        best_score = float("inf")

        for item in self.items():
            if not isinstance(
                item,
                CanvasBlock,
            ):
                continue

            if item in moved_chain or not item.isVisible():
                continue

            if isinstance(
                item,
                RoiBlock,
            ):
                # ROI's normal external bottom still works, but its internal
                # connector was already tested above.
                pass

            if item.stack_child is not None:
                continue

            bottom = item.scene_stack_bottom()

            dx = abs(
                top.x() - bottom.x()
            )
            dy = abs(
                top.y() - bottom.y()
            )

            expanded = item.sceneBoundingRect().adjusted(
                -self.SNAP_X,
                -self.SNAP_Y,
                self.SNAP_X,
                self.SNAP_Y,
            )

            if not expanded.intersects(
                moved_rect
            ):
                continue

            if (
                dx <= self.SNAP_X
                and dy <= self.SNAP_Y
            ):
                score = dx + dy

                if score < best_score:
                    best_score = score
                    best_parent = item

        if best_parent is None:
            self.request_overview_update()
            return False

        attached = moved.attach_under(
            best_parent
        )

        self.request_overview_update()
        return attached


    def drawBackground(
        self,
        painter: QPainter,
        rect: QRectF,
    ) -> None:
        light = (
            getattr(
                self,
                "theme_name",
                "dark",
            )
            == "light"
        )
        painter.fillRect(
            rect,
            QColor(
                "#F4F4F4"
                if light
                else "#191919"
            ),
        )

        minor_pen = QPen(
            QColor(
                "#E4E4E4"
                if light
                else "#242424"
            ),
            1,
        )

        major_pen = QPen(
            QColor(
                "#D2D2D2"
                if light
                else "#303030"
            ),
            1,
        )

        left = (
            int(rect.left())
            - (
                int(rect.left())
                % self.MINOR_GRID
            )
        )

        top = (
            int(rect.top())
            - (
                int(rect.top())
                % self.MINOR_GRID
            )
        )

        x = left

        while x <= rect.right():
            painter.setPen(
                major_pen
                if x % self.MAJOR_GRID == 0
                else minor_pen
            )

            painter.drawLine(
                QPointF(
                    x,
                    rect.top(),
                ),
                QPointF(
                    x,
                    rect.bottom(),
                ),
            )

            x += self.MINOR_GRID

        y = top

        while y <= rect.bottom():
            painter.setPen(
                major_pen
                if y % self.MAJOR_GRID == 0
                else minor_pen
            )

            painter.drawLine(
                QPointF(
                    rect.left(),
                    y,
                ),
                QPointF(
                    rect.right(),
                    y,
                ),
            )

            y += self.MINOR_GRID


class WorkflowView(QGraphicsView):
    def __init__(
        self,
        parent=None,
    ) -> None:
        super().__init__(parent)

        self.workflow_scene = WorkflowScene(self)
        self.setScene(
            self.workflow_scene
        )

        self.setAcceptDrops(True)
        self.setFocusPolicy(
            Qt.StrongFocus
        )

        self.setRenderHints(
            QPainter.Antialiasing
            | QPainter.TextAntialiasing
            | QPainter.SmoothPixmapTransform
        )

        self.setTransformationAnchor(
            QGraphicsView.AnchorUnderMouse
        )

        self.setResizeAnchor(
            QGraphicsView.AnchorViewCenter
        )

        self.setHorizontalScrollBarPolicy(
            Qt.ScrollBarAlwaysOff
        )

        self.setVerticalScrollBarPolicy(
            Qt.ScrollBarAlwaysOff
        )

        self.setFrameShape(
            QFrame.NoFrame
        )

        # Complex antialiased puzzle silhouettes can otherwise leave stale
        # pixels while being dragged. Full viewport redraw is deliberate here:
        # the workspace currently contains relatively few items and visual
        # correctness is more important than micro-optimizing repaint regions.
        self.setViewportUpdateMode(
            QGraphicsView.FullViewportUpdate
        )
        self.setCacheMode(
            QGraphicsView.CacheNone
        )

        # Scratch-like canvas selection:
        # drag on empty space to select multiple blocks.
        self.setDragMode(
            QGraphicsView.RubberBandDrag
        )

        self.setRubberBandSelectionMode(
            Qt.IntersectsItemShape
        )

        self._zoom = 1.0
        self._panning = False
        self._space_pressed = False
        self._pan_start = QPoint()
        self.on_module_dropped = None
        self.on_custom_module_dropped = None

    def keyPressEvent(
        self,
        event: QKeyEvent,
    ) -> None:
        if event.key() in (
            Qt.Key_Delete,
            Qt.Key_Backspace,
        ):
            self.workflow_scene.remove_selected_blocks()
            event.accept()
            return

        if (
            event.key() == Qt.Key_Space
            and not event.isAutoRepeat()
        ):
            self._space_pressed = True
            self.setCursor(
                Qt.OpenHandCursor
            )
            event.accept()
            return

        super().keyPressEvent(event)

    def keyReleaseEvent(
        self,
        event,
    ) -> None:
        if (
            event.key() == Qt.Key_Space
            and not event.isAutoRepeat()
        ):
            self._space_pressed = False

            if not self._panning:
                self.unsetCursor()

            event.accept()
            return

        super().keyReleaseEvent(event)

    def wheelEvent(
        self,
        event: QWheelEvent,
    ) -> None:
        delta = event.angleDelta().y()

        if delta == 0:
            return

        factor = (
            1.12
            if delta > 0
            else 1 / 1.12
        )

        target_zoom = (
            self._zoom * factor
        )

        if not (
            0.25
            <= target_zoom
            <= 4.0
        ):
            return

        self.scale(
            factor,
            factor,
        )

        self._zoom = target_zoom

    def mousePressEvent(
        self,
        event: QMouseEvent,
    ) -> None:
        should_pan = (
            event.button()
            == Qt.MiddleButton
            or (
                event.button()
                == Qt.LeftButton
                and self._space_pressed
            )
        )

        if should_pan:
            self._panning = True

            self._pan_start = (
                event.position().toPoint()
            )

            self.setCursor(
                Qt.ClosedHandCursor
            )

            event.accept()
            return

        super().mousePressEvent(event)

    def mouseMoveEvent(
        self,
        event: QMouseEvent,
    ) -> None:
        if self._panning:
            current = (
                event.position().toPoint()
            )

            delta = (
                current
                - self._pan_start
            )

            self._pan_start = current

            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value()
                - delta.x()
            )

            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value()
                - delta.y()
            )

            event.accept()
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(
        self,
        event: QMouseEvent,
    ) -> None:
        if (
            self._panning
            and event.button()
            in (
                Qt.MiddleButton,
                Qt.LeftButton,
            )
        ):
            self._panning = False

            if self._space_pressed:
                self.setCursor(
                    Qt.OpenHandCursor
                )
            else:
                self.unsetCursor()

            event.accept()
            return

        super().mouseReleaseEvent(event)

    def dragEnterEvent(
        self,
        event,
    ) -> None:
        if event.mimeData().hasFormat(
            MIME_BLOCK
        ):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(
        self,
        event,
    ) -> None:
        if event.mimeData().hasFormat(
            MIME_BLOCK
        ):
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(
        self,
        event,
    ) -> None:
        if not event.mimeData().hasFormat(
            MIME_BLOCK
        ):
            super().dropEvent(event)
            return

        payload = bytes(
            event.mimeData().data(
                MIME_BLOCK
            )
        ).decode("utf-8")

        parts = payload.split("\n", 3)
        if len(parts) < 3:
            return
        category_key, module_type, block_text = parts[:3]
        payload_extra = parts[3] if len(parts) > 3 else ""

        category = category_by_key(category_key)

        scene_pos = self.mapToScene(
            event.position().toPoint()
        )

        if module_type == "custom_module":
            if callable(
                self.on_custom_module_dropped
            ):
                self.on_custom_module_dropped(
                    payload_extra,
                    scene_pos,
                    "simple",
                )

            event.acceptProposedAction()
            self.setFocus()
            return

        if module_type == "roi":
            block = RoiBlock(
                category,
                block_text,
            )
        elif module_type in LOGIC_CONTAINER_TYPES:
            block = LogicContainerBlock(
                category,
                module_type,
                block_text,
            )
        else:
            block = CanvasBlock(
                category,
                module_type,
                block_text,
            )

        self.workflow_scene.add_block(
            block,
            scene_pos,
        )

        self.workflow_scene.try_snap_stack(
            block
        )

        if callable(self.on_module_dropped):
            self.on_module_dropped(
                block,
                payload_extra,
            )

        event.acceptProposedAction()
        self.setFocus()

    def reset_view(self) -> None:
        self.resetTransform()
        self._zoom = 1.0
        self.centerOn(
            0,
            0,
        )


class DelayedToolButton(QToolButton):
    """Icon-only toolbar button with an exact 1-second hover hint."""

    def __init__(
        self,
        hint: str,
        parent=None,
    ) -> None:
        super().__init__(parent)

        self.hint = hint
        self._hover_timer = QTimer(self)
        self._hover_timer.setSingleShot(True)
        self._hover_timer.setInterval(1000)
        self._hover_timer.timeout.connect(
            self._show_hint
        )

    def enterEvent(self, event) -> None:
        self._hover_timer.start()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover_timer.stop()
        QToolTip.hideText()
        super().leaveEvent(event)

    def _show_hint(self) -> None:
        QToolTip.showText(
            self.mapToGlobal(
                self.rect().bottomLeft()
            ),
            self.hint,
            self,
        )


def quick_template_icon() -> QIcon:
    pixmap = QPixmap(
        28,
        28,
    )
    pixmap.fill(Qt.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(
        QPainter.Antialiasing,
        True,
    )

    pen = QPen(
        QColor("#E7E7E7"),
        1.6,
    )
    pen.setStyle(
        Qt.DashLine
    )
    painter.setPen(pen)
    painter.setBrush(
        QColor(255, 255, 255, 18)
    )
    painter.drawRoundedRect(
        QRectF(4, 5, 18, 16),
        3,
        3,
    )

    painter.setPen(
        QPen(
            QColor("#E7E7E7"),
            1.8,
        )
    )
    painter.drawLine(
        QPointF(18, 4),
        QPointF(18, 11),
    )
    painter.drawLine(
        QPointF(14.5, 7.5),
        QPointF(21.5, 7.5),
    )

    painter.end()
    return QIcon(pixmap)





def recognition_view_icon() -> QIcon:
    """Small eye/crosshair icon for the Recognition Engine viewport."""
    pixmap = QPixmap(
        28,
        28,
    )
    pixmap.fill(
        Qt.transparent
    )

    painter = QPainter(
        pixmap
    )
    painter.setRenderHint(
        QPainter.Antialiasing,
        True,
    )

    pen = QPen(
        QColor("#E7E7E7"),
        1.6,
    )
    painter.setPen(
        pen
    )
    painter.setBrush(
        Qt.NoBrush
    )

    eye_path = QPainterPath()
    eye_path.moveTo(
        3.5,
        14,
    )
    eye_path.cubicTo(
        8,
        7,
        20,
        7,
        24.5,
        14,
    )
    eye_path.cubicTo(
        20,
        21,
        8,
        21,
        3.5,
        14,
    )
    painter.drawPath(
        eye_path
    )

    painter.drawEllipse(
        QPointF(
            14,
            14,
        ),
        3.2,
        3.2,
    )

    # Crosshair accents communicate "machine vision" rather than a generic
    # visibility toggle.
    painter.drawLine(
        QPointF(14, 4),
        QPointF(14, 8),
    )
    painter.drawLine(
        QPointF(14, 20),
        QPointF(14, 24),
    )
    painter.drawLine(
        QPointF(4, 14),
        QPointF(8, 14),
    )
    painter.drawLine(
        QPointF(20, 14),
        QPointF(24, 14),
    )

    painter.end()
    return QIcon(
        pixmap
    )


class ComplexConnection(QGraphicsPathItem):
    """Permanent cubic wire. Right-click removes the connection."""

    def __init__(
        self,
        source: "ComplexNode",
        source_port: str,
        target: "ComplexNode",
        target_port: str,
    ) -> None:
        super().__init__()

        self.source = source
        self.source_port = source_port
        self.target = target
        self.target_port = target_port

        is_internal = (
            "inner" in str(source_port)
            or "inner" in str(target_port)
        )

        self.setZValue(
            18
            if is_internal
            else -20
        )
        self.setAcceptedMouseButtons(
            Qt.RightButton
        )

        pen = QPen(
            QColor(185, 185, 185, 195),
            2.0,
        )
        pen.setCapStyle(Qt.RoundCap)
        self.setPen(pen)

        self.update_path()

    def update_path(self) -> None:
        start = self.source.port_scene_pos(
            self.source_port
        )
        end = self.target.port_scene_pos(
            self.target_port
        )

        dx = max(
            45.0,
            abs(end.x() - start.x()) * 0.42,
        )

        path = QPainterPath(start)
        path.cubicTo(
            QPointF(
                start.x() + dx,
                start.y(),
            ),
            QPointF(
                end.x() - dx,
                end.y(),
            ),
            end,
        )
        self.setPath(path)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.RightButton:
            scene = self.scene()

            if isinstance(
                scene,
                ComplexScene,
            ):
                scene.remove_connection(self)

            event.accept()
            return

        super().mousePressEvent(event)


class ComplexPreviewConnection(QGraphicsPathItem):
    """Dashed wire that follows the cursor after the first port is chosen."""

    def __init__(self) -> None:
        super().__init__()

        self.setZValue(-10)
        self.setAcceptedMouseButtons(
            Qt.NoButton
        )

        pen = QPen(
            QColor(235, 235, 235, 180),
            1.8,
        )
        pen.setStyle(Qt.DashLine)
        pen.setCapStyle(Qt.RoundCap)
        self.setPen(pen)

    def update_path(
        self,
        start: QPointF,
        end: QPointF,
        first_is_output: bool,
    ) -> None:
        direction = 1.0 if first_is_output else -1.0

        dx = max(
            45.0,
            abs(end.x() - start.x()) * 0.42,
        )

        path = QPainterPath(start)
        path.cubicTo(
            QPointF(
                start.x() + dx * direction,
                start.y(),
            ),
            QPointF(
                end.x() - dx * direction,
                end.y(),
            ),
            end,
        )
        self.setPath(path)


class ComplexNode(QGraphicsItem):
    WIDTH = 170.0
    HEIGHT = 64.0

    ROI_MIN_WIDTH = 320.0
    ROI_MIN_HEIGHT = 190.0
    ROI_MARGIN_X = 44.0
    ROI_MARGIN_Y = 42.0
    ROI_HEADER = 56.0

    PORT_RADIUS = 6.0

    def __init__(
        self,
        category: BlockCategory,
        module_type: str,
        text: str,
    ) -> None:
        super().__init__()

        self.node_id = uuid.uuid4().hex
        self.category = category
        self.module_type = module_type
        self.text = text
        self.custom_member_ids: list[str] = []
        self.custom_source_path: str = ""
        self._custom_hidden = False

        self.selected_template_path: str | None = None
        self.match_threshold = 0.860
        self.recognition_methods = tuple(DEFAULT_METHODS)
        self.multi_scale = True
        self.confirm_frames = 1
        self.feature_detector = "SIFT"
        self.wait_for_match = True
        self.wait_timeout_ms = 1000
        self.global_anchor_template_path: str | None = None
        self.global_anchor_roi = (0, 0, 1280, 720)

        self.move_advanced = False
        self.move_offset_up = 0.0
        self.move_offset_down = 0.0
        self.move_offset_left = 0.0
        self.move_offset_right = 0.0
        self.move_speed_mode = "duration"
        self.move_speed_value = 0.0
        self.move_speed_variance = 0.0
        self.move_random_route = False

        self.click_count = 1
        self.click_advanced = False
        self.click_press_duration = 0.025
        self.click_interval = 0.100
        self.drag_start_x=0.0; self.drag_start_y=0.0; self.drag_end_x=0.0; self.drag_end_y=0.0; self.drag_press_duration=0.025
        self.key_name="SPACE"; self.key_mode="press"; self.key_count=1; self.key_interval=0.0; self.key_hold_duration=0.5
        self.key_advanced=False; self.key_duration_variance=0.0; self.key_interval_variance=0.0; self.key_humanized=False
        self.key_text_mode=False; self.key_text=""
        self.executable_path=""; self.delay_value=1.0; self.delay_unit="seconds"; self.clock_value=60.0; self.clock_unit="seconds"; self.clock_behavior="stop"
        self.clock_event_slot=0; self.clock_event_claimed=False

        self.fixed_coordinate_x=0
        self.fixed_coordinate_y=0
        self.fixed_coordinate_anchor_path: str | None = None

        self.coordinate_modify_x=0
        self.coordinate_modify_y=0

        self.loop_count=1
        self.loop_infinite=False

        self.type_warning_message = ""
        self.condition_warning_message = ""

        self.roi_values_data = (
            0,
            0,
            1280,
            720,
        )
        self.anchor_template_path: str | None = None

        # Complex-mode ports are owned by the module definition.  Adding a
        # module no longer requires another port-count branch in WorkspacePage.
        (
            self.input_ports,
            self.output_ports,
        ) = complex_ports_for(
            module_type
        )

        self.incoming: dict[
            str,
            ComplexConnection,
        ] = {}
        self.outgoing: dict[
            str,
            ComplexConnection,
        ] = {}

        self.roi_width = self.ROI_MIN_WIDTH
        self.roi_height = self.ROI_MIN_HEIGHT

        self._updating_roi_geometry = False

        self.setFlags(
            QGraphicsItem.ItemIsMovable
            | QGraphicsItem.ItemIsSelectable
            | QGraphicsItem.ItemSendsGeometryChanges
        )
        self.setCursor(
            Qt.OpenHandCursor
        )
        self.setZValue(
            -5
            if self.module_type == "roi"
            else 10
        )

    # --------------------------------------------------------------
    # Geometry
    # --------------------------------------------------------------
    def node_width(self) -> float:
        if self.module_type == "roi":
            return self.roi_width
        return self.WIDTH

    def node_height(self) -> float:
        if self.module_type == "roi":
            return self.roi_height
        return self.HEIGHT

    def boundingRect(self) -> QRectF:
        return QRectF(
            -14,
            -6,
            self.node_width() + 28,
            self.node_height() + 12,
        )

    def roi_inner_rect_local(self) -> QRectF:
        return QRectF(
            self.ROI_MARGIN_X,
            self.ROI_HEADER,
            self.node_width()
            - self.ROI_MARGIN_X * 2,
            self.node_height()
            - self.ROI_HEADER
            - self.ROI_MARGIN_Y,
        )

    def roi_inner_rect_scene(self) -> QRectF:
        local = self.roi_inner_rect_local()
        top_left = self.mapToScene(
            local.topLeft()
        )
        bottom_right = self.mapToScene(
            local.bottomRight()
        )
        return QRectF(
            top_left,
            bottom_right,
        ).normalized()

    # --------------------------------------------------------------
    # Port geometry
    # --------------------------------------------------------------
    def port_kind(
        self,
        port_name: str,
    ) -> str:
        return (
            "input"
            if port_name in self.input_ports
            else "output"
        )

    def port_local_pos(
        self,
        port_name: str,
    ) -> QPointF:
        w = self.node_width()
        h = self.node_height()

        if self.module_type != "roi":
            if port_name in self.input_ports:
                index=self.input_ports.index(port_name)+1
                return QPointF(0,h*index/(len(self.input_ports)+1))
            if port_name in self.output_ports:
                index=self.output_ports.index(port_name)+1
                return QPointF(w,h*index/(len(self.output_ports)+1))
            return QPointF(w,h/2.0)

        # ROI external dataflow ports occupy the header.
        external_index = {
            "input": 1,
            "input_2": 2,
            "input_3": 3,
            "output": 1,
            "output_2": 2,
            "output_3": 3,
        }.get(
            port_name
        )

        if external_index is not None:
            y = (
                external_index
                * 14.0
            )

            if port_name in self.input_ports:
                return QPointF(
                    0,
                    y,
                )

            return QPointF(
                w,
                y,
            )

        inner = self.roi_inner_rect_local()

        # Internal output enters the decorated chain from the left.
        if port_name == "inner_output":
            return QPointF(
                inner.left(),
                inner.center().y(),
            )

        # Internal input receives the decorated chain on the right.
        if port_name == "inner_input":
            return QPointF(
                inner.right(),
                inner.center().y(),
            )

        return QPointF()

    def port_scene_pos(
        self,
        port_name: str,
    ) -> QPointF:
        return self.mapToScene(
            self.port_local_pos(
                port_name
            )
        )

    def port_at(
        self,
        local_pos: QPointF,
    ) -> str | None:
        for port_name in (
            self.input_ports
            + self.output_ports
        ):
            p = self.port_local_pos(
                port_name
            )

            delta = local_pos - p

            if (
                abs(delta.x()) <= 8
                and abs(delta.y()) <= 8
            ):
                return port_name

        return None

    def port_available(
        self,
        port_name: str,
    ) -> bool:
        if self.port_kind(
            port_name
        ) == "input":
            return (
                port_name
                not in self.incoming
            )

        return (
            port_name
            not in self.outgoing
        )

    # --------------------------------------------------------------
    # Drawing
    # --------------------------------------------------------------
    def paint(
        self,
        painter: QPainter,
        _option,
        _widget=None,
    ) -> None:
        painter.setRenderHint(
            QPainter.Antialiasing,
            True,
        )

        base = QColor(
            self.category.color
        )

        painter.setPen(
            QPen(
                (
                    QColor("#FF4D4F")
                    if self.type_warning_message
                    else QColor("#FFD54A")
                )
                if (
                    self.type_warning_message
                    or self.condition_warning_message
                )
                else (
                    QColor("#F4F4F4")
                    if self.isSelected()
                    else base.darker(150)
                ),
                3.0
                if self.type_warning_message
                else (
                    2.0
                    if self.isSelected()
                    else 1.0
                ),
            )
        )
        painter.setBrush(base)

        painter.drawRoundedRect(
            QRectF(
                0,
                0,
                self.node_width(),
                self.node_height(),
            ),
            7,
            7,
        )

        painter.setPen(
            QColor("#FFFFFF")
        )

        font = QFont(
            "Segoe UI",
            10,
        )
        font.setWeight(
            QFont.DemiBold
        )
        painter.setFont(font)

        definition = get_module_definition(
            self.module_type
        )
        module_label = (
            definition.label
            if definition is not None
            else self.text
        )
        label = (
            self.text
            if self.module_type == "custom_module_instance"
            else tr_text(module_label)
        )

        painter.drawText(
            QRectF(
                14,
                8,
                self.node_width() - 28,
                26,
            ),
            Qt.AlignLeft
            | Qt.AlignVCenter,
            label,
        )

        if self.module_type == "loop":
            painter.setPen(QColor(255,255,255,160))
            painter.setFont(QFont("Segoe UI",8))
            painter.drawText(
                QRectF(14,35,self.node_width()-28,22),
                Qt.AlignLeft|Qt.AlignVCenter,
                tr_text(
                    "循环次数：∞"
                    if self.loop_infinite
                    else f"循环次数：{self.loop_count}"
                ),
            )

        if self.module_type == "coordinate_modify":
            painter.setPen(
                QColor(
                    255,
                    255,
                    255,
                    160,
                )
            )
            painter.setFont(
                QFont(
                    "Segoe UI",
                    8,
                )
            )
            painter.drawText(
                QRectF(
                    14,
                    35,
                    self.node_width() - 28,
                    22,
                ),
                Qt.AlignLeft
                | Qt.AlignVCenter,
                (
                    f"X={self.coordinate_modify_x:+d} · "
                    f"Y={self.coordinate_modify_y:+d}"
                ),
            )

        if self.module_type == "fixed_coordinate":
            painter.setPen(
                QColor(
                    255,
                    255,
                    255,
                    160,
                )
            )
            painter.setFont(
                QFont(
                    "Segoe UI",
                    8,
                )
            )
            anchor_name = (
                Path(
                    self.fixed_coordinate_anchor_path
                ).name
                if self.fixed_coordinate_anchor_path
                else tr_text("空")
            )
            painter.drawText(
                QRectF(
                    14,
                    35,
                    self.node_width() - 28,
                    22,
                ),
                Qt.AlignLeft
                | Qt.AlignVCenter,
                tr_text(
                    (
                        f"锚点:{anchor_name} · "
                        f"{self.fixed_coordinate_x},"
                        f"{self.fixed_coordinate_y}"
                    )
                ),
            )

        if self.module_type == "global_anchor_roi":
            painter.setPen(QColor(255,255,255,150))
            painter.setFont(QFont("Segoe UI",8))
            template_name=(Path(self.global_anchor_template_path).name if self.global_anchor_template_path else "未选择锚点")
            x,y,w,h=self.global_anchor_roi
            painter.drawText(QRectF(14,35,self.node_width()-28,22),Qt.AlignLeft|Qt.AlignVCenter,f"{template_name} · {x},{y},{w}×{h}")

        if self.module_type == "roi":
            inner = self.roi_inner_rect_local()

            painter.setPen(
                QPen(
                    QColor(
                        255,
                        255,
                        255,
                        85,
                    ),
                    1.0,
                )
            )
            painter.setBrush(
                QColor(
                    15,
                    15,
                    15,
                    70,
                )
            )
            painter.drawRoundedRect(
                inner,
                6,
                6,
            )

            painter.setPen(
                QColor(
                    255,
                    255,
                    255,
                    150,
                )
            )
            painter.setFont(
                QFont(
                    "Segoe UI",
                    8,
                )
            )
            painter.drawText(
                QRectF(
                    14,
                    28,
                    self.node_width() - 28,
                    16,
                ),
                Qt.AlignLeft
                | Qt.AlignVCenter,
                (
                    f"ROI {self.roi_values_data[0]}, "
                    f"{self.roi_values_data[1]}, "
                    f"{self.roi_values_data[2]}×"
                    f"{self.roi_values_data[3]}"
                ),
            )

        # Ports.
        for port_name in (
            self.input_ports
            + self.output_ports
        ):
            point = self.port_local_pos(
                port_name
            )

            scene = self.scene()
            pending = False

            if isinstance(
                scene,
                ComplexScene,
            ):
                pending = (
                    scene.pending_port is not None
                    and scene.pending_port[0] is self
                    and scene.pending_port[1] == port_name
                )

            if pending:
                painter.setPen(
                    QPen(
                        QColor("#FFFFFF"),
                        2.5,
                    )
                )
                painter.setBrush(
                    QColor("#F4F4F4")
                )
            elif not self.port_available(
                port_name
            ):
                painter.setPen(
                    QPen(
                        QColor("#FFFFFF"),
                        1.5,
                    )
                )
                painter.setBrush(
                    QColor("#626262")
                )
            else:
                painter.setPen(
                    QPen(
                        QColor("#D8D8D8"),
                        1.5,
                    )
                )
                painter.setBrush(
                    QColor("#181818")
                )

            painter.drawEllipse(
                point,
                self.PORT_RADIUS,
                self.PORT_RADIUS,
            )

    # --------------------------------------------------------------
    # ROI container membership / auto-size
    # --------------------------------------------------------------
    def roi_internal_connections(
        self,
    ) -> tuple[
        ComplexConnection | None,
        ComplexConnection | None,
    ]:
        if self.module_type != "roi":
            return (
                None,
                None,
            )

        return (
            self.outgoing.get(
                "inner_output"
            ),
            self.incoming.get(
                "inner_input"
            ),
        )

    def roi_internal_nodes(
        self,
    ) -> list["ComplexNode"]:
        """
        Return every node participating in this ROI's internal chain.

        Membership can be established from either side:
        - ROI.inner_output -> ... forward chain
        - ... -> ROI.inner_input backward chain

        This matters while users are still building the chain. A node wired
        directly into inner_input must already be treated as internal even if
        inner_output has not been connected yet.
        """
        if self.module_type != "roi":
            return []

        ordered: list[
            ComplexNode
        ] = []
        seen: set[str] = set()

        def append_node(
            node: ComplexNode,
        ) -> None:
            if (
                node is self
                or node.node_id in seen
            ):
                return

            seen.add(
                node.node_id
            )
            ordered.append(
                node
            )

        # ----------------------------------------------------------
        # Forward walk from inner_output.
        # ----------------------------------------------------------
        start_connection = self.outgoing.get(
            "inner_output"
        )

        if start_connection is not None:
            current = (
                start_connection.target
            )
            forward_guard: set[str] = set()

            while (
                current is not None
                and current is not self
                and current.node_id
                not in forward_guard
            ):
                forward_guard.add(
                    current.node_id
                )
                append_node(
                    current
                )

                closes_roi = any(
                    connection.target is self
                    and connection.target_port
                    == "inner_input"
                    for connection
                    in current.outgoing.values()
                )

                if closes_roi:
                    break

                next_connection = (
                    current.outgoing.get(
                        "output"
                    )
                )

                if next_connection is None:
                    # During construction the user may use output_2/output_3.
                    next_connection = next(
                        iter(
                            current.outgoing.values()
                        ),
                        None,
                    )

                if next_connection is None:
                    break

                current = (
                    next_connection.target
                )

        # ----------------------------------------------------------
        # Backward walk from inner_input.
        # ----------------------------------------------------------
        end_connection = self.incoming.get(
            "inner_input"
        )

        if end_connection is not None:
            reverse_nodes: list[
                ComplexNode
            ] = []
            current = (
                end_connection.source
            )
            backward_guard: set[str] = set()

            while (
                current is not None
                and current is not self
                and current.node_id
                not in backward_guard
            ):
                backward_guard.add(
                    current.node_id
                )
                reverse_nodes.append(
                    current
                )

                previous_connection = (
                    current.incoming.get(
                        "input"
                    )
                )

                if previous_connection is None:
                    previous_connection = next(
                        iter(
                            current.incoming.values()
                        ),
                        None,
                    )

                if previous_connection is None:
                    break

                if (
                    previous_connection.source
                    is self
                    and previous_connection.source_port
                    == "inner_output"
                ):
                    break

                current = (
                    previous_connection.source
                )

            # Put upstream nodes before downstream nodes when they were not
            # already discovered by the forward walk.
            for node in reversed(
                reverse_nodes
            ):
                append_node(
                    node
                )

        return ordered

    def update_roi_bounds(
        self,
    ) -> None:
        if (
            self.module_type != "roi"
            or self._updating_roi_geometry
        ):
            return

        self._updating_roi_geometry = True

        try:
            nodes = self.roi_internal_nodes()

            if not nodes:
                new_w = self.ROI_MIN_WIDTH
                new_h = self.ROI_MIN_HEIGHT
            else:
                # Internal nodes are scene siblings rather than QGraphicsItem
                # children. Map every scene rect into ROI-local coordinates.
                local_rects: list[QRectF] = []

                for node in nodes:
                    scene_rect = (
                        node.sceneBoundingRect()
                    )

                    top_left = self.mapFromScene(
                        scene_rect.topLeft()
                    )
                    bottom_right = self.mapFromScene(
                        scene_rect.bottomRight()
                    )

                    local_rects.append(
                        QRectF(
                            top_left,
                            bottom_right,
                        ).normalized()
                    )

                # If a legacy/project-loaded node currently lives above/left
                # of the cavity, move the whole internal group INSIDE once,
                # while the recursion guard is already active.
                min_left = min(
                    rect.left()
                    for rect in local_rects
                )
                min_top = min(
                    rect.top()
                    for rect in local_rects
                )

                desired_left = (
                    self.ROI_MARGIN_X
                )
                desired_top = (
                    self.ROI_HEADER
                    + self.ROI_MARGIN_Y
                )

                shift_x = max(
                    0.0,
                    desired_left
                    - min_left,
                )
                shift_y = max(
                    0.0,
                    desired_top
                    - min_top,
                )

                if (
                    shift_x > 0.0
                    or shift_y > 0.0
                ):
                    for node in nodes:
                        node.setPos(
                            node.pos()
                            + QPointF(
                                shift_x,
                                shift_y,
                            )
                        )

                    # Recalculate after the single corrective translation.
                    local_rects = []

                    for node in nodes:
                        scene_rect = (
                            node.sceneBoundingRect()
                        )
                        local_rects.append(
                            QRectF(
                                self.mapFromScene(
                                    scene_rect.topLeft()
                                ),
                                self.mapFromScene(
                                    scene_rect.bottomRight()
                                ),
                            ).normalized()
                        )

                local_bounds = local_rects[0]

                for rect in local_rects[1:]:
                    local_bounds = (
                        local_bounds.united(
                            rect
                        )
                    )

                new_w = max(
                    self.ROI_MIN_WIDTH,
                    local_bounds.right()
                    + self.ROI_MARGIN_X,
                )
                new_h = max(
                    self.ROI_MIN_HEIGHT,
                    local_bounds.bottom()
                    + self.ROI_MARGIN_Y,
                )

                # Corrupt coordinates should never be allowed to grow a
                # container without bound. The scene itself is 10000x10000.
                new_w = min(
                    new_w,
                    9000.0,
                )
                new_h = min(
                    new_h,
                    9000.0,
                )

            if (
                abs(
                    new_w
                    - self.roi_width
                ) < 0.5
                and abs(
                    new_h
                    - self.roi_height
                ) < 0.5
            ):
                return

            self.prepareGeometryChange()
            self.roi_width = new_w
            self.roi_height = new_h
            self.update()

            for connection in set(
                list(
                    self.incoming.values()
                )
                + list(
                    self.outgoing.values()
                )
            ):
                connection.update_path()

            # Internal-node wires are not necessarily stored on the ROI itself.
            for node in nodes:
                for connection in set(
                    list(
                        node.incoming.values()
                    )
                    + list(
                        node.outgoing.values()
                    )
                ):
                    connection.update_path()

        finally:
            self._updating_roi_geometry = False

    # --------------------------------------------------------------
    # Interaction
    # --------------------------------------------------------------
    def itemChange(
        self,
        change,
        value,
    ):
        if (
            change
            == QGraphicsItem.ItemPositionHasChanged
        ):
            for connection in (
                list(
                    self.incoming.values()
                )
                + list(
                    self.outgoing.values()
                )
            ):
                connection.update_path()

            scene = self.scene()

            if isinstance(
                scene,
                ComplexScene,
            ):
                scene.update_all_roi_bounds()

        return super().itemChange(
            change,
            value,
        )

    def mousePressEvent(
        self,
        event,
    ) -> None:
        port_name = self.port_at(
            event.pos()
        )

        if (
            event.button() == Qt.RightButton
            and port_name is not None
        ):
            scene = self.scene()

            if isinstance(
                scene,
                ComplexScene,
            ):
                # Right-click a connected INPUT port to remove its wire.
                if (
                    self.port_kind(
                        port_name
                    ) == "input"
                    and port_name
                    in self.incoming
                ):
                    scene.remove_connection(
                        self.incoming[
                            port_name
                        ]
                    )
                    event.accept()
                    return

        if event.button() == Qt.LeftButton:
            if port_name is not None:
                scene = self.scene()

                if isinstance(
                    scene,
                    ComplexScene,
                ):
                    scene.handle_port_click(
                        self,
                        port_name,
                    )

                event.accept()
                return

        super().mousePressEvent(event)

    def mouseDoubleClickEvent(
        self,
        event,
    ) -> None:
        if event.button() == Qt.LeftButton:
            scene = self.scene()

            if isinstance(
                scene,
                ComplexScene,
            ):
                view = scene.primary_view()

                if view is not None:
                    engine = None
                    if settings_key_for(self.module_type) == "global_anchor":
                        page = view
                        while page is not None:
                            engine = getattr(
                                page,
                                "recognition_engine",
                                None,
                            )
                            if engine is not None:
                                break
                            page = page.parent()

                    if open_module_settings_dialog(
                        self,
                        view.window(),
                        recognition_engine=engine,
                        complex_view=view,
                    ):
                        event.accept()
                        return

        super().mouseDoubleClickEvent(
            event
        )


class ComplexScene(QGraphicsScene):
    def __init__(
        self,
        parent=None,
    ) -> None:
        super().__init__(parent)

        self.setSceneRect(
            -5000,
            -5000,
            10000,
            10000,
        )

        self.theme_name = "dark"

        # (node, port_name)
        self.pending_port: tuple[
            ComplexNode,
            str,
        ] | None = None

        self.preview_connection: (
            ComplexPreviewConnection
            | None
        ) = None

        self.last_mouse_scene_pos = (
            QPointF()
        )

    def primary_view(
        self,
    ) -> "ComplexWorkflowView | None":
        for view in self.views():
            if isinstance(
                view,
                ComplexWorkflowView,
            ):
                return view

        return None

    def cancel_pending_connection(
        self,
    ) -> None:
        if (
            self.preview_connection
            is not None
            and self.preview_connection.scene()
            is self
        ):
            self.removeItem(
                self.preview_connection
            )

        if self.pending_port is not None:
            self.pending_port[0].update()

        self.preview_connection = None
        self.pending_port = None

    def _roi_for_internal_connection(
        self,
        source: ComplexNode,
        source_port: str,
        target: ComplexNode,
        target_port: str,
    ) -> ComplexNode | None:
        if (
            source.module_type == "roi"
            and source_port == "inner_output"
        ):
            return source

        if (
            target.module_type == "roi"
            and target_port == "inner_input"
        ):
            return target

        # If a node already belongs to an ROI chain, extending from it should
        # stay in the same container.
        for item in self.items():
            if (
                isinstance(
                    item,
                    ComplexNode,
                )
                and item.module_type == "roi"
            ):
                internal = (
                    item.roi_internal_nodes()
                )

                if (
                    source in internal
                    or target in internal
                ):
                    return item

        return None

    def _layout_roi_internal_nodes(
        self,
        roi: ComplexNode,
    ) -> None:
        """
        Move connected internal nodes into the ROI cavity before autosizing.

        Layout is left-to-right with wrapping. Existing modules are not placed
        on top of each other, and connections remain scene-level objects.
        """
        nodes = roi.roi_internal_nodes()

        if not nodes:
            roi.update_roi_bounds()
            return

        start_scene = roi.mapToScene(
            QPointF(
                roi.ROI_MARGIN_X,
                roi.ROI_HEADER
                + roi.ROI_MARGIN_Y,
            )
        )

        x = start_scene.x()
        y = start_scene.y()

        max_row_height = 0.0
        usable_width = max(
            420.0,
            roi.roi_width
            - roi.ROI_MARGIN_X * 2,
        )
        row_start_x = x

        for index, node in enumerate(nodes):
            node_w = float(
                node.node_width()
            )
            node_h = float(
                node.node_height()
            )

            if (
                index > 0
                and (
                    x
                    - row_start_x
                    + node_w
                )
                > usable_width
            ):
                x = row_start_x
                y += (
                    max_row_height
                    + 46.0
                )
                max_row_height = 0.0

            node.setPos(
                QPointF(
                    x,
                    y,
                )
            )

            x += (
                node_w
                + 64.0
            )
            max_row_height = max(
                max_row_height,
                node_h,
            )

        roi.update_roi_bounds()

        # Moving nodes updates most paths via itemChange, but explicitly
        # refresh the complete internal chain after final placement.
        for node in nodes:
            for connection in set(
                list(
                    node.incoming.values()
                )
                + list(
                    node.outgoing.values()
                )
            ):
                connection.update_path()

        for connection in set(
            list(
                roi.incoming.values()
            )
            + list(
                roi.outgoing.values()
            )
        ):
            connection.update_path()

    def handle_port_click(
        self,
        node: ComplexNode,
        port_name: str,
    ) -> None:
        port_kind = node.port_kind(
            port_name
        )

        if self.pending_port is None:
            if not node.port_available(
                port_name
            ):
                return

            self.pending_port = (
                node,
                port_name,
            )

            preview = (
                ComplexPreviewConnection()
            )
            self.preview_connection = (
                preview
            )
            self.addItem(preview)

            start = node.port_scene_pos(
                port_name
            )
            self.last_mouse_scene_pos = (
                start
            )

            preview.update_path(
                start,
                start,
                port_kind == "output",
            )

            node.update()

            view = self.primary_view()

            if view is not None:
                view.viewport().setCursor(
                    Qt.CrossCursor
                )

            return

        first_node, first_port = (
            self.pending_port
        )
        first_kind = (
            first_node.port_kind(
                first_port
            )
        )

        if (
            first_node is node
            and first_port == port_name
        ):
            self.cancel_pending_connection()
            return

        # input-input / output-output are illegal.
        if first_kind == port_kind:
            return

        if not node.port_available(
            port_name
        ):
            return

        if first_kind == "output":
            source = first_node
            source_port = first_port
            target = node
            target_port = port_name
        else:
            source = node
            source_port = port_name
            target = first_node
            target_port = first_port

        # A global-setting node can only feed another global-setting node.
        if (
            source.category.key == "global"
            and target.category.key != "global"
        ):
            return

        # The external and internal ports remain independent, but each
        # individual port can have only one connection.
        if (
            source_port in source.outgoing
            or target_port in target.incoming
        ):
            return

        connection = ComplexConnection(
            source,
            source_port,
            target,
            target_port,
        )

        source.outgoing[
            source_port
        ] = connection
        target.incoming[
            target_port
        ] = connection

        self.addItem(
            connection
        )

        self.cancel_pending_connection()

        source.update()
        target.update()

        roi = self._roi_for_internal_connection(
            source,
            source_port,
            target,
            target_port,
        )

        if roi is not None:
            self._layout_roi_internal_nodes(
                roi
            )
        else:
            self.update_all_roi_bounds()

    def update_preview(
        self,
        mouse_scene_pos: QPointF,
    ) -> None:
        self.last_mouse_scene_pos = (
            mouse_scene_pos
        )

        if (
            self.pending_port is None
            or self.preview_connection
            is None
        ):
            return

        node, port_name = (
            self.pending_port
        )
        start = node.port_scene_pos(
            port_name
        )

        self.preview_connection.update_path(
            start,
            mouse_scene_pos,
            node.port_kind(
                port_name
            ) == "output",
        )

    def remove_connection(
        self,
        connection: ComplexConnection,
    ) -> None:
        connection.source.outgoing.pop(
            connection.source_port,
            None,
        )
        connection.target.incoming.pop(
            connection.target_port,
            None,
        )

        connection.source.update()
        connection.target.update()

        if connection.scene() is self:
            self.removeItem(
                connection
            )

        self.update_all_roi_bounds()

        for item in self.items():
            if isinstance(
                item,
                ComplexConnection,
            ):
                item.update_path()

    def remove_selected_nodes(
        self,
    ) -> None:
        nodes = [
            item
            for item in self.selectedItems()
            if isinstance(
                item,
                ComplexNode,
            )
        ]

        member_ids: set[str] = set()
        for node in nodes:
            if node.module_type == "custom_module_instance":
                member_ids.update(
                    node.custom_member_ids
                )

        if member_ids:
            nodes.extend(
                item
                for item in self.items()
                if isinstance(item, ComplexNode)
                and item.node_id in member_ids
                and item not in nodes
            )

        for node in nodes:
            connections = set(
                list(
                    node.incoming.values()
                )
                + list(
                    node.outgoing.values()
                )
            )

            for connection in (
                connections
            ):
                self.remove_connection(
                    connection
                )

            if node.scene() is self:
                self.removeItem(node)

        self.update_all_roi_bounds()

    def update_all_roi_bounds(
        self,
    ) -> None:
        for item in self.items():
            if (
                isinstance(
                    item,
                    ComplexNode,
                )
                and item.module_type
                == "roi"
            ):
                item.update_roi_bounds()

    def drawBackground(
        self,
        painter: QPainter,
        rect: QRectF,
    ) -> None:
        light = (
            getattr(
                self,
                "theme_name",
                "dark",
            )
            == "light"
        )
        painter.fillRect(
            rect,
            QColor(
                "#F4F4F4"
                if light
                else "#191919"
            ),
        )

        grid = 24
        pen = QPen(
            QColor(
                "#DADADA"
                if light
                else "#292929"
            ),
            1,
        )
        painter.setPen(pen)

        left = (
            int(rect.left())
            - int(rect.left())
            % grid
        )
        top = (
            int(rect.top())
            - int(rect.top())
            % grid
        )

        x = left

        while x < rect.right():
            painter.drawLine(
                QPointF(
                    x,
                    rect.top(),
                ),
                QPointF(
                    x,
                    rect.bottom(),
                ),
            )
            x += grid

        y = top

        while y < rect.bottom():
            painter.drawLine(
                QPointF(
                    rect.left(),
                    y,
                ),
                QPointF(
                    rect.right(),
                    y,
                ),
            )
            y += grid




class ComplexWorkflowView(QGraphicsView):
    def __init__(
        self,
        parent=None,
    ) -> None:
        super().__init__(parent)

        self.complex_scene = (
            ComplexScene(self)
        )
        self.setScene(
            self.complex_scene
        )

        self.setAcceptDrops(True)
        self.setFocusPolicy(
            Qt.StrongFocus
        )
        self.setMouseTracking(True)

        self.setRenderHints(
            QPainter.Antialiasing
            | QPainter.TextAntialiasing
        )
        self.setTransformationAnchor(
            QGraphicsView.AnchorUnderMouse
        )
        self.setDragMode(
            QGraphicsView.RubberBandDrag
        )
        self.setHorizontalScrollBarPolicy(
            Qt.ScrollBarAlwaysOff
        )
        self.setVerticalScrollBarPolicy(
            Qt.ScrollBarAlwaysOff
        )
        self.setFrameShape(
            QFrame.NoFrame
        )
        self.setViewportUpdateMode(
            QGraphicsView.FullViewportUpdate
        )

        self._zoom = 1.0
        self._panning = False
        self._pan_start = QPoint()
        self.on_module_dropped = None
        self.on_custom_module_dropped = None

    def wheelEvent(
        self,
        event: QWheelEvent,
    ) -> None:
        factor = (
            1.12
            if event.angleDelta().y() > 0
            else 1 / 1.12
        )
        target = (
            self._zoom
            * factor
        )

        if (
            0.25
            <= target
            <= 4.0
        ):
            self.scale(
                factor,
                factor,
            )
            self._zoom = target

    def mouseMoveEvent(
        self,
        event: QMouseEvent,
    ) -> None:
        if self._panning:
            current = event.position().toPoint()
            delta = current - self._pan_start
            self._pan_start = current
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - delta.x()
            )
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - delta.y()
            )
            event.accept()
            return

        self.complex_scene.update_preview(
            self.mapToScene(
                event.position().toPoint()
            )
        )
        super().mouseMoveEvent(
            event
        )

    def mousePressEvent(
        self,
        event: QMouseEvent,
    ) -> None:
        if event.button() == Qt.MiddleButton:
            self._panning = True
            self._pan_start = event.position().toPoint()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return

        if (
            event.button()
            == Qt.LeftButton
            and self.complex_scene.pending_port
            is not None
        ):
            item = self.itemAt(
                event.position().toPoint()
            )

            if not isinstance(
                item,
                ComplexNode,
            ):
                self.complex_scene.cancel_pending_connection()
                self.viewport().unsetCursor()
                event.accept()
                return

        super().mousePressEvent(
            event
        )

    def mouseReleaseEvent(
        self,
        event: QMouseEvent,
    ) -> None:
        if self._panning and event.button() == Qt.MiddleButton:
            self._panning = False
            self.unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(
        self,
        event: QKeyEvent,
    ) -> None:
        if event.key() in (
            Qt.Key_Delete,
            Qt.Key_Backspace,
        ):
            self.complex_scene.remove_selected_nodes()
            return

        if event.key() == Qt.Key_Escape:
            self.complex_scene.cancel_pending_connection()
            self.viewport().unsetCursor()
            return

        super().keyPressEvent(
            event
        )

    def dragEnterEvent(
        self,
        event,
    ) -> None:
        if event.mimeData().hasFormat(
            MIME_BLOCK
        ):
            event.acceptProposedAction()
            return

        super().dragEnterEvent(event)

    def dragMoveEvent(
        self,
        event,
    ) -> None:
        if event.mimeData().hasFormat(
            MIME_BLOCK
        ):
            event.acceptProposedAction()
            return

        super().dragMoveEvent(event)

    def dropEvent(
        self,
        event,
    ) -> None:
        if not event.mimeData().hasFormat(
            MIME_BLOCK
        ):
            super().dropEvent(event)
            return

        payload = bytes(
            event.mimeData().data(
                MIME_BLOCK
            )
        ).decode("utf-8")

        parts = payload.split("\n", 3)
        if len(parts) < 3:
            return
        category_key, module_type, block_text = parts[:3]
        payload_extra = parts[3] if len(parts) > 3 else ""

        scene_pos = self.mapToScene(
            event.position().toPoint()
        )

        if module_type == "custom_module":
            if callable(
                self.on_custom_module_dropped
            ):
                self.on_custom_module_dropped(
                    payload_extra,
                    scene_pos,
                    "complex",
                )

            event.acceptProposedAction()
            return

        node = ComplexNode(
            category_by_key(
                category_key
            ),
            module_type,
            block_text,
        )

        node.setPos(
            scene_pos
        )

        self.complex_scene.addItem(
            node
        )
        self.complex_scene.update_all_roi_bounds()

        if callable(self.on_module_dropped):
            self.on_module_dropped(
                node,
                payload_extra,
            )

        event.acceptProposedAction()

    def edit_roi_node(
        self,
        node: ComplexNode,
    ) -> None:
        dialog = ComplexRoiDialog(
            node,
            self.window(),
        )

        if dialog.exec() != QDialog.Accepted:
            return

        node.roi_values_data = (
            dialog.values()
        )
        node.update()

    def reset_view(self) -> None:
        self.resetTransform()
        self._zoom = 1.0
        self.centerOn(
            0,
            0,
        )


class OverviewView(QGraphicsView):
    """
    Read-only miniature of the real canvas.

    Because Scratch-style connection is physical stacking rather than a
    separate graph line, the overview simply mirrors block positions.
    """

    def __init__(
        self,
        scene: WorkflowScene,
        parent=None,
    ) -> None:
        super().__init__(
            scene,
            parent,
        )

        self.setRenderHints(
            QPainter.Antialiasing
            | QPainter.TextAntialiasing
        )

        self.setFrameShape(
            QFrame.NoFrame
        )

        self.setHorizontalScrollBarPolicy(
            Qt.ScrollBarAlwaysOff
        )

        self.setVerticalScrollBarPolicy(
            Qt.ScrollBarAlwaysOff
        )

        self.setInteractive(False)

        self.set_theme("dark")

    def set_theme(
        self,
        theme_name: str,
    ) -> None:
        light = (
            str(theme_name).lower()
            == "light"
        )
        self.setStyleSheet(
            "QGraphicsView{"
            + (
                "background:#F4F4F4;"
                if light
                else "background:#181818;"
            )
            + "border:0;"
            + "}"
        )
        self.viewport().update()

    def refresh(self) -> None:
        blocks = [
            item
            for item in self.scene().items()
            if isinstance(
                item,
                (CanvasBlock, ComplexNode),
            )
            and item.isVisible()
        ]

        if not blocks:
            self.resetTransform()
            self.centerOn(
                0,
                0,
            )
            return

        bounds = QRectF()

        for block in blocks:
            rect = (
                block.sceneBoundingRect()
            )

            bounds = (
                rect
                if bounds.isNull()
                else bounds.united(rect)
            )

        bounds.adjust(
            -80,
            -80,
            80,
            80,
        )

        self.fitInView(
            bounds,
            Qt.KeepAspectRatio,
        )


class WorkspacePage(ModuleRuntimeMixin, QWidget):
    def __init__(
        self,
        settings: SettingsStore,
        logger: LoggingService,
    ) -> None:
        super().__init__(
            objectName="page"
        )

        self.settings = settings
        self.logger = logger
        self.project_manager = ProjectManager()
        self.mouse_action_engine = MouseActionEngine()
        self.keyboard_action_engine = KeyboardActionEngine()
        self._clock_threads = []
        self._clock_event_chains: dict[int, list[ExecutionStep]] = {}
        self._event_chain_cancel = threading.Event()
        self._module_library_signature = None
        self._clock_slot_counter = 0

        # Workspace hotkeys are recorded as simultaneous key chords and
        # triggered when the entire chord has been released. This supports
        # arbitrary multi-key combinations rather than only Qt's standard
        # modifier+single-key shortcuts.
        self._hotkey_pressed: set[str] = set()
        self._hotkey_session: set[str] = set()
        self._hotkey_quick_template: frozenset[str] = frozenset(
            {
                "CTRL",
                "S",
            }
        )
        self._hotkey_recognition_view: frozenset[str] = frozenset(
            {
                "CTRL",
                "L",
            }
        )

        try:
            self.recognition_engine = RecognitionEngine(
                str(
                    self.settings.get(
                        "recognition.backend",
                        "native",
                    )
                ),
                max_fps=int(
                    self.settings.get(
                        "recognition.max_fps",
                        60,
                    )
                ),
            )
        except Exception:
            self.recognition_engine = RecognitionEngine(
                "mss",
                max_fps=int(
                    self.settings.get(
                        "recognition.max_fps",
                        60,
                    )
                ),
            )

        self.runtime_signals = (
            WorkspaceRuntimeSignals()
        )
        self.runtime_signals.message.connect(
            self._on_runtime_message
        )
        self.runtime_signals.chain_finished.connect(
            self._on_chain_finished
        )
        self.runtime_signals.clock_expired.connect(
            self._on_clock_expired
        )

        self._active_chains = 0

        # Runtime lifecycle. Global settings remain active until Stop.
        self._stop_event = threading.Event()
        self._active_global_recognition_roi: (
            tuple[int, int, int, int] | None
        ) = None
        self._active_global_anchor_point: (
            tuple[int, int] | None
        ) = None
        self._global_runtime_active = False
        self._runtime_lock = threading.RLock()

        # Refactor safety: detect broken method extraction/binding before the
        # Run button is connected. This specifically prevents silent failures
        # such as an accidentally orphaned @staticmethod decorator.
        validate_workspace_runtime_contract(
            self
        )

        # Recognition viewport debug state. All coordinates are absolute
        # global/physical desktop pixels.
        self._vision_debug_lock = threading.RLock()
        self._vision_debug_module: str | None = None
        self._vision_debug_roi: (
            tuple[int, int, int, int] | None
        ) = None
        self._vision_debug_detection: (
            tuple[int, int, int, int] | None
        ) = None
        self._recognition_viewport_dialog: (
            RecognitionViewportDialog | None
        ) = None

        self._build_ui()

        application = QApplication.instance()

        if application is not None:
            application.installEventFilter(
                self
            )

        self._type_validation_timer = QTimer(
            self
        )
        self._type_validation_timer.setInterval(
            250
        )
        self._type_validation_timer.timeout.connect(
            self._validate_data_connections
        )
        self._type_validation_timer.start()

        self.reload_settings()
        self._load_initial_project()

    # ==============================================================
    # UI
    # ==============================================================
    def _build_ui(self) -> None:
        main = QVBoxLayout(self)
        main.setContentsMargins(
            22,
            18,
            22,
            22,
        )
        main.setSpacing(12)

        header = QHBoxLayout()

        title_column = QVBoxLayout()
        title_column.setSpacing(2)

        self.page_title = QLabel(
            "工作台",
            objectName="pageTitle",
        )
        title_column.addWidget(
            self.page_title
        )

        self.page_subtitle = QLabel(
            "创建或导入项目后开始。",
            objectName="pageSubtitle",
        )
        title_column.addWidget(
            self.page_subtitle
        )

        header.addLayout(
            title_column
        )
        header.addStretch()

        self.project_name_label = QLabel(
            "",
            objectName="muted",
        )
        header.addWidget(
            self.project_name_label
        )

        main.addLayout(header)

        self.page_stack = QStackedWidget()
        main.addWidget(
            self.page_stack,
            1,
        )

        self.empty_page = (
            self._build_empty_page()
        )
        self.editor_page = (
            self._build_editor_page()
        )

        self.page_stack.addWidget(
            self.empty_page
        )
        self.page_stack.addWidget(
            self.editor_page
        )

    def _build_empty_page(self) -> QWidget:
        page = QWidget()

        layout = QVBoxLayout(page)
        layout.setContentsMargins(
            80,
            80,
            80,
            80,
        )
        layout.addStretch()

        title = QLabel(
            "还没有打开项目"
        )
        title.setAlignment(
            Qt.AlignCenter
        )
        title.setStyleSheet(
            "font-size:22px;"
            "font-weight:600;"
        )
        layout.addWidget(title)

        hint = QLabel(
            "每个项目拥有独立的模板、资源和工作流。"
        )
        hint.setAlignment(
            Qt.AlignCenter
        )
        hint.setObjectName(
            "muted"
        )
        layout.addWidget(hint)

        self.project_list = QListWidget()
        self.project_list.setMaximumHeight(
            180
        )
        self.project_list.itemDoubleClicked.connect(
            self._open_selected_library_project
        )
        layout.addWidget(
            self.project_list
        )

        buttons = QHBoxLayout()
        buttons.addStretch()

        new_button = QPushButton(
            "新建项目",
            objectName="primaryButton",
        )
        new_button.clicked.connect(
            self.new_project
        )
        buttons.addWidget(new_button)

        import_button = QPushButton(
            "导入项目",
            objectName="secondaryButton",
        )
        import_button.clicked.connect(
            self.import_project
        )
        buttons.addWidget(import_button)

        open_button = QPushButton(
            "打开选中项目",
            objectName="secondaryButton",
        )
        open_button.clicked.connect(
            self._open_selected_library_project
        )
        buttons.addWidget(open_button)

        delete_button = QPushButton(
            "删除项目",
            objectName="secondaryButton",
        )
        delete_button.clicked.connect(
            self.delete_selected_project
        )
        buttons.addWidget(delete_button)

        buttons.addStretch()
        layout.addLayout(buttons)

        layout.addStretch()
        return page

    def _build_editor_page(self) -> QWidget:
        page = QWidget()

        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(
            0,
            0,
            0,
            0,
        )
        page_layout.setSpacing(8)

        # ----------------------------------------------------------
        # Toolbar
        # ----------------------------------------------------------
        toolbar = QFrame(
            objectName="card"
        )
        toolbar_layout = QHBoxLayout(
            toolbar
        )
        toolbar_layout.setContentsMargins(
            9,
            6,
            9,
            6,
        )
        toolbar_layout.setSpacing(7)

        self.save_button = QPushButton(
            "保存",
            objectName="secondaryButton",
        )
        self.save_button.clicked.connect(
            self.save_project
        )
        toolbar_layout.addWidget(
            self.save_button
        )

        self.import_button = QPushButton(
            "导入",
            objectName="secondaryButton",
        )
        self.import_button.clicked.connect(
            self.import_project
        )
        toolbar_layout.addWidget(
            self.import_button
        )

        self.export_button = QPushButton(
            "导出",
            objectName="secondaryButton",
        )
        self.export_button.clicked.connect(
            self.export_project
        )
        toolbar_layout.addWidget(
            self.export_button
        )

        switch_button = QPushButton(
            "切换项目",
            objectName="secondaryButton",
        )
        switch_button.clicked.connect(
            self.switch_project
        )
        toolbar_layout.addWidget(
            switch_button
        )

        close_button = QPushButton(
            "关闭项目",
            objectName="secondaryButton",
        )
        close_button.clicked.connect(self.close_project)
        toolbar_layout.addWidget(close_button)

        open_folder_button=QPushButton("打开项目文件夹",objectName="secondaryButton")
        open_folder_button.clicked.connect(self.open_project_folder)
        toolbar_layout.addWidget(open_folder_button)

        toolbar_layout.addSpacing(6)

        self.quick_template_button = (
            DelayedToolButton(
                "快捷创建模板"
            )
        )
        self.quick_template_button.setIcon(
            quick_template_icon()
        )
        self.quick_template_button.setIconSize(
            QSize(24, 24)
        )
        self.quick_template_button.setFixedSize(
            34,
            34,
        )
        self.quick_template_button.clicked.connect(
            self.quick_create_template
        )
        toolbar_layout.addWidget(
            self.quick_template_button
        )

        self.recognition_view_button = (
            DelayedToolButton(
                "视觉识别系统视角"
            )
        )
        self.recognition_view_button.setIcon(
            recognition_view_icon()
        )
        self.recognition_view_button.setIconSize(
            QSize(
                24,
                24,
            )
        )
        self.recognition_view_button.setFixedSize(
            34,
            34,
        )
        self.recognition_view_button.clicked.connect(
            self.open_recognition_viewport
        )
        toolbar_layout.addWidget(
            self.recognition_view_button
        )

        self.create_custom_module_button = QPushButton(
            "新建为新自定义模块",
            objectName="secondaryButton",
        )
        self.create_custom_module_button.setVisible(
            False
        )
        self.create_custom_module_button.clicked.connect(
            self.create_custom_module_from_selection
        )
        toolbar_layout.addWidget(
            self.create_custom_module_button
        )

        toolbar_layout.addStretch()

        self.reset_view_button = QPushButton(
            "重置视图",
            objectName="secondaryButton",
        )
        self.reset_view_button.clicked.connect(
            self.reset_current_view
        )
        toolbar_layout.addWidget(
            self.reset_view_button
        )

        self.type_warning_label = QLabel(
            "",
        )
        self.type_warning_label.setStyleSheet(
            "color:#FF5C5C;"
            "font-weight:700;"
        )
        self.type_warning_label.setVisible(
            False
        )
        toolbar_layout.addWidget(
            self.type_warning_label
        )

        self.runtime_status = QLabel(
            "就绪",
            objectName="muted",
        )
        toolbar_layout.addWidget(
            self.runtime_status
        )

        self.run_button = QPushButton(
            "运行",
            objectName="primaryButton",
        )
        self.run_button.clicked.connect(
            self._on_run_button_clicked
        )
        toolbar_layout.addWidget(
            self.run_button
        )

        self.stop_button = QPushButton(
            "停止",
            objectName="secondaryButton",
        )
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(
            self.stop_workflows
        )
        toolbar_layout.addWidget(
            self.stop_button
        )

        page_layout.addWidget(toolbar)

        # ----------------------------------------------------------
        # Main editor
        # ----------------------------------------------------------
        body = QHBoxLayout()
        body.setSpacing(10)

        library_panel = QFrame(
            objectName="card"
        )
        library_panel.setFixedWidth(
            242
        )

        library_layout = QVBoxLayout(
            library_panel
        )
        library_layout.setContentsMargins(
            14,
            13,
            10,
            13,
        )
        library_layout.setSpacing(10)

        library_layout.addWidget(
            QLabel(
                "模块库",
                objectName="sectionTitle",
            )
        )

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(
            QFrame.NoFrame
        )
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarAlwaysOff
        )
        scroll.setStyleSheet(
            "QScrollArea{"
            "background:transparent;"
            "border:0;"
            "}"
        )

        contents = QWidget()
        contents.setStyleSheet(
            "background:transparent;"
        )
        contents_layout = QVBoxLayout(
            contents
        )
        contents_layout.setContentsMargins(
            2,
            0,
            5,
            0,
        )
        contents_layout.setSpacing(3)

        self.module_library_contents = contents
        self.module_library_layout = contents_layout
        self._rebuild_module_library(())
        scroll.setWidget(contents)
        library_layout.addWidget(
            scroll,
            1,
        )

        self.canvas_stack = (
            QStackedWidget()
        )

        self.canvas = WorkflowView()
        self.complex_canvas = (
            ComplexWorkflowView()
        )

        self.canvas.on_module_dropped = self._on_module_dropped
        self.complex_canvas.on_module_dropped = self._on_module_dropped
        self.canvas.on_custom_module_dropped = (
            self._drop_custom_module_from_palette
        )
        self.complex_canvas.on_custom_module_dropped = (
            self._drop_custom_module_from_palette
        )

        self.canvas.workflow_scene.selectionChanged.connect(
            self._update_custom_module_button
        )
        self.complex_canvas.complex_scene.selectionChanged.connect(
            self._update_custom_module_button
        )

        self._module_library_timer = QTimer(self)
        self._module_library_timer.setSingleShot(True)
        self._module_library_timer.setInterval(40)
        self._module_library_timer.timeout.connect(
            self._refresh_module_library
        )
        self.canvas.workflow_scene.changed.connect(
            self._schedule_module_library_refresh
        )
        self.complex_canvas.complex_scene.changed.connect(
            self._schedule_module_library_refresh
        )

        self.canvas_stack.addWidget(
            self.canvas
        )
        self.canvas_stack.addWidget(
            self.complex_canvas
        )

        canvas_panel = QFrame(
            objectName="card"
        )
        canvas_layout = QVBoxLayout(
            canvas_panel
        )
        canvas_layout.setContentsMargins(
            1,
            1,
            1,
            1,
        )
        canvas_layout.addWidget(
            self.canvas_stack
        )

        overview_panel = QFrame(
            objectName="card"
        )
        overview_panel.setFixedWidth(
            210
        )

        overview_layout = QVBoxLayout(
            overview_panel
        )
        overview_layout.setContentsMargins(
            12,
            12,
            12,
            12,
        )
        overview_layout.setSpacing(8)

        overview_layout.addWidget(
            QLabel(
                "概览",
                objectName="sectionTitle",
            )
        )

        self.overview_hint = QLabel(
            "快速查看项目结构。",
            objectName="muted",
        )
        self.overview_hint.setWordWrap(True)
        overview_layout.addWidget(
            self.overview_hint
        )

        self.overview = OverviewView(
            self.canvas.workflow_scene
        )
        overview_layout.addWidget(
            self.overview,
            1,
        )

        body.addWidget(
            library_panel
        )
        body.addWidget(
            canvas_panel,
            1,
        )
        body.addWidget(
            overview_panel
        )

        page_layout.addLayout(
            body,
            1,
        )

        self.canvas.workflow_scene.set_overview_callback(
            self.overview.refresh
        )

        QTimer.singleShot(
            0,
            self.overview.refresh,
        )

        return page

    def _validate_data_connections(
        self,
    ) -> None:
        warnings: list[str] = []
        logic_warnings: list[str] = []

        # Simple mode.
        if hasattr(
            self,
            "canvas",
        ):
            blocks = [
                item
                for item in self.canvas.workflow_scene.items()
                if isinstance(
                    item,
                    CanvasBlock,
                )
            ]

            for block in blocks:
                block.type_warning_message = ""
                block.condition_warning_message = ""

            for block in blocks:
                if isinstance(
                    block,
                    LogicContainerBlock,
                ):
                    block.refresh_condition_warnings()
                    if block.has_condition_action():
                        logic_warnings.append(
                            f"{block.text} 的判定框包含动作模块；动作会执行，但不直接提供判定值。"
                        )

            for block in blocks:
                parent = block.stack_parent

                if parent is None:
                    continue

                source_type = module_output_type(
                    parent.module_type
                )
                target_type = module_input_type(
                    block.module_type
                )

                if not data_types_compatible(
                    source_type,
                    target_type,
                ):
                    message = (
                        f"{parent.text} 输出 {source_type}，"
                        f"但 {block.text} 需要 {target_type}"
                    )
                    block.type_warning_message = (
                        message
                    )
                    parent.type_warning_message = (
                        message
                    )
                    warnings.append(
                        message
                    )

            for block in blocks:
                block.update()

        # Complex mode.
        if hasattr(
            self,
            "complex_canvas",
        ):
            scene = (
                self.complex_canvas
                .complex_scene
            )

            nodes = [
                item
                for item in scene.items()
                if isinstance(
                    item,
                    ComplexNode,
                )
            ]

            for node in nodes:
                node.type_warning_message = ""
                node.condition_warning_message = ""

            condition_ports = {
                "logic_if": ("branch_a_output",),
                "logic_or": ("branch_a_output","branch_b_output"),
                "logic_nor": ("branch_a_output","branch_b_output"),
                "logic_and": ("branch_a_output","branch_b_output"),
            }

            for logic_node in nodes:
                ports=condition_ports.get(logic_node.module_type,())
                for port_name in ports:
                    connection=logic_node.outgoing.get(port_name)
                    if connection is None:
                        continue
                    current=connection.target
                    visited=set()
                    while current is not None and current.node_id not in visited:
                        visited.add(current.node_id)
                        if current.module_type in ACTION_MODULE_TYPES:
                            current.condition_warning_message=(
                                "该动作会在判定时执行，但不直接提供判定值。"
                            )
                            logic_node.condition_warning_message="判定分支包含动作模块"
                            logic_warnings.append(
                                f"{logic_node.text} 的判定分支包含动作模块。"
                            )
                        next_connection=current.outgoing.get("output")
                        if next_connection is None:
                            break
                        current=next_connection.target

            for item in scene.items():
                if not isinstance(
                    item,
                    ComplexConnection,
                ):
                    continue

                source_type = module_output_type(
                    item.source.module_type
                )
                target_type = module_input_type(
                    item.target.module_type
                )

                if not data_types_compatible(
                    source_type,
                    target_type,
                ):
                    message = (
                        f"{item.source.text} 输出 {source_type}，"
                        f"但 {item.target.text} 需要 {target_type}"
                    )
                    item.source.type_warning_message = (
                        message
                    )
                    item.target.type_warning_message = (
                        message
                    )
                    warnings.append(
                        message
                    )

            for node in nodes:
                node.update()

        if not hasattr(
            self,
            "type_warning_label",
        ):
            return

        if warnings:
            unique = list(dict.fromkeys(warnings))
            self.type_warning_label.setStyleSheet(
                "color:#FF5C5C;font-weight:700;"
            )
            self.type_warning_label.setText(
                tr_text(
                    "⚠ 数据类型不匹配："
                    + unique[0]
                    + (
                        f"（另有 {len(unique)-1} 处）"
                        if len(unique) > 1
                        else ""
                    )
                )
            )
            self.type_warning_label.setVisible(True)
        elif logic_warnings:
            unique = list(dict.fromkeys(logic_warnings))
            self.type_warning_label.setStyleSheet(
                "color:#FFD54A;font-weight:700;"
            )
            self.type_warning_label.setText(
                tr_text(
                    "⚠ 判定提醒：" + unique[0]
                )
            )
            self.type_warning_label.setVisible(True)
        else:
            self.type_warning_label.clear()
            self.type_warning_label.setVisible(False)

    def _vision_debug_snapshot(
        self,
    ) -> dict:
        """
        Thread-safe state consumed by RecognitionViewportDialog.

        Active sensing ROI has highest priority. Otherwise persistent global
        Recognition Engine restriction is shown. If neither exists, the
        backend's full capture surface is displayed.
        """
        with self._vision_debug_lock:
            module_name = (
                self._vision_debug_module
            )
            sensing_roi = (
                self._vision_debug_roi
            )
            detection = (
                self._vision_debug_detection
            )

        roi = sensing_roi

        if (
            roi is None
            and self._active_global_recognition_roi
            is not None
        ):
            roi = (
                self._active_global_recognition_roi
            )

        roi = (
            RecognitionViewportDialog
            ._normalize_debug_roi(
                roi
            )
        )

        return {
            "module": module_name,
            "roi": roi,
            "detection": detection,
        }

    def _vision_begin_sensing(
        self,
        module_name: str,
        roi: tuple[int, int, int, int] | None,
    ) -> None:
        """
        Generic hook for every current/future sensing module.
        Calling this automatically removes the previous module's red box.
        """
        with self._vision_debug_lock:
            self._vision_debug_module = (
                module_name
            )
            self._vision_debug_roi = roi
            self._vision_debug_detection = (
                None
            )

    def _vision_publish_detection(
        self,
        module_name: str,
        roi: tuple[int, int, int, int] | None,
        detection: tuple[int, int, int, int] | None,
    ) -> None:
        with self._vision_debug_lock:
            self._vision_debug_module = (
                module_name
            )
            self._vision_debug_roi = roi
            self._vision_debug_detection = (
                detection
            )

    def _vision_clear_debug(
        self,
    ) -> None:
        with self._vision_debug_lock:
            self._vision_debug_module = None
            self._vision_debug_roi = None
            self._vision_debug_detection = None

    def open_recognition_viewport(
        self,
    ) -> None:
        current = (
            self._recognition_viewport_dialog
        )

        if (
            current is not None
            and current.isVisible()
        ):
            current.raise_()
            current.activateWindow()
            return

        dialog = RecognitionViewportDialog(
            self,
            self.window(),
        )
        self._recognition_viewport_dialog = (
            dialog
        )

        def clear_reference(*_args) -> None:
            if (
                self._recognition_viewport_dialog
                is dialog
            ):
                self._recognition_viewport_dialog = (
                    None
                )

        dialog.finished.connect(
            clear_reference
        )
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def eventFilter(
        self,
        watched,
        event,
    ) -> bool:
        event_type = (
            event.type()
        )

        if event_type == QEvent.ApplicationDeactivate:
            self._hotkey_pressed.clear()
            self._hotkey_session.clear()
            return super().eventFilter(
                watched,
                event,
            )

        if event_type not in {
            QEvent.KeyPress,
            QEvent.KeyRelease,
        }:
            return super().eventFilter(
                watched,
                event,
            )

        # Hotkeys are local to the Workbench. Settings recorder and other pages
        # cannot accidentally trigger Workbench actions.
        if not self.isVisible():
            self._hotkey_pressed.clear()
            self._hotkey_session.clear()
            return super().eventFilter(
                watched,
                event,
            )

        application = QApplication.instance()

        if (
            application is not None
            and application.activeModalWidget()
            is not None
        ):
            self._hotkey_pressed.clear()
            self._hotkey_session.clear()
            return super().eventFilter(
                watched,
                event,
            )

        if not isinstance(
            event,
            QKeyEvent,
        ):
            return super().eventFilter(
                watched,
                event,
            )

        if event.isAutoRepeat():
            return super().eventFilter(
                watched,
                event,
            )

        token = workspace_hotkey_token(
            event
        )

        if not token:
            return super().eventFilter(
                watched,
                event,
            )

        if event_type == QEvent.KeyPress:
            if not self._hotkey_pressed:
                self._hotkey_session.clear()

            self._hotkey_pressed.add(
                token
            )
            self._hotkey_session.add(
                token
            )

            return super().eventFilter(
                watched,
                event,
            )

        self._hotkey_pressed.discard(
            token
        )

        if (
            self._hotkey_pressed
            or not self._hotkey_session
        ):
            return super().eventFilter(
                watched,
                event,
            )

        completed = frozenset(
            self._hotkey_session
        )
        self._hotkey_session.clear()

        if (
            completed
            == self._hotkey_quick_template
            and completed
        ):
            QTimer.singleShot(
                0,
                self.quick_create_template,
            )
            return True

        if (
            completed
            == self._hotkey_recognition_view
            and completed
        ):
            QTimer.singleShot(
                0,
                self.open_recognition_viewport,
            )
            return True

        return super().eventFilter(
            watched,
            event,
        )

    # ==============================================================
    # Settings
    # ==============================================================
    def reload_settings(self) -> None:
        self._hotkey_quick_template = (
            workspace_hotkey_set(
                str(
                    self.settings.get(
                        "hotkeys.quick_template",
                        "CTRL+S",
                    )
                )
            )
            or frozenset(
                {
                    "CTRL",
                    "S",
                }
            )
        )

        self._hotkey_recognition_view = (
            workspace_hotkey_set(
                str(
                    self.settings.get(
                        "hotkeys.recognition_viewport",
                        "CTRL+L",
                    )
                )
            )
            or frozenset(
                {
                    "CTRL",
                    "L",
                }
            )
        )

        self._hotkey_pressed.clear()
        self._hotkey_session.clear()

        quick = bool(
            self.settings.get(
                "workspace.quick_toolbar",
                self.settings.get(
                    "workspace.quick_template_capture",
                    False,
                ),
            )
        )

        if hasattr(
            self,
            "quick_template_button",
        ):
            self.quick_template_button.setVisible(
                quick
            )

        if hasattr(
            self,
            "recognition_view_button",
        ):
            self.recognition_view_button.setVisible(
                quick
            )

        mode = str(
            self.settings.get(
                "workspace.mode",
                "simple",
            )
        )

        theme_name = str(
            self.settings.get(
                "ui.theme",
                "dark",
            )
        )

        if hasattr(self, "canvas"):
            self.canvas.workflow_scene.theme_name = theme_name
            self.canvas.viewport().update()
        if hasattr(self, "complex_canvas"):
            self.complex_canvas.complex_scene.theme_name = theme_name
            self.complex_canvas.viewport().update()
        if hasattr(self, "overview"):
            self.overview.set_theme(theme_name)

        backend = str(
            self.settings.get(
                "recognition.backend",
                "native",
            )
        )

        self.recognition_engine.set_max_fps(
            int(
                self.settings.get(
                    "recognition.max_fps",
                    60,
                )
            )
        )

        viewport = getattr(
            self,
            "_recognition_viewport_dialog",
            None,
        )

        if (
            viewport is not None
            and viewport.isVisible()
        ):
            viewport._apply_capture_exclusion_setting()

        try:
            self.recognition_engine.set_backend(
                backend
            )
        except Exception as exc:
            self.logger.warning(
                (
                    f"Recognition backend {backend} unavailable: "
                    f"{exc}; falling back to MSS."
                ),
                source="recognition",
            )
            self.recognition_engine.set_backend(
                "mss"
            )

        if hasattr(
            self,
            "canvas_stack",
        ):
            self.canvas_stack.setCurrentIndex(
                0
                if mode == "simple"
                else 1
            )

            self.page_subtitle.setText(
                (
                    tr_text("简单模式（拼图）")
                    if mode == "simple"
                    else
                    tr_text("复杂模式：节点、端口与连线。")
                )
            )

            if mode == "simple":
                self.overview.setScene(
                    self.canvas.workflow_scene
                )
            else:
                self.overview.setScene(
                    self.complex_canvas.complex_scene
                )

            self.canvas.workflow_scene.update()
            self.complex_canvas.complex_scene.update()
            self.overview.viewport().update()

    # ==============================================================
    # Project lifecycle
    # ==============================================================
        self._module_library_signature = None
        self._refresh_module_library()
        self._update_custom_module_button()

    def _refresh_project_library(self) -> None:
        self.project_list.clear()

        for project in (
            self.project_manager.list_projects()
        ):
            item = QListWidgetItem(
                project.name
            )
            item.setData(
                Qt.UserRole,
                project.project_id,
            )
            self.project_list.addItem(
                item
            )

    def _load_initial_project(self) -> None:
        self._refresh_project_library()

        project = (
            self.project_manager.current_project()
        )

        if project is None:
            self.page_stack.setCurrentWidget(
                self.empty_page
            )
            self.project_name_label.setText(
                ""
            )
            return

        self.open_project(
            project.project_id
        )

    def new_project(self) -> None:
        name, ok = (
            QInputDialog.getText(
                self,
                "新建项目",
                "项目名称：",
            )
        )

        if not ok or not name.strip():
            return

        try:
            project = (
                self.project_manager.create_project(
                    name
                )
            )
        except Exception as exc:
            QMessageBox.warning(
                self,
                "创建失败",
                str(exc),
            )
            return

        self.open_project(
            project.project_id
        )

    def import_project(self) -> None:
        file_path, _filter = (
            QFileDialog.getOpenFileName(
                self,
                "导入 UVAF 项目",
                "",
                (
                    f"UVAF Project (*{PROJECT_EXTENSION});;"
                    "All files (*.*)"
                ),
            )
        )

        if not file_path:
            return

        try:
            project = (
                self.project_manager.import_project(
                    Path(file_path)
                )
            )
        except Exception as exc:
            QMessageBox.warning(
                self,
                "导入失败",
                str(exc),
            )
            return

        self.open_project(
            project.project_id
        )

    def switch_project(self) -> None:
        projects = (
            self.project_manager.list_projects()
        )

        if not projects:
            self.new_project()
            return

        labels = [
            project.name
            for project in projects
        ]

        current = (
            self.project_manager.current_project()
        )
        current_index = 0

        if current is not None:
            for index, project in enumerate(
                projects
            ):
                if (
                    project.project_id
                    == current.project_id
                ):
                    current_index = index
                    break

        selected, ok = (
            QInputDialog.getItem(
                self,
                "切换项目",
                "项目：",
                labels,
                current_index,
                False,
            )
        )

        if not ok:
            return

        for project in projects:
            if project.name == selected:
                # Stop runtime and save before switching.
                self.stop_workflows()

                if (
                    self.project_manager.current_project()
                    is not None
                ):
                    self.save_project()

                self.open_project(
                    project.project_id
                )
                return

    def _active_clock_nodes(self) -> list:
        mode = str(
            self.settings.get(
                "workspace.mode",
                "simple",
            )
        )

        if mode == "complex":
            nodes = [
                item
                for item in self.complex_canvas.complex_scene.items()
                if isinstance(item, ComplexNode)
                and item.module_type == "clock"
                and not getattr(item, "_custom_hidden", False)
            ]
        else:
            nodes = [
                item
                for item in self.canvas.workflow_scene.items()
                if isinstance(item, CanvasBlock)
                and item.module_type == "clock"
                and not getattr(item, "_custom_hidden", False)
            ]

        return sorted(
            nodes,
            key=lambda item: (
                int(getattr(item, "clock_event_slot", 0) or 0),
                item.scenePos().y(),
                item.scenePos().x(),
            ),
        )

    def _all_active_event_nodes(self) -> list:
        mode = str(
            self.settings.get(
                "workspace.mode",
                "simple",
            )
        )
        if mode == "complex":
            return [
                item
                for item in self.complex_canvas.complex_scene.items()
                if isinstance(item, ComplexNode)
                and item.module_type == "clock_end_start"
                and not getattr(item, "_custom_hidden", False)
            ]
        return [
            item
            for item in self.canvas.workflow_scene.items()
            if isinstance(item, CanvasBlock)
            and item.module_type == "clock_end_start"
            and not getattr(item, "_custom_hidden", False)
        ]

    def _next_clock_slot(self) -> int:
        used = [
            int(getattr(node, "clock_event_slot", 0) or 0)
            for node in self._active_clock_nodes()
        ]
        self._clock_slot_counter = max(
            [self._clock_slot_counter, *used, 0]
        ) + 1
        return self._clock_slot_counter

    def _reconcile_clock_event_slots(self) -> None:
        clocks = self._active_clock_nodes()
        events = self._all_active_event_nodes()

        used = {
            int(getattr(node, "clock_event_slot", 0) or 0)
            for node in clocks
            if int(getattr(node, "clock_event_slot", 0) or 0) > 0
        }
        next_slot = max([*used, self._clock_slot_counter, 0]) + 1

        # Old projects may contain clocks from before slot IDs existed.
        for node in clocks:
            slot = int(getattr(node, "clock_event_slot", 0) or 0)
            if slot <= 0:
                while next_slot in used:
                    next_slot += 1
                node.clock_event_slot = next_slot
                node.clock_event_claimed = False
                used.add(next_slot)
                next_slot += 1

        self._clock_slot_counter = max([*used, 0])

        event_slots = {
            int(getattr(node, "clock_event_slot", 0) or 0)
            for node in events
            if int(getattr(node, "clock_event_slot", 0) or 0) > 0
        }

        # If an event module already exists, its palette token is permanently
        # consumed. Deleting that event later does not unclaim the clock.
        for clock in clocks:
            slot = int(clock.clock_event_slot)
            if slot in event_slots:
                clock.clock_event_claimed = True

    def _event_palette_specs(self) -> tuple[ModuleSpec, ...]:
        self._reconcile_clock_event_slots()
        specs = []
        for clock in self._active_clock_nodes():
            slot = int(getattr(clock, "clock_event_slot", 0) or 0)
            claimed = bool(getattr(clock, "clock_event_claimed", False))
            if slot > 0 and not claimed:
                specs.append(
                    ModuleSpec(
                        "event",
                        "clock_end_start",
                        f"时钟终止后链{slot}",
                        str(slot),
                    )
                )
        return tuple(specs)

    # ==============================================================
    # Project-scoped custom modules
    # ==============================================================
    def _custom_modules_dir(
        self,
    ) -> Path | None:
        project = (
            self.project_manager
            .current_project()
        )

        if project is None:
            return None

        directory = (
            Path(project.path)
            / "custom_modules"
        )
        directory.mkdir(
            parents=True,
            exist_ok=True,
        )
        return directory

    @staticmethod
    def _read_custom_module_file(
        path: Path,
    ) -> dict:
        payload = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )

        if not isinstance(
            payload,
            dict,
        ):
            raise ValueError(
                "自定义模块文件格式无效。"
            )

        if payload.get(
            "format"
        ) != CUSTOM_MODULE_FORMAT:
            raise ValueError(
                "这不是 UVAF 自定义模块文件。"
            )

        state = payload.get(
            "workspace_state"
        )

        if not isinstance(
            state,
            dict,
        ):
            raise ValueError(
                "自定义模块缺少工作流数据。"
            )

        return payload

    def _custom_module_palette_specs(
        self,
    ) -> tuple[
        ModuleSpec,
        ...
    ]:
        directory = (
            self._custom_modules_dir()
        )

        if directory is None:
            return ()

        result = []

        for path in sorted(
            directory.glob(
                f"*{CUSTOM_MODULE_EXTENSION}"
            ),
            key=lambda item:
            item.name.casefold(),
        ):
            try:
                payload = (
                    self._read_custom_module_file(
                        path
                    )
                )
            except Exception:
                continue

            name = str(
                payload.get(
                    "name"
                )
                or path.stem
            ).strip()

            result.append(
                ModuleSpec(
                    "custom",
                    "custom_module",
                    name,
                    str(path),
                )
            )

        return tuple(
            result
        )

    def _show_custom_module_add_menu(
        self,
        global_pos=None,
    ) -> None:
        if (
            self.project_manager
            .current_project()
            is None
        ):
            return

        menu = QMenu(
            self
        )
        import_action = menu.addAction(
            "导入自定义模块"
        )
        folder_action = menu.addAction(
            "打开自定义模块文件夹"
        )

        chosen = menu.exec(
            global_pos
            if global_pos is not None
            else QCursor.pos()
        )

        if chosen is import_action:
            self.import_custom_module()
        elif chosen is folder_action:
            self.open_custom_module_folder()

    def _unique_custom_module_path(
        self,
        source_name: str,
    ) -> Path | None:
        directory = (
            self._custom_modules_dir()
        )

        if directory is None:
            return None

        stem = (
            Path(source_name).stem
            or "custom_module"
        )
        candidate = (
            directory
            / (
                stem
                + CUSTOM_MODULE_EXTENSION
            )
        )

        if not candidate.exists():
            return candidate

        index = 2

        while True:
            candidate = (
                directory
                / (
                    f"{stem}_{index}"
                    f"{CUSTOM_MODULE_EXTENSION}"
                )
            )

            if not candidate.exists():
                return candidate

            index += 1

    def import_custom_module(
        self,
    ) -> None:
        directory = (
            self._custom_modules_dir()
        )

        if directory is None:
            return

        file_path, _filter = (
            QFileDialog.getOpenFileName(
                self,
                "导入自定义模块",
                str(directory),
                (
                    "UVAF Custom Module "
                    f"(*{CUSTOM_MODULE_EXTENSION})"
                ),
            )
        )

        if not file_path:
            return

        source = Path(
            file_path
        )

        try:
            self._read_custom_module_file(
                source
            )
        except Exception as exc:
            QMessageBox.warning(
                self,
                "导入失败",
                str(exc),
            )
            return

        try:
            if (
                source.resolve().parent
                == directory.resolve()
            ):
                self._module_library_signature = None
                self._refresh_module_library()
                return
        except OSError:
            pass

        destination = (
            self._unique_custom_module_path(
                source.name
            )
        )

        if destination is None:
            return

        try:
            shutil.copy2(
                source,
                destination,
            )
        except Exception as exc:
            QMessageBox.warning(
                self,
                "导入失败",
                str(exc),
            )
            return

        self._module_library_signature = None
        self._refresh_module_library()
        self.runtime_status.setText(
            tr_text(
                f"已导入 {destination.stem}"
            )
        )

    def open_custom_module_folder(
        self,
    ) -> None:
        directory = (
            self._custom_modules_dir()
        )

        if directory is None:
            return

        try:
            os.startfile(
                str(directory)
            )
        except Exception as exc:
            QMessageBox.warning(
                self,
                "无法打开文件夹",
                str(exc),
            )

    def _show_custom_module_context_menu(
        self,
        file_path: str,
        global_pos=None,
    ) -> None:
        path = Path(
            file_path
        )

        menu = QMenu(
            self
        )
        open_action = menu.addAction(
            "打开文件位置"
        )
        delete_action = menu.addAction(
            "删除"
        )

        chosen = menu.exec(
            global_pos
            if global_pos is not None
            else QCursor.pos()
        )

        if chosen is open_action:
            try:
                if os.name == "nt":
                    subprocess.Popen(
                        [
                            "explorer",
                            "/select,",
                            str(path),
                        ]
                    )
                else:
                    os.startfile(
                        str(
                            path.parent
                        )
                    )
            except Exception as exc:
                QMessageBox.warning(
                    self,
                    "无法打开文件位置",
                    str(exc),
                )

        elif chosen is delete_action:
            answer = QMessageBox.question(
                self,
                "删除自定义模块",
                (
                    f"确定删除“{path.stem}”吗？"
                ),
                QMessageBox.Yes
                | QMessageBox.No,
                QMessageBox.No,
            )

            if answer != QMessageBox.Yes:
                return

            try:
                path.unlink(
                    missing_ok=True
                )
            except Exception as exc:
                QMessageBox.warning(
                    self,
                    "删除失败",
                    str(exc),
                )
                return

            self._module_library_signature = None
            self._refresh_module_library()

    def _current_selected_module_items(
        self,
    ) -> list:
        mode = str(
            self.settings.get(
                "workspace.mode",
                "simple",
            )
        )

        if mode == "complex":
            return [
                item
                for item in (
                    self.complex_canvas
                    .complex_scene
                    .selectedItems()
                )
                if isinstance(
                    item,
                    ComplexNode,
                )
            ]

        return [
            item
            for item in (
                self.canvas
                .workflow_scene
                .selectedItems()
            )
            if isinstance(
                item,
                CanvasBlock,
            )
        ]

    def _update_custom_module_button(
        self,
        *_args,
    ) -> None:
        if not hasattr(
            self,
            "create_custom_module_button",
        ):
            return

        self.create_custom_module_button.setVisible(
            (
                self.project_manager
                .current_project()
                is not None
            )
            and bool(
                self._current_selected_module_items()
            )
        )

    @staticmethod
    def _custom_template_reference_keys() -> tuple[
        str,
        ...
    ]:
        return (
            "template",
            "global_anchor_template",
            "fixed_coordinate_anchor",
            "roi_anchor",
        )

    def _bundle_custom_module_templates(
        self,
        state: dict,
    ) -> list[dict]:
        assets = []
        seen = set()

        for record in state.get(
            "nodes",
            [],
        ):
            if not isinstance(
                record,
                dict,
            ):
                continue

            for key in (
                self._custom_template_reference_keys()
            ):
                stored = record.get(
                    key
                )

                if (
                    not isinstance(
                        stored,
                        str,
                    )
                    or not stored
                    or stored in seen
                ):
                    continue

                resolved = (
                    self._resolve_template(
                        stored
                    )
                )

                if not resolved:
                    continue

                path = Path(
                    resolved
                )

                if not path.is_file():
                    continue

                try:
                    encoded = (
                        base64.b64encode(
                            path.read_bytes()
                        )
                        .decode(
                            "ascii"
                        )
                    )
                except OSError:
                    continue

                assets.append(
                    {
                        "reference": stored,
                        "name": path.name,
                        "data_b64": encoded,
                    }
                )
                seen.add(
                    stored
                )

        return assets

    def _selected_state_for_custom_module(
        self,
    ) -> dict | None:
        mode = str(
            self.settings.get(
                "workspace.mode",
                "simple",
            )
        )

        full_state = (
            self._serialize_complex()
            if mode == "complex"
            else self._serialize_simple()
        )

        if mode == "complex":
            selected_ids = {
                item.node_id
                for item in (
                    self.complex_canvas
                    .complex_scene
                    .selectedItems()
                )
                if isinstance(
                    item,
                    ComplexNode,
                )
            }
        else:
            selected_ids = {
                item.node_id
                for item in (
                    self.canvas
                    .workflow_scene
                    .selectedItems()
                )
                if isinstance(
                    item,
                    CanvasBlock,
                )
            }

        if not selected_ids:
            return None

        # Selecting an already-encapsulated custom block means selecting the
        # whole opaque unit, including its hidden executable members.
        record_by_id = {
            str(record.get("id")): record
            for record in full_state.get(
                "nodes",
                [],
            )
            if isinstance(record, dict)
        }
        pending = list(selected_ids)
        while pending:
            owner_id = pending.pop()
            record = record_by_id.get(owner_id)
            if record is None:
                continue
            for member_id in record.get(
                "custom_member_ids",
                [],
            ):
                member_id = str(member_id)
                if member_id and member_id not in selected_ids:
                    selected_ids.add(member_id)
                    pending.append(member_id)

        state = json.loads(
            json.dumps(
                full_state,
                ensure_ascii=False,
            )
        )

        nodes = [
            record
            for record in state.get(
                "nodes",
                [],
            )
            if str(
                record.get(
                    "id"
                )
            )
            in selected_ids
        ]

        if not nodes:
            return None

        # Disconnect references that point outside the selected set.
        for record in nodes:
            if (
                record.get(
                    "parent"
                )
                not in selected_ids
            ):
                record[
                    "parent"
                ] = None

            if (
                record.get(
                    "container"
                )
                not in selected_ids
            ):
                record[
                    "container"
                ] = None

            if isinstance(
                record.get(
                    "logic_slot_roots"
                ),
                list,
            ):
                record[
                    "logic_slot_roots"
                ] = [
                    root
                    if root in selected_ids
                    else None
                    for root in record[
                        "logic_slot_roots"
                    ]
                ]

        state[
            "nodes"
        ] = nodes

        if mode == "complex":
            state[
                "connections"
            ] = [
                connection
                for connection in state.get(
                    "connections",
                    [],
                )
                if (
                    connection.get(
                        "source"
                    )
                    in selected_ids
                    and connection.get(
                        "target"
                    )
                    in selected_ids
                )
            ]
        else:
            state[
                "connections"
            ] = []

        # Store positions relative to the selected group's top-left corner.
        min_x = min(
            float(
                record.get(
                    "x",
                    0,
                )
            )
            for record in nodes
        )
        min_y = min(
            float(
                record.get(
                    "y",
                    0,
                )
            )
            for record in nodes
        )

        for record in nodes:
            record[
                "x"
            ] = (
                float(
                    record.get(
                        "x",
                        0,
                    )
                )
                - min_x
            )
            record[
                "y"
            ] = (
                float(
                    record.get(
                        "y",
                        0,
                    )
                )
                - min_y
            )

        return state

    def create_custom_module_from_selection(
        self,
    ) -> None:
        state = (
            self._selected_state_for_custom_module()
        )

        if state is None:
            QMessageBox.information(
                self,
                "没有选择模块",
                "请先用左键框选或选择要保存的模块。",
            )
            return

        name, ok = QInputDialog.getText(
            self,
            "新建自定义模块",
            "自定义模块名称：",
        )

        if (
            not ok
            or not name.strip()
        ):
            return

        clean_name = re.sub(
            r'[<>:"/\\\\|?*]+',
            "_",
            name.strip(),
        ).strip(
            " ."
        )

        if not clean_name:
            QMessageBox.warning(
                self,
                "名称无效",
                "请输入有效名称。",
            )
            return

        directory = (
            self._custom_modules_dir()
        )

        if directory is None:
            return

        destination = (
            directory
            / (
                clean_name
                + CUSTOM_MODULE_EXTENSION
            )
        )

        if destination.exists():
            answer = QMessageBox.question(
                self,
                "覆盖自定义模块",
                (
                    f"“{clean_name}”已经存在。"
                    "是否覆盖？"
                ),
                QMessageBox.Yes
                | QMessageBox.No,
                QMessageBox.No,
            )

            if answer != QMessageBox.Yes:
                return

        payload = {
            "format": CUSTOM_MODULE_FORMAT,
            "version": 1,
            "name": clean_name,
            "created_at": time.strftime(
                "%Y-%m-%dT%H:%M:%S"
            ),
            "workspace_state": state,
            "assets": (
                self._bundle_custom_module_templates(
                    state
                )
            ),
        }

        try:
            destination.write_text(
                json.dumps(
                    payload,
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        except Exception as exc:
            QMessageBox.warning(
                self,
                "创建失败",
                str(exc),
            )
            return

        self._module_library_signature = None
        self._refresh_module_library()
        self.runtime_status.setText(
            tr_text(
                f"已创建自定义模块 {clean_name}"
            )
        )

    def _prepare_custom_module_state(
        self,
        payload: dict,
        module_path: Path,
        scene_pos: QPointF,
    ) -> dict:
        state = json.loads(
            json.dumps(
                payload[
                    "workspace_state"
                ],
                ensure_ascii=False,
            )
        )

        template_root = (
            self.project_manager
            .project_templates_dir()
        )
        template_root.mkdir(
            parents=True,
            exist_ok=True,
        )

        reference_mapping = {}

        for asset in payload.get(
            "assets",
            [],
        ):
            if not isinstance(
                asset,
                dict,
            ):
                continue

            reference = str(
                asset.get(
                    "reference",
                    ""
                )
            )
            name = Path(
                str(
                    asset.get(
                        "name",
                        ""
                    )
                )
            ).name
            encoded = asset.get(
                "data_b64"
            )

            if (
                not reference
                or not name
                or not isinstance(
                    encoded,
                    str,
                )
            ):
                continue

            safe_prefix = re.sub(
                r"[^A-Za-z0-9_.-]+",
                "_",
                module_path.stem,
            )
            target = (
                template_root
                / (
                    f"{safe_prefix}__"
                    f"{name}"
                )
            )

            if not target.exists():
                try:
                    target.write_bytes(
                        base64.b64decode(
                            encoded
                        )
                    )
                except Exception:
                    continue

            reference_mapping[
                reference
            ] = target.name

        for record in state.get(
            "nodes",
            [],
        ):
            if not isinstance(
                record,
                dict,
            ):
                continue

            for key in (
                self._custom_template_reference_keys()
            ):
                value = record.get(
                    key
                )

                if value in reference_mapping:
                    record[
                        key
                    ] = (
                        reference_mapping[
                            value
                        ]
                    )

        # Every placement receives fresh ids, so one custom module can be
        # dragged into the same project any number of times.
        id_mapping = {
            str(
                record.get(
                    "id"
                )
            ): uuid.uuid4().hex
            for record in state.get(
                "nodes",
                [],
            )
        }

        for record in state.get(
            "nodes",
            [],
        ):
            old_id = str(
                record.get(
                    "id"
                )
            )
            record[
                "id"
            ] = id_mapping[
                old_id
            ]

            parent = record.get(
                "parent"
            )
            record[
                "parent"
            ] = (
                id_mapping.get(
                    str(parent)
                )
                if parent
                else None
            )

            container = record.get(
                "container"
            )
            record[
                "container"
            ] = (
                id_mapping.get(
                    str(container)
                )
                if container
                else None
            )

            if isinstance(
                record.get(
                    "custom_member_ids"
                ),
                list,
            ):
                record[
                    "custom_member_ids"
                ] = [
                    id_mapping.get(
                        str(member_id),
                        str(member_id),
                    )
                    for member_id in record[
                        "custom_member_ids"
                    ]
                    if member_id
                ]

            if isinstance(
                record.get(
                    "logic_slot_roots"
                ),
                list,
            ):
                record[
                    "logic_slot_roots"
                ] = [
                    (
                        id_mapping.get(
                            str(root)
                        )
                        if root
                        else None
                    )
                    for root in record[
                        "logic_slot_roots"
                    ]
                ]

            record[
                "x"
            ] = (
                float(
                    record.get(
                        "x",
                        0,
                    )
                )
                + scene_pos.x()
            )
            record[
                "y"
            ] = (
                float(
                    record.get(
                        "y",
                        0,
                    )
                )
                + scene_pos.y()
            )

        for connection in state.get(
            "connections",
            [],
        ):
            source = connection.get(
                "source"
            )
            target = connection.get(
                "target"
            )

            if source:
                connection[
                    "source"
                ] = id_mapping.get(
                    str(source),
                    str(source),
                )

            if target:
                connection[
                    "target"
                ] = id_mapping.get(
                    str(target),
                    str(target),
                )

        state[
            "_new_node_ids"
        ] = list(
            id_mapping.values()
        )

        return state

    def _drop_custom_module_from_palette(
        self,
        file_path: str,
        scene_pos: QPointF,
        target_mode: str,
    ) -> None:
        path = Path(file_path)

        try:
            payload = self._read_custom_module_file(path)
        except Exception as exc:
            QMessageBox.warning(
                self,
                "无法载入自定义模块",
                str(exc),
            )
            return

        source_mode = str(
            payload.get(
                "workspace_state",
                {},
            ).get(
                "workspace_mode",
                "simple",
            )
        )

        if source_mode != target_mode:
            QMessageBox.information(
                self,
                "模式不匹配",
                (
                    "这个自定义模块创建于"
                    + (
                        "复杂模式"
                        if source_mode == "complex"
                        else "拼图模式"
                    )
                    + "。请切换到对应模式后再拖入。"
                ),
            )
            return

        try:
            state = self._prepare_custom_module_state(
                payload,
                path,
                scene_pos,
            )
            new_ids = set(
                state.pop(
                    "_new_node_ids",
                    [],
                )
            )
            display_name = str(
                payload.get("name")
                or path.stem
            )

            if target_mode == "complex":
                self._load_complex(state)
                scene = self.complex_canvas.complex_scene
                members = {
                    item.node_id: item
                    for item in scene.items()
                    if isinstance(item, ComplexNode)
                    and item.node_id in new_ids
                }

                outer = ComplexNode(
                    category_by_key("custom"),
                    "custom_module_instance",
                    display_name,
                )
                outer.custom_member_ids = list(new_ids)
                outer.custom_source_path = str(path)
                outer.setPos(scene_pos)
                scene.addItem(outer)

            else:
                self._load_simple(state)
                scene = self.canvas.workflow_scene
                members = {
                    item.node_id: item
                    for item in scene.items()
                    if isinstance(item, CanvasBlock)
                    and item.node_id in new_ids
                }

                outer = CanvasBlock(
                    category_by_key("custom"),
                    "custom_module_instance",
                    display_name,
                )
                outer.block_width = 260.0
                outer.custom_member_ids = list(new_ids)
                outer.custom_source_path = str(path)
                scene.add_block(
                    outer,
                    scene_pos,
                )

            # The original components are executable implementation details of
            # the custom module. They remain in the project state, but are not
            # individual workbench objects from the user's point of view.
            for member in members.values():
                member._custom_hidden = True
                member.setSelected(False)
                member.setVisible(False)
                member.setEnabled(False)

            if target_mode == "complex":
                for item in scene.items():
                    if (
                        isinstance(item, ComplexConnection)
                        and item.source.node_id in new_ids
                        and item.target.node_id in new_ids
                    ):
                        item.setVisible(False)
                        item.setEnabled(False)

            scene.clearSelection()
            outer.setVisible(True)
            outer.setEnabled(True)
            outer.setSelected(True)

            if target_mode == "simple":
                scene.try_snap_stack(outer)
            else:
                scene.update_all_roi_bounds()

            self.runtime_status.setText(
                tr_text(
                    f"已放置自定义模块 {display_name}"
                )
            )
            self._update_custom_module_button()

        except Exception as exc:
            QMessageBox.warning(
                self,
                "放置自定义模块失败",
                str(exc),
            )

    def _rebuild_module_library(
        self,
        event_specs: tuple[ModuleSpec, ...],
        custom_specs: tuple[ModuleSpec, ...] = (),
    ) -> None:
        layout = self.module_library_layout
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        for category in CATEGORIES:
            layout.addWidget(
                CategorySection(
                    category,
                    event_specs=(
                        event_specs
                        if category.key == "event"
                        else ()
                    ),
                    custom_specs=(
                        custom_specs
                        if category.key == "custom"
                        else ()
                    ),
                    custom_add_callback=(
                        self._show_custom_module_add_menu
                        if category.key == "custom"
                        else None
                    ),
                    custom_context_callback=(
                        self._show_custom_module_context_menu
                        if category.key == "custom"
                        else None
                    ),
                )
            )
        layout.addStretch()

    def _schedule_module_library_refresh(self, *_args) -> None:
        if hasattr(self, "_module_library_timer"):
            self._module_library_timer.start()

    def _refresh_module_library(self) -> None:
        if not hasattr(self, "canvas"):
            return

        specs = self._event_palette_specs()
        custom_specs = (
            self._custom_module_palette_specs()
        )

        signature = (
            tuple(
                (
                    "event",
                    spec.label,
                    spec.payload_extra,
                )
                for spec in specs
            )
            + tuple(
                (
                    "custom",
                    spec.label,
                    spec.payload_extra,
                    (
                        Path(
                            spec.payload_extra
                        ).stat().st_mtime_ns
                        if Path(
                            spec.payload_extra
                        ).exists()
                        else 0
                    ),
                )
                for spec in custom_specs
            )
        )

        if (
            signature
            == self._module_library_signature
        ):
            return

        self._module_library_signature = (
            signature
        )
        self._rebuild_module_library(
            specs,
            custom_specs,
        )

    def _find_clock_by_slot(self, slot: int):
        for clock in self._active_clock_nodes():
            if int(getattr(clock, "clock_event_slot", 0) or 0) == int(slot):
                return clock
        return None

    def _on_module_dropped(self, node, payload_extra: str = "") -> None:
        if node.module_type == "clock":
            if int(getattr(node, "clock_event_slot", 0) or 0) <= 0:
                node.clock_event_slot = self._next_clock_slot()
            node.clock_event_claimed = False

        elif node.module_type == "clock_end_start":
            try:
                slot = int(str(payload_extra).strip())
            except ValueError:
                slot = 0

            if slot <= 0:
                # Defensive fallback for manually constructed/legacy drags.
                available = [
                    clock
                    for clock in self._active_clock_nodes()
                    if not bool(getattr(clock, "clock_event_claimed", False))
                ]
                if available:
                    slot = int(available[0].clock_event_slot)

            node.clock_event_slot = slot
            if slot > 0:
                clock = self._find_clock_by_slot(slot)
                if clock is not None:
                    clock.clock_event_claimed = True

        self._module_library_signature = None
        self._refresh_module_library()

    def open_project_folder(self) -> None:
        project=self.project_manager.current_project()
        if project is None:return
        try: os.startfile(str(project.path))
        except Exception as exc: QMessageBox.warning(self,"无法打开项目文件夹",str(exc))

    def close_project(self) -> None:
        self.stop_workflows()

        if (
            self.project_manager.current_project()
            is not None
        ):
            self.save_project()

        self.project_manager.set_current(
            None
        )

        self._clear_all_canvases()
        self.project_name_label.setText(
            ""
        )
        self.runtime_status.setText(
            tr_text(
                "就绪"
            )
        )
        self.page_subtitle.setText(
            tr_text(
                "创建或导入项目后开始。"
            )
        )
        self._refresh_project_library()
        self.page_stack.setCurrentWidget(
            self.empty_page
        )
        self._update_custom_module_button()

    def export_project(self) -> None:
        project = (
            self.project_manager.current_project()
        )

        if project is None:
            return

        # Save first so the archive is self-contained and current.
        self.save_project()

        default_export = (
            project.path
            / f"{project.name}{PROJECT_EXTENSION}"
        )

        file_path, _filter = (
            QFileDialog.getSaveFileName(
                self,
                "导出 UVAF 项目",
                str(default_export),
                (
                    f"UVAF Project (*{PROJECT_EXTENSION})"
                ),
            )
        )

        if not file_path:
            return

        try:
            destination = (
                self.project_manager.export_project(
                    Path(file_path)
                )
            )
        except Exception as exc:
            QMessageBox.warning(
                self,
                "导出失败",
                str(exc),
            )
            return

        self.runtime_status.setText(
            tr_text(
                f"已导出 {destination.name}"
            )
        )

    def delete_selected_project(self) -> None:
        item = self.project_list.currentItem()

        if item is None:
            QMessageBox.information(
                self,
                "未选择项目",
                "请先在项目库中选择要删除的项目。",
            )
            return

        project_id = item.data(
            Qt.UserRole
        )

        if not project_id:
            return

        project = (
            self.project_manager.get_project(
                str(project_id)
            )
        )

        if project is None:
            self._refresh_project_library()
            return

        first = QMessageBox.warning(
            self,
            "删除项目",
            (
                f"确定永久删除项目“{project.name}”吗？\n\n"
                "项目内的工作流、模板和资源都会一起删除。"
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if first != QMessageBox.Yes:
            return

        # A second confirmation deliberately requires the user to identify
        # the project by name, making accidental permanent deletion unlikely.
        typed_name, ok = QInputDialog.getText(
            self,
            "确认永久删除",
            (
                "此操作无法撤销。\n"
                f"请输入项目名称“{project.name}”确认："
            ),
        )

        if (
            not ok
            or typed_name.strip()
            != project.name
        ):
            if ok:
                QMessageBox.information(
                    self,
                    "名称不匹配",
                    "项目名称不匹配，未执行删除。",
                )
            return

        was_current = (
            self.project_manager.current_project_id()
            == project.project_id
        )

        try:
            self.project_manager.delete_project(
                project.project_id
            )
        except Exception as exc:
            QMessageBox.warning(
                self,
                "删除失败",
                str(exc),
            )
            return

        if was_current:
            self._clear_all_canvases()
            self.project_name_label.setText(
                ""
            )
            self.runtime_status.setText(
                tr_text(
                    "就绪"
                )
            )
            self.page_subtitle.setText(
                tr_text(
                    "创建或导入项目后开始。"
                )
            )
            self.page_stack.setCurrentWidget(
                self.empty_page
            )

        self._refresh_project_library()

    def _open_selected_library_project(
        self,
        *_args,
    ) -> None:
        item = (
            self.project_list.currentItem()
        )

        if item is None:
            return

        project_id = item.data(
            Qt.UserRole
        )

        if project_id:
            self.open_project(
                str(project_id)
            )

    def open_project(
        self,
        project_id: str,
    ) -> None:
        project = (
            self.project_manager.get_project(
                project_id
            )
        )

        if project is None:
            return

        self.project_manager.set_current(
            project_id
        )
        self.project_name_label.setText(
            project.name
        )
        self.page_stack.setCurrentWidget(
            self.editor_page
        )

        self._clear_all_canvases()
        state = (
            self.project_manager.load_workflow(
                project_id
            )
        )
        self.load_state(state)
        self.reload_settings()
        self._refresh_project_library()
        self._module_library_signature = None
        self._refresh_module_library()
        self._update_custom_module_button()

    def _clear_all_canvases(self) -> None:
        self.canvas.workflow_scene.clear()
        self.complex_canvas.complex_scene.clear()
        self.complex_canvas.complex_scene.pending_port = None
        self._module_library_signature = None
        self._clock_slot_counter = 0
        self._schedule_module_library_refresh()

    # ==============================================================
    # Save / load
    # ==============================================================
    def _localize_template(
        self,
        path_value: str | None,
    ) -> str | None:
        if not path_value:
            return None

        source = Path(path_value)

        if not source.exists():
            return path_value

        template_root = (
            self.project_manager.project_templates_dir()
        )

        try:
            source.resolve().relative_to(
                template_root.resolve()
            )
            return source.name
        except ValueError:
            pass

        destination = (
            template_root
            / source.name
        )

        if destination.exists():
            index = 2

            while True:
                candidate = (
                    template_root
                    / (
                        f"{source.stem}_{index}"
                        f"{source.suffix}"
                    )
                )

                if not candidate.exists():
                    destination = candidate
                    break

                index += 1

        shutil.copy2(
            source,
            destination,
        )
        return destination.name

    def _resolve_template(
        self,
        stored: str | None,
    ) -> str | None:
        if not stored:
            return None

        path = Path(stored)

        if path.is_absolute():
            return str(path)

        return str(
            self.project_manager
            .project_templates_dir()
            / path
        )

    def serialize_state(self) -> dict:
        mode = str(
            self.settings.get(
                "workspace.mode",
                "simple",
            )
        )

        if mode == "complex":
            return self._serialize_complex()

        return self._serialize_simple()

    def _serialize_simple(self) -> dict:
        nodes = []

        for item in (
            self.canvas.workflow_scene.items()
        ):
            if not isinstance(
                item,
                CanvasBlock,
            ):
                continue

            record = {
                "id": item.node_id,
                "category": item.category.key,
                "module_type": item.module_type,
                "text": item.text,
                "custom_member_ids": list(
                    getattr(
                        item,
                        "custom_member_ids",
                        [],
                    )
                ),
                "custom_source_path": str(
                    getattr(
                        item,
                        "custom_source_path",
                        "",
                    )
                ),
                "x": item.pos().x(),
                "y": item.pos().y(),
                "parent": (
                    item.stack_parent.node_id
                    if item.stack_parent
                    is not None
                    else None
                ),
                "container": (
                    item.container_parent.node_id
                    if getattr(
                        item,
                        "container_parent",
                        None,
                    )
                    is not None
                    else None
                ),
                "template": self._localize_template(
                    item.selected_template_path
                ),
                "threshold": item.match_threshold,
                "recognition_methods": list(
                    item.recognition_methods
                ),
                "multi_scale": bool(
                    item.multi_scale
                ),
                "confirm_frames": int(
                    item.confirm_frames
                ),
                "feature_detector": str(
                    item.feature_detector
                ),
                "wait_for_match": bool(
                    getattr(
                        item,
                        "wait_for_match",
                        True,
                    )
                ),
                "wait_timeout_ms": int(
                    getattr(
                        item,
                        "wait_timeout_ms",
                        1000,
                    )
                ),
                "global_anchor_template": self._localize_template(
                    getattr(item, "global_anchor_template_path", None)
                ),
                "global_anchor_roi": list(
                    getattr(item, "global_anchor_roi", (0, 0, 1280, 720))
                ),

                "fixed_coordinate_x": int(
                    getattr(
                        item,
                        "fixed_coordinate_x",
                        0,
                    )
                ),
                "fixed_coordinate_y": int(
                    getattr(
                        item,
                        "fixed_coordinate_y",
                        0,
                    )
                ),
                "fixed_coordinate_anchor": self._localize_template(
                    getattr(
                        item,
                        "fixed_coordinate_anchor_path",
                        None,
                    )
                ),

                "coordinate_modify_x": int(
                    getattr(
                        item,
                        "coordinate_modify_x",
                        0,
                    )
                ),
                "coordinate_modify_y": int(
                    getattr(
                        item,
                        "coordinate_modify_y",
                        0,
                    )
                ),

                "move_advanced": bool(item.move_advanced),
                "move_offset_up": float(item.move_offset_up),
                "move_offset_down": float(item.move_offset_down),
                "move_offset_left": float(item.move_offset_left),
                "move_offset_right": float(item.move_offset_right),
                "move_speed_mode": str(item.move_speed_mode),
                "move_speed_value": float(item.move_speed_value),
                "move_speed_variance": float(item.move_speed_variance),
                "move_random_route": bool(item.move_random_route),

                "click_count": int(item.click_count),
                "click_advanced": bool(item.click_advanced),
                "click_press_duration": float(item.click_press_duration),
                "click_interval": float(item.click_interval),
                "drag_start_x":float(item.drag_start_x),"drag_start_y":float(item.drag_start_y),"drag_end_x":float(item.drag_end_x),"drag_end_y":float(item.drag_end_y),"drag_press_duration":float(item.drag_press_duration),
                "key_name":str(item.key_name),"key_mode":str(item.key_mode),"key_count":int(item.key_count),"key_interval":float(item.key_interval),"key_hold_duration":float(item.key_hold_duration),
                "key_advanced":bool(item.key_advanced),"key_duration_variance":float(item.key_duration_variance),"key_interval_variance":float(item.key_interval_variance),"key_humanized":bool(item.key_humanized),
                "key_text_mode":bool(item.key_text_mode),"key_text":str(item.key_text),
                "executable_path":str(item.executable_path),"delay_value":float(item.delay_value),"delay_unit":str(item.delay_unit),
                "clock_value":float(item.clock_value),"clock_unit":str(item.clock_unit),"clock_behavior":str(item.clock_behavior),
                "clock_event_slot":int(getattr(item,"clock_event_slot",0) or 0),
                "clock_event_claimed":bool(getattr(item,"clock_event_claimed",False)),
            }

            if isinstance(
                item,
                RoiBlock,
            ):
                record["roi"] = item.roi_values()
                record["roi_anchor"] = self._localize_template(item.anchor_template_path)

            if isinstance(
                item,
                LogicContainerBlock,
            ):
                record["loop_count"]=int(item.loop_count)
                record["loop_infinite"]=bool(item.loop_infinite)
                record["logic_slot_roots"]=[
                    root.node_id if root is not None else None
                    for root in item.slot_roots
                ]

            nodes.append(record)

        return {
            "schema_version": 1,
            "workspace_mode": "simple",
            "nodes": nodes,
            "connections": [],
        }

    def _serialize_complex(self) -> dict:
        scene = (
            self.complex_canvas
            .complex_scene
        )

        nodes = []
        connections = []

        for item in scene.items():
            if isinstance(
                item,
                ComplexNode,
            ):
                nodes.append(
                    {
                        "id": item.node_id,
                        "category": item.category.key,
                        "module_type": item.module_type,
                        "text": item.text,
                        "custom_member_ids": list(
                            getattr(
                                item,
                                "custom_member_ids",
                                [],
                            )
                        ),
                        "custom_source_path": str(
                            getattr(
                                item,
                                "custom_source_path",
                                "",
                            )
                        ),
                        "x": item.pos().x(),
                        "y": item.pos().y(),
                        "template": self._localize_template(
                            item.selected_template_path
                        ),
                        "threshold": item.match_threshold,
                        "recognition_methods": list(
                            item.recognition_methods
                        ),
                        "multi_scale": bool(
                            item.multi_scale
                        ),
                        "confirm_frames": int(
                            item.confirm_frames
                        ),
                        "feature_detector": str(
                            item.feature_detector
                        ),
                        "wait_for_match": bool(
                            getattr(
                                item,
                                "wait_for_match",
                                True,
                            )
                        ),
                        "wait_timeout_ms": int(
                            getattr(
                                item,
                                "wait_timeout_ms",
                                1000,
                            )
                        ),
                        "global_anchor_template": self._localize_template(
                            getattr(item, "global_anchor_template_path", None)
                        ),
                        "global_anchor_roi": list(
                            getattr(item, "global_anchor_roi", (0, 0, 1280, 720))
                        ),

                        "fixed_coordinate_x": int(
                            getattr(
                                item,
                                "fixed_coordinate_x",
                                0,
                            )
                        ),
                        "fixed_coordinate_y": int(
                            getattr(
                                item,
                                "fixed_coordinate_y",
                                0,
                            )
                        ),
                        "fixed_coordinate_anchor": self._localize_template(
                            getattr(
                                item,
                                "fixed_coordinate_anchor_path",
                                None,
                            )
                        ),

                        "coordinate_modify_x": int(
                            getattr(
                                item,
                                "coordinate_modify_x",
                                0,
                            )
                        ),
                        "coordinate_modify_y": int(
                            getattr(
                                item,
                                "coordinate_modify_y",
                                0,
                            )
                        ),

                        "move_advanced": bool(item.move_advanced),
                        "move_offset_up": float(item.move_offset_up),
                        "move_offset_down": float(item.move_offset_down),
                        "move_offset_left": float(item.move_offset_left),
                        "move_offset_right": float(item.move_offset_right),
                        "move_speed_mode": str(item.move_speed_mode),
                        "move_speed_value": float(item.move_speed_value),
                        "move_speed_variance": float(item.move_speed_variance),
                        "move_random_route": bool(item.move_random_route),

                        "click_count": int(item.click_count),
                        "click_advanced": bool(item.click_advanced),
                        "click_press_duration": float(item.click_press_duration),
                        "click_interval": float(item.click_interval),
                        "drag_start_x":float(item.drag_start_x),"drag_start_y":float(item.drag_start_y),"drag_end_x":float(item.drag_end_x),"drag_end_y":float(item.drag_end_y),"drag_press_duration":float(item.drag_press_duration),
                        "key_name":str(item.key_name),"key_mode":str(item.key_mode),"key_count":int(item.key_count),"key_interval":float(item.key_interval),"key_hold_duration":float(item.key_hold_duration),
                        "key_advanced":bool(item.key_advanced),"key_duration_variance":float(item.key_duration_variance),"key_interval_variance":float(item.key_interval_variance),"key_humanized":bool(item.key_humanized),
                "key_text_mode":bool(item.key_text_mode),"key_text":str(item.key_text),
                        "executable_path":str(item.executable_path),"delay_value":float(item.delay_value),"delay_unit":str(item.delay_unit),
                        "clock_value":float(item.clock_value),"clock_unit":str(item.clock_unit),"clock_behavior":str(item.clock_behavior),
                        "clock_event_slot":int(getattr(item,"clock_event_slot",0) or 0),
                        "clock_event_claimed":bool(getattr(item,"clock_event_claimed",False)),
                        "loop_count":int(getattr(item,"loop_count",1)),
                        "loop_infinite":bool(getattr(item,"loop_infinite",False)),

                        "roi": item.roi_values_data,
                        "roi_anchor": self._localize_template(
                            item.anchor_template_path
                        ),
                    }
                )

            elif isinstance(
                item,
                ComplexConnection,
            ):
                connections.append(
                    {
                        "source": item.source.node_id,
                        "source_port": item.source_port,
                        "target": item.target.node_id,
                        "target_port": item.target_port,
                    }
                )

        return {
            "schema_version": 1,
            "workspace_mode": "complex",
            "nodes": nodes,
            "connections": connections,
        }

    def save_project(self) -> None:
        if (
            self.project_manager.current_project()
            is None
        ):
            return

        try:
            state = self.serialize_state()
            self.project_manager.save_workflow(
                state
            )
        except Exception as exc:
            QMessageBox.warning(
                self,
                "保存失败",
                str(exc),
            )
            return

        self.runtime_status.setText(
            tr_text(
                "已保存"
            )
        )

    def load_state(
        self,
        state: dict,
    ) -> None:
        stored_mode = str(
            state.get(
                "workspace_mode",
                "simple",
            )
        )

        # Respect project mode when first opening it.
        self.settings.set(
            "workspace.mode",
            stored_mode,
        )

        if stored_mode == "complex":
            self._load_complex(state)
        else:
            self._load_simple(state)

    def _load_simple(
        self,
        state: dict,
    ) -> None:
        scene = (
            self.canvas.workflow_scene
        )

        node_map: dict[
            str,
            CanvasBlock,
        ] = {}
        records = list(
            state.get(
                "nodes",
                [],
            )
        )

        for record in records:
            category = category_by_key(
                str(
                    record.get(
                        "category",
                        "sensing",
                    )
                )
            )
            module_type = str(
                record.get(
                    "module_type",
                    "placeholder",
                )
            )
            text_value = str(
                record.get(
                    "text",
                    "占位",
                )
            )

            if module_type == "roi":
                block = RoiBlock(category,text_value)
            elif module_type in LOGIC_CONTAINER_TYPES:
                block = LogicContainerBlock(category,module_type,text_value)
            else:
                block = CanvasBlock(category,module_type,text_value)

            block.node_id = str(
                record.get(
                    "id",
                    uuid.uuid4().hex,
                )
            )
            block.custom_member_ids = [
                str(value)
                for value in record.get(
                    "custom_member_ids",
                    [],
                )
                if value
            ]
            block.custom_source_path = str(
                record.get(
                    "custom_source_path",
                    "",
                )
                or ""
            )
            if block.module_type == "custom_module_instance":
                block.block_width = 260.0
            block.selected_template_path = (
                self._resolve_template(
                    record.get(
                        "template"
                    )
                )
            )

            if (
                block.module_type
                in VISUAL_MODULE_TYPES
            ):
                block.sync_template_button()

            block.match_threshold = float(
                record.get(
                    "threshold",
                    0.860,
                )
            )
            block.recognition_methods = tuple(
                record.get(
                    "recognition_methods",
                    DEFAULT_METHODS,
                )
            )
            block.multi_scale = bool(
                record.get(
                    "multi_scale",
                    True,
                )
            )
            block.confirm_frames = int(
                record.get(
                    "confirm_frames",
                    1,
                )
            )
            block.feature_detector = str(
                record.get(
                    "feature_detector",
                    "SIFT",
                )
            )
            block.wait_for_match = bool(
                record.get(
                    "wait_for_match",
                    True,
                )
            )
            block.wait_timeout_ms = max(
                1,
                int(
                    record.get(
                        "wait_timeout_ms",
                        1000,
                    )
                ),
            )
            block.global_anchor_template_path = self._resolve_template(
                record.get("global_anchor_template")
            )
            global_roi = record.get("global_anchor_roi")
            if isinstance(global_roi, (list, tuple)) and len(global_roi) == 4:
                block.global_anchor_roi = tuple(int(value) for value in global_roi)
                block.sync_global_controls()

            block.fixed_coordinate_x = int(
                record.get(
                    "fixed_coordinate_x",
                    0,
                )
            )
            block.fixed_coordinate_y = int(
                record.get(
                    "fixed_coordinate_y",
                    0,
                )
            )
            block.fixed_coordinate_anchor_path = self._resolve_template(
                record.get(
                    "fixed_coordinate_anchor"
                )
            )

            block.coordinate_modify_x = int(
                record.get(
                    "coordinate_modify_x",
                    0,
                )
            )
            block.coordinate_modify_y = int(
                record.get(
                    "coordinate_modify_y",
                    0,
                )
            )
            block.sync_coordinate_modify_controls()

            block.move_advanced = bool(
                record.get("move_advanced", False)
            )
            block.move_offset_up = float(
                record.get("move_offset_up", 0.0)
            )
            block.move_offset_down = float(
                record.get("move_offset_down", 0.0)
            )
            block.move_offset_left = float(
                record.get("move_offset_left", 0.0)
            )
            block.move_offset_right = float(
                record.get("move_offset_right", 0.0)
            )
            block.move_speed_mode = str(
                record.get("move_speed_mode", "duration")
            )
            block.move_speed_value = float(
                record.get("move_speed_value", 0.0)
            )
            block.move_speed_variance = float(
                record.get("move_speed_variance", 0.0)
            )
            block.move_random_route = bool(
                record.get("move_random_route", False)
            )

            block.click_count = int(
                record.get("click_count", 1)
            )
            block.click_advanced = bool(
                record.get("click_advanced", False)
            )
            block.click_press_duration = float(
                record.get("click_press_duration", 0.025)
            )
            block.click_interval = float(record.get("click_interval",0.100))
            for attr,default in [("drag_start_x",0.0),("drag_start_y",0.0),("drag_end_x",0.0),("drag_end_y",0.0),("drag_press_duration",0.025),("key_interval",0.0),("key_hold_duration",0.5),("key_duration_variance",0.0),("key_interval_variance",0.0),("delay_value",1.0),("clock_value",60.0)]:
                setattr(block,attr,float(record.get(attr,default)))
            block.key_name=str(record.get("key_name","SPACE")); block.key_mode=str(record.get("key_mode","press")); block.key_count=int(record.get("key_count",1)); block.key_advanced=bool(record.get("key_advanced",False)); block.key_humanized=bool(record.get("key_humanized",False))
            block.key_text_mode=bool(record.get("key_text_mode",False)); block.key_text=str(record.get("key_text",""))
            block.executable_path=str(record.get("executable_path","")); block.delay_unit=str(record.get("delay_unit","seconds")); block.clock_unit=str(record.get("clock_unit","seconds")); block.clock_behavior=str(record.get("clock_behavior","stop"));
            block.clock_event_slot=int(record.get("clock_event_slot",0) or 0); block.clock_event_claimed=bool(record.get("clock_event_claimed",False)); block.sync_inline_action_controls()
            block.loop_count=max(1,int(record.get("loop_count",1)))
            block.loop_infinite=bool(record.get("loop_infinite",False))
            if isinstance(block,LogicContainerBlock):
                block.sync_loop_control()

            if (
                block.threshold_edit
                is not None
            ):
                block.threshold_edit.setText(
                    f"{block.match_threshold:.3f}"
                )

            if isinstance(
                block,
                RoiBlock,
            ):
                roi = record.get(
                    "roi"
                )

                if (
                    isinstance(
                        roi,
                        (list, tuple),
                    )
                    and len(roi) == 4
                ):
                    block.set_roi_values(
                        tuple(
                            int(value)
                            for value in roi
                        )
                    )

                block.anchor_template_path = (
                    self._resolve_template(
                        record.get(
                            "roi_anchor"
                        )
                    )
                )

            scene.addItem(block)
            block.setPos(
                float(
                    record.get(
                        "x",
                        0,
                    )
                ),
                float(
                    record.get(
                        "y",
                        0,
                    )
                ),
            )

            node_map[
                block.node_id
            ] = block

        # First normal stack relations.
        for record in records:
            node = node_map.get(
                str(
                    record.get("id")
                )
            )

            if node is None:
                continue

            parent_id = record.get(
                "parent"
            )

            if parent_id:
                parent = node_map.get(
                    str(parent_id)
                )

                if parent is not None:
                    node.stack_parent = parent
                    parent.stack_child = node

        # Then ROI internal-root relation.
        for record in records:
            node = node_map.get(
                str(
                    record.get("id")
                )
            )

            if node is None:
                continue

            container_id = record.get(
                "container"
            )

            if not container_id:
                continue

            container = node_map.get(
                str(container_id)
            )

            if isinstance(container,RoiBlock):
                node.container_parent=container
                if node.stack_parent is None:
                    container.inner_child=node
            elif isinstance(container,LogicContainerBlock):
                node.container_parent=container

        # Restore exact roots for multi-slot containers.
        for record in records:
            container=node_map.get(str(record.get("id")))
            if not isinstance(container,LogicContainerBlock):
                continue
            roots=record.get("logic_slot_roots",[])
            if not isinstance(roots,(list,tuple)):
                continue
            for index,root_id in enumerate(roots):
                if index>=container.slot_count(): break
                if not root_id: continue
                root=node_map.get(str(root_id))
                if root is not None:
                    container.slot_roots[index]=root
                    root.container_parent=container

        for block in node_map.values():
            if isinstance(block,(RoiBlock,LogicContainerBlock)):
                block.update_dynamic_height()

        hidden_custom_ids: set[str] = set()
        for candidate in node_map.values():
            if candidate.module_type == "custom_module_instance":
                hidden_custom_ids.update(
                    candidate.custom_member_ids
                )

        for member_id in hidden_custom_ids:
            member = node_map.get(
                member_id
            )
            if member is None:
                continue
            member._custom_hidden = True
            member.setSelected(False)
            member.setVisible(False)
            member.setEnabled(False)

        self._reconcile_clock_event_slots()
        self._module_library_signature = None
        self._refresh_module_library()
        self.overview.refresh()

    def _load_complex(
        self,
        state: dict,
    ) -> None:
        scene = (
            self.complex_canvas
            .complex_scene
        )

        node_map: dict[
            str,
            ComplexNode,
        ] = {}

        for record in state.get(
            "nodes",
            [],
        ):
            node = ComplexNode(
                category_by_key(
                    str(
                        record.get(
                            "category",
                            "sensing",
                        )
                    )
                ),
                str(
                    record.get(
                        "module_type",
                        "placeholder",
                    )
                ),
                str(
                    record.get(
                        "text",
                        "占位",
                    )
                ),
            )

            node.node_id = str(
                record.get(
                    "id",
                    uuid.uuid4().hex,
                )
            )
            node.custom_member_ids = [
                str(value)
                for value in record.get(
                    "custom_member_ids",
                    [],
                )
                if value
            ]
            node.custom_source_path = str(
                record.get(
                    "custom_source_path",
                    "",
                )
                or ""
            )
            node.selected_template_path = (
                self._resolve_template(
                    record.get(
                        "template"
                    )
                )
            )
            node.match_threshold = float(
                record.get(
                    "threshold",
                    0.860,
                )
            )
            node.recognition_methods = tuple(
                record.get(
                    "recognition_methods",
                    DEFAULT_METHODS,
                )
            )
            node.multi_scale = bool(
                record.get(
                    "multi_scale",
                    True,
                )
            )
            node.confirm_frames = int(
                record.get(
                    "confirm_frames",
                    1,
                )
            )
            node.feature_detector = str(
                record.get(
                    "feature_detector",
                    "SIFT",
                )
            )
            node.wait_for_match = bool(
                record.get(
                    "wait_for_match",
                    True,
                )
            )
            node.wait_timeout_ms = max(
                1,
                int(
                    record.get(
                        "wait_timeout_ms",
                        1000,
                    )
                ),
            )
            node.global_anchor_template_path = self._resolve_template(
                record.get("global_anchor_template")
            )
            global_roi = record.get("global_anchor_roi")
            if isinstance(global_roi, (list, tuple)) and len(global_roi) == 4:
                node.global_anchor_roi = tuple(int(value) for value in global_roi)

            node.fixed_coordinate_x = int(
                record.get(
                    "fixed_coordinate_x",
                    0,
                )
            )
            node.fixed_coordinate_y = int(
                record.get(
                    "fixed_coordinate_y",
                    0,
                )
            )
            node.fixed_coordinate_anchor_path = self._resolve_template(
                record.get(
                    "fixed_coordinate_anchor"
                )
            )

            node.coordinate_modify_x = int(
                record.get(
                    "coordinate_modify_x",
                    0,
                )
            )
            node.coordinate_modify_y = int(
                record.get(
                    "coordinate_modify_y",
                    0,
                )
            )

            node.move_advanced = bool(
                record.get("move_advanced", False)
            )
            node.move_offset_up = float(
                record.get("move_offset_up", 0.0)
            )
            node.move_offset_down = float(
                record.get("move_offset_down", 0.0)
            )
            node.move_offset_left = float(
                record.get("move_offset_left", 0.0)
            )
            node.move_offset_right = float(
                record.get("move_offset_right", 0.0)
            )
            node.move_speed_mode = str(
                record.get("move_speed_mode", "duration")
            )
            node.move_speed_value = float(
                record.get("move_speed_value", 0.0)
            )
            node.move_speed_variance = float(
                record.get("move_speed_variance", 0.0)
            )
            node.move_random_route = bool(
                record.get("move_random_route", False)
            )

            node.click_count = int(
                record.get("click_count", 1)
            )
            node.click_advanced = bool(
                record.get("click_advanced", False)
            )
            node.click_press_duration = float(
                record.get("click_press_duration", 0.025)
            )
            node.click_interval = float(record.get("click_interval",0.100))
            for attr,default in [("drag_start_x",0.0),("drag_start_y",0.0),("drag_end_x",0.0),("drag_end_y",0.0),("drag_press_duration",0.025),("key_interval",0.0),("key_hold_duration",0.5),("key_duration_variance",0.0),("key_interval_variance",0.0),("delay_value",1.0),("clock_value",60.0)]:
                setattr(node,attr,float(record.get(attr,default)))
            node.key_name=str(record.get("key_name","SPACE")); node.key_mode=str(record.get("key_mode","press")); node.key_count=int(record.get("key_count",1)); node.key_advanced=bool(record.get("key_advanced",False)); node.key_humanized=bool(record.get("key_humanized",False))
            node.key_text_mode=bool(record.get("key_text_mode",False)); node.key_text=str(record.get("key_text",""))
            node.executable_path=str(record.get("executable_path","")); node.delay_unit=str(record.get("delay_unit","seconds")); node.clock_unit=str(record.get("clock_unit","seconds")); node.clock_behavior=str(record.get("clock_behavior","stop"));
            node.clock_event_slot=int(record.get("clock_event_slot",0) or 0); node.clock_event_claimed=bool(record.get("clock_event_claimed",False))
            node.loop_count=max(1,int(record.get("loop_count",1)))
            node.loop_infinite=bool(record.get("loop_infinite",False))

            roi = record.get(
                "roi"
            )

            if (
                isinstance(
                    roi,
                    (list, tuple),
                )
                and len(roi) == 4
            ):
                node.roi_values_data = tuple(
                    int(value)
                    for value in roi
                )

            node.anchor_template_path = (
                self._resolve_template(
                    record.get(
                        "roi_anchor"
                    )
                )
            )

            scene.addItem(node)
            node.setPos(
                float(
                    record.get("x", 0)
                ),
                float(
                    record.get("y", 0)
                ),
            )

            node_map[
                node.node_id
            ] = node

        for connection_data in state.get(
            "connections",
            [],
        ):
            source = node_map.get(
                str(
                    connection_data.get(
                        "source"
                    )
                )
            )
            target = node_map.get(
                str(
                    connection_data.get(
                        "target"
                    )
                )
            )

            if source is None or target is None:
                continue

            source_port = str(
                connection_data.get(
                    "source_port",
                    "output",
                )
            )
            target_port = str(
                connection_data.get(
                    "target_port",
                    "input",
                )
            )

            connection = ComplexConnection(
                source,
                source_port,
                target,
                target_port,
            )

            source.outgoing[
                source_port
            ] = connection
            target.incoming[
                target_port
            ] = connection
            scene.addItem(connection)

        hidden_custom_ids: set[str] = set()
        for candidate in node_map.values():
            if candidate.module_type == "custom_module_instance":
                hidden_custom_ids.update(
                    candidate.custom_member_ids
                )

        for member_id in hidden_custom_ids:
            member = node_map.get(
                member_id
            )
            if member is None:
                continue
            member._custom_hidden = True
            member.setSelected(False)
            member.setVisible(False)
            member.setEnabled(False)

        for item in scene.items():
            if (
                isinstance(item, ComplexConnection)
                and item.source.node_id in hidden_custom_ids
                and item.target.node_id in hidden_custom_ids
            ):
                item.setVisible(False)
                item.setEnabled(False)

        scene.update_all_roi_bounds()

    # ==============================================================
    # Quick template capture
    # ==============================================================
        self._reconcile_clock_event_slots()
        self._module_library_signature = None
        self._refresh_module_library()

    def quick_create_template(self) -> None:
        if (
            self.project_manager.current_project()
            is None
        ):
            return

        capture_result = (
            capture_screen_region_with_image(
                self.window()
            )
        )

        if capture_result is None:
            return

        region, image = (
            capture_result
        )

        name, ok = (
            QInputDialog.getText(
                self,
                "快捷创建模板",
                "模板名称：",
            )
        )

        if not ok or not name.strip():
            return

        safe_name = re.sub(
            r'[<>:"/\\\\|?*]+',
            "_",
            name.strip(),
        )

        if not safe_name.lower().endswith(
            ".png"
        ):
            safe_name += ".png"

        destination = (
            self.project_manager
            .project_templates_dir()
            / safe_name
        )

        if destination.exists():
            answer = QMessageBox.question(
                self,
                "覆盖模板",
                f"{destination.name} 已存在，是否覆盖？",
            )

            if answer != QMessageBox.Yes:
                return

        x, y, width, height = region

        try:
            # IMPORTANT: do NOT take a second screenshot here. `image` is the
            # exact frozen crop the user saw while selecting.
            if not cv2.imwrite(
                str(destination),
                image,
            ):
                raise RuntimeError(
                    "无法写入 PNG 文件。"
                )
        except Exception as exc:
            QMessageBox.warning(
                self,
                "保存失败",
                str(exc),
            )
            return

        self.runtime_status.setText(
            tr_text(
                (
                    f"已创建模板 {destination.name} · "
                    f"{width}×{height} @ ({x},{y})"
                )
            )
        )

    # ==============================================================
    # Runtime
    # ==============================================================
    def reset_current_view(self) -> None:
        mode = str(
            self.settings.get(
                "workspace.mode",
                "simple",
            )
        )

        if mode == "complex":
            self.complex_canvas.reset_view()
        else:
            self.canvas.reset_view()

    def _custom_simple_branches(
        self,
        outer: CanvasBlock,
        excluded: set[int],
    ) -> tuple[
        tuple[ExecutionStep, ...],
        ...
    ]:
        scene = outer.scene()
        if scene is None:
            return ()

        by_id = {
            item.node_id: item
            for item in scene.items()
            if isinstance(item, CanvasBlock)
        }
        member_ids = {
            str(value)
            for value in outer.custom_member_ids
            if str(value) in by_id
        }

        # Nested custom modules stay opaque inside their parent module. Their
        # implementation nodes must not appear as additional top-level roots.
        nested_member_ids: set[str] = set()
        for member_id in member_ids:
            member = by_id[member_id]
            if member.module_type == "custom_module_instance":
                nested_member_ids.update(
                    member.custom_member_ids
                )

        direct_ids = member_ids - nested_member_ids
        roots: list[CanvasBlock] = []

        for member_id in direct_ids:
            member = by_id[member_id]
            parent_inside = (
                member.stack_parent is not None
                and member.stack_parent.node_id in direct_ids
            )
            container = getattr(
                member,
                "container_parent",
                None,
            )
            container_inside = (
                container is not None
                and getattr(
                    container,
                    "node_id",
                    None,
                ) in direct_ids
            )
            if not parent_inside and not container_inside:
                roots.append(member)

        roots.sort(
            key=lambda item: (
                item.scenePos().y(),
                item.scenePos().x(),
            )
        )

        branches: list[tuple[ExecutionStep, ...]] = []
        consumed: set[str] = set()

        def chain_from(first: CanvasBlock | None) -> tuple[ExecutionStep, ...]:
            steps: list[ExecutionStep] = []
            current = first
            local_seen: set[str] = set()
            while (
                current is not None
                and current.node_id in direct_ids
                and current.node_id not in local_seen
            ):
                local_seen.add(current.node_id)
                consumed.add(current.node_id)
                excluded.add(id(current))
                steps.append(
                    self._step_from_block(
                        current,
                        excluded,
                    )
                )
                current = current.stack_child
            return tuple(steps)

        for root in roots:
            if root.node_id in consumed:
                continue

            if self._is_event_root_type(
                root.module_type
            ):
                branch = chain_from(
                    root.stack_child
                )
            else:
                branch = chain_from(root)

            if branch:
                branches.append(branch)

        return tuple(branches)

    def _step_from_block(
        self,
        block: CanvasBlock,
        excluded: set[int],
    ) -> ExecutionStep:
        if block.module_type == "custom_module_instance":
            return ExecutionStep(
                module_type="custom_module_instance",
                label=block.text,
                branches=self._custom_simple_branches(
                    block,
                    excluded,
                ),
            )

        if isinstance(
            block,
            LogicContainerBlock,
        ):
            branches=[]
            for slot_index in range(block.slot_count()):
                branch_steps=[]
                current=block.slot_roots[slot_index]
                while current is not None:
                    excluded.add(id(current))
                    branch_steps.append(
                        self._step_from_block(
                            current,
                            excluded,
                        )
                    )
                    current=current.stack_child
                branches.append(tuple(branch_steps))

            return ExecutionStep(
                module_type=block.module_type,
                label=block.text,
                loop_count=max(1,int(block.loop_count)),
                loop_infinite=bool(block.loop_infinite),
                branches=tuple(branches),
            )

        if isinstance(
            block,
            RoiBlock,
        ):
            children: list[
                ExecutionStep
            ] = []

            current = (
                block.inner_child
            )

            while current is not None:
                excluded.add(
                    id(current)
                )
                children.append(
                    self._step_from_block(
                        current,
                        excluded,
                    )
                )
                current = (
                    current.stack_child
                )

            return ExecutionStep(
                module_type="roi",
                label="ROI",
                roi=block.roi_values(),
                roi_anchor_template_path=(
                    block.anchor_template_path
                ),
                children=tuple(children),
            )

        if block.module_type == "global_anchor_roi":
            return ExecutionStep(
                module_type="global_anchor_roi",
                label=block.text,
                global_anchor_template_path=block.global_anchor_template_path,
                global_anchor_roi=block.global_anchor_roi,
            )

        return ExecutionStep(
            module_type=block.module_type,
            label=block.text,
            template_path=(
                block.selected_template_path
            ),
            match_threshold=(
                block.match_threshold
            ),
            recognition_methods=tuple(
                block.recognition_methods
            ),
            multi_scale=bool(
                block.multi_scale
            ),
            confirm_frames=int(
                block.confirm_frames
            ),
            feature_detector=str(
                block.feature_detector
            ),
            wait_for_match=bool(
                block.wait_for_match
            ),
            wait_timeout_ms=max(
                1,
                int(
                    block.wait_timeout_ms
                ),
            ),

            fixed_coordinate_x=int(
                block.fixed_coordinate_x
            ),
            fixed_coordinate_y=int(
                block.fixed_coordinate_y
            ),
            fixed_coordinate_anchor_path=(
                block.fixed_coordinate_anchor_path
            ),
            coordinate_modify_x=int(
                block.coordinate_modify_x
            ),
            coordinate_modify_y=int(
                block.coordinate_modify_y
            ),

            move_advanced=bool(
                block.move_advanced
            ),
            move_offset_up=float(
                block.move_offset_up
            ),
            move_offset_down=float(
                block.move_offset_down
            ),
            move_offset_left=float(
                block.move_offset_left
            ),
            move_offset_right=float(
                block.move_offset_right
            ),
            move_speed_mode=str(
                block.move_speed_mode
            ),
            move_speed_value=float(
                block.move_speed_value
            ),
            move_speed_variance=float(
                block.move_speed_variance
            ),
            move_random_route=bool(
                block.move_random_route
            ),

            click_count=int(
                block.click_count
            ),
            click_advanced=bool(
                block.click_advanced
            ),
            click_press_duration=float(block.click_press_duration),
            click_interval=float(block.click_interval),
            drag_start_x=float(block.drag_start_x),drag_start_y=float(block.drag_start_y),drag_end_x=float(block.drag_end_x),drag_end_y=float(block.drag_end_y),drag_press_duration=float(block.drag_press_duration),
            key_name=str(block.key_name),key_mode=str(block.key_mode),key_count=int(block.key_count),key_interval=float(block.key_interval),key_hold_duration=float(block.key_hold_duration),
            key_advanced=bool(block.key_advanced),key_duration_variance=float(block.key_duration_variance),key_interval_variance=float(block.key_interval_variance),key_humanized=bool(block.key_humanized),
            key_text_mode=bool(block.key_text_mode),key_text=str(block.key_text),
            executable_path=str(block.executable_path),delay_value=float(block.delay_value),delay_unit=str(block.delay_unit),
            clock_value=float(block.clock_value),clock_unit=str(block.clock_unit),clock_behavior=str(block.clock_behavior),
            clock_event_slot=int(getattr(block,"clock_event_slot",0) or 0),
        )

    @staticmethod
    def _is_event_root_type(
        module_type: str,
    ) -> bool:
        return module_type in EVENT_ROOT_MODULE_TYPES

    def _is_simple_block_energized(
        self,
        block: CanvasBlock,
    ) -> bool:
        """
        A simple-mode block is energized iff following stack_parent upward
        eventually reaches an event-root module.

        This is intentionally independent from geometric proximity: merely
        placing a block near a chain never activates it.
        """
        seen: set[int] = set()
        current: CanvasBlock | None = block

        while current is not None:
            marker = id(current)

            if marker in seen:
                return False

            seen.add(marker)

            if self._is_event_root_type(
                current.module_type
            ):
                return True

            current = current.stack_parent

        return False

    def _build_chain_snapshot(
        self,
        start_block: CanvasBlock,
    ) -> list[ExecutionStep]:
        if not self._is_event_root_type(
            start_block.module_type
        ):
            return []

        steps: list[
            ExecutionStep
        ] = []

        excluded: set[int] = {
            id(start_block)
        }

        current = (
            start_block.stack_child
        )

        while current is not None:
            excluded.add(
                id(current)
            )
            steps.append(
                self._step_from_block(
                    current,
                    excluded,
                )
            )
            current = (
                current.stack_child
            )

        return steps

    def _is_global_step(
        self,
        step: ExecutionStep,
    ) -> bool:
        return step.module_type in GLOBAL_MODULE_TYPES

    def _split_global_prefix(
        self,
        steps: list[ExecutionStep],
    ) -> tuple[
        list[ExecutionStep],
        list[ExecutionStep],
    ]:
        """
        Separate reachable global modules from ordinary execution.

        Global settings are activated because they belong to an event-powered
        chain, not because they happen to be the first blocks geometrically.
        Detached global modules are never present in `steps` and therefore
        remain unpowered.
        """
        globals_part: list[
            ExecutionStep
        ] = []
        normal_part: list[
            ExecutionStep
        ] = []

        for step in steps:
            if self._is_global_step(
                step
            ):
                globals_part.append(
                    step
                )
            else:
                normal_part.append(
                    step
                )

        return (
            globals_part,
            normal_part,
        )


    def _on_run_button_clicked(
        self,
        _checked: bool = False,
    ) -> None:
        """Qt-safe entry point for the Run button.

        Keep UI signal handling separate from the runtime implementation.
        If a later module refactor breaks the runtime contract, the error is
        reported visibly instead of being swallowed by Qt's signal dispatch.
        """
        try:
            self.run_workflows()
        except Exception as exc:
            message = (
                "运行失败："
                f"{type(exc).__name__}: {exc}"
            )
            if hasattr(
                self,
                "runtime_status",
            ):
                self.runtime_status.setText(
                    tr_text(message)
                )
            self.logger.error(
                message,
                source="workspace",
            )

    def run_workflows(self) -> None:
        if (
            self._active_chains > 0
            or self._global_runtime_active
        ):
            return

        self._vision_clear_debug()

        self._stop_event.clear()
        self._event_chain_cancel.clear()

        mode = str(
            self.settings.get(
                "workspace.mode",
                "simple",
            )
        )

        if mode == "complex":
            self._run_complex_workflows()
            return

        starts = [
            item
            for item in (
                self.canvas
                .workflow_scene
                .items()
            )
            if isinstance(
                item,
                CanvasBlock,
            )
            and item.module_type
            == "start"
            and item.stack_parent
            is None
            and not getattr(
                item,
                "_custom_hidden",
                False,
            )
        ]

        starts.sort(key=lambda block:(block.scenePos().y(),block.scenePos().x()))

        clock_events=[item for item in self.canvas.workflow_scene.items() if isinstance(item,CanvasBlock) and item.module_type=="clock_end_start" and item.stack_parent is None and not getattr(item,"_custom_hidden",False)]
        self._clock_event_chains = {}
        for event_block in clock_events:
            slot = int(getattr(event_block,"clock_event_slot",0) or 0)
            if slot > 0:
                self._clock_event_chains[slot] = self._build_chain_snapshot(event_block)

        if not starts:
            self._no_start()
            return

        global_steps: list[
            ExecutionStep
        ] = []
        normal_chains: list[
            list[ExecutionStep]
        ] = []

        for start_block in starts:
            full_chain = (
                self._build_chain_snapshot(
                    start_block
                )
            )

            globals_part, normal_part = (
                self._split_global_prefix(
                    full_chain
                )
            )

            global_steps.extend(
                globals_part
            )

            if normal_part:
                normal_chains.append(
                    normal_part
                )

        if not self._activate_global_steps(
            global_steps
        ):
            self.stop_workflows()
            return

        self.stop_button.setEnabled(
            True
        )

        if normal_chains:
            self._launch_chains(
                normal_chains
            )
            return

        if self._global_runtime_active:
            self.run_button.setEnabled(
                False
            )
            self.runtime_status.setText(
                tr_text(
                    "全局设置运行中"
                )
            )
            return

        self.runtime_status.setText(
            tr_text(
                "没有可执行模块"
            )
        )

    def _complex_branch_steps(
        self,
        node: ComplexNode,
        port_name: str,
    ) -> tuple[ExecutionStep, ...]:
        connection=node.outgoing.get(port_name)
        if connection is None:
            return ()

        steps=[]
        current=connection.target
        visited={node.node_id}

        while current is not None:
            if current.node_id in visited:
                break
            visited.add(current.node_id)
            steps.append(
                self._execution_step_from_complex_node(
                    current
                )
            )
            next_connection=current.outgoing.get("output")
            if next_connection is None:
                break
            current=next_connection.target

        return tuple(steps)

    def _complex_chain_within(
        self,
        first: ComplexNode | None,
        allowed_ids: set[str],
    ) -> tuple[ExecutionStep, ...]:
        steps: list[ExecutionStep] = []
        current = first
        visited: set[str] = set()

        while (
            current is not None
            and current.node_id in allowed_ids
            and current.node_id not in visited
        ):
            visited.add(current.node_id)
            steps.append(
                self._execution_step_from_complex_node(
                    current
                )
            )
            connection = current.outgoing.get(
                "output"
            )
            if connection is None:
                break
            target = connection.target
            if target.node_id not in allowed_ids:
                break
            current = target

        return tuple(steps)

    def _custom_complex_branches(
        self,
        outer: ComplexNode,
    ) -> tuple[
        tuple[ExecutionStep, ...],
        ...
    ]:
        scene = outer.scene()
        if scene is None:
            return ()

        by_id = {
            item.node_id: item
            for item in scene.items()
            if isinstance(item, ComplexNode)
        }
        member_ids = {
            str(value)
            for value in outer.custom_member_ids
            if str(value) in by_id
        }
        nested_member_ids: set[str] = set()

        for member_id in member_ids:
            member = by_id[member_id]
            if member.module_type == "custom_module_instance":
                nested_member_ids.update(
                    member.custom_member_ids
                )

        direct_ids = member_ids - nested_member_ids
        branches: list[tuple[ExecutionStep, ...]] = []

        start_nodes = [
            by_id[member_id]
            for member_id in direct_ids
            if by_id[member_id].module_type in {
                "start",
                "clock_end_start",
            }
        ]

        for start in start_nodes:
            for port in (
                "output",
                "output_2",
                "output_3",
            ):
                connection = start.outgoing.get(port)
                if (
                    connection is None
                    or connection.target.node_id not in direct_ids
                ):
                    continue
                branch = self._complex_chain_within(
                    connection.target,
                    direct_ids,
                )
                if branch:
                    branches.append(branch)

        if branches:
            return tuple(branches)

        # No explicit event root: preserve disconnected selected chains as
        # parallel internal roots of the opaque custom block.
        roots: list[ComplexNode] = []
        for member_id in direct_ids:
            member = by_id[member_id]
            if member.module_type in {
                "start",
                "clock_end_start",
            }:
                continue
            has_internal_input = any(
                connection.source.node_id in direct_ids
                for connection in member.incoming.values()
            )
            if not has_internal_input:
                roots.append(member)

        roots.sort(
            key=lambda item: (
                item.scenePos().y(),
                item.scenePos().x(),
            )
        )
        for root in roots:
            branch = self._complex_chain_within(
                root,
                direct_ids,
            )
            if branch:
                branches.append(branch)

        return tuple(branches)

    def _execution_step_from_complex_node(
        self,
        target: ComplexNode,
    ) -> ExecutionStep:
        if target.module_type == "custom_module_instance":
            return ExecutionStep(
                module_type="custom_module_instance",
                label=target.text,
                branches=self._custom_complex_branches(
                    target
                ),
            )

        if target.module_type in LOGIC_CONTAINER_TYPES:
            if target.module_type=="loop":
                branch_ports=("body_output",)
            elif target.module_type in {"loop_until","logic_if"}:
                branch_ports=("branch_a_output","branch_b_output")
            else:
                branch_ports=("branch_a_output","branch_b_output","branch_c_output")

            return ExecutionStep(
                module_type=target.module_type,
                label=target.text,
                loop_count=max(1,int(target.loop_count)),
                loop_infinite=bool(target.loop_infinite),
                branches=tuple(
                    self._complex_branch_steps(
                        target,
                        port_name,
                    )
                    for port_name in branch_ports
                ),
            )

        if (
            target.module_type
            == "global_anchor_roi"
        ):
            return ExecutionStep(
                module_type="global_anchor_roi",
                label=target.text,
                global_anchor_template_path=(
                    target.global_anchor_template_path
                ),
                global_anchor_roi=(
                    target.global_anchor_roi
                ),
            )

        if target.module_type == "roi":
            return ExecutionStep(
                module_type="roi",
                label="ROI",
                roi=target.roi_values_data,
                roi_anchor_template_path=(
                    target.anchor_template_path
                ),
                children=(),
            )

        return ExecutionStep(
            module_type=target.module_type,
            label=target.text,
            template_path=(
                target.selected_template_path
            ),
            match_threshold=(
                target.match_threshold
            ),
            recognition_methods=tuple(
                target.recognition_methods
            ),
            multi_scale=bool(
                target.multi_scale
            ),
            confirm_frames=int(
                target.confirm_frames
            ),
            feature_detector=str(
                target.feature_detector
            ),
            wait_for_match=bool(
                target.wait_for_match
            ),
            wait_timeout_ms=max(
                1,
                int(
                    target.wait_timeout_ms
                ),
            ),
            fixed_coordinate_x=int(
                target.fixed_coordinate_x
            ),
            fixed_coordinate_y=int(
                target.fixed_coordinate_y
            ),
            fixed_coordinate_anchor_path=(
                target.fixed_coordinate_anchor_path
            ),
            coordinate_modify_x=int(
                target.coordinate_modify_x
            ),
            coordinate_modify_y=int(
                target.coordinate_modify_y
            ),
            move_advanced=bool(
                target.move_advanced
            ),
            move_offset_up=float(
                target.move_offset_up
            ),
            move_offset_down=float(
                target.move_offset_down
            ),
            move_offset_left=float(
                target.move_offset_left
            ),
            move_offset_right=float(
                target.move_offset_right
            ),
            move_speed_mode=str(
                target.move_speed_mode
            ),
            move_speed_value=float(
                target.move_speed_value
            ),
            move_speed_variance=float(
                target.move_speed_variance
            ),
            move_random_route=bool(
                target.move_random_route
            ),
            click_count=int(
                target.click_count
            ),
            click_advanced=bool(
                target.click_advanced
            ),
            click_press_duration=float(target.click_press_duration),
            click_interval=float(target.click_interval),
            drag_start_x=float(target.drag_start_x),drag_start_y=float(target.drag_start_y),drag_end_x=float(target.drag_end_x),drag_end_y=float(target.drag_end_y),drag_press_duration=float(target.drag_press_duration),
            key_name=str(target.key_name),key_mode=str(target.key_mode),key_count=int(target.key_count),key_interval=float(target.key_interval),key_hold_duration=float(target.key_hold_duration),
            key_advanced=bool(target.key_advanced),key_duration_variance=float(target.key_duration_variance),key_interval_variance=float(target.key_interval_variance),key_humanized=bool(target.key_humanized),
            key_text_mode=bool(target.key_text_mode),key_text=str(target.key_text),
            executable_path=str(target.executable_path),delay_value=float(target.delay_value),delay_unit=str(target.delay_unit),
            clock_value=float(target.clock_value),clock_unit=str(target.clock_unit),clock_behavior=str(target.clock_behavior),
            clock_event_slot=int(getattr(target,"clock_event_slot",0) or 0),
        )

    def _run_complex_workflows(self) -> None:
        scene = (
            self.complex_canvas
            .complex_scene
        )

        starts = [
            item
            for item in scene.items()
            if isinstance(
                item,
                ComplexNode,
            )
            and item.module_type
            == "start"
            and not getattr(
                item,
                "_custom_hidden",
                False,
            )
        ]

        clock_event_nodes = [
            item
            for item in scene.items()
            if isinstance(item, ComplexNode)
            and item.module_type == "clock_end_start"
            and not getattr(
                item,
                "_custom_hidden",
                False,
            )
        ]

        self._clock_event_chains = {}

        for event_node in clock_event_nodes:
            slot = int(getattr(event_node,"clock_event_slot",0) or 0)
            if slot <= 0:
                continue

            chain_steps: list[ExecutionStep] = []
            current = event_node
            visited = {event_node.node_id}

            while current.outgoing:
                connection = (
                    current.outgoing.get("output")
                    or current.outgoing.get("output_2")
                    or current.outgoing.get("output_3")
                )
                if connection is None:
                    break
                target = connection.target
                if target.node_id in visited:
                    break
                visited.add(target.node_id)
                chain_steps.append(
                    self._execution_step_from_complex_node(target)
                )
                current = target

            self._clock_event_chains[slot] = chain_steps

        if not starts:
            self._no_start()
            return

        global_steps: list[
            ExecutionStep
        ] = []
        normal_chains: list[
            list[ExecutionStep]
        ] = []

        for start in starts:
            for start_port in (
                "output",
                "output_2",
                "output_3",
            ):
                first_connection = (
                    start.outgoing.get(
                        start_port
                    )
                )

                if first_connection is None:
                    continue

                steps: list[
                    ExecutionStep
                ] = []
                visited: set[str] = {
                    start.node_id
                }

                current = (
                    first_connection.target
                )

                while current is not None:
                    if current.node_id in visited:
                        break

                    visited.add(
                        current.node_id
                    )

                    steps.append(
                        self._execution_step_from_complex_node(
                            current
                        )
                    )

                    # Primary output remains the sequential continuation.
                    # output_2/output_3 are available for separate branches
                    # from Start and for future branching semantics.
                    next_connection = (
                        current.outgoing.get(
                            "output"
                        )
                    )

                    if next_connection is None:
                        break

                    current = (
                        next_connection.target
                    )

                globals_part, normal_part = (
                    self._split_global_prefix(
                        steps
                    )
                )

                global_steps.extend(
                    globals_part
                )

                if normal_part:
                    normal_chains.append(
                        normal_part
                    )

        if not self._activate_global_steps(
            global_steps
        ):
            self.stop_workflows()
            return

        self.stop_button.setEnabled(
            True
        )

        if normal_chains:
            self._launch_chains(
                normal_chains
            )
            return

        if self._global_runtime_active:
            self.run_button.setEnabled(
                False
            )
            self.runtime_status.setText(
                tr_text(
                    "全局设置运行中"
                )
            )
            return

        self.runtime_status.setText(
            tr_text(
                "没有可执行模块"
            )
        )

    def _no_start(self) -> None:
        message = "没有可运行的起始模块。"
        self.runtime_status.setText(
            message
        )
        self.logger.warning(
            message,
            source="workspace",
        )




