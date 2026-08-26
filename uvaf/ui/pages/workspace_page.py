from __future__ import annotations

from dataclasses import dataclass
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


MIME_BLOCK = "application/x-uvaf-block"
CUSTOM_MODULE_EXTENSION = ".uvafmodule"
CUSTOM_MODULE_FORMAT = "UVAF_CUSTOM_MODULE"

# Every two executable modules are separated by at least 5 ms.
MODULE_MIN_GAP_SECONDS = 0.005


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


@dataclass(frozen=True)
class BlockCategory:
    key: str
    title: str
    description: str
    color: str
    translucent: bool = True


CATEGORIES = (
    BlockCategory("sensing", "感知", "检测画面、窗口或状态，并输出结果。", "#49A96C", False),
    BlockCategory("action", "动作", "根据状态执行点击、键盘等操作。", "#D5A52F", False),
    BlockCategory("control", "逻辑", "负责 ROI、条件、分支、循环和流程顺序。", "#D57A33", False),
    BlockCategory("data", "数据", "保存、转换和比较流程中的数据。", "#4C8FC5", False),
    BlockCategory("debug", "调试", "检查流程中的数据与运行状态。", "#6F7C8C", False),
    BlockCategory("global", "全局设置", "连接到起始执行链后，对后续流程全局生效。", "#B85C6F", False),
    BlockCategory("custom", "自定义模块", "当前项目中的可复用模块组合。", "#548F8B", False),
    BlockCategory("event", "事件", "定义流程开始和触发方式。", "#8C65B3", False),
)



VISUAL_MODULE_TYPES = {
    "findtemplate",
    "template_count",
    "lock_template",
    "scan_until_found",
}

ACTION_MODULE_TYPES = {
    "move_to",
    "drag",
    "click",
    "keyboard_input",
    "launch_exe",
    "delay_wait",
}

LOGIC_CONTAINER_TYPES = {
    "loop",
    "loop_until",
    "logic_if",
    "logic_or",
    "logic_nor",
    "logic_and",
}

CONDITION_LOGIC_TYPES = {
    "logic_if",
    "logic_or",
    "logic_nor",
    "logic_and",
}


def module_output_type(
    module_type: str,
) -> str | None:
    if module_type in {
        "findtemplate",
        "lock_template",
        "scan_until_found",
        "move_to",
        "fixed_coordinate",
        "coordinate_modify",
    }:
        return "coordinate"

    if module_type == "template_count":
        return "number"

    # inspect_input is a transparent pass-through. Its actual runtime type
    # comes from upstream, so static validation treats it as wildcard.
    if module_type == "inspect_input":
        return None

    return None


def module_input_type(
    module_type: str,
) -> str | None:
    if module_type in {
        "move_to",
        "coordinate_modify",
    }:
        return "coordinate"

    # Accept every runtime data type.
    if module_type == "inspect_input":
        return None

    return None


def data_types_compatible(
    source_type: str | None,
    target_type: str | None,
) -> bool:
    if (
        source_type is None
        or target_type is None
    ):
        return True

    return source_type == target_type


def category_by_key(key: str) -> BlockCategory:
    for category in CATEGORIES:
        if category.key == key:
            return category
    return CATEGORIES[0]


@dataclass(frozen=True)
class ModuleSpec:
    category_key: str
    module_type: str
    label: str
    payload_extra: str = ""


@dataclass(frozen=True)
class ExecutionStep:
    module_type: str
    label: str
    template_path: str | None = None
    match_threshold: float = 0.860
    recognition_methods: tuple[str, ...] = DEFAULT_METHODS
    multi_scale: bool = True
    confirm_frames: int = 1
    feature_detector: str = "SIFT"

    # Scan Template completion policy.
    # When enabled, the module itself remains RUNNING until a match appears
    # or this timeout expires. The downstream module cannot start earlier.
    wait_for_match: bool = True
    wait_timeout_ms: int = 1000

    roi: tuple[int, int, int, int] | None = None
    roi_anchor_template_path: str | None = None
    global_anchor_template_path: str | None = None
    global_anchor_roi: tuple[int, int, int, int] | None = None

    # Fixed coordinate data
    fixed_coordinate_x: int = 0
    fixed_coordinate_y: int = 0
    fixed_coordinate_anchor_path: str | None = None

    # Coordinate modifier data
    coordinate_modify_x: int = 0
    coordinate_modify_y: int = 0

    # Mouse movement
    move_advanced: bool = False
    move_offset_up: float = 0.0
    move_offset_down: float = 0.0
    move_offset_left: float = 0.0
    move_offset_right: float = 0.0
    move_speed_mode: str = "duration"
    move_speed_value: float = 0.0
    move_speed_variance: float = 0.0
    move_random_route: bool = False

    # Click
    click_count: int = 1
    click_advanced: bool = False
    click_press_duration: float = 0.025
    click_interval: float = 0.100

    drag_start_x: float = 0.0
    drag_start_y: float = 0.0
    drag_end_x: float = 0.0
    drag_end_y: float = 0.0
    drag_press_duration: float = 0.025

    key_name: str = "SPACE"
    key_mode: str = "press"
    key_count: int = 1
    key_interval: float = 0.0
    key_hold_duration: float = 0.500
    key_advanced: bool = False
    key_duration_variance: float = 0.0
    key_interval_variance: float = 0.0
    key_humanized: bool = False
    key_text_mode: bool = False
    key_text: str = ""

    executable_path: str = ""

    delay_value: float = 1.0
    delay_unit: str = "seconds"

    clock_value: float = 60.0
    clock_unit: str = "seconds"
    clock_behavior: str = "stop"
    clock_event_slot: int = 0

    loop_count: int = 1
    loop_infinite: bool = False
    branches: tuple[tuple["ExecutionStep", ...], ...] = ()

    children: tuple["ExecutionStep", ...] = ()


class WorkspaceRuntimeSignals(QObject):
    message = Signal(str)
    chain_finished = Signal()
    clock_expired = Signal(str, int)


IMAGE_FILTER = (
    "Image files (*.png *.jpg *.jpeg *.bmp *.webp);;"
    "All files (*.*)"
)

SUPPORTED_TEMPLATE_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".bmp",
    ".webp",
}


def library_templates() -> list[Path]:
    directory = templates_dir()
    directory.mkdir(parents=True, exist_ok=True)

    return sorted(
        (
            path
            for path in directory.iterdir()
            if path.is_file()
            and path.suffix.lower() in SUPPORTED_TEMPLATE_SUFFIXES
        ),
        key=lambda path: path.name.casefold(),
    )


def unique_library_path(source: Path) -> Path:
    directory = templates_dir()
    directory.mkdir(parents=True, exist_ok=True)

    candidate = directory / source.name
    if not candidate.exists():
        return candidate

    index = 2
    while True:
        candidate = directory / f"{source.stem}_{index}{source.suffix}"
        if not candidate.exists():
            return candidate
        index += 1



_TEMPLATE_CACHE: dict[
    tuple[str, int],
    np.ndarray,
] = {}


def _load_template_cached(
    template_path: str,
) -> np.ndarray:
    path = Path(template_path)

    try:
        stamp = path.stat().st_mtime_ns
    except OSError:
        stamp = 0

    key = (
        str(path.resolve()),
        stamp,
    )

    cached = _TEMPLATE_CACHE.get(key)

    if cached is not None:
        return cached

    template = cv2.imread(
        str(path),
        cv2.IMREAD_COLOR,
    )

    if template is None:
        raise RuntimeError(
            f"无法读取模板：{template_path}"
        )

    # Keep only the current version of this template in memory.
    stale_keys = [
        old_key
        for old_key in _TEMPLATE_CACHE
        if old_key[0] == key[0]
        and old_key != key
    ]

    for old_key in stale_keys:
        _TEMPLATE_CACHE.pop(
            old_key,
            None,
        )

    _TEMPLATE_CACHE[key] = template
    return template


def _color_similarity(
    template: np.ndarray,
    region: np.ndarray,
    mode: str,
) -> float:
    if template.shape != region.shape:
        return 0.0

    if mode == "rgb_count":
        diff = cv2.absdiff(
            template,
            region,
        )

        # RGBCount-style tolerant per-pixel color agreement.
        mask = np.max(
            diff,
            axis=2,
        ) <= 32

        return float(
            mask.mean()
        )

    if mode == "hsv_count":
        template_hsv = cv2.cvtColor(
            template,
            cv2.COLOR_BGR2HSV,
        )
        region_hsv = cv2.cvtColor(
            region,
            cv2.COLOR_BGR2HSV,
        )

        hue_a = template_hsv[:, :, 0].astype(
            np.int16
        )
        hue_b = region_hsv[:, :, 0].astype(
            np.int16
        )

        hue_diff = np.abs(
            hue_a - hue_b
        )
        hue_diff = np.minimum(
            hue_diff,
            180 - hue_diff,
        )

        sat_diff = np.abs(
            template_hsv[:, :, 1].astype(np.int16)
            - region_hsv[:, :, 1].astype(np.int16)
        )
        val_diff = np.abs(
            template_hsv[:, :, 2].astype(np.int16)
            - region_hsv[:, :, 2].astype(np.int16)
        )

        mask = (
            (hue_diff <= 10)
            & (sat_diff <= 55)
            & (val_diff <= 55)
        )

        return float(
            mask.mean()
        )

    return 0.0


def find_template_once(
    template_path: str,
    threshold: float = 0.860,
    roi: tuple[int, int, int, int] | None = None,
    method: str = "ccoeff",
) -> tuple[int, int, float] | None:
    """
    MAA-inspired one-shot recognition path.

    Efficiency choices:
    - restrict capture to ROI whenever available;
    - cache decoded templates;
    - one MSS capture per recognition call;
    - Ccoeff produces candidate locations;
    - RGB/HSV modes only perform heavier color verification on top candidates.
    """
    template = _load_template_cached(
        template_path
    )

    template_h, template_w = (
        template.shape[:2]
    )

    threshold = max(
        0.0,
        min(
            1.0,
            float(threshold),
        ),
    )

    with mss.mss() as capture:
        if roi is None:
            monitor = dict(
                capture.monitors[0]
            )
        else:
            x, y, width, height = roi

            if width <= 0 or height <= 0:
                raise RuntimeError(
                    "ROI 的宽度和高度必须大于 0。"
                )

            monitor = {
                "left": int(x),
                "top": int(y),
                "width": int(width),
                "height": int(height),
            }

        frame = np.asarray(
            capture.grab(monitor)
        )

    screen = cv2.cvtColor(
        frame,
        cv2.COLOR_BGRA2BGR,
    )

    if (
        template_h > screen.shape[0]
        or template_w > screen.shape[1]
    ):
        return None

    ccoeff = cv2.matchTemplate(
        screen,
        template,
        cv2.TM_CCOEFF_NORMED,
    )

    if method == "ccoeff":
        _min_val, max_val, _min_loc, max_loc = (
            cv2.minMaxLoc(ccoeff)
        )

        score = float(max_val)

        if score < threshold:
            return None

        best_loc = max_loc

    else:
        # MAA's RGBCount/HSVCount concept is used as a color-sensitive
        # second stage. We evaluate only the strongest Ccoeff candidates,
        # avoiding a costly color sliding-window pass across the whole frame.
        flat = ccoeff.reshape(-1)
        candidate_count = min(
            12,
            flat.size,
        )

        if candidate_count <= 0:
            return None

        indices = np.argpartition(
            flat,
            -candidate_count,
        )[-candidate_count:]

        best_score = -1.0
        best_loc = (0, 0)

        result_width = ccoeff.shape[1]

        for flat_index in indices:
            y = int(
                flat_index
                // result_width
            )
            x = int(
                flat_index
                % result_width
            )

            region = screen[
                y:y + template_h,
                x:x + template_w,
            ]

            color_score = (
                _color_similarity(
                    template,
                    region,
                    method,
                )
            )

            ccoeff_score = float(
                ccoeff[y, x]
            )

            # Keep Ccoeff's shape robustness while making color decisive.
            combined = (
                ccoeff_score * 0.55
                + color_score * 0.45
            )

            if combined > best_score:
                best_score = combined
                best_loc = (x, y)

        score = float(best_score)

        if score < threshold:
            return None

    center_x = (
        int(monitor["left"])
        + best_loc[0]
        + template_w // 2
    )
    center_y = (
        int(monitor["top"])
        + best_loc[1]
        + template_h // 2
    )

    return (
        center_x,
        center_y,
        score,
    )


def intersect_roi(
    first: tuple[int, int, int, int] | None,
    second: tuple[int, int, int, int] | None,
) -> tuple[int, int, int, int] | None:
    if first is None:
        return second
    if second is None:
        return first
    ax, ay, aw, ah = first
    bx, by, bw, bh = second
    left = max(ax, bx)
    top = max(ay, by)
    right = min(ax + aw, bx + bw)
    bottom = min(ay + ah, by + bh)
    if right <= left or bottom <= top:
        return None
    return int(left), int(top), int(right-left), int(bottom-top)


def parse_size_text(text_value: str) -> tuple[int, int] | None:
    cleaned = text_value.strip().lower().replace('×','*').replace('x','*').replace('\\','*')
    parts=[x.strip() for x in cleaned.split('*')]
    if len(parts)!=2:
        return None
    try:
        w,h=int(parts[0]),int(parts[1])
    except ValueError:
        return None
    return (w,h) if w>0 and h>0 else None


def parse_coord_text(text_value: str) -> tuple[int, int] | None:
    cleaned=text_value.strip().replace('，',',').replace(' ', ',')
    parts=[x.strip() for x in cleaned.split(',') if x.strip()]
    if len(parts)!=2:
        return None
    try:
        return int(parts[0]),int(parts[1])
    except ValueError:
        return None


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


class GlobalAnchorSettingsDialog(QDialog):
    def __init__(self, owner, engine: RecognitionEngine, parent=None) -> None:
        super().__init__(parent)
        self.owner=owner
        self.engine=engine
        self.anchor_template_path=getattr(owner,'global_anchor_template_path',None)
        self.setWindowTitle('仅识别锚点设置')
        self.setModal(True)
        self.resize(610,340)
        layout=QVBoxLayout(self); layout.setContentsMargins(16,16,16,16); layout.setSpacing(12)
        row=QHBoxLayout(); row.addWidget(QLabel('锚点模板'))
        self.template_label=QLabel(self._template_name(),objectName='muted'); row.addWidget(self.template_label,1)
        b=QPushButton('选择锚点',objectName='secondaryButton'); b.clicked.connect(self.choose_anchor); row.addWidget(b); layout.addLayout(row)
        row=QHBoxLayout(); row.addWidget(QLabel('ROI'))
        values=getattr(owner,'global_anchor_roi',(0,0,1280,720)); self.roi_edits={}
        for k,v in zip(('X','Y','W','H'),values):
            row.addWidget(QLabel(k)); e=QLineEdit(str(int(v))); e.setFixedWidth(72); e.setValidator(QIntValidator(-100000,100000,e)); row.addWidget(e); self.roi_edits[k]=e
        b=QPushButton('ROI框选',objectName='secondaryButton'); b.clicked.connect(self.select_roi); row.addWidget(b); layout.addLayout(row)
        hint=QLabel('连接在起始执行链中后，会直接限制 Recognition Engine 的全局可视范围；ROI 坐标相对于锚点中心。',objectName='muted'); hint.setWordWrap(True); layout.addWidget(hint)
        layout.addStretch(); bottom=QHBoxLayout(); bottom.addStretch()
        c=QPushButton('取消',objectName='secondaryButton'); c.clicked.connect(self.reject); bottom.addWidget(c)
        ok=QPushButton('确定',objectName='primaryButton'); ok.clicked.connect(self.accept_settings); bottom.addWidget(ok); layout.addLayout(bottom)

    def _template_name(self) -> str:
        return Path(self.anchor_template_path).name if self.anchor_template_path else '未选择'
    def choose_anchor(self) -> None:
        selected,_=choose_template_with_search(self,'选择锚点模板',allow_external=False)
        if selected:
            self.anchor_template_path=selected; self.template_label.setText(self._template_name())
    def current_roi(self) -> tuple[int,int,int,int]:
        vals=[]
        for k in ('X','Y','W','H'):
            try: vals.append(int(self.roi_edits[k].text()))
            except ValueError: vals.append(0)
        x,y,w,h=vals; return x,y,max(1,w),max(1,h)
    def set_roi(self,values) -> None:
        for k,v in zip(('X','Y','W','H'),values): self.roi_edits[k].setText(str(int(v)))
    def select_roi(self) -> None:
        if not self.anchor_template_path:
            QMessageBox.information(self,'尚未选择锚点','请先选择锚点模板。'); return
        try:
            anchor=self.engine.scan_template(self.anchor_template_path,roi=None,
                options=TemplateScanOptions(threshold=0.860,methods=('ccoeff_color','grayscale','feature'),scales=(0.90,1.0,1.10)))
        except Exception as exc:
            QMessageBox.warning(self,'锚点识别失败',str(exc)); return
        if anchor is None:
            QMessageBox.warning(self,'未找到锚点','当前屏幕中没有找到所选锚点模板。'); return
        region=capture_screen_region(self)
        if region is None: return
        x,y,w,h=region; self.set_roi((x-anchor.x,y-anchor.y,w,h))
    def accept_settings(self) -> None:
        if not self.anchor_template_path:
            QMessageBox.warning(self,'缺少锚点','请选择锚点模板。'); return
        self.owner.global_anchor_template_path=self.anchor_template_path
        self.owner.global_anchor_roi=self.current_roi()
        try: self.owner.sync_global_controls()
        except Exception: pass
        try: self.owner.update()
        except Exception: pass
        self.accept()


class SearchableTemplateDialog(QDialog):
    """Searchable template-library picker shared by all template dropdowns."""

    def __init__(
        self,
        parent=None,
        title: str = "选择模板",
        allow_external: bool = True,
    ) -> None:
        super().__init__(parent)

        self.allow_external = allow_external
        self.selected_path: str | None = None
        self.choose_external = False

        self.setWindowTitle(title)
        self.setModal(True)
        self.resize(430, 390)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("搜索模板名称…")
        layout.addWidget(self.search_edit)

        self.list_widget = QListWidget()
        layout.addWidget(self.list_widget, 1)

        button_row = QHBoxLayout()

        if allow_external:
            external_button = QPushButton(
                "选择其他文件…",
                objectName="secondaryButton",
            )
            external_button.clicked.connect(
                self._select_external
            )
            button_row.addWidget(external_button)

        button_row.addStretch()

        self.select_button = QPushButton(
            "选择",
            objectName="primaryButton",
        )
        self.select_button.setEnabled(False)
        self.select_button.clicked.connect(
            self._accept_current
        )
        button_row.addWidget(
            self.select_button
        )

        cancel_button = QPushButton(
            "取消",
            objectName="secondaryButton",
        )
        cancel_button.clicked.connect(self.reject)
        button_row.addWidget(cancel_button)

        layout.addLayout(button_row)

        self._all_templates = library_templates()
        self._refresh_list("")

        self.search_edit.textChanged.connect(
            self._refresh_list
        )
        self.list_widget.itemDoubleClicked.connect(
            self._accept_item
        )
        self.list_widget.itemClicked.connect(
            self._select_item
        )
        self.list_widget.currentItemChanged.connect(
            self._current_item_changed
        )
        self.search_edit.returnPressed.connect(
            self._accept_current
        )

    def _refresh_list(self, query: str) -> None:
        query = query.strip().casefold()

        self.list_widget.clear()

        for path in self._all_templates:
            if query and query not in path.name.casefold():
                continue

            item = QListWidgetItem(path.name)
            item.setData(Qt.UserRole, str(path))
            self.list_widget.addItem(item)

        if self.list_widget.count() == 0:
            empty = QListWidgetItem("没有匹配的模板")
            empty.setFlags(Qt.NoItemFlags)
            self.list_widget.addItem(empty)

    def _current_item_changed(
        self,
        current,
        _previous,
    ) -> None:
        valid = bool(
            current is not None
            and current.data(
                Qt.UserRole
            )
        )
        self.select_button.setEnabled(
            valid
        )

    def _select_item(
        self,
        item: QListWidgetItem,
    ) -> None:
        path = item.data(
            Qt.UserRole
        )

        if path:
            self.selected_path = str(
                path
            )

    def _accept_current(self) -> None:
        item = (
            self.list_widget.currentItem()
        )

        if item is None:
            return

        self._accept_item(
            item
        )

    def _accept_item(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.UserRole)

        if not path:
            return

        self.selected_path = str(path)
        self.accept()

    def _select_external(self) -> None:
        self.choose_external = True
        self.accept()



