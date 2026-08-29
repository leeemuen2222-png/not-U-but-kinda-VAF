from __future__ import annotations

from pathlib import Path
import re
import shutil

import cv2
import mss
import numpy as np

from PySide6.QtCore import (
    QEvent, QObject, QPoint, QRect, QRegularExpression, Qt, QTimer,
)
from PySide6.QtGui import (
    QColor, QCursor, QDoubleValidator, QGuiApplication, QImage, QIntValidator,
    QKeyEvent, QKeySequence, QMouseEvent, QPainter, QRegularExpressionValidator,
)
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QGroupBox,
    QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMessageBox, QPlainTextEdit, QPushButton, QRubberBand, QSpinBox, QToolTip,
    QVBoxLayout, QWidget,
)

from ...core.app_paths import templates_dir
from ...core.i18n import tr_text
from ...core.keyboard_action_engine import KeyboardActionEngine
from ...core.recognition_engine import (
    DEFAULT_METHODS, RecognitionEngine, TemplateScanOptions,
)
from .registry import get_module_definition, settings_key_for
from .runtime import MODULE_MIN_GAP_SECONDS

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


class MouseButtonSettingsDialog(QDialog):
    BUTTONS = (
        ("左键", "left"),
        ("右键", "right"),
        ("中键", "middle"),
    )

    def __init__(self, owner, parent=None) -> None:
        super().__init__(parent)
        self.owner = owner

        module_type = str(getattr(owner, "module_type", "mouse_press"))
        title = "按下设置" if module_type == "mouse_press" else "抬起设置"
        self.setWindowTitle(tr_text(title))
        self.setModal(True)
        self.resize(430, 190)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        row = QHBoxLayout()
        row.addWidget(QLabel(tr_text("鼠标按键")))

        self.button_combo = QComboBox()
        for label, value in self.BUTTONS:
            self.button_combo.addItem(tr_text(label), value)

        current = str(getattr(owner, "mouse_button", "left"))
        index = self.button_combo.findData(current)
        self.button_combo.setCurrentIndex(max(0, index))
        row.addWidget(self.button_combo, 1)
        layout.addLayout(row)

        if module_type == "mouse_press":
            hint = QLabel(
                tr_text("按下会保持鼠标按键处于按住状态，直到遇到对应的抬起模块。"),
                objectName="muted",
            )
        else:
            hint = QLabel(
                tr_text("抬起会释放所选择的鼠标按键。"),
                objectName="muted",
            )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        layout.addStretch()
        bottom = QHBoxLayout()
        bottom.addStretch()
        cancel = QPushButton(tr_text("取消"), objectName="secondaryButton")
        cancel.clicked.connect(self.reject)
        bottom.addWidget(cancel)
        confirm = QPushButton(tr_text("确定"), objectName="primaryButton")
        confirm.clicked.connect(self._accept_settings)
        bottom.addWidget(confirm)
        layout.addLayout(bottom)

    def _accept_settings(self) -> None:
        value = str(self.button_combo.currentData() or "left")
        if value not in {"left", "right", "middle"}:
            value = "left"
        self.owner.mouse_button = value
        try:
            self.owner.update()
        except Exception:
            pass
        self.accept()