class DelayedHoverTip(QObject):
    """Show a compact tooltip only after the pointer rests for 600 ms."""

    def __init__(
        self,
        widget: QWidget,
        text_value: str,
        delay_ms: int = 600,
    ) -> None:
        super().__init__(widget)

        self.widget = widget
        self.text_value = text_value

        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(delay_ms)
        self.timer.timeout.connect(
            self._show_tip
        )

        widget.installEventFilter(self)

    def _show_tip(self) -> None:
        if self.widget.underMouse():
            QToolTip.showText(
                QCursor.pos(),
                self.text_value,
                self.widget,
            )

    def eventFilter(
        self,
        watched,
        event,
    ) -> bool:
        event_type = event.type()

        if event_type in (
            QEvent.Enter,
            QEvent.HoverEnter,
        ):
            self.timer.start()

        elif event_type in (
            QEvent.Leave,
            QEvent.HoverLeave,
            QEvent.MouseButtonPress,
        ):
            self.timer.stop()
            QToolTip.hideText()

        return super().eventFilter(
            watched,
            event,
        )


RECOGNITION_METHOD_TIPS = {
    "ccoeff_color": (
        "彩色 Ccoeff：比较模板与画面的整体像素结构。"
        "速度快，适合尺寸和方向基本不变的 UI，是常用的基础模板匹配。"
    ),
    "grayscale": (
        "灰度匹配：先忽略颜色，只比较亮度与形状结构。"
        "适合颜色会变化、但明暗轮廓较稳定的目标。"
    ),
    "rgb_count": (
        "RGBCount：强调模板与候选区域的 RGB 颜色一致程度。"
        "适合颜色固定、需要排除形状相似但颜色不同目标的场景。"
    ),
    "hsv_count": (
        "HSVCount：在色相、饱和度和亮度空间比较颜色。"
        "通常比直接 RGB 更能容忍一定的明暗变化。"
    ),
    "edge": (
        "边缘匹配：提取轮廓后再进行匹配，弱化颜色和内部纹理影响。"
        "适合轮廓明显的目标；边缘过少的模板会被引擎自动保护性过滤。"
    ),
    "feature": (
        "FeatureMatch：提取局部特征点并进行描述子匹配，再用 RANSAC/Homography 验证几何关系。"
        "更能适应缩放、旋转和部分透视变化，但通常比普通模板匹配更慢。"
    ),
}

METHOD_LABELS = (
    ("ccoeff_color", "彩色 Ccoeff"),
    ("grayscale", "灰度匹配"),
    ("rgb_count", "RGBCount"),
    ("hsv_count", "HSVCount"),
    ("edge", "边缘匹配"),
    ("feature", "FeatureMatch"),
)


class CoordinateModifySettingsDialog(QDialog):
    """
    Configure a signed offset applied to incoming coordinate data.

    Both fields deliberately require an explicit '+' or '-' prefix so the
    operation reads as a modification rather than an absolute coordinate.
    """

    SIGNED_PATTERN = QRegularExpression(
        r"^[+-]\d+$"
    )

    def __init__(
        self,
        owner,
        parent=None,
    ) -> None:
        super().__init__(parent)

        self.owner = owner

        self.setWindowTitle(
            "坐标修改设置"
        )
        self.setModal(True)
        self.resize(
            500,
            230,
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            16,
            16,
            16,
            16,
        )
        layout.setSpacing(
            12
        )

        hint = QLabel(
            "X 和 Y 必须显式带正负号，例如 X=+20、Y=-15。"
            "模块会把这两个偏移量加到输入坐标后再输出。",
            objectName="muted",
        )
        hint.setWordWrap(
            True
        )
        layout.addWidget(
            hint
        )

        row = QHBoxLayout()

        row.addWidget(
            QLabel(
                "X"
            )
        )
        self.x_edit = self._make_signed_edit(
            int(
                getattr(
                    owner,
                    "coordinate_modify_x",
                    0,
                )
            )
        )
        row.addWidget(
            self.x_edit,
            1,
        )

        row.addWidget(
            QLabel(
                "Y"
            )
        )
        self.y_edit = self._make_signed_edit(
            int(
                getattr(
                    owner,
                    "coordinate_modify_y",
                    0,
                )
            )
        )
        row.addWidget(
            self.y_edit,
            1,
        )

        layout.addLayout(
            row
        )
        layout.addStretch()

        buttons = QHBoxLayout()
        buttons.addStretch()

        cancel = QPushButton(
            "取消"
        )
        cancel.clicked.connect(
            self.reject
        )
        buttons.addWidget(
            cancel
        )

        ok = QPushButton(
            "确定",
            objectName="primaryButton",
        )
        ok.clicked.connect(
            self._save
        )
        buttons.addWidget(
            ok
        )

        layout.addLayout(
            buttons
        )

    @staticmethod
    def _format_signed(
        value: int,
    ) -> str:
        return f"{int(value):+d}"

    def _make_signed_edit(
        self,
        value: int,
    ) -> QLineEdit:
        edit = QLineEdit(
            self._format_signed(
                value
            )
        )
        edit.setPlaceholderText(
            "+0 或 -0"
        )
        edit.setToolTip(
            "必须带 + 或 -，例如 +20、-15"
        )
        edit.setValidator(
            QRegularExpressionValidator(
                QRegularExpression(
                    r"^[+-]\d{0,9}$"
                ),
                edit,
            )
        )
        return edit

    def _read_signed(
        self,
        edit: QLineEdit,
        axis: str,
    ) -> int | None:
        value = (
            edit.text()
            .strip()
        )

        if (
            self.SIGNED_PATTERN
            .match(
                value
            )
            .hasMatch()
        ):
            return int(
                value
            )

        QMessageBox.warning(
            self,
            "坐标偏移格式错误",
            (
                f"{axis} 必须带有明确的正负号。"
                f"\n例如：+20 或 -15。"
            ),
        )
        edit.setFocus()
        edit.selectAll()
        return None

    def _save(
        self,
    ) -> None:
        x_value = self._read_signed(
            self.x_edit,
            "X",
        )

        if x_value is None:
            return

        y_value = self._read_signed(
            self.y_edit,
            "Y",
        )

        if y_value is None:
            return

        self.owner.coordinate_modify_x = (
            x_value
        )
        self.owner.coordinate_modify_y = (
            y_value
        )

        sync = getattr(
            self.owner,
            "sync_coordinate_modify_controls",
            None,
        )

        if callable(
            sync
        ):
            sync()

        try:
            self.owner.update()
        except Exception:
            pass

        self.accept()


class FixedCoordinateSettingsDialog(QDialog):
    """
    Configure a deterministic coordinate output.

    Anchor = 空:
        X/Y are absolute virtual-desktop coordinates.

    Anchor = template:
        X/Y are offsets from the anchor template's recognised GLOBAL
        coordinate. The module still outputs a GLOBAL coordinate.
    """

    def __init__(
        self,
        owner,
        parent=None,
    ) -> None:
        super().__init__(parent)

        self.owner = owner

        self.setWindowTitle(
            "固定坐标设置"
        )
        self.setModal(True)
        self.resize(
            520,
            260,
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            16,
            16,
            16,
            16,
        )
        layout.setSpacing(
            12
        )

        anchor_row = QHBoxLayout()
        anchor_row.addWidget(
            QLabel(
                "锚点"
            )
        )

        self.anchor_combo = QComboBox()
        self.anchor_combo.addItem(
            "空（全屏坐标）",
            "",
        )

        current_anchor = str(
            getattr(
                owner,
                "fixed_coordinate_anchor_path",
                "",
            )
            or ""
        )

        known_paths: set[str] = set()

        for path in library_templates():
            value = str(path)
            known_paths.add(value)
            self.anchor_combo.addItem(
                path.name,
                value,
            )

        # Preserve a valid older/external anchor even if it is no longer
        # currently enumerated in the project library.
        if (
            current_anchor
            and current_anchor not in known_paths
        ):
            self.anchor_combo.addItem(
                Path(
                    current_anchor
                ).name,
                current_anchor,
            )

        if current_anchor:
            index = self.anchor_combo.findData(
                current_anchor
            )
            self.anchor_combo.setCurrentIndex(
                max(
                    0,
                    index,
                )
            )
        else:
            self.anchor_combo.setCurrentIndex(
                0
            )

        anchor_row.addWidget(
            self.anchor_combo,
            1,
        )
        layout.addLayout(
            anchor_row
        )

        coord_row = QHBoxLayout()
        coord_row.addWidget(
            QLabel(
                "X"
            )
        )

        self.x_spin = QSpinBox()
        self.x_spin.setRange(
            -1000000,
            1000000,
        )
        self.x_spin.setValue(
            int(
                getattr(
                    owner,
                    "fixed_coordinate_x",
                    0,
                )
            )
        )
        coord_row.addWidget(
            self.x_spin,
            1,
        )

        coord_row.addWidget(
            QLabel(
                "Y"
            )
        )

        self.y_spin = QSpinBox()
        self.y_spin.setRange(
            -1000000,
            1000000,
        )
        self.y_spin.setValue(
            int(
                getattr(
                    owner,
                    "fixed_coordinate_y",
                    0,
                )
            )
        )
        coord_row.addWidget(
            self.y_spin,
            1,
        )

        layout.addLayout(
            coord_row
        )

        self.hint = QLabel(
            objectName="muted",
        )
        self.hint.setWordWrap(
            True
        )
        layout.addWidget(
            self.hint
        )

        self.anchor_combo.currentIndexChanged.connect(
            self._update_hint
        )
        self._update_hint()

        layout.addStretch()

        buttons = QHBoxLayout()
        buttons.addStretch()

        cancel = QPushButton(
            "取消"
        )
        cancel.clicked.connect(
            self.reject
        )
        buttons.addWidget(
            cancel
        )

        ok = QPushButton(
            "确定",
            objectName="primaryButton",
        )
        ok.clicked.connect(
            self._save
        )
        buttons.addWidget(
            ok
        )

        layout.addLayout(
            buttons
        )

    def _update_hint(
        self,
        _index: int = 0,
    ) -> None:
        anchor = str(
            self.anchor_combo.currentData()
            or ""
        )

        if anchor:
            self.hint.setText(
                tr_text(
                    "已选择锚点：X/Y 将作为相对该模板识别坐标的偏移；"
                    "运行时最终输出仍为全局屏幕坐标。"
                )
            )
        else:
            self.hint.setText(
                tr_text(
                    "锚点为空：X/Y 直接作为全局虚拟桌面坐标输出。"
                )
            )

    def _save(
        self,
    ) -> None:
        anchor = str(
            self.anchor_combo.currentData()
            or ""
        )

        self.owner.fixed_coordinate_anchor_path = (
            anchor
            if anchor
            else None
        )
        self.owner.fixed_coordinate_x = (
            int(
                self.x_spin.value()
            )
        )
        self.owner.fixed_coordinate_y = (
            int(
                self.y_spin.value()
            )
        )

        try:
            self.owner.update()
        except Exception:
            pass

        self.accept()


class MoveToSettingsDialog(QDialog):
    def __init__(
        self,
        owner,
        parent=None,
    ) -> None:
        super().__init__(parent)

        self.owner = owner

        self.setWindowTitle(
            "移至设置"
        )
        self.setModal(True)
        self.resize(
            580,
            500,
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            16,
            16,
            16,
            16,
        )
        layout.setSpacing(12)

        normal_hint = QLabel(
            "普通模式：读取上一个模块输出的坐标，并将鼠标瞬移到该精确坐标。",
            objectName="muted",
        )
        normal_hint.setWordWrap(True)
        layout.addWidget(
            normal_hint
        )

        self.advanced_check = QCheckBox(
            "高级模式"
        )
        self.advanced_check.setChecked(
            bool(
                getattr(
                    owner,
                    "move_advanced",
                    False,
                )
            )
        )
        layout.addWidget(
            self.advanced_check
        )

        self.advanced_group = QGroupBox(
            "高级移动"
        )
        advanced = QVBoxLayout(
            self.advanced_group
        )
        advanced.setSpacing(10)

        # ----------------------------------------------------------
        # Directional signed offsets
        # ----------------------------------------------------------
        advanced.addWidget(
            QLabel(
                "坐标偏移（允许正负值）",
                objectName="sectionTitle",
            )
        )

        offset_row = QHBoxLayout()

        self.offset_spins: dict[
            str,
            QDoubleSpinBox,
        ] = {}

        offset_values = {
            "上": float(
                getattr(
                    owner,
                    "move_offset_up",
                    0.0,
                )
            ),
            "下": float(
                getattr(
                    owner,
                    "move_offset_down",
                    0.0,
                )
            ),
            "左": float(
                getattr(
                    owner,
                    "move_offset_left",
                    0.0,
                )
            ),
            "右": float(
                getattr(
                    owner,
                    "move_offset_right",
                    0.0,
                )
            ),
        }

        for label, value in offset_values.items():
            column = QVBoxLayout()
            column.addWidget(
                QLabel(label)
            )

            spin = QDoubleSpinBox()
            spin.setRange(
                -100000.0,
                100000.0,
            )
            spin.setDecimals(2)
            spin.setValue(value)
            spin.setSuffix(
                " px"
            )
            spin.setMinimumWidth(
                110
            )

            column.addWidget(
                spin
            )
            offset_row.addLayout(
                column
            )

            self.offset_spins[
                label
            ] = spin

        advanced.addLayout(
            offset_row
        )

        offset_hint = QLabel(
            "最终 X = 输入 X + 右 − 左；最终 Y = 输入 Y + 下 − 上。"
            "四项自身仍允许填写负数。",
            objectName="muted",
        )
        offset_hint.setWordWrap(
            True
        )
        advanced.addWidget(
            offset_hint
        )

        # ----------------------------------------------------------
        # Speed
        # ----------------------------------------------------------
        speed_row = QHBoxLayout()
        speed_row.addWidget(
            QLabel("移速模式")
        )

        self.speed_mode_combo = QComboBox()
        self.speed_mode_combo.addItem(
            "规定时间到达（秒）",
            "duration",
        )
        self.speed_mode_combo.addItem(
            "像素每秒",
            "pixels_per_second",
        )

        current_mode = str(
            getattr(
                owner,
                "move_speed_mode",
                "duration",
            )
        )
        mode_index = (
            self.speed_mode_combo.findData(
                current_mode
            )
        )
        self.speed_mode_combo.setCurrentIndex(
            max(
                0,
                mode_index,
            )
        )
        speed_row.addWidget(
            self.speed_mode_combo
        )

        speed_row.addWidget(
            QLabel("数值")
        )

        self.speed_value_spin = (
            QDoubleSpinBox()
        )
        self.speed_value_spin.setRange(
            0.0,
            100000.0,
        )
        self.speed_value_spin.setDecimals(
            3
        )
        self.speed_value_spin.setValue(
            float(
                getattr(
                    owner,
                    "move_speed_value",
                    0.0,
                )
            )
        )
        self.speed_value_spin.setMinimumWidth(
            110
        )
        speed_row.addWidget(
            self.speed_value_spin
        )

        advanced.addLayout(
            speed_row
        )

        variance_row = QHBoxLayout()
        variance_row.addWidget(
            QLabel("移速偏移 ±")
        )

        self.speed_variance_spin = (
            QDoubleSpinBox()
        )
        self.speed_variance_spin.setRange(
            0.0,
            100000.0,
        )
        self.speed_variance_spin.setDecimals(
            3
        )
        self.speed_variance_spin.setValue(
            float(
                getattr(
                    owner,
                    "move_speed_variance",
                    0.0,
                )
            )
        )
        self.speed_variance_spin.setMinimumWidth(
            110
        )
        variance_row.addWidget(
            self.speed_variance_spin
        )
        variance_row.addStretch()

        advanced.addLayout(
            variance_row
        )

        self.speed_hint = QLabel(
            "",
            objectName="muted",
        )
        self.speed_hint.setWordWrap(
            True
        )
        advanced.addWidget(
            self.speed_hint
        )

        # ----------------------------------------------------------
        # Route
        # ----------------------------------------------------------
        self.random_route_check = QCheckBox(
            "随机移动路线"
        )
        self.random_route_check.setChecked(
            bool(
                getattr(
                    owner,
                    "move_random_route",
                    False,
                )
            )
        )
        advanced.addWidget(
            self.random_route_check
        )

        route_hint = QLabel(
            "启用后会随机生成平滑曲线路径；仍会严格落在最终目标点。"
            "像素/秒模式会按实际曲线路径长度计算时间。",
            objectName="muted",
        )
        route_hint.setWordWrap(
            True
        )
        advanced.addWidget(
            route_hint
        )

        layout.addWidget(
            self.advanced_group
        )

        self.advanced_check.toggled.connect(
            self.advanced_group.setEnabled
        )
        self.speed_mode_combo.currentIndexChanged.connect(
            self._refresh_speed_ui
        )

        self.advanced_group.setEnabled(
            self.advanced_check.isChecked()
        )
        self._refresh_speed_ui()

        layout.addStretch()

        bottom = QHBoxLayout()
        bottom.addStretch()

        cancel = QPushButton(
            "取消",
            objectName="secondaryButton",
        )
        cancel.clicked.connect(
            self.reject
        )
        bottom.addWidget(
            cancel
        )

        confirm = QPushButton(
            "确定",
            objectName="primaryButton",
        )
        confirm.clicked.connect(
            self._accept_settings
        )
        bottom.addWidget(
            confirm
        )

        layout.addLayout(
            bottom
        )

    def _refresh_speed_ui(self) -> None:
        mode = (
            self.speed_mode_combo.currentData()
        )

        if mode == "pixels_per_second":
            self.speed_value_spin.setSuffix(
                " px/s"
            )
            self.speed_variance_spin.setSuffix(
                " px/s"
            )
            self.speed_hint.setText(
                tr_text(
                    "像素/秒：根据实际移动路线长度计算所需时间。"
                )
            )
        else:
            self.speed_value_spin.setSuffix(
                " s"
            )
            self.speed_variance_spin.setSuffix(
                " s"
            )
            self.speed_hint.setText(
                tr_text(
                    "秒：填写 0 即瞬移；大于 0 时会在规定时间内到达目标。"
                )
            )

    def _accept_settings(self) -> None:
        self.owner.move_advanced = (
            self.advanced_check.isChecked()
        )

        self.owner.move_offset_up = (
            self.offset_spins["上"].value()
        )
        self.owner.move_offset_down = (
            self.offset_spins["下"].value()
        )
        self.owner.move_offset_left = (
            self.offset_spins["左"].value()
        )
        self.owner.move_offset_right = (
            self.offset_spins["右"].value()
        )

        self.owner.move_speed_mode = str(
            self.speed_mode_combo.currentData()
        )
        self.owner.move_speed_value = (
            self.speed_value_spin.value()
        )
        self.owner.move_speed_variance = (
            self.speed_variance_spin.value()
        )
        self.owner.move_random_route = (
            self.random_route_check.isChecked()
        )

        try:
            self.owner.update()
        except Exception:
            pass

        self.accept()