class DragSettingsDialog(QDialog):
    MODE_COORDINATE = "coordinate_to_coordinate"
    MODE_PIXELS = "coordinate_drag_pixels"

    def __init__(self, owner, parent=None) -> None:
        super().__init__(parent)
        self.owner = owner
        self._is_complex = hasattr(owner, "incoming") and hasattr(owner, "input_ports")
        self.setWindowTitle(tr_text("拖动设置"))
        self.resize(680, 560)

        layout = QVBoxLayout(self)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel(tr_text("拖动模式")))
        self.mode_button = QPushButton()
        self.mode_button.clicked.connect(self._toggle_mode)
        mode_row.addWidget(self.mode_button, 1)
        layout.addLayout(mode_row)

        self.coordinate_box = QGroupBox(tr_text("坐标至坐标"))
        coordinate_layout = QVBoxLayout(self.coordinate_box)
        if self._is_complex:
            coordinate_layout.addWidget(
                QLabel(
                    tr_text(
                        "复杂模式：第一个输入口接入起点坐标，第二个输入口接入终点坐标。"
                    )
                )
            )
            # Preserve the stored manual end point for backward compatibility,
            # but do not expose it because complex mode obtains it from input_2.
            self.ex = QDoubleSpinBox()
            self.ey = QDoubleSpinBox()
            self.ex.setRange(-100000, 100000)
            self.ey.setRange(-100000, 100000)
            self.ex.setValue(float(getattr(owner, "drag_end_x", 0)))
            self.ey.setValue(float(getattr(owner, "drag_end_y", 0)))
            self.ex.hide()
            self.ey.hide()
        else:
            coordinate_layout.addWidget(
                QLabel(
                    tr_text(
                        "起点坐标来自拖动模块上方的坐标输入；在这里手动设置终点坐标。"
                    )
                )
            )
            end_row = QHBoxLayout()
            end_row.addWidget(QLabel(tr_text("终点 X")))
            self.ex = QDoubleSpinBox()
            self.ex.setRange(-100000, 100000)
            self.ex.setDecimals(2)
            self.ex.setValue(float(getattr(owner, "drag_end_x", 0)))
            end_row.addWidget(self.ex)
            end_row.addWidget(QLabel("Y"))
            self.ey = QDoubleSpinBox()
            self.ey.setRange(-100000, 100000)
            self.ey.setDecimals(2)
            self.ey.setValue(float(getattr(owner, "drag_end_y", 0)))
            end_row.addWidget(self.ey)
            coordinate_layout.addLayout(end_row)
        layout.addWidget(self.coordinate_box)

        self.pixel_box = QGroupBox(tr_text("坐标为起始拖动特定像素"))
        pixel_layout = QVBoxLayout(self.pixel_box)
        pixel_layout.addWidget(
            QLabel(
                tr_text(
                    "起点坐标来自输入。填写相对起点的像素位移；正负号决定拖动方向。"
                )
            )
        )
        pixel_row = QHBoxLayout()
        pixel_row.addWidget(QLabel(tr_text("X 像素")))
        self.pixel_x = QDoubleSpinBox()
        self.pixel_x.setRange(-100000, 100000)
        self.pixel_x.setDecimals(2)
        self.pixel_x.setSuffix(" px")
        self.pixel_x.setValue(float(getattr(owner, "drag_pixels_x", 0)))
        pixel_row.addWidget(self.pixel_x)
        pixel_row.addWidget(QLabel(tr_text("Y 像素")))
        self.pixel_y = QDoubleSpinBox()
        self.pixel_y.setRange(-100000, 100000)
        self.pixel_y.setDecimals(2)
        self.pixel_y.setSuffix(" px")
        self.pixel_y.setValue(float(getattr(owner, "drag_pixels_y", 0)))
        pixel_row.addWidget(self.pixel_y)
        pixel_layout.addLayout(pixel_row)
        layout.addWidget(self.pixel_box)

        self.advanced = QCheckBox(tr_text("高级模式"))
        self.advanced.setChecked(bool(getattr(owner, "move_advanced", False)))
        layout.addWidget(self.advanced)

        group = QGroupBox(tr_text("高级移动"))
        g = QVBoxLayout(group)
        offs = QHBoxLayout()
        self.off = {}
        for label, attr in [
            ("上", "move_offset_up"),
            ("下", "move_offset_down"),
            ("左", "move_offset_left"),
            ("右", "move_offset_right"),
        ]:
            col = QVBoxLayout()
            col.addWidget(QLabel(tr_text(label)))
            sp = QDoubleSpinBox()
            sp.setRange(-100000, 100000)
            sp.setSuffix(" px")
            sp.setValue(float(getattr(owner, attr, 0)))
            col.addWidget(sp)
            offs.addLayout(col)
            self.off[attr] = sp
        g.addLayout(offs)

        sr = QHBoxLayout()
        sr.addWidget(QLabel(tr_text("移速模式")))
        self.speed_mode = QComboBox()
        self.speed_mode.addItem(tr_text("规定时间到达（秒）"), "duration")
        self.speed_mode.addItem(tr_text("像素每秒"), "pixels_per_second")
        idx = self.speed_mode.findData(str(getattr(owner, "move_speed_mode", "duration")))
        self.speed_mode.setCurrentIndex(max(0, idx))
        sr.addWidget(self.speed_mode)
        sr.addWidget(QLabel(tr_text("数值")))
        self.speed = QDoubleSpinBox()
        self.speed.setRange(0, 100000)
        self.speed.setDecimals(3)
        self.speed.setValue(float(getattr(owner, "move_speed_value", 0)))
        sr.addWidget(self.speed)
        sr.addWidget(QLabel(tr_text("移速偏移 ±")))
        self.var = QDoubleSpinBox()
        self.var.setRange(0, 100000)
        self.var.setDecimals(3)
        self.var.setValue(float(getattr(owner, "move_speed_variance", 0)))
        sr.addWidget(self.var)
        g.addLayout(sr)

        self.random = QCheckBox(tr_text("随机移动路线"))
        self.random.setChecked(bool(getattr(owner, "move_random_route", False)))
        g.addWidget(self.random)

        hr = QHBoxLayout()
        hr.addWidget(QLabel(tr_text("起始点按下等待")))
        self.press = QDoubleSpinBox()
        self.press.setRange(0, 60)
        self.press.setDecimals(3)
        self.press.setSuffix(" s")
        self.press.setValue(float(getattr(owner, "drag_press_duration", 0.025)))
        hr.addWidget(self.press)
        hr.addStretch()
        g.addLayout(hr)

        group.setEnabled(self.advanced.isChecked())
        self.advanced.toggled.connect(group.setEnabled)
        layout.addWidget(group)

        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton(tr_text("取消"))
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        ok = QPushButton(tr_text("确定"))
        ok.clicked.connect(self._save)
        buttons.addWidget(ok)
        layout.addLayout(buttons)

        mode = str(getattr(owner, "drag_mode", self.MODE_COORDINATE))
        if mode not in {self.MODE_COORDINATE, self.MODE_PIXELS}:
            mode = self.MODE_COORDINATE
        self._mode = mode
        self._sync_mode_ui()

    def _toggle_mode(self) -> None:
        self._mode = (
            self.MODE_PIXELS
            if self._mode == self.MODE_COORDINATE
            else self.MODE_COORDINATE
        )
        self._sync_mode_ui()

    def _sync_mode_ui(self) -> None:
        coordinate_mode = self._mode == self.MODE_COORDINATE
        self.coordinate_box.setVisible(coordinate_mode)
        self.pixel_box.setVisible(not coordinate_mode)
        label = (
            "坐标至坐标"
            if coordinate_mode
            else "坐标为起始拖动特定像素"
        )
        self.mode_button.setText(tr_text(f"模式：{label}"))

    def _save(self) -> None:
        owner = self.owner
        owner.drag_mode = self._mode
        owner.drag_end_x = self.ex.value()
        owner.drag_end_y = self.ey.value()
        owner.drag_pixels_x = self.pixel_x.value()
        owner.drag_pixels_y = self.pixel_y.value()
        owner.drag_press_duration = self.press.value()
        owner.move_advanced = self.advanced.isChecked()
        for attr, spin in self.off.items():
            setattr(owner, attr, spin.value())
        owner.move_speed_mode = str(self.speed_mode.currentData())
        owner.move_speed_value = self.speed.value()
        owner.move_speed_variance = self.var.value()
        owner.move_random_route = self.random.isChecked()

        # Complex-mode drag ports are dynamic: coordinate-to-coordinate has
        # start + end inputs; pixel mode only needs the start input.  The node
        # owns removal of now-invalid input_2 connections so no orphan wire is
        # left in the scene.
        refresh = getattr(owner, "refresh_dynamic_ports", None)
        if callable(refresh):
            refresh()

        owner.update()
        self.accept()


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

        definition = get_module_definition(
            getattr(
                owner,
                "module_type",
                "findtemplate",
            )
        )
        self.setWindowTitle(
            tr_text(
                definition.settings_title
                if definition is not None
                and definition.settings_title
                else "视觉识别设置"
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

def open_module_settings_dialog(
    target,
    parent=None,
    *,
    recognition_engine=None,
    complex_view=None,
) -> bool:
    """Open the settings UI selected by the module definition.

    Module files own the ``settings_key``.  WorkspacePage only maps those
    generic setting families to reusable dialogs, so adding another module
    that reuses an existing settings family does not require another
    ``module_type == ...`` branch here.
    """
    key = settings_key_for(
        getattr(target, "module_type", "")
    )

    if not key:
        return False

    if key == "roi":
        if complex_view is not None:
            complex_view.edit_roi_node(target)
        else:
            SimpleRoiSettingsDialog(
                target,
                parent,
            ).exec()
        return True

    if key == "visual":
        ScanTemplateSettingsDialog(
            target,
            parent,
        ).exec()
        return True

    if key == "global_anchor":
        if recognition_engine is None:
            QMessageBox.warning(
                parent,
                tr_text("识别引擎不可用"),
                tr_text("当前无法访问 Recognition Engine。"),
            )
            return True
        GlobalAnchorSettingsDialog(
            target,
            recognition_engine,
            parent,
        ).exec()
        return True

    dialogs = {
        "fixed_coordinate": FixedCoordinateSettingsDialog,
        "coordinate_modify": CoordinateModifySettingsDialog,
        "move_to": MoveToSettingsDialog,
        "click": ClickSettingsDialog,
        "mouse_button": MouseButtonSettingsDialog,
        "drag": DragSettingsDialog,
        "keyboard_input": KeyboardSettingsDialog,
        "launch_exe": LaunchExeSettingsDialog,
        "delay_wait": DelaySettingsDialog,
        "clock": ClockSettingsDialog,
        "loop": LoopSettingsDialog,
    }
    dialog_type = dialogs.get(key)
    if dialog_type is None:
        return False

    dialog_type(
        target,
        parent,
    ).exec()
    return True

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