class ClickSettingsDialog(QDialog):
    def __init__(
        self,
        owner,
        parent=None,
    ) -> None:
        super().__init__(parent)

        self.owner = owner

        self.setWindowTitle(
            "点击设置"
        )
        self.setModal(True)
        self.resize(
            470,
            330,
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            16,
            16,
            16,
            16,
        )
        layout.setSpacing(12)

        count_row = QHBoxLayout()
        count_row.addWidget(
            QLabel("点击次数")
        )

        self.count_spin = QSpinBox()
        self.count_spin.setRange(
            1,
            10000,
        )
        self.count_spin.setValue(
            int(
                getattr(
                    owner,
                    "click_count",
                    1,
                )
            )
        )
        count_row.addWidget(
            self.count_spin
        )
        count_row.addStretch()

        layout.addLayout(
            count_row
        )

        default_hint = QLabel(
            "“点击”始终表示一次完整的按下→松开动作，与以后单独的“按下”和“松开”模块区分。",
            objectName="muted",
        )
        default_hint.setWordWrap(
            True
        )
        layout.addWidget(
            default_hint
        )

        self.advanced_check = QCheckBox(
            "高级模式"
        )
        self.advanced_check.setChecked(
            bool(
                getattr(
                    owner,
                    "click_advanced",
                    False,
                )
            )
        )
        layout.addWidget(
            self.advanced_check
        )

        self.advanced_group = QGroupBox(
            "高级点击"
        )
        advanced = QVBoxLayout(
            self.advanced_group
        )

        hold_row = QHBoxLayout()
        hold_row.addWidget(
            QLabel("每次按下时长")
        )

        self.hold_spin = QDoubleSpinBox()
        self.hold_spin.setRange(
            0.0,
            60.0,
        )
        self.hold_spin.setDecimals(
            3
        )
        self.hold_spin.setSingleStep(
            0.01
        )
        self.hold_spin.setSuffix(
            " s"
        )
        self.hold_spin.setValue(
            float(
                getattr(
                    owner,
                    "click_press_duration",
                    0.025,
                )
            )
        )
        hold_row.addWidget(
            self.hold_spin
        )
        hold_row.addStretch()

        advanced.addLayout(
            hold_row
        )

        interval_row = QHBoxLayout()
        interval_row.addWidget(
            QLabel("两次点击间隔")
        )

        self.interval_spin = QDoubleSpinBox()
        self.interval_spin.setRange(
            0.0,
            3600.0,
        )
        self.interval_spin.setDecimals(
            3
        )
        self.interval_spin.setSingleStep(
            0.01
        )
        self.interval_spin.setSuffix(
            " s"
        )
        self.interval_spin.setValue(
            float(
                getattr(
                    owner,
                    "click_interval",
                    0.100,
                )
            )
        )
        interval_row.addWidget(
            self.interval_spin
        )
        interval_row.addStretch()

        advanced.addLayout(
            interval_row
        )

        self.advanced_group.setEnabled(
            self.advanced_check.isChecked()
        )
        self.advanced_check.toggled.connect(
            self.advanced_group.setEnabled
        )

        layout.addWidget(
            self.advanced_group
        )
        layout.addStretch()

        bottom = QHBoxLayout()
        bottom.addStretch()

        cancel = QPushButton(
            "取消",
            objectName="secondaryButton",
        )
        cancel.clicked.connect(
            self.reject
        )
        bottom.addWidget(
            cancel
        )

        confirm = QPushButton(
            "确定",
            objectName="primaryButton",
        )
        confirm.clicked.connect(
            self._accept_settings
        )
        bottom.addWidget(
            confirm
        )

        layout.addLayout(
            bottom
        )

    def _accept_settings(self) -> None:
        self.owner.click_count = (
            self.count_spin.value()
        )
        self.owner.click_advanced = (
            self.advanced_check.isChecked()
        )
        self.owner.click_press_duration = (
            self.hold_spin.value()
        )
        self.owner.click_interval = (
            self.interval_spin.value()
        )

        try:
            self.owner.update()
        except Exception:
            pass

        self.accept()


class DragSettingsDialog(QDialog):
    def __init__(self, owner, parent=None) -> None:
        super().__init__(parent); self.owner=owner
        self.setWindowTitle("拖动设置"); self.resize(640,500)
        layout=QVBoxLayout(self)
        box=QGroupBox("起始点与结束点"); b=QVBoxLayout(box)
        r1=QHBoxLayout(); r1.addWidget(QLabel("起始 X")); self.sx=QDoubleSpinBox(); self.sx.setRange(-100000,100000); self.sx.setValue(float(getattr(owner,"drag_start_x",0))); r1.addWidget(self.sx); r1.addWidget(QLabel("Y")); self.sy=QDoubleSpinBox(); self.sy.setRange(-100000,100000); self.sy.setValue(float(getattr(owner,"drag_start_y",0))); r1.addWidget(self.sy)
        r2=QHBoxLayout(); r2.addWidget(QLabel("结束 X")); self.ex=QDoubleSpinBox(); self.ex.setRange(-100000,100000); self.ex.setValue(float(getattr(owner,"drag_end_x",0))); r2.addWidget(self.ex); r2.addWidget(QLabel("Y")); self.ey=QDoubleSpinBox(); self.ey.setRange(-100000,100000); self.ey.setValue(float(getattr(owner,"drag_end_y",0))); r2.addWidget(self.ey)
        b.addLayout(r1); b.addLayout(r2); layout.addWidget(box)
        self.advanced=QCheckBox("高级模式"); self.advanced.setChecked(bool(getattr(owner,"move_advanced",False))); layout.addWidget(self.advanced)
        group=QGroupBox("高级移动"); g=QVBoxLayout(group)
        offs=QHBoxLayout(); self.off={}
        for label,attr in [("上","move_offset_up"),("下","move_offset_down"),("左","move_offset_left"),("右","move_offset_right")]:
            col=QVBoxLayout(); col.addWidget(QLabel(label)); sp=QDoubleSpinBox(); sp.setRange(-100000,100000); sp.setSuffix(" px"); sp.setValue(float(getattr(owner,attr,0))); col.addWidget(sp); offs.addLayout(col); self.off[attr]=sp
        g.addLayout(offs)
        sr=QHBoxLayout(); sr.addWidget(QLabel("移速模式")); self.speed_mode=QComboBox(); self.speed_mode.addItem("规定时间到达（秒）","duration"); self.speed_mode.addItem("像素每秒","pixels_per_second"); idx=self.speed_mode.findData(str(getattr(owner,"move_speed_mode","duration"))); self.speed_mode.setCurrentIndex(max(0,idx)); sr.addWidget(self.speed_mode)
        sr.addWidget(QLabel("数值")); self.speed=QDoubleSpinBox(); self.speed.setRange(0,100000); self.speed.setDecimals(3); self.speed.setValue(float(getattr(owner,"move_speed_value",0))); sr.addWidget(self.speed)
        sr.addWidget(QLabel("移速偏移 ±")); self.var=QDoubleSpinBox(); self.var.setRange(0,100000); self.var.setDecimals(3); self.var.setValue(float(getattr(owner,"move_speed_variance",0))); sr.addWidget(self.var); g.addLayout(sr)
        self.random=QCheckBox("随机移动路线"); self.random.setChecked(bool(getattr(owner,"move_random_route",False))); g.addWidget(self.random)
        hr=QHBoxLayout(); hr.addWidget(QLabel("起始点按下等待")); self.press=QDoubleSpinBox(); self.press.setRange(0,60); self.press.setDecimals(3); self.press.setSuffix(" s"); self.press.setValue(float(getattr(owner,"drag_press_duration",0.025))); hr.addWidget(self.press); hr.addStretch(); g.addLayout(hr)
        group.setEnabled(self.advanced.isChecked()); self.advanced.toggled.connect(group.setEnabled); layout.addWidget(group)
        buttons=QHBoxLayout(); buttons.addStretch(); c=QPushButton("取消"); c.clicked.connect(self.reject); buttons.addWidget(c); ok=QPushButton("确定"); ok.clicked.connect(self._save); buttons.addWidget(ok); layout.addLayout(buttons)
    def _save(self):
        o=self.owner; o.drag_start_x=self.sx.value(); o.drag_start_y=self.sy.value(); o.drag_end_x=self.ex.value(); o.drag_end_y=self.ey.value(); o.drag_press_duration=self.press.value(); o.move_advanced=self.advanced.isChecked()
        for attr,sp in self.off.items(): setattr(o,attr,sp.value())
        o.move_speed_mode=str(self.speed_mode.currentData()); o.move_speed_value=self.speed.value(); o.move_speed_variance=self.var.value(); o.move_random_route=self.random.isChecked(); o.update(); self.accept()

class KeyRecorderDialog(QDialog):
    def __init__(
        self,
        parent=None,
    ) -> None:
        super().__init__(parent)

        self.recorded_key = ""

        self.setWindowTitle(
            "录制按键"
        )
        self.setModal(True)
        self.resize(
            360,
            150,
        )

        layout = QVBoxLayout(self)

        title = QLabel(
            "请按下任意键"
        )
        title.setAlignment(
            Qt.AlignCenter
        )
        title.setStyleSheet(
            "font-size:18px;"
            "font-weight:700;"
        )
        layout.addWidget(
            title
        )

        hint = QLabel(
            "按下后会立即记录并关闭此窗口。Esc 也可以被记录。"
        )
        hint.setAlignment(
            Qt.AlignCenter
        )
        hint.setWordWrap(
            True
        )
        hint.setObjectName(
            "muted"
        )
        layout.addWidget(
            hint
        )

        self.setFocusPolicy(
            Qt.StrongFocus
        )

    @staticmethod
    def key_name_from_event(
        event: QKeyEvent,
    ) -> str:
        special = {
            Qt.Key_Space: "SPACE",
            Qt.Key_Return: "ENTER",
            Qt.Key_Enter: "ENTER",
            Qt.Key_Escape: "ESC",
            Qt.Key_Tab: "TAB",
            Qt.Key_Backspace: "BACKSPACE",
            Qt.Key_Delete: "DELETE",
            Qt.Key_Insert: "INSERT",
            Qt.Key_Home: "HOME",
            Qt.Key_End: "END",
            Qt.Key_PageUp: "PAGEUP",
            Qt.Key_PageDown: "PAGEDOWN",
            Qt.Key_Left: "LEFT",
            Qt.Key_Right: "RIGHT",
            Qt.Key_Up: "UP",
            Qt.Key_Down: "DOWN",
            Qt.Key_Shift: "SHIFT",
            Qt.Key_Control: "CTRL",
            Qt.Key_Alt: "ALT",
            Qt.Key_CapsLock: "CAPSLOCK",
        }

        key = event.key()

        if key in special:
            return special[
                key
            ]

        if (
            Qt.Key_F1
            <= key
            <= Qt.Key_F24
        ):
            return (
                f"F"
                f"{key - Qt.Key_F1 + 1}"
            )

        value = event.text()

        if value:
            return value.upper()

        return (
            QKeySequence(
                key
            )
            .toString()
            .upper()
        )

    def keyPressEvent(
        self,
        event: QKeyEvent,
    ) -> None:
        name = self.key_name_from_event(
            event
        )

        if not name:
            return

        self.recorded_key = name
        self.accept()


class KeyboardSettingsDialog(QDialog):
    def __init__(
        self,
        owner,
        parent=None,
    ) -> None:
        super().__init__(parent)

        self.owner = owner

        self.setWindowTitle(
            "键盘输入设置"
        )
        self.resize(
            650,
            530,
        )

        layout = QVBoxLayout(self)

        self.text_mode = QCheckBox(
            "输入文本"
        )
        self.text_mode.setChecked(
            bool(
                getattr(
                    owner,
                    "key_text_mode",
                    False,
                )
            )
        )
        layout.addWidget(
            self.text_mode
        )

        # ---------------- Key mode ----------------
        self.key_group = QGroupBox(
            "按键模式"
        )
        key_layout = QVBoxLayout(
            self.key_group
        )

        key_row = QHBoxLayout()
        key_row.addWidget(
            QLabel(
                "当前按键"
            )
        )

        self.key_display = QLineEdit(
            str(
                getattr(
                    owner,
                    "key_name",
                    "SPACE",
                )
            )
        )
        self.key_display.setReadOnly(
            True
        )
        key_row.addWidget(
            self.key_display,
            1,
        )

        self.record_button = QPushButton(
            "录制按键"
        )
        self.record_button.clicked.connect(
            self._record_key
        )
        key_row.addWidget(
            self.record_button
        )

        key_layout.addLayout(
            key_row
        )

        mode_row = QHBoxLayout()
        mode_row.addWidget(
            QLabel(
                "模式"
            )
        )

        self.mode = QComboBox()
        self.mode.addItem(
            "按下",
            "press",
        )
        self.mode.addItem(
            "长按",
            "hold",
        )

        index = self.mode.findData(
            str(
                getattr(
                    owner,
                    "key_mode",
                    "press",
                )
            )
        )
        self.mode.setCurrentIndex(
            max(
                0,
                index,
            )
        )
        mode_row.addWidget(
            self.mode
        )

        mode_row.addWidget(
            QLabel(
                "次数"
            )
        )
        self.count = QSpinBox()
        self.count.setRange(
            1,
            100000,
        )
        self.count.setValue(
            int(
                getattr(
                    owner,
                    "key_count",
                    1,
                )
            )
        )
        mode_row.addWidget(
            self.count
        )
        key_layout.addLayout(
            mode_row
        )

        timing_row = QHBoxLayout()
        timing_row.addWidget(
            QLabel(
                "两次间隔"
            )
        )
        self.interval = QDoubleSpinBox()
        self.interval.setRange(
            0,
            3600,
        )
        self.interval.setDecimals(
            4
        )
        self.interval.setSuffix(
            " s"
        )
        self.interval.setValue(
            float(
                getattr(
                    owner,
                    "key_interval",
                    0,
                )
            )
        )
        timing_row.addWidget(
            self.interval
        )

        timing_row.addWidget(
            QLabel(
                "长按时长"
            )
        )
        self.hold = QDoubleSpinBox()
        self.hold.setRange(
            0,
            3600,
        )
        self.hold.setDecimals(
            4
        )
        self.hold.setSuffix(
            " s"
        )
        self.hold.setValue(
            float(
                getattr(
                    owner,
                    "key_hold_duration",
                    0.5,
                )
            )
        )
        timing_row.addWidget(
            self.hold
        )
        key_layout.addLayout(
            timing_row
        )

        layout.addWidget(
            self.key_group
        )

        # ---------------- Text mode ----------------
        self.text_group = QGroupBox(
            "文本输入"
        )
        text_layout = QVBoxLayout(
            self.text_group
        )

        self.text_edit = QPlainTextEdit()
        self.text_edit.setPlaceholderText(
            "输入任意文本；运行时将按原内容输入。"
        )
        self.text_edit.setPlainText(
            str(
                getattr(
                    owner,
                    "key_text",
                    "",
                )
            )
        )
        text_layout.addWidget(
            self.text_edit
        )

        text_hint = QLabel(
            "文本模式支持 Unicode 文本。高级模式中的间隔偏移与模拟输入可用于随机化字符之间的节奏。",
            objectName="muted",
        )
        text_hint.setWordWrap(
            True
        )
        text_layout.addWidget(
            text_hint
        )

        self.text_auto_delay_label = QLabel(
            objectName="muted",
        )
        self.text_auto_delay_label.setWordWrap(
            True
        )
        text_layout.addWidget(
            self.text_auto_delay_label
        )
        self.text_edit.textChanged.connect(
            self._update_text_auto_delay_label
        )
        self._update_text_auto_delay_label()

        layout.addWidget(
            self.text_group
        )

        # ---------------- Advanced ----------------
        self.advanced = QCheckBox(
            "高级设置"
        )
        self.advanced.setChecked(
            bool(
                getattr(
                    owner,
                    "key_advanced",
                    False,
                )
            )
        )
        layout.addWidget(
            self.advanced
        )

        self.advanced_group = QGroupBox(
            "高级键盘输入"
        )
        advanced_layout = QVBoxLayout(
            self.advanced_group
        )

        variance_row = QHBoxLayout()
        variance_row.addWidget(
            QLabel(
                "时长偏移 ±"
            )
        )
        self.dv = QDoubleSpinBox()
        self.dv.setRange(
            0,
            60,
        )
        self.dv.setDecimals(
            4
        )
        self.dv.setSuffix(
            " s"
        )
        self.dv.setValue(
            float(
                getattr(
                    owner,
                    "key_duration_variance",
                    0,
                )
            )
        )
        variance_row.addWidget(
            self.dv
        )

        variance_row.addWidget(
            QLabel(
                "间隔偏移 ±"
            )
        )
        self.iv = QDoubleSpinBox()
        self.iv.setRange(
            0,
            60,
        )
        self.iv.setDecimals(
            4
        )
        self.iv.setSuffix(
            " s"
        )
        self.iv.setValue(
            float(
                getattr(
                    owner,
                    "key_interval_variance",
                    0,
                )
            )
        )
        variance_row.addWidget(
            self.iv
        )
        advanced_layout.addLayout(
            variance_row
        )

        self.human = QCheckBox(
            "模拟键盘输入"
        )
        self.human.setChecked(
            bool(
                getattr(
                    owner,
                    "key_humanized",
                    False,
                )
            )
        )
        advanced_layout.addWidget(
            self.human
        )

        hint = QLabel(
            "模拟模式会在允许的偏移范围内随机化按下/松开与输入间隔，尽量接近真实用户的键盘节奏。",
            objectName="muted",
        )
        hint.setWordWrap(
            True
        )
        advanced_layout.addWidget(
            hint
        )

        self.advanced_group.setEnabled(
            self.advanced.isChecked()
        )
        self.advanced.toggled.connect(
            self.advanced_group.setEnabled
        )

        layout.addWidget(
            self.advanced_group
        )

        self.text_mode.toggled.connect(
            self._sync_mode_visibility
        )
        self._sync_mode_visibility(
            self.text_mode.isChecked()
        )

        buttons = QHBoxLayout()
        buttons.addStretch()

        cancel = QPushButton(
            "取消"
        )
        cancel.clicked.connect(
            self.reject
        )
        buttons.addWidget(
            cancel
        )

        ok = QPushButton(
            "确定"
        )
        ok.clicked.connect(
            self._save
        )
        buttons.addWidget(
            ok
        )

        layout.addLayout(
            buttons
        )

    def _update_text_auto_delay_label(
        self,
    ) -> None:
        text_value = (
            self.text_edit.toPlainText()
        )
        settle_seconds = (
            KeyboardActionEngine
            .recommended_text_settle_delay(
                text_value
            )
        )
        utf16_units = (
            len(
                text_value.encode(
                    "utf-16-le"
                )
            )
            // 2
            if text_value
            else 0
        )
        total_ms = (
            MODULE_MIN_GAP_SECONDS
            + settle_seconds
        ) * 1000.0
        self.text_auto_delay_label.setText(
            tr_text(
                (
                    f"自动缓冲估算：5 ms 模块间隔 + "
                    f"{utf16_units} × 2 ms = {total_ms:.0f} ms。"
                    "此缓冲发生在文本发送完成后。"
                )
            )
        )

    def _record_key(
        self,
    ) -> None:
        dialog = KeyRecorderDialog(
            self
        )

        if dialog.exec() != QDialog.Accepted:
            return

        if dialog.recorded_key:
            self.key_display.setText(
                dialog.recorded_key
            )

    def _sync_mode_visibility(
        self,
        text_mode: bool,
    ) -> None:
        self.key_group.setVisible(
            not text_mode
        )
        self.text_group.setVisible(
            text_mode
        )

        # Duration variance is meaningful for key down/up; text typing uses
        # interval variation only.
        self.dv.setEnabled(
            not text_mode
        )

    def _save(
        self,
    ) -> None:
        owner = self.owner

        owner.key_text_mode = (
            self.text_mode.isChecked()
        )
        owner.key_text = (
            self.text_edit.toPlainText()
        )

        owner.key_name = (
            self.key_display.text()
            .strip()
            .upper()
            or "SPACE"
        )
        owner.key_mode = str(
            self.mode.currentData()
        )
        owner.key_count = (
            self.count.value()
        )
        owner.key_interval = (
            self.interval.value()
        )
        owner.key_hold_duration = (
            self.hold.value()
        )
        owner.key_advanced = (
            self.advanced.isChecked()
        )
        owner.key_duration_variance = (
            self.dv.value()
        )
        owner.key_interval_variance = (
            self.iv.value()
        )
        owner.key_humanized = (
            self.human.isChecked()
        )

        try:
            owner.update()
        except Exception:
            pass

        self.accept()


class LaunchExeSettingsDialog(QDialog):
    def __init__(self, owner, parent=None) -> None:
        super().__init__(parent); self.owner=owner; self.setWindowTitle("启动程序设置"); self.resize(680,160)
        layout=QVBoxLayout(self); r=QHBoxLayout(); r.addWidget(QLabel("程序路径")); self.path=QLineEdit(str(getattr(owner,"executable_path",""))); r.addWidget(self.path,1); b=QPushButton("浏览…"); b.clicked.connect(self._browse); r.addWidget(b); layout.addLayout(r)
        br=QHBoxLayout(); br.addStretch(); c=QPushButton("取消"); c.clicked.connect(self.reject); br.addWidget(c); ok=QPushButton("确定"); ok.clicked.connect(self._save); br.addWidget(ok); layout.addLayout(br)
    def _browse(self):
        path,_=QFileDialog.getOpenFileName(self,"选择程序",self.path.text(),"Programs (*.exe);;All files (*.*)")
        if path:self.path.setText(path)
    def _save(self):
        self.owner.executable_path=self.path.text().strip(); sync=getattr(self.owner,"sync_inline_action_controls",None); sync() if callable(sync) else None; self.accept()


class DelaySettingsDialog(QDialog):
    UNITS=(("毫秒","milliseconds"),("秒","seconds"),("分钟","minutes"),("小时","hours"))
    def __init__(self, owner, parent=None) -> None:
        super().__init__(parent); self.owner=owner; self.setWindowTitle("延时等待设置")
        layout=QVBoxLayout(self); r=QHBoxLayout(); r.addWidget(QLabel("时长")); self.value=QDoubleSpinBox(); self.value.setRange(0,100000000); self.value.setDecimals(3); self.value.setValue(float(getattr(owner,"delay_value",1))); r.addWidget(self.value); self.unit=QComboBox()
        for label,data in self.UNITS:self.unit.addItem(label,data)
        idx=self.unit.findData(str(getattr(owner,"delay_unit","seconds"))); self.unit.setCurrentIndex(max(0,idx)); r.addWidget(self.unit); layout.addLayout(r)
        br=QHBoxLayout(); br.addStretch(); c=QPushButton("取消"); c.clicked.connect(self.reject); br.addWidget(c); ok=QPushButton("确定"); ok.clicked.connect(self._save); br.addWidget(ok); layout.addLayout(br)
    def _save(self):
        self.owner.delay_value=self.value.value(); self.owner.delay_unit=str(self.unit.currentData()); sync=getattr(self.owner,"sync_inline_action_controls",None); sync() if callable(sync) else None; self.accept()


class ClockSettingsDialog(QDialog):
    def __init__(self, owner, parent=None) -> None:
        super().__init__(parent); self.owner=owner; self.setWindowTitle("时钟设置"); self.resize(540,220)
        layout=QVBoxLayout(self); r=QHBoxLayout(); r.addWidget(QLabel("计时")); self.value=QDoubleSpinBox(); self.value.setRange(0,100000000); self.value.setDecimals(3); self.value.setValue(float(getattr(owner,"clock_value",60))); r.addWidget(self.value); self.unit=QComboBox()
        for label,data in DelaySettingsDialog.UNITS:self.unit.addItem(label,data)
        idx=self.unit.findData(str(getattr(owner,"clock_unit","seconds"))); self.unit.setCurrentIndex(max(0,idx)); r.addWidget(self.unit); layout.addLayout(r)
        b=QHBoxLayout(); b.addWidget(QLabel("结束后行为")); self.beh=QComboBox(); self.beh.addItem("结束进程","stop"); self.beh.addItem("结束进程并关闭程序","stop_close"); self.beh.addItem("执行链","execute_chain"); self.beh.addItem("终止其他事件链条并执行链","stop_others_execute_chain"); idx=self.beh.findData(str(getattr(owner,"clock_behavior","stop"))); self.beh.setCurrentIndex(max(0,idx)); b.addWidget(self.beh,1); layout.addLayout(b)
        hint=QLabel("“执行链”会触发事件模块“时钟终止后链”。一个项目只允许放置一个该事件模块。",objectName="muted"); hint.setWordWrap(True); layout.addWidget(hint)
        br=QHBoxLayout(); br.addStretch(); c=QPushButton("取消"); c.clicked.connect(self.reject); br.addWidget(c); ok=QPushButton("确定"); ok.clicked.connect(self._save); br.addWidget(ok); layout.addLayout(br)
    def _save(self):
        self.owner.clock_value=self.value.value(); self.owner.clock_unit=str(self.unit.currentData()); self.owner.clock_behavior=str(self.beh.currentData()); self.owner.update(); self.accept()


class LoopSettingsDialog(QDialog):
    def __init__(self, owner, parent=None) -> None:
        super().__init__(parent)
        self.owner = owner
        self.setWindowTitle("循环设置")
        self.setModal(True)
        self.resize(420, 210)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16,16,16,16)
        layout.setSpacing(12)
        self.infinite_check = QCheckBox("无限循环")
        self.infinite_check.setChecked(bool(getattr(owner,"loop_infinite",False)))
        layout.addWidget(self.infinite_check)
        row = QHBoxLayout()
        row.addWidget(QLabel("循环次数"))
        self.count_spin = QSpinBox()
        self.count_spin.setRange(1,100000000)
        self.count_spin.setValue(max(1,int(getattr(owner,"loop_count",1))))
        row.addWidget(self.count_spin,1)
        layout.addLayout(row)
        self.count_spin.setEnabled(not self.infinite_check.isChecked())
        self.infinite_check.toggled.connect(lambda checked:self.count_spin.setEnabled(not checked))
        hint=QLabel("同一轮内部模块会严格按顺序完整执行；一轮完成后才会进入下一轮。",objectName="muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch()
        buttons=QHBoxLayout(); buttons.addStretch()
        cancel=QPushButton("取消"); cancel.clicked.connect(self.reject); buttons.addWidget(cancel)
        ok=QPushButton("确定",objectName="primaryButton"); ok.clicked.connect(self._save); buttons.addWidget(ok)
        layout.addLayout(buttons)

    def _save(self) -> None:
        self.owner.loop_infinite=self.infinite_check.isChecked()
        self.owner.loop_count=max(1,int(self.count_spin.value()))
        sync=getattr(self.owner,"sync_loop_control",None)
        if callable(sync): sync()
        try: self.owner.update()
        except Exception: pass
        self.accept()


class ScanTemplateSettingsDialog(QDialog):
    """Shared settings UI for simple and complex Scan Template modules."""

    def __init__(
        self,
        owner,
        parent=None,
    ) -> None:
        super().__init__(parent)

        self.owner = owner
        self.template_path = (
            owner.selected_template_path
        )
        self._hover_tips: list[DelayedHoverTip] = []

        dialog_titles = {
            "findtemplate": "扫描模板设置",
            "template_count": "模板计数设置",
            "lock_template": "锁定模板设置",
        }
        self.setWindowTitle(
            dialog_titles.get(
                getattr(
                    owner,
                    "module_type",
                    "findtemplate",
                ),
                "视觉识别设置",
            )
        )
        self.setModal(True)
        self.resize(
            540,
            470,
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            16,
            16,
            16,
            16,
        )
        layout.setSpacing(11)

        # Template
        template_row = QHBoxLayout()
        template_row.addWidget(
            QLabel("模板")
        )

        self.template_label = QLabel(
            self._template_text(),
            objectName="muted",
        )
        self.template_label.setMinimumWidth(
            250
        )
        template_row.addWidget(
            self.template_label,
            1,
        )

        choose_button = QPushButton(
            "选择模板",
            objectName="secondaryButton",
        )
        choose_button.clicked.connect(
            self.choose_template
        )
        template_row.addWidget(
            choose_button
        )

        layout.addLayout(
            template_row
        )

        # Threshold
        threshold_row = QHBoxLayout()
        threshold_row.addWidget(
            QLabel("匹配度")
        )

        self.threshold_edit = QLineEdit(
            f"{float(owner.match_threshold):.3f}"
        )
        self.threshold_edit.setValidator(
            QDoubleValidator(
                0.0,
                1.0,
                3,
                self.threshold_edit,
            )
        )
        self.threshold_edit.setMaximumWidth(
            90
        )
        threshold_row.addWidget(
            self.threshold_edit
        )
        threshold_row.addStretch()

        layout.addLayout(
            threshold_row
        )

        # Completion / wait policy.
        self.wait_for_match_check = None
        self.wait_timeout_spin = None

        if (
            getattr(
                owner,
                "module_type",
                "findtemplate",
            )
            == "findtemplate"
        ):
            wait_row = QHBoxLayout()

            self.wait_for_match_check = QCheckBox(
                "等待识别"
            )
            self.wait_for_match_check.setChecked(
                bool(
                    getattr(
                        owner,
                        "wait_for_match",
                        True,
                    )
                )
            )
            self.wait_for_match_check.setToolTip(
                "开启后，扫描模板会保持运行，直到识别到目标或达到最大等待时间；"
                "同一条链中的下一个模块不会提前执行。"
            )
            wait_row.addWidget(
                self.wait_for_match_check
            )

            wait_row.addWidget(
                QLabel(
                    "最大等待"
                )
            )

            self.wait_timeout_spin = QSpinBox()
            self.wait_timeout_spin.setRange(
                1,
                60000,
            )
            self.wait_timeout_spin.setValue(
                max(
                    1,
                    int(
                        getattr(
                            owner,
                            "wait_timeout_ms",
                            1000,
                        )
                    ),
                )
            )
            self.wait_timeout_spin.setSuffix(
                " ms"
            )
            self.wait_timeout_spin.setToolTip(
                "从本模块开始扫描起计算。目标一旦出现会立即完成，不会等待到上限。"
            )
            wait_row.addWidget(
                self.wait_timeout_spin
            )
            wait_row.addStretch()

            self.wait_for_match_check.toggled.connect(
                self.wait_timeout_spin.setEnabled
            )
            self.wait_timeout_spin.setEnabled(
                self.wait_for_match_check.isChecked()
            )

            layout.addLayout(
                wait_row
            )

            wait_hint = QLabel(
                "等待识别属于扫描模板模块本身的执行时间：目标出现后立即输出坐标并完成；"
                "超时仍未出现则本链停止。不同事件链不会因此互相等待。",
                objectName="muted",
            )
            wait_hint.setWordWrap(
                True
            )
            layout.addWidget(
                wait_hint
            )

        # Methods
        layout.addWidget(
            QLabel(
                "识别方法（默认全部启用）",
                objectName="sectionTitle",
            )
        )

        current_methods = set(
            getattr(
                owner,
                "recognition_methods",
                DEFAULT_METHODS,
            )
        )

        self.method_checks: dict[
            str,
            QCheckBox,
        ] = {}

        for method_id, label in METHOD_LABELS:
            checkbox = QCheckBox(
                label
            )
            checkbox.setChecked(
                method_id
                in current_methods
            )
            self.method_checks[
                method_id
            ] = checkbox
            layout.addWidget(
                checkbox
            )

            self._hover_tips.append(
                DelayedHoverTip(
                    checkbox,
                    RECOGNITION_METHOD_TIPS[
                        method_id
                    ],
                    600,
                )
            )

        # Advanced recognition engine options.
        advanced_row = QHBoxLayout()

        self.multi_scale_check = QCheckBox(
            "多尺度匹配"
        )
        self.multi_scale_check.setChecked(
            bool(
                getattr(
                    owner,
                    "multi_scale",
                    True,
                )
            )
        )
        advanced_row.addWidget(
            self.multi_scale_check
        )
        self._hover_tips.append(
            DelayedHoverTip(
                self.multi_scale_check,
                "多尺度匹配：以多个缩放比例尝试模板，适合窗口缩放或游戏分辨率导致的目标尺寸变化；会增加识别耗时。",
                600,
            )
        )

        confirm_label = QLabel(
            "连续帧确认"
        )
        advanced_row.addWidget(
            confirm_label
        )
        self._hover_tips.append(
            DelayedHoverTip(
                confirm_label,
                "连续帧确认：要求目标在连续多帧中稳定出现，减少动画、闪烁或偶然误识别；数值越高越稳，但响应更慢。",
                600,
            )
        )

        self.confirm_spin = QSpinBox()
        self.confirm_spin.setRange(
            1,
            5,
        )
        self.confirm_spin.setValue(
            int(
                getattr(
                    owner,
                    "confirm_frames",
                    1,
                )
            )
        )
        advanced_row.addWidget(
            self.confirm_spin
        )
        self._hover_tips.append(
            DelayedHoverTip(
                self.confirm_spin,
                "连续帧确认次数：1 表示单帧即可通过；更高数值要求多次识别位置保持接近。",
                600,
            )
        )

        detector_label = QLabel(
            "Feature detector"
        )
        advanced_row.addWidget(
            detector_label
        )
        self._hover_tips.append(
            DelayedHoverTip(
                detector_label,
                "Feature detector：选择 FeatureMatch 用于提取特征点的算法。SIFT 通常更稳健；ORB/BRISK 通常更快；AKAZE/KAZE 介于两者之间。",
                600,
            )
        )

        self.detector_combo = QComboBox()

        for detector in (
            "SIFT",
            "AKAZE",
            "KAZE",
            "BRISK",
            "ORB",
        ):
            self.detector_combo.addItem(
                detector,
                detector,
            )

        detector = str(
            getattr(
                owner,
                "feature_detector",
                "SIFT",
            )
        )

        index = (
            self.detector_combo.findData(
                detector
            )
        )

        self.detector_combo.setCurrentIndex(
            max(
                0,
                index,
            )
        )
        advanced_row.addWidget(
            self.detector_combo
        )
        self._hover_tips.append(
            DelayedHoverTip(
                self.detector_combo,
                "SIFT：稳健、较慢；AKAZE/KAZE：兼顾精度与速度；BRISK/ORB：速度优先。此选项只影响 FeatureMatch。",
                600,
            )
        )

        layout.addLayout(
            advanced_row
        )

        hint = QLabel(
            "“全部”并不是把同一张图重复做六次全屏扫描：UVAF Recognition Engine "
            "会优先 ROI、缓存模板，并复用候选位置；FeatureMatch 用于尺度/旋转变化，"
            "灰度与边缘模式用于弱化颜色变化。",
            objectName="muted",
        )
        hint.setWordWrap(True)
        layout.addWidget(
            hint
        )

        layout.addStretch()

        buttons = QHBoxLayout()
        buttons.addStretch()

        cancel = QPushButton(
            "取消",
            objectName="secondaryButton",
        )
        cancel.clicked.connect(
            self.reject
        )
        buttons.addWidget(
            cancel
        )

        confirm = QPushButton(
            "确定",
            objectName="primaryButton",
        )
        confirm.clicked.connect(
            self._accept_settings
        )
        buttons.addWidget(
            confirm
        )

        layout.addLayout(
            buttons
        )

    def _template_text(self) -> str:
        if not self.template_path:
            return "未选择"

        return Path(
            self.template_path
        ).name

    def choose_template(self) -> None:
        selected, choose_external = (
            choose_template_with_search(
                self,
                "选择扫描模板",
                allow_external=True,
            )
        )

        if choose_external:
            file_path, _filter = (
                QFileDialog.getOpenFileName(
                    self,
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
                self,
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
                        self,
                        "复制失败",
                        str(exc),
                    )
                    return

                self.template_path = str(
                    destination
                )
            else:
                self.template_path = str(
                    source
                )

        elif selected:
            self.template_path = selected

        self.template_label.setText(
            self._template_text()
        )

    def _accept_settings(self) -> None:
        try:
            threshold = float(
                self.threshold_edit.text()
            )
        except ValueError:
            threshold = 0.860

        threshold = max(
            0.0,
            min(
                1.0,
                threshold,
            ),
        )

        methods = tuple(
            method_id
            for method_id, checkbox
            in self.method_checks.items()
            if checkbox.isChecked()
        )

        if not methods:
            QMessageBox.warning(
                self,
                "至少选择一种识别方法",
                "扫描模板至少需要启用一种识别方法。",
            )
            return

        self.owner.selected_template_path = (
            self.template_path
        )

        sync_template_button = getattr(
            self.owner,
            "sync_template_button",
            None,
        )

        if callable(
            sync_template_button
        ):
            sync_template_button()

        self.owner.match_threshold = threshold
        self.owner.recognition_methods = (
            methods
        )
        self.owner.multi_scale = (
            self.multi_scale_check.isChecked()
        )
        self.owner.confirm_frames = (
            self.confirm_spin.value()
        )
        self.owner.feature_detector = str(
            self.detector_combo.currentData()
        )

        if (
            self.wait_for_match_check
            is not None
        ):
            self.owner.wait_for_match = (
                self.wait_for_match_check.isChecked()
            )
            self.owner.wait_timeout_ms = max(
                1,
                int(
                    self.wait_timeout_spin.value()
                ),
            )

        threshold_edit = getattr(
            self.owner,
            "threshold_edit",
            None,
        )

        if threshold_edit is not None:
            threshold_edit.setText(
                f"{threshold:.3f}"
            )

        try:
            self.owner.update()
        except Exception:
            pass

        self.accept()


class ScreenRegionSelector(QDialog):
    """
    WYSIWYG screen-region selector.

    The old implementation mixed Qt logical coordinates, Windows physical
    cursor coordinates and MSS capture coordinates. That could make the PNG
    differ from the visible rectangle.

    This selector first freezes the complete virtual desktop using MSS, then
    displays that exact image underneath the selection overlay. The selected
    rectangle is mapped back into the frozen image and the template crop is
    taken DIRECTLY from it. Therefore what the user sees is what UVAF saves.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        self.result_rect: QRect | None = None
        self.result_image: np.ndarray | None = None

        self._origin: QPoint | None = None
        self._current: QPoint | None = None

        # ----------------------------------------------------------
        # Freeze the actual desktop in the same coordinate system MSS uses.
        # ----------------------------------------------------------
        with mss.mss() as capture:
            monitor = dict(
                capture.monitors[0]
            )
            frame = np.asarray(
                capture.grab(monitor)
            )

        self._capture_left = int(
            monitor["left"]
        )
        self._capture_top = int(
            monitor["top"]
        )
        self._capture_width = int(
            monitor["width"]
        )
        self._capture_height = int(
            monitor["height"]
        )

        self._frozen_bgr = cv2.cvtColor(
            frame,
            cv2.COLOR_BGRA2BGR,
        )
        frozen_rgb = cv2.cvtColor(
            self._frozen_bgr,
            cv2.COLOR_BGR2RGB,
        )

        image_h, image_w, channels = (
            frozen_rgb.shape
        )

        self._frozen_qimage = QImage(
            frozen_rgb.data,
            image_w,
            image_h,
            channels * image_w,
            QImage.Format_RGB888,
        ).copy()

        # ----------------------------------------------------------
        # Qt's virtual geometry is only used as a presentation surface.
        # Selection -> source-image mapping is done with explicit ratios.
        # ----------------------------------------------------------
        geometry = QRect()

        for screen in QGuiApplication.screens():
            geometry = (
                screen.geometry()
                if geometry.isNull()
                else geometry.united(
                    screen.geometry()
                )
            )

        self._virtual_geometry = geometry

        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
        )
        self.setModal(True)
        self.setCursor(
            Qt.CrossCursor
        )
        self.setGeometry(
            geometry
        )
        self.setMouseTracking(
            True
        )

        # Use a dedicated overlay for the selection border. This remains
        # visible while dragging even if the heavy frozen-desktop paint is
        # temporarily delayed by Qt.
        self._rubber_band = QRubberBand(
            QRubberBand.Rectangle,
            self,
        )
        self._rubber_band.setStyleSheet(
            "QRubberBand {"
            "border: 2px solid white;"
            "background: rgba(255,255,255,18);"
            "}"
        )
        self._rubber_band.hide()

        # Opaque selector: the frozen desktop is painted by us, so the window
        # itself never contaminates the template capture.
        self.setAttribute(
            Qt.WA_TranslucentBackground,
            False,
        )

    # --------------------------------------------------------------
    # Coordinate mapping
    # --------------------------------------------------------------
    def _local_to_capture(
        self,
        point: QPoint,
    ) -> tuple[int, int]:
        view_w = max(
            1,
            self.width(),
        )
        view_h = max(
            1,
            self.height(),
        )

        scale_x = (
            self._capture_width
            / float(view_w)
        )
        scale_y = (
            self._capture_height
            / float(view_h)
        )

        capture_x = int(
            round(
                point.x()
                * scale_x
            )
        )
        capture_y = int(
            round(
                point.y()
                * scale_y
            )
        )

        capture_x = max(
            0,
            min(
                self._capture_width,
                capture_x,
            ),
        )
        capture_y = max(
            0,
            min(
                self._capture_height,
                capture_y,
            ),
        )

        return (
            capture_x,
            capture_y,
        )

    def _selection_capture_rect(
        self,
    ) -> tuple[
        int,
        int,
        int,
        int,
    ] | None:
        if (
            self._origin is None
            or self._current is None
        ):
            return None

        x1, y1 = self._local_to_capture(
            self._origin
        )
        x2, y2 = self._local_to_capture(
            self._current
        )

        left = min(
            x1,
            x2,
        )
        top = min(
            y1,
            y2,
        )
        right = max(
            x1,
            x2,
        )
        bottom = max(
            y1,
            y2,
        )

        width = (
            right - left
        )
        height = (
            bottom - top
        )

        if (
            width < 2
            or height < 2
        ):
            return None

        return (
            left,
            top,
            width,
            height,
        )

    # --------------------------------------------------------------
    # Painting
    # --------------------------------------------------------------
    def paintEvent(
        self,
        _event,
    ) -> None:
        painter = QPainter(self)

        try:
            painter.setRenderHint(
                QPainter.Antialiasing,
                True,
            )

            # Full frozen desktop.
            painter.drawImage(
                self.rect(),
                self._frozen_qimage,
            )

            # Darken everything first.
            painter.fillRect(
                self.rect(),
                QColor(
                    0,
                    0,
                    0,
                    95,
                ),
            )

            if (
                self._origin is None
                or self._current is None
            ):
                painter.setPen(
                    QColor("#FFFFFF")
                )
                painter.drawText(
                    self.rect(),
                    Qt.AlignCenter,
                    "按住左键拖动框选区域 · Esc 取消",
                )
                return

            selection = QRect(
                self._origin,
                self._current,
            ).normalized()

            source_rect = (
                self._selection_capture_rect()
            )

            if source_rect is not None:
                sx, sy, sw, sh = (
                    source_rect
                )

                # Clamp against the actual frozen image, then COPY the crop.
                # This deliberately avoids PySide6's fragile
                # drawImage(QRect, QImage, QRectF) overload which caused the
                # "called with wrong argument values" exception.
                image_w = (
                    self._frozen_qimage.width()
                )
                image_h = (
                    self._frozen_qimage.height()
                )

                sx = max(
                    0,
                    min(
                        image_w - 1,
                        int(sx),
                    ),
                )
                sy = max(
                    0,
                    min(
                        image_h - 1,
                        int(sy),
                    ),
                )
                sw = max(
                    1,
                    min(
                        int(sw),
                        image_w - sx,
                    ),
                )
                sh = max(
                    1,
                    min(
                        int(sh),
                        image_h - sy,
                    ),
                )

                crop = (
                    self._frozen_qimage
                    .copy(
                        QRect(
                            sx,
                            sy,
                            sw,
                            sh,
                        )
                    )
                )

                if not crop.isNull():
                    painter.drawImage(
                        selection,
                        crop,
                    )

                label = (
                    f"{sw} × {sh}"
                )
            else:
                label = (
                    f"{selection.width()} × "
                    f"{selection.height()}"
                )

            painter.setPen(
                QColor("#FFFFFF")
            )
            painter.drawText(
                selection.adjusted(
                    8,
                    8,
                    -8,
                    -8,
                ),
                Qt.AlignTop
                | Qt.AlignLeft,
                label,
            )

        finally:
            # Prevent QBackingStore::endPaint() warnings even if Qt rejects a
            # paint operation for an unexpected platform-specific reason.
            if painter.isActive():
                painter.end()


    # --------------------------------------------------------------
    # Interaction
    # --------------------------------------------------------------
    def mousePressEvent(
        self,
        event: QMouseEvent,
    ) -> None:
        if (
            event.button()
            == Qt.LeftButton
        ):
            self._origin = (
                event.position()
                .toPoint()
            )
            self._current = (
                self._origin
            )
            self._rubber_band.setGeometry(
                QRect(
                    self._origin,
                    self._current,
                ).normalized()
            )
            self._rubber_band.show()
            self._rubber_band.raise_()
            self.update()
            event.accept()
            return

        super().mousePressEvent(
            event
        )

    def mouseMoveEvent(
        self,
        event: QMouseEvent,
    ) -> None:
        if self._origin is not None:
            self._current = (
                event.position()
                .toPoint()
            )
            self._rubber_band.setGeometry(
                QRect(
                    self._origin,
                    self._current,
                ).normalized()
            )
            self._rubber_band.show()
            self._rubber_band.raise_()
            self.update()
            event.accept()
            return

        super().mouseMoveEvent(
            event
        )

    def mouseReleaseEvent(
        self,
        event: QMouseEvent,
    ) -> None:
        if (
            event.button()
            == Qt.LeftButton
            and self._origin is not None
        ):
            self._current = (
                event.position()
                .toPoint()
            )
            self._rubber_band.hide()

            capture_rect = (
                self._selection_capture_rect()
            )

            if capture_rect is None:
                self.reject()
                return

            sx, sy, width, height = (
                capture_rect
            )

            # Absolute MSS / recognition coordinates.
            global_x = (
                self._capture_left
                + sx
            )
            global_y = (
                self._capture_top
                + sy
            )

            self.result_rect = QRect(
                global_x,
                global_y,
                width,
                height,
            )

            # This exact image is what the user visibly selected.
            self.result_image = (
                self._frozen_bgr[
                    sy:sy + height,
                    sx:sx + width,
                ]
                .copy()
            )

            self.accept()
            return

        super().mouseReleaseEvent(
            event
        )

    def keyPressEvent(
        self,
        event: QKeyEvent,
    ) -> None:
        if (
            event.key()
            == Qt.Key_Escape
        ):
            self._rubber_band.hide()
            self.reject()
            return

        super().keyPressEvent(
            event
        )


def capture_screen_region(
    parent,
) -> tuple[
    int,
    int,
    int,
    int,
] | None:
    selector = ScreenRegionSelector(
        parent
    )

    if (
        selector.exec()
        != QDialog.Accepted
    ):
        return None

    rect = selector.result_rect

    if rect is None:
        return None

    return (
        rect.x(),
        rect.y(),
        rect.width(),
        rect.height(),
    )


def capture_screen_region_with_image(
    parent,
) -> tuple[
    tuple[
        int,
        int,
        int,
        int,
    ],
    np.ndarray,
] | None:
    """
    Return both the absolute recognition ROI and the exact pixels that were
    visible inside the selection rectangle.
    """
    selector = ScreenRegionSelector(
        parent
    )

    if (
        selector.exec()
        != QDialog.Accepted
    ):
        return None

    rect = selector.result_rect
    image = selector.result_image

    if (
        rect is None
        or image is None
        or image.size == 0
    ):
        return None

    return (
        (
            rect.x(),
            rect.y(),
            rect.width(),
            rect.height(),
        ),
        image,
    )


def create_anchor_template_from_selection(
    parent,
) -> str | None:
    """
    Create a NEW anchor template for the current project.

    Workflow:
        1. user selects an exact screen region;
        2. prompt for template name;
        3. save the exact frozen crop into the current project's templates dir;
        4. return the new template path.

    This function deliberately does NOT modify ROI coordinates. "锚点框选"
    is template creation only; ROI selection remains the responsibility of
    "ROI框选".
    """
    capture_result = (
        capture_screen_region_with_image(
            parent
        )
    )

    if capture_result is None:
        return None

    region, image = capture_result

    name, ok = QInputDialog.getText(
        parent,
        "新建锚点模板",
        "锚点模板名称：",
    )

    if (
        not ok
        or not name.strip()
    ):
        return None

    safe_name = re.sub(
        r'[<>:"/\\\\|?*]+',
        "_",
        name.strip(),
    )

    safe_name = safe_name.strip(
        " ."
    )

    if not safe_name:
        QMessageBox.warning(
            parent,
            "名称无效",
            "请输入有效的模板名称。",
        )
        return None

    if not safe_name.lower().endswith(
        ".png"
    ):
        safe_name += ".png"

    directory = templates_dir()
    directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    destination = (
        directory
        / safe_name
    )

    if destination.exists():
        answer = QMessageBox.question(
            parent,
            "覆盖锚点模板",
            (
                f"{destination.name} 已存在。\n"
                "是否覆盖这个模板？"
            ),
            QMessageBox.Yes
            | QMessageBox.No,
            QMessageBox.No,
        )

        if answer != QMessageBox.Yes:
            return None

    try:
        # Use the exact frozen crop shown during selection. Never take a
        # second screenshot, otherwise moving UI can corrupt the anchor.
        if not cv2.imwrite(
            str(destination),
            image,
        ):
            raise RuntimeError(
                "无法写入 PNG 文件。"
            )
    except Exception as exc:
        QMessageBox.warning(
            parent,
            "保存锚点模板失败",
            str(exc),
        )
        return None

    x, y, width, height = region

    QMessageBox.information(
        parent,
        "锚点模板已创建",
        (
            f"已保存到当前项目模板库：\n"
            f"{destination.name}\n\n"
            f"截取区域：{width}×{height} @ ({x}, {y})"
        ),
    )

    return str(
        destination
    )


def choose_template_with_search(
    parent,
    title: str,
    allow_external: bool = True,
) -> tuple[str | None, bool]:
    dialog = SearchableTemplateDialog(
        parent,
        title=title,
        allow_external=allow_external,
    )

    if dialog.exec() != QDialog.Accepted:
        return None, False

    return dialog.selected_path, dialog.choose_external



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

        if category.key == "sensing":
            specs = (
                ModuleSpec(
                    "sensing",
                    "findtemplate",
                    "扫描模板（坐标输出）",
                ),
                ModuleSpec(
                    "sensing",
                    "template_count",
                    "模板计数（单数字输出）",
                ),
                ModuleSpec(
                    "sensing",
                    "lock_template",
                    "锁定模板（坐标输出）",
                ),
                ModuleSpec(
                    "sensing",
                    "scan_until_found",
                    "持续扫描模板直到发现（坐标输出）",
                ),
            )
        elif category.key == "action":
            specs = (
                ModuleSpec("action", "move_to", "移至"),
                ModuleSpec("action", "drag", "拖动"),
                ModuleSpec("action", "click", "点击"),
                ModuleSpec("action", "keyboard_input", "键盘输入"),
                ModuleSpec("action", "launch_exe", "启动程序"),
                ModuleSpec("action", "delay_wait", "延时等待"),
            )
        elif category.key == "control":
            specs = (
                ModuleSpec("control", "roi", "ROI"),
                ModuleSpec("control", "loop", "循环"),
                ModuleSpec("control", "loop_until", "循环…直到…"),
                ModuleSpec("control", "logic_if", "IF…THEN…"),
                ModuleSpec("control", "logic_or", "OR（任一满足）"),
                ModuleSpec("control", "logic_nor", "NOR（均不满足）"),
                ModuleSpec("control", "logic_and", "AND（同时满足）"),
            )
        elif category.key == "data":
            specs = (
                ModuleSpec(
                    "data",
                    "fixed_coordinate",
                    "固定坐标（坐标输出）",
                ),
                ModuleSpec(
                    "data",
                    "coordinate_modify",
                    tr_text("坐标修改（坐标输出）"),
                ),
            )
        elif category.key == "debug":
            specs = (
                ModuleSpec(
                    "debug",
                    "inspect_input",
                    "检测输入",
                ),
            )
        elif category.key == "global":
            specs = (
                ModuleSpec("global", "global_anchor_roi", "仅识别锚点"),
                ModuleSpec("global", "clock", "时钟"),
            )
        elif category.key == "custom":
            specs = tuple(
                custom_specs
            )
        elif category.key == "event":
            specs = (
                ModuleSpec("event", "start", "起始"),
                *event_specs,
            )
        else:
            specs = (
                ModuleSpec(category.key, "placeholder", "占位1"),
                ModuleSpec(category.key, "placeholder", "占位2"),
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

        if module_type == "custom_module_instance":
            self.block_width = 260.0
        elif module_type in VISUAL_MODULE_TYPES:
            self.block_width = self.FIND_TEMPLATE_WIDTH
        elif module_type == "global_anchor_roi":
            self.block_width = self.GLOBAL_ANCHOR_WIDTH
        elif module_type == "launch_exe":
            self.block_width = 520.0
        elif module_type == "fixed_coordinate":
            self.block_width = 430.0
        elif module_type == "coordinate_modify":
            self.block_width = 440.0
        elif module_type in {"drag","keyboard_input","delay_wait","clock"}:
            self.block_width = 360.0
        else:
            self.block_width = self.DEFAULT_WIDTH

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

        if self.module_type in VISUAL_MODULE_TYPES:
            self._build_visual_controls()
        elif self.module_type == "global_anchor_roi":
            self._build_global_anchor_controls()
        elif self.module_type == "launch_exe":
            self._build_inline_exe_controls()
        elif self.module_type == "delay_wait":
            self._build_inline_delay_controls()
        elif self.module_type == "coordinate_modify":
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

        if self.module_type in {
            "start",
            "clock_end_start",
        }:
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
            visual_labels = {
                "findtemplate": "扫描模板（坐标输出）",
                "template_count": "模板计数（单数字输出）",
                "lock_template": "锁定模板（坐标输出）",
                "scan_until_found": "持续扫描直到发现（坐标输出）",
            }

            painter.drawText(
                QRectF(
                    15,
                    5,
                    168,
                    27,
                ),
                Qt.AlignVCenter
                | Qt.AlignLeft,
                tr_text(
                    visual_labels.get(
                        self.module_type,
                        self.text,
                    )
                ),
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

            if self.module_type in VISUAL_MODULE_TYPES:
                dialog = ScanTemplateSettingsDialog(
                    self,
                    parent,
                )
                dialog.exec()
                event.accept()
                return

            if self.module_type == "global_anchor_roi":
                engine=self._workspace_recognition_engine()
                if engine is None:
                    QMessageBox.warning(parent,"识别引擎不可用","当前无法访问 Recognition Engine。")
                    return
                GlobalAnchorSettingsDialog(self,engine,parent).exec()
                event.accept()
                return

            if self.module_type == "fixed_coordinate":
                FixedCoordinateSettingsDialog(
                    self,
                    parent,
                ).exec()
                event.accept()
                return

            if self.module_type == "coordinate_modify":
                CoordinateModifySettingsDialog(
                    self,
                    parent,
                ).exec()
                event.accept()
                return

            if self.module_type == "move_to":
                MoveToSettingsDialog(
                    self,
                    parent,
                ).exec()
                event.accept()
                return

            if self.module_type == "click":
                ClickSettingsDialog(self,parent).exec(); event.accept(); return
            if self.module_type == "drag":
                DragSettingsDialog(self,parent).exec(); event.accept(); return
            if self.module_type == "keyboard_input":
                KeyboardSettingsDialog(self,parent).exec(); event.accept(); return
            if self.module_type == "launch_exe":
                LaunchExeSettingsDialog(self,parent).exec(); event.accept(); return
            if self.module_type == "delay_wait":
                DelaySettingsDialog(self,parent).exec(); event.accept(); return
            if self.module_type == "clock":
                ClockSettingsDialog(self,parent).exec(); event.accept(); return

        super().mouseDoubleClickEvent(
            event
        )


class SimpleRoiSettingsDialog(QDialog):
    def __init__(self, roi_block: "RoiBlock", parent=None) -> None:
        super().__init__(parent)
        self.roi_block=roi_block
        self.setWindowTitle('ROI 设置'); self.setModal(True); self.resize(570,310)
        layout=QVBoxLayout(self); layout.setContentsMargins(16,16,16,16); layout.setSpacing(11)
        x,y,w,h=roi_block.roi_values()
        direct=QHBoxLayout(); self.edits={}
        for k,v in zip(('X','Y','W','H'),(x,y,w,h)):
            direct.addWidget(QLabel(k)); e=QLineEdit(str(v)); e.setFixedWidth(72); e.setValidator(QIntValidator(-100000,100000,e)); direct.addWidget(e); self.edits[k]=e
        layout.addLayout(direct)
        quick=QHBoxLayout(); quick.addWidget(QLabel('左上角坐标'))
        self.coord_edit=QLineEdit(f'{x},{y}'); self.coord_edit.setPlaceholderText('例如 758,373'); quick.addWidget(self.coord_edit)
        quick.addWidget(QLabel('大小')); self.size_edit=QLineEdit(f'{w}*{h}'); self.size_edit.setPlaceholderText('例如 1920*800'); quick.addWidget(self.size_edit)
        apply=QPushButton('应用',objectName='secondaryButton'); apply.clicked.connect(self.apply_quick); quick.addWidget(apply); layout.addLayout(quick)
        tools=QHBoxLayout()
        b=QPushButton('ROI框选',objectName='secondaryButton'); b.clicked.connect(self.select_roi); tools.addWidget(b)
        b=QPushButton('选择锚点',objectName='secondaryButton'); b.clicked.connect(self.choose_anchor); tools.addWidget(b)
        b=QPushButton('锚点框选',objectName='secondaryButton'); b.clicked.connect(self.create_anchor_template); tools.addWidget(b); tools.addStretch(); layout.addLayout(tools)
        self.anchor_label=QLabel('锚点：'+(Path(roi_block.anchor_template_path).name if roi_block.anchor_template_path else '无'),objectName='muted'); layout.addWidget(self.anchor_label)
        layout.addStretch(); bottom=QHBoxLayout(); bottom.addStretch()
        c=QPushButton('取消',objectName='secondaryButton'); c.clicked.connect(self.reject); bottom.addWidget(c)
        ok=QPushButton('确定',objectName='primaryButton'); ok.clicked.connect(self.accept_values); bottom.addWidget(ok); layout.addLayout(bottom)
    def values(self):
        vals=[]
        for k in ('X','Y','W','H'):
            try: vals.append(int(self.edits[k].text()))
            except ValueError: vals.append(0)
        x,y,w,h=vals; return x,y,max(1,w),max(1,h)
    def set_values(self,values):
        for k,v in zip(('X','Y','W','H'),values): self.edits[k].setText(str(int(v)))
        x,y,w,h=values; self.coord_edit.setText(f'{x},{y}'); self.size_edit.setText(f'{w}*{h}')
    def apply_quick(self):
        coord=parse_coord_text(self.coord_edit.text()); size=parse_size_text(self.size_edit.text())
        if coord is None or size is None:
            QMessageBox.warning(self,'格式错误','坐标示例：758,373；大小示例：1920*800。'); return
        self.set_values((coord[0],coord[1],size[0],size[1]))
    def select_roi(self):
        region = capture_screen_region(
            self
        )

        if region is None:
            return

        x, y, w, h = region
        selected = (
            self.roi_block.anchor_template_path
        )

        # Preserve anchor. When present, ROI框选 writes anchor-relative X/Y.
        if selected:
            try:
                engine = (
                    self.roi_block
                    ._workspace_recognition_engine()
                )

                if engine is not None:
                    anchor = engine.scan_template(
                        selected,
                        roi=None,
                        options=TemplateScanOptions(
                            threshold=0.860,
                            methods=(
                                "ccoeff_color",
                                "grayscale",
                                "rgb_count",
                                "hsv_count",
                            ),
                            scales=(1.0,),
                            confirm_frames=1,
                        ),
                    )

                    if anchor is None:
                        raise RuntimeError(
                            "当前屏幕中没有找到所选锚点。"
                        )

                    self.set_values(
                        (
                            x - anchor.global_x,
                            y - anchor.global_y,
                            w,
                            h,
                        )
                    )
                    return

                legacy = find_template_once(
                    selected,
                    threshold=0.860,
                    roi=None,
                )

                if legacy is None:
                    raise RuntimeError(
                        "当前屏幕中没有找到所选锚点。"
                    )

                ax, ay, _score = legacy
                self.set_values(
                    (
                        x - ax,
                        y - ay,
                        w,
                        h,
                    )
                )
                return

            except Exception as exc:
                QMessageBox.warning(
                    self,
                    "锚点识别失败",
                    str(exc),
                )
                return

        self.set_values(
            (
                x,
                y,
                w,
                h,
            )
        )
    def choose_anchor(self):
        selected,_=choose_template_with_search(self,'选择锚点模板',allow_external=False)
        if selected:
            self.roi_block.anchor_template_path=selected; self.anchor_label.setText(tr_text(f'锚点：{Path(selected).name}'))
    def create_anchor_template(
        self,
    ) -> None:
        """
        "锚点框选" creates a new anchor template only.

        It does NOT change X/Y/W/H. After creation, the new template is
        immediately assigned as this ROI's selected anchor.
        """
        selected = (
            create_anchor_template_from_selection(
                self
            )
        )

        if not selected:
            return

        self.roi_block.anchor_template_path = (
            selected
        )
        self.anchor_label.setText(
            tr_text(
                f"锚点：{Path(selected).name}"
            )
        )

    def accept_values(self):
        self.roi_block.set_roi_values(self.values()); self.accept()

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
        if block is self or block.module_type in {"start","clock_end_start"}: return False
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

    SLOT_LABELS={
        "loop":("循环体",),
        "loop_until":("循环任务（重复）","直到"),
        "logic_if":("IF · 判定","THEN · 执行"),
        "logic_or":("条件 A","条件 B","任一满足后执行"),
        "logic_nor":("条件 A","条件 B","均不满足后执行"),
        "logic_and":("条件 A","条件 B","两者均满足后执行"),
    }
    DISPLAY_NAMES={
        "loop":"循环",
        "loop_until":"循环…直到…",
        "logic_if":"IF…THEN…",
        "logic_or":"OR（任一满足）",
        "logic_nor":"NOR（均不满足）",
        "logic_and":"AND（同时满足）",
    }

    def __init__(self,category:BlockCategory,module_type:str,text:str)->None:
        super().__init__(category,module_type,text)
        self.block_width=self.DEFAULT_WIDTH
        self.logic_height=150.0
        self.slot_roots=[None for _ in self.SLOT_LABELS[module_type]]
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
        if block is self or block.module_type in {"start","clock_end_start"} or not 0<=slot_index<self.slot_count():
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
        if self.module_type=="logic_if": return (0,)
        if self.module_type in {"logic_or","logic_nor","logic_and"}: return (0,1)
        return ()

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
        title=tr_text(self.DISPLAY_NAMES.get(self.module_type,self.text))
        painter.drawText(QRectF(15,5,260 if self.module_type!="loop" else 62,30),Qt.AlignVCenter|Qt.AlignLeft,title)
        if self.module_type=="loop" and not self.loop_infinite:
            painter.drawText(
                QRectF(174,5,44,30),
                Qt.AlignVCenter|Qt.AlignLeft,
                tr_text("次"),
            )
        for index,label in enumerate(self.SLOT_LABELS[self.module_type]):
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
        if event.button()==Qt.LeftButton and self.module_type=="loop":
            parent=None; scene=self.scene()
            if scene is not None:
                for view in scene.views(): parent=view.window(); break
            LoopSettingsDialog(self,parent).exec(); event.accept(); return
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

        # Complex mode exposes at least three external inputs/outputs on
        # every node. Existing "input"/"output" names are preserved for
        # project compatibility and remain the primary execution path.
        if module_type in {
            "start",
            "clock_end_start",
        }:
            self.input_ports: tuple[str, ...] = ()
            self.output_ports: tuple[str, ...] = (
                "output",
                "output_2",
                "output_3",
            )
        elif module_type == "roi":
            self.input_ports = (
                "input",
                "input_2",
                "input_3",
                "inner_input",
            )
            self.output_ports = (
                "output",
                "output_2",
                "output_3",
                "inner_output",
            )
        elif module_type == "loop":
            self.input_ports=("input","input_2","input_3")
            self.output_ports=("output","output_2","output_3","body_output")
        elif module_type in {"loop_until","logic_if"}:
            self.input_ports=("input","input_2","input_3")
            self.output_ports=("output","output_2","output_3","branch_a_output","branch_b_output")
        elif module_type in {"logic_or","logic_nor","logic_and"}:
            self.input_ports=("input","input_2","input_3")
            self.output_ports=("output","output_2","output_3","branch_a_output","branch_b_output","branch_c_output")
        else:
            self.input_ports = (
                "input",
                "input_2",
                "input_3",
            )
            self.output_ports = (
                "output",
                "output_2",
                "output_3",
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

        visual_labels = {
            "findtemplate": "扫描模板（坐标输出）",
            "template_count": "模板计数（单数字输出）",
            "lock_template": "锁定模板（坐标输出）",
            "scan_until_found": "持续扫描直到发现（坐标输出）",
        }

        label = (
            self.text
            if self.module_type == "custom_module_instance"
            else tr_text(
                visual_labels.get(
                    self.module_type,
                    self.text,
                )
            )
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
                    if self.module_type == "roi":
                        view.edit_roi_node(
                            self
                        )
                        event.accept()
                        return

                    if self.module_type in VISUAL_MODULE_TYPES:
                        dialog = ScanTemplateSettingsDialog(
                            self,
                            view.window(),
                        )
                        dialog.exec()
                        event.accept()
                        return

                    if self.module_type == "global_anchor_roi":
                        page=view
                        while page is not None:
                            engine=getattr(page,"recognition_engine",None)
                            if engine is not None:
                                GlobalAnchorSettingsDialog(self,engine,view.window()).exec()
                                event.accept()
                                return
                            page=page.parent()

                    if self.module_type == "fixed_coordinate":
                        FixedCoordinateSettingsDialog(
                            self,
                            view.window(),
                        ).exec()
                        event.accept()
                        return

                    if self.module_type == "coordinate_modify":
                        CoordinateModifySettingsDialog(
                            self,
                            view.window(),
                        ).exec()
                        event.accept()
                        return

                    if self.module_type == "loop":
                        LoopSettingsDialog(self,view.window()).exec()
                        event.accept()
                        return

                    if self.module_type == "move_to":
                        MoveToSettingsDialog(
                            self,
                            view.window(),
                        ).exec()
                        event.accept()
                        return

                    if self.module_type == "click":
                        ClickSettingsDialog(self,view.window()).exec(); event.accept(); return
                    if self.module_type == "drag":
                        DragSettingsDialog(self,view.window()).exec(); event.accept(); return
                    if self.module_type == "keyboard_input":
                        KeyboardSettingsDialog(self,view.window()).exec(); event.accept(); return
                    if self.module_type == "launch_exe":
                        LaunchExeSettingsDialog(self,view.window()).exec(); event.accept(); return
                    if self.module_type == "delay_wait":
                        DelaySettingsDialog(self,view.window()).exec(); event.accept(); return
                    if self.module_type == "clock":
                        ClockSettingsDialog(self,view.window()).exec(); event.accept(); return

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


class ComplexRoiDialog(QDialog):
    def __init__(
        self,
        node: ComplexNode,
        parent=None,
    ) -> None:
        super().__init__(parent)

        self.node = node
        self.setWindowTitle(
            "ROI 设置"
        )
        self.setModal(True)
        self.resize(
            460,
            250,
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            16,
            16,
            16,
            16,
        )
        layout.setSpacing(10)

        fields = QHBoxLayout()

        self.edits: dict[
            str,
            QLineEdit,
        ] = {}

        values = (
            node.roi_values_data
        )

        for key, value in zip(
            ("X", "Y", "W", "H"),
            values,
        ):
            column = QVBoxLayout()
            column.addWidget(
                QLabel(key)
            )

            edit = QLineEdit(
                str(value)
            )
            edit.setValidator(
                QIntValidator(
                    -100000,
                    100000,
                    edit,
                )
            )
            edit.setFixedWidth(
                82
            )
            column.addWidget(
                edit
            )

            fields.addLayout(
                column
            )
            self.edits[key] = edit

        layout.addLayout(fields)

        quick_row = QHBoxLayout()
        quick_row.addWidget(QLabel("左上角坐标"))
        self.quick_coord_edit = QLineEdit(f"{values[0]},{values[1]}")
        self.quick_coord_edit.setPlaceholderText("例如 758,373")
        quick_row.addWidget(self.quick_coord_edit)
        quick_row.addWidget(QLabel("大小"))
        self.quick_size_edit = QLineEdit(f"{values[2]}*{values[3]}")
        self.quick_size_edit.setPlaceholderText("例如 1920*800")
        quick_row.addWidget(self.quick_size_edit)
        apply_quick_button = QPushButton("应用", objectName="secondaryButton")
        quick_row.addWidget(apply_quick_button)
        layout.addLayout(quick_row)

        anchor_label = QLabel(
            (
                "锚点："
                + (
                    Path(
                        node.anchor_template_path
                    ).name
                    if node.anchor_template_path
                    else "无"
                )
            ),
            objectName="muted",
        )
        layout.addWidget(
            anchor_label
        )

        tool_row = QHBoxLayout()

        select_button = QPushButton(
            "ROI框选",
            objectName="secondaryButton",
        )
        tool_row.addWidget(
            select_button
        )

        choose_anchor_button = QPushButton(
            "选择锚点",
            objectName="secondaryButton",
        )
        tool_row.addWidget(
            choose_anchor_button
        )

        anchor_button = QPushButton(
            "锚点框选",
            objectName="secondaryButton",
        )
        tool_row.addWidget(
            anchor_button
        )

        clear_anchor_button = QPushButton(
            "清除锚点",
            objectName="secondaryButton",
        )
        tool_row.addWidget(
            clear_anchor_button
        )

        tool_row.addStretch()
        layout.addLayout(
            tool_row
        )

        bottom = QHBoxLayout()
        bottom.addStretch()

        cancel = QPushButton(
            "取消",
            objectName="secondaryButton",
        )
        cancel.clicked.connect(
            self.reject
        )
        bottom.addWidget(cancel)

        confirm = QPushButton(
            "确定",
            objectName="primaryButton",
        )
        confirm.clicked.connect(
            self.accept
        )
        bottom.addWidget(confirm)

        layout.addLayout(bottom)

        def set_values(
            values_tuple,
        ):
            for key, value in zip(
                ("X", "Y", "W", "H"),
                values_tuple,
            ):
                self.edits[key].setText(
                    str(int(value))
                )

        def select_plain():
            values_tuple = (
                capture_screen_region(
                    self
                )
            )

            if values_tuple is None:
                return

            x, y, w, h = values_tuple
            selected = (
                node.anchor_template_path
            )

            # Preserve anchor and store relative coordinates whenever one is
            # selected. Do not silently switch coordinate systems.
            if selected:
                try:
                    result = find_template_once(
                        selected,
                        threshold=0.860,
                        roi=None,
                    )

                    if result is None:
                        raise RuntimeError(
                            "当前屏幕中没有找到所选锚点。"
                        )

                    anchor_x, anchor_y, _score = (
                        result
                    )
                    set_values(
                        (
                            x - anchor_x,
                            y - anchor_y,
                            w,
                            h,
                        )
                    )
                    return

                except Exception as exc:
                    QMessageBox.warning(
                        self,
                        "锚点识别失败",
                        str(exc),
                    )
                    return

            set_values(
                (
                    x,
                    y,
                    w,
                    h,
                )
            )

        def choose_anchor():
            selected, _external = (
                choose_template_with_search(
                    self,
                    "选择锚点模板",
                    allow_external=False,
                )
            )

            if not selected:
                return

            node.anchor_template_path = (
                selected
            )
            anchor_label.setText(
                tr_text(
                    f"锚点：{Path(selected).name}"
                )
            )

        def create_anchor():
            selected = (
                create_anchor_template_from_selection(
                    self
                )
            )

            if not selected:
                return

            node.anchor_template_path = (
                selected
            )
            anchor_label.setText(
                tr_text(
                    f"锚点：{Path(selected).name}"
                )
            )
            node.update()

        def apply_quick():
            coord = parse_coord_text(self.quick_coord_edit.text())
            size = parse_size_text(self.quick_size_edit.text())
            if coord is None or size is None:
                QMessageBox.warning(self, "格式错误", "坐标示例：758,373；大小示例：1920*800。")
                return
            set_values((coord[0], coord[1], size[0], size[1]))

        apply_quick_button.clicked.connect(apply_quick)

        select_button.clicked.connect(
            select_plain
        )
        choose_anchor_button.clicked.connect(
            choose_anchor
        )
        anchor_button.clicked.connect(
            create_anchor
        )
        clear_anchor_button.clicked.connect(
            lambda: (
                setattr(
                    node,
                    "anchor_template_path",
                    None,
                ),
                anchor_label.setText(
                    tr_text(
                        "锚点：无"
                    )
                ),
            )
        )

    def values(
        self,
    ) -> tuple[
        int,
        int,
        int,
        int,
    ]:
        result = []

        for key in (
            "X",
            "Y",
            "W",
            "H",
        ):
            try:
                value = int(
                    self.edits[
                        key
                    ].text()
                )
            except ValueError:
                value = 0

            result.append(
                value
            )

        x, y, w, h = result

        return (
            x,
            y,
            max(1, w),
            max(1, h),
        )


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


class WorkspacePage(QWidget):
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
            self.run_workflows
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
        return module_type in {
            "start",
            "clock_end_start",
        }

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
        return step.module_type in {
            "global_anchor_roi",
            "clock",
        }

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

    def _runtime_cancelled(self) -> bool:
        return (
            self._stop_event.is_set()
            or self._event_chain_cancel.is_set()
        )

    def _wait_module_gap(
        self,
        seconds: float = MODULE_MIN_GAP_SECONDS,
        ignore_event_chain_cancel: bool = False,
    ) -> bool:
        """
        Cooperative gap between two COMPLETED modules in the same chain.

        _execute_steps is intentionally synchronous: the next iteration is
        unreachable until the current module has finished all of its internal
        work. Separate event chains use separate worker threads and therefore
        remain concurrent.
        """
        end_time = (
            time.perf_counter()
            + max(
                0.0,
                float(seconds),
            )
        )

        while True:
            if self._stop_event.is_set():
                return False

            if (
                not ignore_event_chain_cancel
                and self._event_chain_cancel.is_set()
            ):
                return False

            remaining = (
                end_time
                - time.perf_counter()
            )

            if remaining <= 0:
                return True

            time.sleep(
                min(
                    remaining,
                    0.001,
                )
            )

    @staticmethod
    def _duration_seconds(value: float, unit: str) -> float:
        return max(0.0,float(value))*{"milliseconds":0.001,"seconds":1.0,"minutes":60.0,"hours":3600.0}.get(str(unit),1.0)

    def _start_clock(self, step: ExecutionStep) -> None:
        seconds=self._duration_seconds(step.clock_value,step.clock_unit); behavior=step.clock_behavior
        def worker():
            if not self._stop_event.wait(seconds):
                self.runtime_signals.clock_expired.emit(
                    str(behavior),
                    int(step.clock_event_slot),
                )
        th=threading.Thread(target=worker,daemon=True,name="UVAF-Clock"); self._clock_threads.append(th); th.start()
        self.logger.info(f"时钟已启动：{seconds:.3f}s → {behavior}",source="global")

    def _on_clock_expired(
        self,
        behavior: str,
        clock_event_slot: int,
    ) -> None:
        self.logger.info(
            f"时钟结束：{behavior}",
            source="global",
        )

        if behavior in {
            "execute_chain",
            "stop_others_execute_chain",
        }:
            if behavior == "stop_others_execute_chain":
                # Stop ordinary/event chains only. Do not set _stop_event,
                # because the clock-end chain must remain allowed to run.
                self._event_chain_cancel.set()
                self.logger.info(
                    "时钟：已终止其他事件链条，开始执行时钟终止后链。",
                    source="global",
                )

            event_chain = self._clock_event_chains.get(
                int(clock_event_slot),
                [],
            )

            if event_chain:
                context = {
                    "last_output": None,
                    "last_output_space": None,
                    "global_recognition_roi": (
                        self._active_global_recognition_roi
                    ),
                    "global_anchor_point": (
                        self._active_global_anchor_point
                    ),
                }

                def runner():
                    self._execute_steps(
                        9001,
                        event_chain,
                        context,
                        None,
                        ignore_event_chain_cancel=True,
                    )

                threading.Thread(
                    target=runner,
                    daemon=True,
                    name="UVAF-ClockEvent",
                ).start()

            return

        self.stop_workflows()

        if behavior == "stop_close":
            self.window().close()

    def _activate_global_steps(
        self,
        global_steps: list[ExecutionStep],
    ) -> bool:
        """
        Apply global settings synchronously before ordinary workflow threads
        start. Their effects remain stored on WorkspacePage until Stop.
        """
        if not global_steps:
            return True

        combined_roi: (
            tuple[int, int, int, int]
            | None
        ) = None

        first_anchor_point = None

        for step in global_steps:
            if self._stop_event.is_set():
                return False

            if not self._wait_module_gap():
                return False

            if step.module_type == "clock":
                self._start_clock(step)
                continue

            if (
                not step.global_anchor_template_path
                or step.global_anchor_roi is None
            ):
                self.runtime_status.setText(
                    tr_text(
                        "全局设置未完成配置"
                    )
                )
                return False

            anchor = (
                self.recognition_engine.scan_template(
                    step.global_anchor_template_path,
                    roi=combined_roi,
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

            if anchor is None:
                self.runtime_status.setText(
                    tr_text(
                        "全局锚点未找到"
                    )
                )
                return False

            if first_anchor_point is None:
                first_anchor_point = (
                    anchor.global_x,
                    anchor.global_y,
                )

            off_x, off_y, width, height = (
                step.global_anchor_roi
            )

            resolved = (
                anchor.x + off_x,
                anchor.y + off_y,
                width,
                height,
            )

            combined_roi = intersect_roi(
                combined_roi,
                resolved,
            )

            if combined_roi is None:
                self.runtime_status.setText(
                    tr_text(
                        "多个全局识别范围没有交集"
                    )
                )
                return False

        with self._runtime_lock:
            self._active_global_recognition_roi = (
                combined_roi
            )
            self._active_global_anchor_point = (
                first_anchor_point
            )
            self._global_runtime_active = True

        global_message = (
            "全局设置已持续启用："
            f"{combined_roi}"
        )

        self.logger.info(
            global_message,
            source="global",
        )
        self.runtime_signals.message.emit(
            global_message
        )

        return True

    def stop_workflows(self) -> None:
        """
        Stop the current runtime and remove every persistent global setting.

        Existing worker threads are cooperative: each module boundary checks
        _stop_event and exits as soon as possible.
        """
        self._vision_clear_debug()

        self._stop_event.set()

        with self._runtime_lock:
            self._active_global_recognition_roi = None
            self._active_global_anchor_point = None
            self._global_runtime_active = False

        self._active_chains = 0

        if hasattr(
            self,
            "run_button",
        ):
            self.run_button.setEnabled(
                True
            )

        if hasattr(
            self,
            "stop_button",
        ):
            self.stop_button.setEnabled(
                False
            )

        if hasattr(
            self,
            "runtime_status",
        ):
            self.runtime_status.setText(
                tr_text(
                    "已停止"
                )
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

    def _resolve_global_step_roi(
        self,
        step: ExecutionStep,
    ) -> tuple[int, int, int, int] | None:
        if (
            step.module_type != "global_anchor_roi"
            or not step.global_anchor_template_path
            or step.global_anchor_roi is None
        ):
            return None

        anchor = self.recognition_engine.scan_template(
            step.global_anchor_template_path,
            roi=None,
            options=TemplateScanOptions(
                threshold=0.860,
                methods=("ccoeff_color", "grayscale", "feature"),
                scales=(0.90, 1.0, 1.10),
                confirm_frames=1,
            ),
        )

        if anchor is None:
            return None

        off_x, off_y, width, height = step.global_anchor_roi
        return (
            anchor.x + off_x,
            anchor.y + off_y,
            width,
            height,
        )

    def _launch_chains(
        self,
        chains: list[
            list[ExecutionStep]
        ],
    ) -> None:
        # Global settings are intentionally resolved before any start chain
        # launches, so one connected global-setting module constrains every
        # concurrently executing start chain. Multiple global restrictions
        # combine by intersection.
        # Global settings have already been resolved synchronously by
        # _activate_global_steps() before ordinary chains are launched.
        # Start from that persistent restriction instead of None.
        with self._runtime_lock:
            run_global_roi = (
                self._active_global_recognition_roi
            )

        for chain in chains:
            for step in chain:
                if step.module_type != "global_anchor_roi":
                    continue

                try:
                    resolved = self._resolve_global_step_roi(step)
                except Exception as exc:
                    self.logger.warning(
                        f"Global recognition restriction failed: {exc}",
                        source="global",
                    )
                    resolved = None

                if resolved is not None:
                    run_global_roi = intersect_roi(
                        run_global_roi,
                        resolved,
                    )

        self._active_chains = len(
            chains
        )
        self.run_button.setEnabled(
            False
        )
        self.stop_button.setEnabled(
            True
        )
        self.runtime_status.setText(
            tr_text(
                f"正在运行 {len(chains)} 条流程"
            )
        )

        barrier = threading.Barrier(
            len(chains)
        )

        for index, steps in enumerate(
            chains,
            start=1,
        ):
            worker = threading.Thread(
                target=self._execute_chain,
                args=(
                    index,
                    steps,
                    barrier,
                    run_global_roi,
                ),
                daemon=True,
                name=(
                    f"UVAF-Workflow-{index}"
                ),
            )
            worker.start()

    def _execute_chain(
        self,
        chain_index: int,
        steps: list[ExecutionStep],
        barrier: threading.Barrier,
        run_global_roi: tuple[int, int, int, int] | None,
    ) -> None:
        try:
            try:
                barrier.wait(
                    timeout=3.0
                )
            except (
                threading.BrokenBarrierError
            ):
                pass

            context: dict[
                str,
                object,
            ] = {
                "last_output": None,
                "last_output_space": None,
                "global_recognition_roi": (
                    run_global_roi
                    if run_global_roi is not None
                    else self._active_global_recognition_roi
                ),
                "global_anchor_point": (
                    self._active_global_anchor_point
                    if hasattr(
                        self,
                        "_active_global_anchor_point",
                    )
                    else None
                ),
            }

            self._execute_steps(
                chain_index,
                steps,
                context,
                active_roi=None,
            )

        finally:
            self.runtime_signals.chain_finished.emit()

    @staticmethod
    def _condition_truth(value) -> bool:
        if isinstance(value,bool):
            return value
        if isinstance(value,(int,float)):
            return value != 0
        if isinstance(value,(tuple,list)) and len(value)>=2:
            return True
        if value is None:
            return False
        return bool(value)

    @classmethod
    def _step_contributes_condition(
        cls,
        step: ExecutionStep,
    ) -> bool:
        if step.module_type in ACTION_MODULE_TYPES:
            return False

        if step.module_type == "roi":
            return any(
                cls._step_contributes_condition(child)
                for child in step.children
            )

        if step.module_type in LOGIC_CONTAINER_TYPES:
            return any(
                cls._step_contributes_condition(child)
                for branch in step.branches
                for child in branch
            )

        if step.module_type == "global_anchor_roi":
            return False

        return True

    def _evaluate_condition_branch(
        self,
        chain_index:int,
        branch,
        context:dict[str,object],
        active_roi,
        selection_anchor,
        ignore_event_chain_cancel:bool,
        local_cancel_event=None,
    ) -> tuple[bool,dict[str,object]]:
        branch_context=dict(context)

        # An empty judgement frame does not satisfy a condition.
        if not branch:
            return False, branch_context

        contributes=any(
            self._step_contributes_condition(step)
            for step in branch
        )

        success=self._execute_steps(
            chain_index,
            branch,
            branch_context,
            active_roi,
            selection_anchor=selection_anchor,
            ignore_event_chain_cancel=ignore_event_chain_cancel,
            local_cancel_event=local_cancel_event,
        )

        if not success:
            return False,branch_context

        # Explicit user rule: if the judgement frame contains only actions,
        # successful completion counts as True, while those actions themselves
        # never provide a separate judgement value.
        if not contributes:
            return True,branch_context

        return (
            self._condition_truth(
                branch_context.get("last_output")
            ),
            branch_context,
        )


    def _evaluate_two_conditions_parallel(
        self,
        chain_index:int,
        first,
        second,
        context:dict[str,object],
        active_roi,
        selection_anchor,
        ignore_event_chain_cancel:bool,
        mode:str,
        local_cancel_event=None,
    ):
        """
        Evaluate two judgement branches concurrently.

        OR:  return as soon as either branch becomes True.
        AND: return False as soon as either branch becomes False; otherwise
             wait for both True.
        NOR: return False as soon as either becomes True; otherwise wait until
             both finish False.

        The unneeded sibling branch receives a local cancellation event, so an
        infinite detector in that branch cannot block a decision already made
        by the other branch.
        """
        results=[None,None]
        done=[threading.Event(),threading.Event()]
        cancel=[threading.Event(),threading.Event()]

        def worker(index:int,branch)->None:
            try:
                results[index]=self._evaluate_condition_branch(
                    chain_index,
                    branch,
                    context,
                    active_roi,
                    selection_anchor,
                    ignore_event_chain_cancel,
                    cancel[index],
                )
            finally:
                done[index].set()

        threads=[
            threading.Thread(
                target=worker,
                args=(0,first),
                daemon=True,
                name=f"UVAF-Cond-{chain_index}-A",
            ),
            threading.Thread(
                target=worker,
                args=(1,second),
                daemon=True,
                name=f"UVAF-Cond-{chain_index}-B",
            ),
        ]

        for thread in threads:
            thread.start()

        verdict=None
        selected_context=dict(context)

        while verdict is None:
            if (
                self._stop_event.is_set()
                or (
                    local_cancel_event is not None
                    and local_cancel_event.is_set()
                )
            ):
                cancel[0].set(); cancel[1].set()
                verdict=False
                break

            known=[
                (
                    results[index][0]
                    if results[index] is not None
                    else None
                )
                for index in range(2)
            ]

            if mode=="or":
                for index,value in enumerate(known):
                    if value is True:
                        verdict=True
                        selected_context=results[index][1]
                        cancel[1-index].set()
                        break

                if verdict is None and all(done_event.is_set() for done_event in done):
                    verdict=False
                    for result in results:
                        if result is not None:
                            selected_context=result[1]

            elif mode=="and":
                for index,value in enumerate(known):
                    if value is False:
                        verdict=False
                        selected_context=results[index][1]
                        cancel[1-index].set()
                        break

                if (
                    verdict is None
                    and all(value is True for value in known)
                ):
                    verdict=True
                    selected_context=results[1][1]

            else:  # NOR
                for index,value in enumerate(known):
                    if value is True:
                        verdict=False
                        selected_context=results[index][1]
                        cancel[1-index].set()
                        break

                if (
                    verdict is None
                    and all(done_event.is_set() for done_event in done)
                ):
                    verdict=all(value is False for value in known)
                    for result in results:
                        if result is not None:
                            selected_context=result[1]

            if verdict is None:
                time.sleep(0.005)

        for thread in threads:
            thread.join(timeout=0.10)

        values=[
            (
                results[index][0]
                if results[index] is not None
                else False
            )
            for index in range(2)
        ]

        return (
            bool(verdict),
            selected_context,
            bool(values[0]),
            bool(values[1]),
        )


    def _execute_steps(
        self,
        chain_index: int,
        steps,
        context: dict[str, object],
        active_roi,
        selection_anchor=None,
        ignore_event_chain_cancel: bool = False,
        local_cancel_event=None,
    ) -> bool:
        def module_cancelled() -> bool:
            if self._stop_event.is_set():
                return True
            if (
                not ignore_event_chain_cancel
                and self._event_chain_cancel.is_set()
            ):
                return True
            if (
                local_cancel_event is not None
                and local_cancel_event.is_set()
            ):
                return True
            return False

        for step_index, step in enumerate(
            steps
        ):
            if self._stop_event.is_set():
                return False

            if (
                not ignore_event_chain_cancel
                and self._event_chain_cancel.is_set()
            ):
                return False

            if (
                local_cancel_event is not None
                and local_cancel_event.is_set()
            ):
                return False

            # Mandatory executor guard: every module gets at least a 5 ms
            # scheduling gap before it runs. This also covers the first child
            # inside ROI containers and event-triggered chains.
            if not self._wait_module_gap(
                MODULE_MIN_GAP_SECONDS,
                ignore_event_chain_cancel=(
                    ignore_event_chain_cancel
                ),
            ):
                return False

            if step.module_type == "custom_module_instance":
                branches = [
                    branch
                    for branch in step.branches
                    if branch
                ]

                if not branches:
                    self.logger.warning(
                        f"流程 {chain_index}：自定义模块 {step.label} 没有可执行内容。",
                        source="custom",
                    )
                    continue

                if len(branches) == 1:
                    if not self._execute_steps(
                        chain_index,
                        branches[0],
                        context,
                        active_roi,
                        selection_anchor=selection_anchor,
                        ignore_event_chain_cancel=ignore_event_chain_cancel,
                        local_cancel_event=local_cancel_event,
                    ):
                        return False
                else:
                    done_events: list[threading.Event] = []
                    results: list[tuple[bool, dict[str, object]] | None] = [
                        None
                        for _ in branches
                    ]

                    def run_custom_branch(
                        branch_index: int,
                        branch_steps,
                    ) -> None:
                        branch_context = dict(context)
                        ok = self._execute_steps(
                            chain_index,
                            branch_steps,
                            branch_context,
                            active_roi,
                            selection_anchor=selection_anchor,
                            ignore_event_chain_cancel=ignore_event_chain_cancel,
                            local_cancel_event=local_cancel_event,
                        )
                        results[branch_index] = (
                            ok,
                            branch_context,
                        )
                        done_events[branch_index].set()

                    for branch_index, branch_steps in enumerate(branches):
                        done = threading.Event()
                        done_events.append(done)
                        threading.Thread(
                            target=run_custom_branch,
                            args=(branch_index, branch_steps),
                            daemon=True,
                            name=f"UVAF-Custom-{chain_index}-{branch_index+1}",
                        ).start()

                    while not all(
                        event.is_set()
                        for event in done_events
                    ):
                        if self._stop_event.wait(0.005):
                            return False
                        if (
                            local_cancel_event is not None
                            and local_cancel_event.is_set()
                        ):
                            return False

                    for result in results:
                        if result is None or not result[0]:
                            return False

                    # Multiple internal roots complete as one module. Use the
                    # last branch's final output as the custom module output.
                    if results and results[-1] is not None:
                        context.update(results[-1][1])

                self.logger.info(
                    f"流程 {chain_index}：自定义模块 {step.label} 完成",
                    source="custom",
                )
                continue

            if step.module_type == "loop":
                branch = step.branches[0] if step.branches else ()
                iteration = 0

                while (
                    step.loop_infinite
                    or iteration < max(1, int(step.loop_count))
                ):
                    if module_cancelled():
                        return False
                    if local_cancel_event is not None and local_cancel_event.is_set():
                        return False

                    if branch:
                        if not self._execute_steps(
                            chain_index,
                            branch,
                            context,
                            active_roi,
                            selection_anchor=selection_anchor,
                            ignore_event_chain_cancel=ignore_event_chain_cancel,
                            local_cancel_event=local_cancel_event,
                        ):
                            return False
                    else:
                        if not self._wait_module_gap(
                            MODULE_MIN_GAP_SECONDS,
                            ignore_event_chain_cancel=ignore_event_chain_cancel,
                        ):
                            return False

                    iteration += 1

                self.logger.info(
                    f"流程 {chain_index}：循环完成 · {iteration} 次",
                    source="logic",
                )
                continue

            if step.module_type == "loop_until":
                repeating = step.branches[0] if len(step.branches) > 0 else ()
                terminator = step.branches[1] if len(step.branches) > 1 else ()

                stop_repeating = threading.Event()
                repeating_done = threading.Event()
                repeating_context = dict(context)

                def repeat_worker() -> None:
                    try:
                        while (
                            not stop_repeating.is_set()
                            and not self._stop_event.is_set()
                        ):
                            if repeating:
                                completed = self._execute_steps(
                                    chain_index,
                                    repeating,
                                    repeating_context,
                                    active_roi,
                                    selection_anchor=selection_anchor,
                                    ignore_event_chain_cancel=ignore_event_chain_cancel,
                                    local_cancel_event=stop_repeating,
                                )
                                if not completed and not stop_repeating.is_set():
                                    break
                            else:
                                if stop_repeating.wait(MODULE_MIN_GAP_SECONDS):
                                    break
                    finally:
                        repeating_done.set()

                thread = threading.Thread(
                    target=repeat_worker,
                    daemon=True,
                    name=f"UVAF-LoopUntil-{chain_index}",
                )
                thread.start()

                terminator_context = dict(context)

                if terminator:
                    self._execute_steps(
                        chain_index,
                        terminator,
                        terminator_context,
                        active_roi,
                        selection_anchor=selection_anchor,
                        ignore_event_chain_cancel=ignore_event_chain_cancel,
                        local_cancel_event=local_cancel_event,
                    )

                stop_repeating.set()

                while not repeating_done.wait(0.005):
                    if self._stop_event.is_set():
                        break

                thread.join(timeout=0.10)
                context.update(terminator_context)

                self.logger.info(
                    f"流程 {chain_index}：循环…直到…终止分支已完成",
                    source="logic",
                )
                continue

            if step.module_type == "logic_if":
                condition_branch = step.branches[0] if len(step.branches) > 0 else ()
                then_branch = step.branches[1] if len(step.branches) > 1 else ()

                condition, condition_context = self._evaluate_condition_branch(
                    chain_index,
                    condition_branch,
                    context,
                    active_roi,
                    selection_anchor,
                    ignore_event_chain_cancel,
                    local_cancel_event,
                )
                context.update(condition_context)

                if condition and then_branch:
                    if not self._execute_steps(
                        chain_index,
                        then_branch,
                        context,
                        active_roi,
                        selection_anchor=selection_anchor,
                        ignore_event_chain_cancel=ignore_event_chain_cancel,
                        local_cancel_event=local_cancel_event,
                    ):
                        return False

                self.logger.info(
                    f"流程 {chain_index}：IF 判定 → {condition}",
                    source="logic",
                )
                continue

            if step.module_type in {"logic_or", "logic_nor", "logic_and"}:
                first_branch = step.branches[0] if len(step.branches) > 0 else ()
                second_branch = step.branches[1] if len(step.branches) > 1 else ()
                action_branch = step.branches[2] if len(step.branches) > 2 else ()

                mode = (
                    "or"
                    if step.module_type == "logic_or"
                    else (
                        "nor"
                        if step.module_type == "logic_nor"
                        else "and"
                    )
                )

                (
                    verdict,
                    selected_context,
                    first_value,
                    second_value,
                ) = self._evaluate_two_conditions_parallel(
                    chain_index,
                    first_branch,
                    second_branch,
                    context,
                    active_roi,
                    selection_anchor,
                    ignore_event_chain_cancel,
                    mode,
                    local_cancel_event,
                )

                context.update(selected_context)

                if verdict and action_branch:
                    if not self._execute_steps(
                        chain_index,
                        action_branch,
                        context,
                        active_roi,
                        selection_anchor=selection_anchor,
                        ignore_event_chain_cancel=ignore_event_chain_cancel,
                        local_cancel_event=local_cancel_event,
                    ):
                        return False

                self.logger.info(
                    (
                        f"流程 {chain_index}：{step.module_type} → "
                        f"A={first_value}, B={second_value}, 结果={verdict}"
                    ),
                    source="logic",
                )
                continue

            if step.module_type == "global_anchor_roi":
                if not step.global_anchor_template_path or step.global_anchor_roi is None:
                    self.logger.warning(f"流程 {chain_index}：仅识别锚点未完成设置。", source="global")
                    return False

                anchor = self.recognition_engine.scan_template(
                    step.global_anchor_template_path,
                    roi=None,
                    options=TemplateScanOptions(
                        threshold=0.860,
                        methods=("ccoeff_color", "grayscale", "feature"),
                        scales=(0.90, 1.0, 1.10),
                        confirm_frames=1,
                    ),
                )
                if anchor is None:
                    self.logger.warning(f"流程 {chain_index}：全局锚点未找到。", source="global")
                    return False
                off_x, off_y, width, height = step.global_anchor_roi
                resolved_global_roi = (
                    anchor.x + off_x,
                    anchor.y + off_y,
                    width,
                    height,
                )
                context["global_recognition_roi"] = intersect_roi(
                    context.get("global_recognition_roi"),
                    resolved_global_roi,
                )
                if context["global_recognition_roi"] is None:
                    return False
                self.runtime_signals.message.emit(
                    f"流程 {chain_index}：全局识别视野已限制为 {context['global_recognition_roi']}"
                )
                continue

            if step.module_type == "roi":
                roi = step.roi

                if roi is None:
                    return False

                resolved_roi = roi

                if step.roi_anchor_template_path:
                    anchor_result = (
                        self.recognition_engine.scan_template(
                            step.roi_anchor_template_path,
                            roi=context.get("global_recognition_roi"),
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

                    if anchor_result is None:
                        return False

                    anchor_x = anchor_result.x
                    anchor_y = anchor_result.y
                    off_x, off_y, width, height = roi

                    resolved_roi = (
                        anchor_x + off_x,
                        anchor_y + off_y,
                        width,
                        height,
                    )

                resolved_roi = intersect_roi(
                    resolved_roi,
                    context.get("global_recognition_roi"),
                )
                if resolved_roi is None:
                    self.logger.warning(f"流程 {chain_index}：ROI 与全局识别视野没有交集。", source="roi")
                    return False

                roi_anchor_point = (
                    (
                        anchor_x,
                        anchor_y,
                    )
                    if step.roi_anchor_template_path
                    else None
                )

                if step.children:
                    if not self._execute_steps(
                        chain_index,
                        step.children,
                        context,
                        resolved_roi,
                        selection_anchor=(
                            roi_anchor_point
                            or context.get(
                                "global_anchor_point"
                            )
                        ),
                        ignore_event_chain_cancel=(
                            ignore_event_chain_cancel
                        ),
                        local_cancel_event=(
                            local_cancel_event
                        ),
                    ):
                        return False

                # In complex mode an ROI node with no embedded children acts
                # as a modifier for the following chain.
                active_roi = resolved_roi
                selection_anchor = (
                    roi_anchor_point
                    or context.get(
                        "global_anchor_point"
                    )
                )
                continue

            if step.module_type == "coordinate_modify":
                incoming = context.get(
                    "last_output"
                )

                if (
                    not isinstance(
                        incoming,
                        (tuple, list),
                    )
                    or len(incoming) != 2
                ):
                    self.logger.warning(
                        (
                            f"流程 {chain_index}："
                            "坐标修改需要一个坐标输入，"
                            f"实际输入={incoming!r}"
                        ),
                        source="data",
                    )
                    return False

                try:
                    input_x = int(
                        round(
                            float(
                                incoming[0]
                            )
                        )
                    )
                    input_y = int(
                        round(
                            float(
                                incoming[1]
                            )
                        )
                    )
                except (
                    TypeError,
                    ValueError,
                    OverflowError,
                ):
                    self.logger.warning(
                        (
                            f"流程 {chain_index}："
                            "坐标修改收到的坐标无法转换为数值。"
                        ),
                        source="data",
                    )
                    return False

                output = (
                    input_x
                    + int(
                        step.coordinate_modify_x
                    ),
                    input_y
                    + int(
                        step.coordinate_modify_y
                    ),
                )

                context[
                    "last_output"
                ] = output
                context[
                    "last_output_space"
                ] = (
                    context.get(
                        "last_output_space"
                    )
                    or "global_screen"
                )

                self.logger.info(
                    (
                        f"流程 {chain_index}："
                        f"坐标修改 {incoming} "
                        f"+ ({step.coordinate_modify_x:+d}, "
                        f"{step.coordinate_modify_y:+d}) "
                        f"→ {output}"
                    ),
                    source="data",
                )
                continue

            if step.module_type == "fixed_coordinate":
                output_x = int(
                    step.fixed_coordinate_x
                )
                output_y = int(
                    step.fixed_coordinate_y
                )

                anchor_path = (
                    step.fixed_coordinate_anchor_path
                )

                if anchor_path:
                    effective_roi = intersect_roi(
                        active_roi,
                        context.get(
                            "global_recognition_roi"
                        ),
                    )

                    if (
                        active_roi is not None
                        and context.get(
                            "global_recognition_roi"
                        ) is not None
                        and effective_roi is None
                    ):
                        self.logger.warning(
                            (
                                f"流程 {chain_index}："
                                "固定坐标的锚点搜索范围为空。"
                            ),
                            source="data",
                        )
                        return False

                    try:
                        anchor = (
                            self.recognition_engine
                            .scan_template(
                                anchor_path,
                                roi=effective_roi,
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
                    except Exception as exc:
                        self.logger.warning(
                            (
                                f"流程 {chain_index}："
                                f"固定坐标锚点识别失败：{exc}"
                            ),
                            source="data",
                        )
                        return False

                    if anchor is None:
                        self.logger.warning(
                            (
                                f"流程 {chain_index}："
                                "固定坐标未找到锚点。"
                            ),
                            source="data",
                        )
                        return False

                    output_x = int(
                        anchor.global_x
                    ) + output_x
                    output_y = int(
                        anchor.global_y
                    ) + output_y

                    anchor_name = Path(
                        anchor_path
                    ).name
                    mode_text = (
                        f"锚点={anchor_name}"
                    )
                else:
                    mode_text = "全屏坐标"

                output = (
                    output_x,
                    output_y,
                )

                context[
                    "last_output"
                ] = output
                context[
                    "last_output_space"
                ] = "global_screen"

                self.logger.info(
                    (
                        f"流程 {chain_index}："
                        f"固定坐标 → {output} · "
                        f"{mode_text}"
                    ),
                    source="data",
                )
                continue

            if step.module_type in VISUAL_MODULE_TYPES:
                if not step.template_path:
                    return False

                effective_roi = intersect_roi(
                    active_roi,
                    context.get(
                        "global_recognition_roi"
                    ),
                )

                if (
                    active_roi is not None
                    and context.get(
                        "global_recognition_roi"
                    ) is not None
                    and effective_roi is None
                ):
                    return False

                module_display = {
                    "findtemplate": "扫描模板",
                    "template_count": "模板计数",
                    "lock_template": "锁定模板",
                }.get(
                    step.module_type,
                    step.label,
                )

                self._vision_begin_sensing(
                    module_display,
                    effective_roi,
                )

                scales = (
                    (
                        0.90,
                        0.95,
                        1.0,
                        1.05,
                        1.10,
                    )
                    if step.multi_scale
                    else (1.0,)
                )

                options = TemplateScanOptions(
                    threshold=(
                        step.match_threshold
                    ),
                    methods=tuple(
                        step.recognition_methods
                    ),
                    scales=scales,
                    confirm_frames=max(
                        1,
                        int(
                            step.confirm_frames
                        ),
                    ),
                    feature_detector=(
                        step.feature_detector
                    ),
                )

                def get_matches():
                    return (
                        self.recognition_engine
                        .scan_templates(
                            step.template_path,
                            roi=effective_roi,
                            options=options,
                        )
                    )

                def boxes_for(matches):
                    try:
                        template_image = (
                            self.recognition_engine
                            .load_template(
                                step.template_path
                            )
                        )
                        template_h, template_w = (
                            template_image.shape[:2]
                        )
                    except Exception:
                        return []

                    boxes = []

                    for item in matches:
                        matched_w = max(
                            1,
                            int(
                                round(
                                    template_w
                                    * float(
                                        item.scale
                                    )
                                )
                            ),
                        )
                        matched_h = max(
                            1,
                            int(
                                round(
                                    template_h
                                    * float(
                                        item.scale
                                    )
                                )
                            ),
                        )
                        boxes.append(
                            (
                                int(
                                    round(
                                        item.global_x
                                        - matched_w
                                        / 2.0
                                    )
                                ),
                                int(
                                    round(
                                        item.global_y
                                        - matched_h
                                        / 2.0
                                    )
                                ),
                                matched_w,
                                matched_h,
                            )
                        )

                    return boxes

                def choose_match(matches):
                    if not matches:
                        return None

                    anchor_point = (
                        selection_anchor
                        or context.get(
                            "global_anchor_point"
                        )
                    )

                    if anchor_point is not None:
                        anchor_x, anchor_y = (
                            anchor_point
                        )
                        return min(
                            matches,
                            key=lambda item: (
                                (
                                    item.global_x
                                    - anchor_x
                                )
                                ** 2
                                + (
                                    item.global_y
                                    - anchor_y
                                )
                                ** 2,
                                item.global_x,
                                item.global_y,
                            ),
                        )

                    # No anchor: always choose the left-most visible instance.
                    return min(
                        matches,
                        key=lambda item: (
                            item.global_x,
                            item.global_y,
                        ),
                    )

                if step.module_type == "template_count":
                    try:
                        matches = get_matches()
                    except Exception as exc:
                        self.logger.error(
                            str(exc),
                            source="template_count",
                        )
                        return False

                    self._vision_publish_detection(
                        module_display,
                        effective_roi,
                        boxes_for(
                            matches
                        ),
                    )

                    count = len(
                        matches
                    )
                    context[
                        "last_output"
                    ] = count
                    context[
                        "last_output_space"
                    ] = "number"

                    message = (
                        f"流程 {chain_index}："
                        f"模板计数 → {count}"
                    )
                    self.logger.info(
                        message,
                        source="template_count",
                    )
                    self.runtime_signals.message.emit(
                        message
                    )
                    continue

                if step.module_type == "lock_template":
                    remaining_steps = list(
                        steps[
                            step_index + 1:
                        ]
                    )

                    while not module_cancelled():
                        try:
                            matches = get_matches()
                        except Exception as exc:
                            self.logger.error(
                                str(exc),
                                source="lock_template",
                            )
                            return False

                        self._vision_publish_detection(
                            module_display,
                            effective_roi,
                            boxes_for(
                                matches
                            ),
                        )

                        chosen = choose_match(
                            matches
                        )

                        if chosen is None:
                            self.runtime_signals.message.emit(
                                (
                                    f"流程 {chain_index}："
                                    "锁定模板已消失"
                                )
                            )
                            return True

                        context[
                            "last_output"
                        ] = (
                            int(
                                chosen.global_x
                            ),
                            int(
                                chosen.global_y
                            ),
                        )
                        context[
                            "last_output_space"
                        ] = "global_screen"

                        self.runtime_signals.message.emit(
                            (
                                f"流程 {chain_index}："
                                "锁定模板 → "
                                f"({chosen.global_x}, "
                                f"{chosen.global_y})"
                            )
                        )

                        if remaining_steps:
                            if not self._execute_steps(
                                chain_index,
                                remaining_steps,
                                context,
                                effective_roi,
                                selection_anchor=(
                                    selection_anchor
                                ),
                                ignore_event_chain_cancel=(
                                    ignore_event_chain_cancel
                                ),
                                local_cancel_event=(
                                    local_cancel_event
                                ),
                            ):
                                return False

                        frame_wait = max(
                            0.001,
                            1.0 / max(
                                1,
                                int(
                                    self.recognition_engine.max_fps
                                ),
                            ),
                        )
                        wait_end=time.perf_counter()+frame_wait
                        while time.perf_counter()<wait_end:
                            if module_cancelled():
                                return False
                            time.sleep(
                                min(
                                    0.005,
                                    max(
                                        0.0,
                                        wait_end-time.perf_counter(),
                                    ),
                                )
                            )

                    return False

                continuous_until_found = (
                    step.module_type == "scan_until_found"
                )

                # Standard Scan Template.
                #
                # Strict same-chain completion rule:
                # this module remains inside this loop and therefore has NOT
                # completed while the target is absent. No downstream module
                # in this chain can execute until a match is produced or the
                # timeout terminates the chain.
                wait_enabled = (
                    True
                    if continuous_until_found
                    else bool(step.wait_for_match)
                )
                wait_timeout_seconds = (
                    max(
                        1,
                        int(
                            step.wait_timeout_ms
                        ),
                    )
                    / 1000.0
                )
                wait_started = (
                    time.perf_counter()
                )
                wait_deadline = (
                    wait_started
                    + wait_timeout_seconds
                )

                matches = []
                result = None
                attempts = 0

                while True:
                    if module_cancelled():
                        return False

                    if (
                        not ignore_event_chain_cancel
                        and self._event_chain_cancel.is_set()
                    ):
                        return False

                    if (
                        local_cancel_event is not None
                        and local_cancel_event.is_set()
                    ):
                        return False

                    attempt_started = (
                        time.perf_counter()
                    )
                    attempts += 1

                    try:
                        matches = get_matches()
                    except Exception as exc:
                        self.logger.error(
                            str(exc),
                            source="findtemplate",
                        )
                        return False

                    self._vision_publish_detection(
                        module_display,
                        effective_roi,
                        boxes_for(
                            matches
                        ),
                    )

                    result = choose_match(
                        matches
                    )

                    if result is not None:
                        break

                    # Legacy one-shot behavior remains available by disabling
                    # "等待识别" in this module's settings.
                    if not wait_enabled:
                        message = (
                            f"流程 {chain_index}："
                            "扫描模板未命中"
                        )
                        self.runtime_signals.message.emit(
                            message
                        )
                        return False

                    now = time.perf_counter()

                    if (
                        not continuous_until_found
                        and now >= wait_deadline
                    ):
                        elapsed_ms = int(
                            round(
                                (
                                    now
                                    - wait_started
                                )
                                * 1000.0
                            )
                        )
                        message = (
                            f"流程 {chain_index}："
                            "扫描模板等待识别超时 · "
                            f"{elapsed_ms} ms · "
                            f"尝试 {attempts} 次"
                        )
                        self.logger.warning(
                            message,
                            source="findtemplate",
                        )
                        self.runtime_signals.message.emit(
                            message
                        )
                        return False

                    # Poll no faster than the Recognition Engine frame rate.
                    # Recognition itself may already take longer than one
                    # frame; in that case there is no extra frame wait.
                    scan_elapsed = (
                        time.perf_counter()
                        - attempt_started
                    )
                    frame_period = (
                        1.0
                        / max(
                            1,
                            int(
                                self.recognition_engine
                                .max_fps
                            ),
                        )
                    )
                    until_next_frame = max(
                        0.0,
                        frame_period
                        - scan_elapsed,
                    )
                    remaining = (
                        max(
                            0.0,
                            wait_deadline - time.perf_counter(),
                        )
                        if not continuous_until_found
                        else max(
                            0.001,
                            1.0 / max(
                                1,
                                int(
                                    self.recognition_engine.max_fps
                                ),
                            ),
                        )
                    )

                    # A tiny cooperative pause also prevents a very fast
                    # matcher from busy-spinning when the target is absent.
                    poll_wait = min(
                        remaining,
                        max(
                            0.001,
                            until_next_frame,
                        ),
                    )

                    if poll_wait > 0:
                        poll_end=(
                            time.perf_counter()
                            + poll_wait
                        )

                        while (
                            time.perf_counter()
                            < poll_end
                        ):
                            if module_cancelled():
                                return False

                            time.sleep(
                                min(
                                    0.005,
                                    max(
                                        0.0,
                                        poll_end
                                        - time.perf_counter(),
                                    ),
                                )
                            )

                global_x = int(
                    result.global_x
                )
                global_y = int(
                    result.global_y
                )

                context[
                    "last_output"
                ] = (
                    global_x,
                    global_y,
                )
                context[
                    "last_output_space"
                ] = "global_screen"

                selection_text = (
                    "靠近锚点"
                    if (
                        selection_anchor
                        or context.get(
                            "global_anchor_point"
                        )
                    )
                    else "最左侧"
                )

                elapsed_ms = int(
                    round(
                        (
                            time.perf_counter()
                            - wait_started
                        )
                        * 1000.0
                    )
                )

                message = (
                    f"流程 {chain_index}："
                    f"扫描模板 → "
                    f"({global_x}, {global_y}) · "
                    f"候选 {len(matches)} · "
                    f"选择 {selection_text} · "
                    f"完成 {elapsed_ms} ms"
                    + (
                        f" · 尝试 {attempts} 次"
                        if wait_enabled
                        else ""
                    )
                )

                self.logger.info(
                    message,
                    source="findtemplate",
                )
                self.runtime_signals.message.emit(
                    message
                )

            elif (
                step.module_type
                == "move_to"
            ):
                coordinate = context.get(
                    "last_output"
                )
                coordinate_space = context.get(
                    "last_output_space"
                )

                if (
                    not isinstance(
                        coordinate,
                        (tuple, list),
                    )
                    or len(coordinate) < 2
                ):
                    self.logger.warning(
                        (
                            f"流程 {chain_index}："
                            "移至需要上一个模块提供坐标数据。"
                        ),
                        source="mouse",
                    )
                    self.runtime_signals.message.emit(
                        (
                            f"流程 {chain_index}："
                            "移至缺少坐标输入"
                        )
                    )
                    return False

                if coordinate_space != "global_screen":
                    self.logger.warning(
                        (
                            f"流程 {chain_index}："
                            "移至拒绝非全局屏幕坐标输入。"
                        ),
                        source="mouse",
                    )
                    self.runtime_signals.message.emit(
                        (
                            f"流程 {chain_index}："
                            "移至收到的不是全局屏幕坐标"
                        )
                    )
                    return False

                try:
                    input_x = float(
                        coordinate[0]
                    )
                    input_y = float(
                        coordinate[1]
                    )

                    if step.move_advanced:
                        move_options = MoveOptions(
                            offset_up=step.move_offset_up,
                            offset_down=step.move_offset_down,
                            offset_left=step.move_offset_left,
                            offset_right=step.move_offset_right,
                            speed_mode=step.move_speed_mode,
                            speed_value=step.move_speed_value,
                            speed_variance=step.move_speed_variance,
                            random_route=step.move_random_route,
                        )
                    else:
                        # Normal mode is intentionally deterministic:
                        # exact target + immediate movement.
                        move_options = MoveOptions()

                    final_x, final_y = (
                        self.mouse_action_engine.move_to(
                            input_x,
                            input_y,
                            options=move_options,
                            stop_requested=(
                                module_cancelled
                            ),
                        )
                    )

                    if self._stop_event.is_set():
                        return False

                    context[
                        "last_output"
                    ] = (
                        final_x,
                        final_y,
                    )
                    context[
                        "last_output_space"
                    ] = "global_screen"

                    message = (
                        f"流程 {chain_index}："
                        f"移至 → ({final_x}, {final_y})"
                    )

                    if step.move_advanced:
                        message += (
                            " · "
                            + (
                                f"{step.move_speed_value:.3f}s"
                                if step.move_speed_mode
                                == "duration"
                                else
                                f"{step.move_speed_value:.1f}px/s"
                            )
                            + (
                                " · 随机路线"
                                if step.move_random_route
                                else ""
                            )
                        )

                    self.logger.info(
                        message,
                        source="mouse",
                    )
                    self.runtime_signals.message.emit(
                        message
                    )

                except Exception as exc:
                    self.logger.error(
                        f"移至失败：{exc}",
                        source="mouse",
                    )
                    self.runtime_signals.message.emit(
                        f"流程 {chain_index}：移至失败"
                    )
                    return False

            elif (
                step.module_type
                == "click"
            ):
                try:
                    if step.click_advanced:
                        press_duration = (
                            step.click_press_duration
                        )
                        interval = (
                            step.click_interval
                        )
                    else:
                        # Stable short press and repeat interval. Even normal
                        # Click remains explicit DOWN -> UP internally.
                        press_duration = 0.025
                        interval = 0.100

                    completed = (
                        self.mouse_action_engine.click(
                            ClickOptions(
                                count=max(
                                    1,
                                    int(
                                        step.click_count
                                    ),
                                ),
                                press_duration=max(
                                    0.0,
                                    float(
                                        press_duration
                                    ),
                                ),
                                interval=max(
                                    0.0,
                                    float(
                                        interval
                                    ),
                                ),
                            ),
                            stop_requested=(
                                module_cancelled
                            ),
                        )
                    )

                    if self._stop_event.is_set():
                        return False

                    # Click does not destroy coordinate data from a preceding
                    # scan/move, so downstream modules may still reuse it.
                    message = (
                        f"流程 {chain_index}："
                        f"点击 × {completed}"
                    )

                    self.logger.info(
                        message,
                        source="mouse",
                    )
                    self.runtime_signals.message.emit(
                        message
                    )

                except Exception as exc:
                    self.logger.error(
                        f"点击失败：{exc}",
                        source="mouse",
                    )
                    self.runtime_signals.message.emit(
                        f"流程 {chain_index}：点击失败"
                    )
                    return False

            elif step.module_type == "drag":
                opts=MoveOptions(
                    offset_up=step.move_offset_up if step.move_advanced else 0.0,
                    offset_down=step.move_offset_down if step.move_advanced else 0.0,
                    offset_left=step.move_offset_left if step.move_advanced else 0.0,
                    offset_right=step.move_offset_right if step.move_advanced else 0.0,
                    speed_mode=step.move_speed_mode if step.move_advanced else "duration",
                    speed_value=step.move_speed_value if step.move_advanced else 0.0,
                    speed_variance=step.move_speed_variance if step.move_advanced else 0.0,
                    random_route=step.move_random_route if step.move_advanced else False,
                )
                final=self.mouse_action_engine.drag(step.drag_start_x,step.drag_start_y,step.drag_end_x,step.drag_end_y,options=opts,press_duration=step.drag_press_duration,stop_requested=module_cancelled)
                context["last_output"]=final; context["last_output_space"]="global_screen"
                self.logger.info(f"流程 {chain_index}：拖动 → {final}",source="mouse")

            elif step.module_type == "keyboard_input":
                stop_requested = (
                    module_cancelled
                )

                if step.key_text_mode:
                    done = (
                        self.keyboard_action_engine
                        .type_text(
                            step.key_text,
                            interval=step.key_interval,
                            interval_variance=(
                                step.key_interval_variance
                                if step.key_advanced
                                else 0.0
                            ),
                            humanized=(
                                step.key_humanized
                                if step.key_advanced
                                else False
                            ),
                            stop_requested=stop_requested,
                        )
                    )

                    completed_text = (
                        step.key_text[:done]
                    )
                    settle_seconds = (
                        self.keyboard_action_engine
                        .recommended_text_settle_delay(
                            completed_text
                        )
                    )

                    self.logger.info(
                        (
                            f"流程 {chain_index}："
                            f"文本输入 {done} 字符 · "
                            f"自动处理缓冲 {settle_seconds * 1000:.0f} ms "
                            "(+ 下一模块固定 5 ms)"
                        ),
                        source="keyboard",
                    )

                    if settle_seconds > 0:
                        settle_end=(
                            time.perf_counter()
                            + settle_seconds
                        )

                        while (
                            time.perf_counter()
                            < settle_end
                        ):
                            if module_cancelled():
                                return False

                            time.sleep(
                                min(
                                    0.005,
                                    max(
                                        0.0,
                                        settle_end
                                        - time.perf_counter(),
                                    ),
                                )
                            )
                else:
                    opts = KeyboardOptions(
                        mode=step.key_mode,
                        count=step.key_count,
                        interval=step.key_interval,
                        hold_duration=(
                            step.key_hold_duration
                        ),
                        duration_variance=(
                            step.key_duration_variance
                            if step.key_advanced
                            else 0.0
                        ),
                        interval_variance=(
                            step.key_interval_variance
                            if step.key_advanced
                            else 0.0
                        ),
                        humanized=(
                            step.key_humanized
                            if step.key_advanced
                            else False
                        ),
                    )

                    done = (
                        self.keyboard_action_engine
                        .press_key(
                            step.key_name,
                            options=opts,
                            stop_requested=(
                                stop_requested
                            ),
                        )
                    )

                    self.logger.info(
                        (
                            f"流程 {chain_index}："
                            f"键盘 {step.key_name} "
                            f"× {done}"
                        ),
                        source="keyboard",
                    )

            elif step.module_type == "launch_exe":
                path=os.path.expandvars(os.path.expanduser(step.executable_path.strip()))
                if not path:return False
                try:
                    subprocess.Popen([path],cwd=str(Path(path).parent) if Path(path).parent.exists() else None)
                    self.logger.info(f"流程 {chain_index}：已启动 {path}",source="process")
                except Exception as exc:
                    self.logger.error(f"启动程序失败：{exc}",source="process"); return False

            elif step.module_type == "delay_wait":
                seconds=self._duration_seconds(step.delay_value,step.delay_unit)
                self.logger.info(f"流程 {chain_index}：延时等待 {seconds:.3f}s",source="runtime")
                end_time = time.perf_counter() + seconds
                while time.perf_counter() < end_time:
                    if module_cancelled():
                        return False
                    time.sleep(
                        min(
                            0.02,
                            max(
                                0.0,
                                end_time - time.perf_counter(),
                            ),
                        )
                    )

            elif (
                step.module_type
                == "inspect_input"
            ):
                value = context.get(
                    "last_output"
                )
                value_space = context.get(
                    "last_output_space"
                )

                python_type = type(
                    value
                ).__name__

                if value_space is None:
                    space_text = "未标记"
                else:
                    space_text = str(
                        value_space
                    )

                # Report the ACTUAL resolved recognition/execution viewport,
                # not the ROI module's stored anchor-relative offsets.
                global_roi = context.get(
                    "global_recognition_roi"
                )

                effective_debug_roi = intersect_roi(
                    active_roi,
                    global_roi,
                )

                if (
                    active_roi is not None
                    and global_roi is not None
                    and effective_debug_roi is None
                ):
                    roi_text = "无交集"
                elif effective_debug_roi is None:
                    roi_text = "全屏"
                else:
                    roi_x, roi_y, roi_w, roi_h = (
                        effective_debug_roi
                    )

                    if (
                        active_roi is None
                        and global_roi is not None
                    ):
                        roi_source = "全局"
                    elif (
                        active_roi is not None
                        and global_roi is None
                    ):
                        roi_source = "局部"
                    elif (
                        active_roi is not None
                        and global_roi is not None
                    ):
                        roi_source = "交集"
                    else:
                        roi_source = "有效"

                    roi_text = (
                        f"{roi_source}"
                        f"({roi_x}, {roi_y}, "
                        f"{roi_w}×{roi_h})"
                    )

                message = (
                    f"流程 {chain_index}："
                    f"检测输入 → "
                    f"值={value!r} · "
                    f"类型={python_type} · "
                    f"数据标记={space_text} · "
                    f"ROI={roi_text}"
                )

                self.logger.info(
                    message,
                    source="debug",
                )
                self.runtime_signals.message.emit(
                    message
                )

                # Transparent pass-through: do not modify last_output or
                # last_output_space, so downstream modules receive exactly
                # the same value.
                continue

            elif (
                step.module_type
                == "placeholder"
            ):
                self.logger.info(
                    (
                        f"流程 {chain_index}："
                        f"执行 {step.label}；"
                        f"输入="
                        f"{context['last_output']!r}"
                    ),
                    source="workspace",
                )

        return True

    def _on_runtime_message(
        self,
        message: str,
    ) -> None:
        self.runtime_status.setText(
            message
        )

    def _on_chain_finished(
        self,
    ) -> None:
        # Stop may have already zeroed the counter.
        if self._stop_event.is_set():
            return

        self._active_chains = max(
            0,
            self._active_chains - 1,
        )

        if self._active_chains != 0:
            return

        if self._global_runtime_active:
            self.run_button.setEnabled(
                False
            )
            self.stop_button.setEnabled(
                True
            )
            self.runtime_status.setText(
                tr_text(
                    "普通流程完成 · 全局设置持续运行中"
                )
            )
        else:
            self.run_button.setEnabled(
                True
            )
            self.stop_button.setEnabled(
                False
            )
            self.runtime_status.setText(
                tr_text(
                    "运行完成"
                )
            )

