from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QTimer, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from .manual import MODULE_TUTORIALS, OPERATIONS_ZH, entry_text
from .welcome_project import ensure_tutorial_welcome_project


class TutorialWelcomeDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.choice = ""
        self.setWindowTitle("UVAF 教程")
        self.setModal(True)
        self.resize(560, 320)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 24)
        layout.setSpacing(16)

        title = QLabel("欢迎使用 UVAF")
        title.setStyleSheet("font-size:26px;font-weight:800;")
        layout.addWidget(title)

        body = QLabel(
            "这个教程会先带你运行一次欢迎项目中的 Arknights 搜索示例，"
            "然后详细解释“模板”“锚点”和模板识别。接着你会亲手关闭欢迎项目、建立一个新的训练项目，"
            "最后制作一个真正使用模板识别的桌面自动化：截取一个桌面应用图标 → 找到它 → 移动鼠标 → 双击打开应用。\n\n"
            "教程最后还包含完整模块手册，解释每个模块的功能、设置和常见用法。"
        )
        body.setWordWrap(True)
        layout.addWidget(body)
        layout.addStretch()

        row = QHBoxLayout()
        skip = QPushButton("跳过教程（不建议）")
        start = QPushButton("让我们开始吧")
        start.setDefault(True)
        skip.clicked.connect(self._skip)
        start.clicked.connect(self._start)
        row.addStretch()
        row.addWidget(skip)
        row.addWidget(start)
        layout.addLayout(row)

    def _start(self) -> None:
        self.choice = "start"
        self.accept()

    def _skip(self) -> None:
        self.choice = "skip"
        self.accept()


class TutorialHighlight(QWidget):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.hide()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        pen = QPen(QColor(255, 201, 76), 3)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(self.rect().adjusted(2, 2, -3, -3), 8, 8)


class TutorialCoach(QFrame):
    def __init__(self, parent: QWidget) -> None:
        # A tool window can live beside UVAF instead of covering the workbench.
        # It remains associated with the main window and does not create a
        # normal taskbar entry.
        super().__init__(parent, Qt.Tool | Qt.FramelessWindowHint)
        self.setObjectName("tutorialCoach")
        self.setStyleSheet(
            "QFrame#tutorialCoach{background:#202020;border:1px solid #666;"
            "border-radius:10px;}"
        )
        self.setFixedWidth(440)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)
        self.title = QLabel()
        self.title.setWordWrap(True)
        self.title.setStyleSheet("font-size:17px;font-weight:700;")

        # QTextBrowser is used instead of a plain wrapping QLabel because
        # QLabel.adjustSize() can under-estimate height for long wrapped text
        # on some DPI/font combinations.  The browser gets an explicit
        # content-derived height and becomes scrollable only when the text is
        # genuinely too tall for the current monitor.
        self.body = QTextBrowser()
        self.body.setFrameShape(QFrame.NoFrame)
        self.body.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.body.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.body.setOpenExternalLinks(False)
        self.body.setStyleSheet(
            "QTextBrowser{background:transparent;border:0;padding:0;margin:0;}"
        )

        self.hint = QLabel()
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color:#B7B7B7;")
        self.next_button = QPushButton("继续")
        self.next_button.hide()
        layout.addWidget(self.title)
        layout.addWidget(self.body)
        layout.addWidget(self.hint)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(self.next_button)
        layout.addLayout(row)
        self._body_text = ""
        self._screen_height_hint = 900
        self.adjustSize()
        self.hide()

    def _fit_body_height(self) -> None:
        viewport_width = max(240, self.width() - 40)
        document = self.body.document()
        document.setTextWidth(float(viewport_width))
        wanted = int(document.size().height()) + 12
        # Keep every line visible whenever practical. On smaller displays,
        # cap the body to roughly half the usable screen and allow scrolling
        # rather than clipping any text.
        maximum = max(150, min(420, int(self._screen_height_hint * 0.48)))
        self.body.setFixedHeight(max(72, min(wanted, maximum)))

    def prepare_for_screen(self, width: int, screen_height: int) -> None:
        self.setFixedWidth(max(320, int(width)))
        self._screen_height_hint = max(360, int(screen_height))
        self._fit_body_height()
        self.adjustSize()

    def set_content(self, title: str, body: str, hint: str = "") -> None:
        self.title.setText(title)
        self._body_text = body
        self.body.setPlainText(body)
        self.hint.setText(hint)
        self.hint.setVisible(bool(hint))
        self._fit_body_height()
        self.adjustSize()


class TutorialReferenceDialog(QDialog):
    def __init__(self, settings, parent=None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("UVAF 完整模块手册")
        self.resize(980, 680)

        outer = QVBoxLayout(self)
        title = QLabel("UVAF 完整模块手册")
        title.setStyleSheet("font-size:24px;font-weight:800;")
        outer.addWidget(title)

        splitter = QSplitter(Qt.Horizontal)
        self.list = QListWidget()
        self.browser = QTextBrowser()
        splitter.addWidget(self.list)
        splitter.addWidget(self.browser)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([270, 690])
        outer.addWidget(splitter, 1)

        self._entries: list[tuple[str, object]] = []
        operations = QListWidgetItem("基础操作")
        operations.setData(Qt.UserRole, ("operations", None))
        self.list.addItem(operations)
        for entry in MODULE_TUTORIALS:
            language = str(self.settings.get("ui.language", "zh_CN"))
            title_text, *_ = entry_text(entry, language)
            item = QListWidgetItem(title_text)
            item.setData(Qt.UserRole, ("module", entry.module_type))
            self.list.addItem(item)

        self.list.currentItemChanged.connect(self._show_item)
        self.list.setCurrentRow(0)

        close = QPushButton("关闭")
        close.clicked.connect(self.accept)
        outer.addWidget(close, alignment=Qt.AlignRight)

    def _show_item(self, current, _previous) -> None:
        if current is None:
            return
        kind, key = current.data(Qt.UserRole)
        language = str(self.settings.get("ui.language", "zh_CN"))
        if kind == "operations":
            html = ["<h2>基础操作</h2>"]
            for heading, body in OPERATIONS_ZH:
                html.append(f"<h3>{heading}</h3><p>{body}</p>")
            self.browser.setHtml("".join(html))
            return
        entry = next((x for x in MODULE_TUTORIALS if x.module_type == key), None)
        if entry is None:
            return
        title, function, settings_text, usage = entry_text(entry, language)
        self.browser.setHtml(
            f"<h2>{title}</h2>"
            f"<h3>功能 / Function</h3><p>{function}</p>"
            f"<h3>设置 / Settings</h3><p>{settings_text}</p>"
            f"<h3>操作与示例 / Usage</h3><p>{usage}</p>"
        )


@dataclass
class GuideStep:
    title: str
    body: str
    hint: str = ""
    target: Callable[[], QWidget | None] | None = None
    target_rect: Callable[[], QRect | None] | None = None
    advance_on_click: bool = False
    predicate: Callable[[], bool] | None = None
    on_enter: Callable[[], None] | None = None
    manual_next: bool = False
    # The interactive tutorial is designed for windowed mode so the coach can
    # stay beside UVAF instead of covering controls or desktop targets.
    requires_windowed: bool = True
    hide_coach: bool = False


class TutorialController(QObject):
    """First-run guided tutorial plus full module reference."""

    def __init__(self, main_window) -> None:
        super().__init__(main_window)
        self.window = main_window
        self.settings = main_window.settings
        self.workspace = main_window.workspace_page
        self.highlight = TutorialHighlight(main_window)
        self.coach = TutorialCoach(main_window)
        self.coach.next_button.clicked.connect(self._manual_advance)
        self._target: QWidget | None = None
        self._step_index = -1
        self._steps: list[GuideStep] = []
        self._poll = QTimer(self)
        self._poll.setInterval(250)
        self._poll.timeout.connect(self._poll_step)

        # Tutorial geometry is always derived from live Qt widget geometry.
        # This avoids fixed-pixel assumptions and keeps the highlight/coach in
        # sync across DPI scaling, 1080p/2K/4K, resize, maximize and multi-screen
        # layouts.
        self._geometry_timer = QTimer(self)
        self._geometry_timer.setInterval(100)
        self._geometry_timer.timeout.connect(self._sync_geometry)
        self._geometry_timer.start()
        self.window.installEventFilter(self)
        self._fullscreen_warning_open = False
        self._window_mode_notice_shown = False
        self._blocked_target_click = False
        self._template_snapshot: set[str] = set()
        self._tutorial_template_path: str | None = None
        self._welcome_project_id: str | None = None
        self._invalid_template_names_warned: set[str] = set()

    def maybe_start(self) -> None:
        completed = bool(self.settings.get("tutorial.completed", False))
        skipped = bool(self.settings.get("tutorial.skipped", False))
        if completed or skipped:
            return
        self.start(force=False)

    def start(self, force: bool = True) -> None:
        if force:
            self.settings.set("tutorial.completed", False)
            self.settings.set("tutorial.skipped", False)
        dialog = TutorialWelcomeDialog(self.window)
        if dialog.exec() != QDialog.Accepted:
            return
        if dialog.choice == "skip":
            self.settings.set("tutorial.skipped", True)
            self.settings.set("tutorial.completed", True)
            return
        self._prepare_welcome_project(reset=force)
        self._build_steps()
        self._step_index = -1
        self._advance()

    def open_reference(self) -> None:
        TutorialReferenceDialog(self.settings, self.window).exec()

    def _prepare_welcome_project(self, reset: bool = False) -> None:
        try:
            welcome = ensure_tutorial_welcome_project(
                self.workspace.project_manager,
                reset=reset,
            )
        except Exception as exc:
            self.window.logger.error(
                f"Tutorial welcome project preparation failed: {exc}",
                source="tutorial",
            )
            welcome = None
        if welcome is not None:
            self._welcome_project_id = str(welcome.project_id)
            self.workspace.open_project(welcome.project_id)
        self.window.switch_page("workspace")

    def _build_steps(self) -> None:
        self._steps = [
            GuideStep(
                "先体验现成的搜索示例",
                "欢迎项目中保留了现有的 Arknights 搜索流程。请点击 Run，让它完整执行一次。你会先看到一个已经完成的视觉自动化，再开始自己制作。",
                "教程运行桌面自动化时必须使用窗口模式，并会在执行期间隐藏教程提示。",
                target=lambda: getattr(self.workspace, "run_button", None),
                advance_on_click=True,
            ),
            GuideStep(
                "等待示例运行完成",
                "UVAF 正在执行欢迎项目。这里用到的核心能力之一就是模板识别：先在画面中找到保存过的图像，再把识别结果转换成坐标交给后面的动作模块。",
                "同一条链中的模块会严格等待上一个模块完成。",
                hide_coach=True,
                predicate=lambda: (
                    getattr(self.workspace, "_active_chains", 0) == 0
                    and not getattr(self.workspace, "_global_runtime_active", False)
                ),
            ),
            GuideStep(
                "模板是什么？",
                "模板（Template）可以理解为“让 UVAF 记住的一小张参考图片”。例如桌面上的某个应用图标、游戏中的按钮、一个菜单图标。视觉模块会拿这张模板去当前屏幕或 ROI 中寻找相似区域。\n\n"
                "模板应该尽量只截目标本身，并包含足够有辨识度的图形；不要把大量会变化的背景、时间、动画或无关内容一起截进去。模板保存在当前项目的 templates 模板库中，因此不同项目可以拥有不同模板。",
                "后面的训练会亲手建立一个桌面应用图标模板。",
                manual_next=True,
            ),
            GuideStep(
                "锚点是什么？",
                "锚点（Anchor）本质上也是一个模板，但用途不同：普通模板负责“找到目标”；锚点负责建立一个会跟随画面移动的参考坐标系。\n\n"
                "例如某个游戏窗口里的面板整体会移动，你可以把面板左上角稳定的小图标设为锚点。以后 ROI、固定坐标等数据可以写成“相对这个锚点偏移多少”，这样面板换位置时不必重新填写所有绝对屏幕坐标。",
                "锚点不是每个模板识别都必须使用。今天的桌面图标训练直接用全屏模板识别；当目标区域会整体移动时，再考虑锚点 + ROI。",
                manual_next=True,
            ),
            GuideStep(
                "模板识别是怎样工作的？",
                "“扫描模板（坐标输出）”会在允许的视野中搜索目标模板，命中后输出全局屏幕坐标。后面的“移至”可以直接读取这个坐标。\n\n"
                "匹配度越高越严格；太低容易误认，太高又可能因为缩放、抗锯齿或亮度变化而找不到。默认 0.860 是常用起点。彩色 Ccoeff、灰度、RGB/HSV、边缘、FeatureMatch 等方法用于应对不同画面变化，默认全部启用时 Recognition Engine 会组合使用，而不是机械地重复整屏扫描。",
                "如果同一模板出现多次：有锚点时优先选择靠近锚点的候选；没有锚点时优先选择屏幕最左侧候选。视觉模块输出的是全局坐标。",
                manual_next=True,
            ),
            GuideStep(
                "先认识项目",
                "UVAF 的每个项目都是一个独立工作空间：工作流、templates 模板库、resources 资源和自定义模块都会按项目隔离。这样为不同游戏或应用制作自动化时，不会把彼此的模板和流程混在一起。",
                "欢迎项目只用于演示。接下来我们不会清空它，而是亲手建立一个全新的训练项目。",
                manual_next=True,
            ),
            GuideStep(
                "关闭欢迎项目",
                "点击工作台上方的“关闭项目”。关闭只会退出当前项目，不会删除项目文件。关闭后会回到“还没有打开项目”的项目库页面。",
                "这是以后切换不同自动化工程时经常会使用的操作。",
                target=lambda: self._workspace_button(("关闭项目", "Close project", "Close Project")),
                predicate=self._no_project_open,
            ),
            GuideStep(
                "建立一个新的训练项目",
                "在项目库页面点击“新建项目”，然后输入一个你喜欢的项目名称，例如 UVAF Training。创建完成后 UVAF 会自动打开这个新项目。",
                "项目名称可以按你的需要填写。模板、资源和工作流都会保存到这个新项目自己的文件夹中。",
                target=lambda: self._workspace_button(("新建项目", "New project", "New Project")),
                predicate=self._training_project_created,
            ),
            GuideStep(
                "新的项目已经准备好了",
                "现在画布和模板库应该都是这个训练项目自己的内容。接下来建立的桌面应用模板也只属于这个项目，不会污染欢迎项目。",
                "训练流程：Start → 扫描模板 → 移至 → 延时等待 → 点击（双击）。",
                manual_next=True,
            ),
            GuideStep(
                "准备一个桌面应用图标",
                "把 UVAF 保持在窗口模式，并移动到不会挡住目标的位置。请在桌面上选择一个当前可见的应用快捷方式作为训练目标，例如你经常使用的任意应用。",
                "不要选择任务栏图标，因为有些用户会隐藏任务栏。后面的识别和点击都会直接针对桌面图标。",
                manual_next=True,
            ),
            GuideStep(
                "建立你的第一个模板",
                "点击工作台工具栏中的“快捷创建模板”图标，然后只框选刚才选择的桌面应用图标。框选完成后给模板命名。\n\n"
                "重要：当前版本推荐模板文件名只使用英文、数字、下划线 _ 和短横线 -，不要使用中文名称。中文模板名在部分路径/图像后端组合下可能造成模板文件无法正常读取或损坏。",
                "例如可以命名为 chrome_icon、discord、app01。尽量紧贴图标主体框选，不要把会变化的文字、大片桌面背景或旁边其他图标一起截入。",
                target=lambda: getattr(self.workspace, "quick_template_button", None),
                predicate=self._new_template_created,
                on_enter=self._begin_template_capture_step,
            ),
            GuideStep(
                "拖入起始模块",
                "从模块库的“事件”分类拖出“起始”到画布。它是整个流程的电源入口。",
                "拖入成功后自动继续。",
                target=lambda: self._palette_widget("start"),
                predicate=lambda: self._has_simple_module("start"),
            ),
            GuideStep(
                "拖入扫描模板",
                "从“感知”分类拖出“扫描模板（坐标输出）”，连接在起始下面。它会在当前视觉范围中寻找你刚才截取的桌面应用图标，并输出找到的位置。",
                "扫描模板是一次性识别：运行到这里时扫描一次，找到后把坐标交给后续模块。",
                target=lambda: self._palette_widget("findtemplate"),
                predicate=lambda: self._chain_has_prefix(("start", "findtemplate")),
            ),
            GuideStep(
                "为扫描模板选择刚才的图片",
                "双击画布中的“扫描模板（坐标输出）”，在模板选择中选择刚才创建的桌面应用图标模板。先保持默认匹配度和默认全部识别方法即可。",
                "如果以后识别不到：先检查截图是否准确，再适当降低匹配度；如果误认其他位置，则提高匹配度、缩小 ROI 或换更有辨识度的模板。",
                target_rect=lambda: self._simple_module_rect("findtemplate"),
                predicate=self._scan_uses_tutorial_template,
            ),
            GuideStep(
                "加入移至",
                "从“动作”分类拖出“移至”，连接在扫描模板下面。扫描模板输出的是全局坐标，因此“移至”可以直接把鼠标移动到识别到的应用图标。",
                "这就是视觉模块与动作模块最常见的数据链：识别 → 坐标 → 动作。",
                target=lambda: self._palette_widget("move_to"),
                predicate=lambda: self._chain_has_prefix(("start", "findtemplate", "move_to")),
            ),
            GuideStep(
                "在动作之间加入延迟",
                "先不要马上点击。拖入“延时等待”，连接在“移至”下面。",
                "桌面和应用需要时间处理鼠标移动、焦点和动画。训练中建议先使用约 200 ms。",
                target=lambda: self._palette_widget("delay_wait"),
                predicate=lambda: self._chain_has_prefix(("start", "findtemplate", "move_to", "delay_wait")),
            ),
            GuideStep(
                "设置约 200 ms 延迟",
                "双击延时等待模块，把时间设置为约 200 毫秒。",
                "100–500 ms 通常是桌面自动化比较稳妥的起点。稳定后可以逐渐缩短；目标应用较慢时则增加。",
                target_rect=lambda: self._simple_module_rect("delay_wait"),
                predicate=self._delay_is_reasonable,
            ),
            GuideStep(
                "加入点击",
                "拖出“点击”并连接在延时等待下面。桌面快捷方式通常需要双击才能打开，所以还需要修改点击次数。",
                "完成后双击“点击”模块进入设置。",
                target=lambda: self._palette_widget("click"),
                predicate=lambda: self._chain_has_prefix(("start", "findtemplate", "move_to", "delay_wait", "click")),
            ),
            GuideStep(
                "把点击设置成双击",
                "双击画布中的“点击”模块，把点击次数设置为 2。两次点击间隔保持约 0.10 秒即可，这样会像正常 Windows 双击一样尝试打开桌面应用。",
                "如果某个系统的双击阈值不同，可在高级点击设置中微调两次点击间隔。",
                target_rect=lambda: self._simple_module_rect("click"),
                predicate=self._click_is_double,
            ),
            GuideStep(
                "保存模板点击流程",
                "现在你的流程已经是：Start → 扫描桌面应用模板 → 移至识别坐标 → 等待 → 双击。点击保存。",
                "保存后就可以真正运行。",
                target=lambda: getattr(self.workspace, "save_button", None),
                advance_on_click=True,
            ),
            GuideStep(
                "运行模板点击训练",
                "确认目标桌面应用图标没有被 UVAF 窗口挡住，然后点击 Run。UVAF 会寻找模板、移动到识别位置并双击打开它。",
                "运行期间教程框和黄色高亮会隐藏，避免污染视觉识别。",
                target=lambda: getattr(self.workspace, "run_button", None),
                advance_on_click=True,
            ),
            GuideStep(
                "等待训练流程完成",
                "正在执行模板识别训练。",
                "如果没有找到图标：检查模板截图和匹配度；如果找错目标：提高匹配度或使用 ROI；如果鼠标到了正确位置但应用没打开：检查双击次数/间隔并增加动作延迟。",
                hide_coach=True,
                predicate=lambda: (
                    getattr(self.workspace, "_active_chains", 0) == 0
                    and not getattr(self.workspace, "_global_runtime_active", False)
                ),
            ),
        ]

    def _show_clear_button(self) -> None:
        self.coach.next_button.setText("清空并开始训练")

    def _clear_welcome_workflow(self) -> None:
        try:
            self.workspace.stop_workflows()
        except Exception:
            pass
        self.workspace._clear_all_canvases()
        self.workspace.save_project()

    def _begin_template_capture_step(self) -> None:
        button = getattr(self.workspace, "quick_template_button", None)
        if button is not None:
            try:
                button.setVisible(True)
                button.setEnabled(True)
            except Exception:
                pass
        try:
            templates_dir = self.workspace.project_manager.project_templates_dir()
            self._template_snapshot = {
                str(path.resolve())
                for path in templates_dir.glob("*.png")
                if path.is_file()
            }
        except Exception:
            self._template_snapshot = set()
        self._tutorial_template_path = None

    def _new_template_created(self) -> bool:
        try:
            templates_dir = self.workspace.project_manager.project_templates_dir()
            current = {
                str(path.resolve())
                for path in templates_dir.glob("*.png")
                if path.is_file()
            }
        except Exception:
            return False
        new_paths = sorted(current - self._template_snapshot)
        if not new_paths:
            return False

        # Template files currently pass through several Windows/OpenCV/path
        # backends.  Keep the tutorial on the safest portable naming subset so
        # new users do not build their first workflow on a path that may fail
        # to load on another backend or machine.
        valid_paths: list[str] = []
        for candidate in new_paths:
            stem = Path(candidate).stem
            if self._template_name_is_portable(stem):
                valid_paths.append(candidate)
                continue
            if candidate not in self._invalid_template_names_warned:
                self._invalid_template_names_warned.add(candidate)
                QMessageBox.warning(
                    self.window,
                    "请使用英文模板名",
                    "检测到新模板名称中包含中文或其他当前不推荐的字符。\n\n"
                    "为避免模板文件在部分 Windows 路径、OpenCV 或识别后端中出现读取失败/损坏，"
                    "当前版本建议模板名只使用：\n"
                    "英文 A-Z / a-z、数字 0-9、下划线 _、短横线 -。\n\n"
                    "例如：chrome_icon、desktop_app、app01。\n"
                    "请重新使用“快捷创建模板”建立一个英文名称的模板，教程随后会自动继续。",
                )

        if not valid_paths:
            return False
        self._tutorial_template_path = valid_paths[-1]
        return True

    @staticmethod
    def _template_name_is_portable(name: str) -> bool:
        value = str(name or "").strip()
        if not value:
            return False
        return all(
            ("a" <= ch.lower() <= "z")
            or ("0" <= ch <= "9")
            or ch in {"_", "-"}
            for ch in value
        )

    def _current_project(self):
        try:
            return self.workspace.project_manager.current_project()
        except Exception:
            return None

    def _no_project_open(self) -> bool:
        return self._current_project() is None

    def _training_project_created(self) -> bool:
        project = self._current_project()
        if project is None:
            return False
        project_id = str(getattr(project, "project_id", "") or "")
        if not project_id:
            return False
        if self._welcome_project_id and project_id == self._welcome_project_id:
            return False
        return True

    def _workspace_button(self, labels: tuple[str, ...]) -> QPushButton | None:
        wanted = {str(label).strip().casefold() for label in labels}
        try:
            buttons = self.workspace.findChildren(QPushButton)
        except Exception:
            return None
        visible_match = None
        fallback = None
        for button in buttons:
            text = str(button.text() or "").strip().casefold()
            if text not in wanted:
                continue
            fallback = fallback or button
            if button.isVisible() and button.isEnabled():
                visible_match = button
                break
        return visible_match or fallback

    def _scan_uses_tutorial_template(self) -> bool:
        block = self._simple_module_item("findtemplate")
        if block is None:
            return False
        selected = str(getattr(block, "selected_template_path", "") or "").strip()
        if not selected:
            return False
        if self._tutorial_template_path:
            try:
                return str(Path(selected).resolve()) == str(Path(self._tutorial_template_path).resolve())
            except Exception:
                return Path(selected).name == Path(self._tutorial_template_path).name
        return True

    def _click_is_double(self) -> bool:
        block = self._simple_module_item("click")
        if block is None:
            return False
        try:
            count = int(getattr(block, "click_count", 1))
            interval = float(getattr(block, "click_interval", 0.100))
        except Exception:
            return False
        return count >= 2 and 0.02 <= interval <= 0.50

    def _has_simple_module(self, module_type: str) -> bool:
        try:
            from ...ui.pages.workspace_page import CanvasBlock
            return any(
                isinstance(item, CanvasBlock)
                and getattr(item, "module_type", "") == module_type
                for item in self.workspace.canvas.workflow_scene.items()
            )
        except Exception:
            return False

    def _palette_widget(self, module_type: str) -> QWidget | None:
        """Return the exact palette block for a module and scroll it into view."""
        contents = getattr(self.workspace, "module_library_contents", None)
        if contents is None:
            return None
        for widget in contents.findChildren(QWidget):
            if getattr(widget, "module_type", "") == module_type:
                parent = widget.parentWidget()
                while parent is not None:
                    if hasattr(parent, "ensureWidgetVisible"):
                        try:
                            parent.ensureWidgetVisible(widget, 8, 20)
                        except Exception:
                            pass
                        break
                    parent = parent.parentWidget()
                return widget
        return None

    def _simple_module_item(self, module_type: str):
        try:
            from ...ui.pages.workspace_page import CanvasBlock
            items = self.workspace.canvas.workflow_scene.items()
            candidates = [
                item for item in items
                if isinstance(item, CanvasBlock)
                and getattr(item, "module_type", "") == module_type
            ]
            if not candidates:
                return None
            return sorted(candidates, key=lambda x: (x.scenePos().y(), x.scenePos().x()))[0]
        except Exception:
            return None

    def _simple_module_rect(self, module_type: str) -> QRect | None:
        item = self._simple_module_item(module_type)
        if item is None:
            return None
        try:
            view = self.workspace.canvas
            scene_rect = item.sceneBoundingRect()
            poly = view.mapFromScene(scene_rect)
            local_rect = poly.boundingRect()
            global_tl = view.viewport().mapToGlobal(local_rect.topLeft())
            window_tl = self.window.mapFromGlobal(global_tl)
            return QRect(window_tl, local_rect.size())
        except Exception:
            return None

    def _simple_chain_types(self) -> tuple[str, ...]:
        start = self._simple_module_item("start")
        if start is None:
            return ()
        result: list[str] = []
        seen: set[int] = set()
        current = start
        while current is not None and id(current) not in seen:
            seen.add(id(current))
            result.append(str(getattr(current, "module_type", "")))
            current = getattr(current, "stack_child", None)
        return tuple(result)

    def _chain_has_prefix(self, expected: tuple[str, ...]) -> bool:
        chain = self._simple_chain_types()
        return len(chain) >= len(expected) and chain[: len(expected)] == expected

    def _delay_is_reasonable(self) -> bool:
        block = self._simple_module_item("delay_wait")
        if block is None:
            return False
        try:
            value = float(getattr(block, "delay_value", 0.0))
            unit = str(getattr(block, "delay_unit", "milliseconds"))
        except Exception:
            return False
        factor = {
            "milliseconds": 1.0,
            "seconds": 1000.0,
            "minutes": 60_000.0,
            "hours": 3_600_000.0,
        }.get(unit, 1.0)
        milliseconds = value * factor
        # Teach a practical desktop-automation starting range rather than one
        # magic number. 200 ms is recommended in the coach text.
        return 100.0 <= milliseconds <= 1000.0

    def _manual_advance(self) -> None:
        if 0 <= self._step_index < len(self._steps):
            self._advance()

    def _advance(self) -> None:
        self._detach_target()
        self._poll.stop()
        self.coach.next_button.hide()
        self._step_index += 1
        if self._step_index >= len(self._steps):
            self._finish()
            return

        step = self._steps[self._step_index]
        if step.on_enter is not None:
            step.on_enter()

        self.coach.set_content(step.title, step.body, step.hint)
        if step.manual_next:
            self.coach.next_button.setText(
                "继续"
            )
            self.coach.next_button.show()

        self._attach_target(step)

        if step.hide_coach:
            # During the example automation the tutorial itself must not cover
            # the desktop or recognition targets.
            self.coach.hide()
            self.highlight.hide()
        else:
            self._sync_geometry()
            if not (step.requires_windowed and self._window_is_effectively_fullscreen()):
                self.coach.show()
                self.coach.raise_()

        if step.requires_windowed:
            QTimer.singleShot(80, self._warn_if_windowed_required)

        if step.predicate is not None:
            self._poll.start()

    def _attach_target(self, step: GuideStep) -> None:
        target = step.target() if step.target is not None else None
        self._target = target
        if target is not None:
            try:
                target.installEventFilter(self)
            except Exception:
                pass
        self._position_highlight(target)

    def _detach_target(self) -> None:
        if self._target is not None:
            try:
                self._target.removeEventFilter(self)
            except Exception:
                pass
        self._target = None
        self.highlight.hide()

    def _target_rect_in_window(self, target: QWidget) -> QRect:
        """Return target geometry in main-window logical coordinates."""
        if target is None or not target.isVisible():
            return QRect()
        global_top_left = target.mapToGlobal(QPoint(0, 0))
        window_top_left = self.window.mapFromGlobal(global_top_left)
        return QRect(window_top_left, target.size())

    def _active_target_rect_in_window(self) -> QRect:
        if self._step_index < 0 or self._step_index >= len(self._steps):
            return QRect()
        step = self._steps[self._step_index]
        if step.target_rect is not None:
            try:
                rect = step.target_rect()
                if rect is not None and rect.isValid():
                    return QRect(rect)
            except Exception:
                pass
        if self._target is not None:
            return self._target_rect_in_window(self._target)
        return QRect()

    def _position_highlight(self, target: QWidget | None = None) -> None:
        rect = self._active_target_rect_in_window()
        if rect.isNull() or not rect.isValid():
            self.highlight.hide()
            return
        padded = rect.adjusted(-5, -5, 5, 5)
        visible = padded.intersected(self.window.rect())
        if visible.isNull() or not visible.isValid():
            self.highlight.hide()
            return
        # Never draw a misleading partial yellow frame. If the requested
        # target is mostly outside the current viewport (for example while a
        # module-library scroll is still settling), wait for the next geometry
        # tick instead of framing the wrong area.
        original_area = max(1, padded.width() * padded.height())
        visible_area = max(0, visible.width() * visible.height())
        if visible_area / original_area < 0.80:
            self.highlight.hide()
            return
        self.highlight.setGeometry(visible)
        self.highlight.show()
        self.highlight.raise_()

    @staticmethod
    def _rect_overlap_area(a: QRect, b: QRect) -> int:
        inter = a.intersected(b)
        if inter.isNull() or not inter.isValid():
            return 0
        return max(0, inter.width()) * max(0, inter.height())

    def _coach_candidate_rects(self, coach_w: int, coach_h: int) -> list[QRect]:
        margin = max(12, min(24, self.window.width() // 80))
        bounds = self.window.rect().adjusted(margin, margin, -margin, -margin)
        result: list[QRect] = []

        target = self._active_target_rect_in_window()
        if not target.isNull() and target.isValid():
            gap = max(12, min(22, self.window.width() // 90))
            # Try all four sides of the actual target first. These coordinates
            # are calculated from live widget geometry, never a fixed screen
            # resolution.
            result.extend(
                [
                    QRect(target.right() + gap, target.top(), coach_w, coach_h),
                    QRect(target.left() - gap - coach_w, target.top(), coach_w, coach_h),
                    QRect(target.left(), target.bottom() + gap, coach_w, coach_h),
                    QRect(target.left(), target.top() - gap - coach_h, coach_w, coach_h),
                ]
            )

        # Resolution-independent fallback positions. Having all corners and
        # edge-centres available prevents the coach from being trapped over a
        # control on narrow/tall screens.
        result.extend(
            [
                QRect(bounds.left(), bounds.top(), coach_w, coach_h),
                QRect(bounds.right() - coach_w + 1, bounds.top(), coach_w, coach_h),
                QRect(bounds.left(), bounds.bottom() - coach_h + 1, coach_w, coach_h),
                QRect(bounds.right() - coach_w + 1, bounds.bottom() - coach_h + 1, coach_w, coach_h),
                QRect(bounds.center().x() - coach_w // 2, bounds.top(), coach_w, coach_h),
                QRect(bounds.center().x() - coach_w // 2, bounds.bottom() - coach_h + 1, coach_w, coach_h),
            ]
        )
        return result

    def _position_coach(self) -> None:
        if self.coach.isHidden() and self._step_index >= 0:
            try:
                if self._steps[self._step_index].hide_coach:
                    return
            except Exception:
                pass

        screen = self.window.screen()
        app = QApplication.instance()
        if screen is None and app is not None:
            screen = app.primaryScreen()
        if screen is None:
            return

        screen_rect = screen.availableGeometry()
        desired_w = max(320, min(460, int(self.window.width() * 0.36)))
        desired_w = min(desired_w, max(320, screen_rect.width() - 32))
        self.coach.prepare_for_screen(desired_w, screen_rect.height())
        coach_w = self.coach.width()
        coach_h = min(self.coach.height(), max(220, screen_rect.height() - 24))
        if self.coach.height() != coach_h:
            self.coach.setFixedHeight(coach_h)

        window_rect = self.window.frameGeometry()
        gap = max(12, min(22, screen_rect.width() // 100))

        # First preference: place the tutorial completely OUTSIDE UVAF. This is
        # the only way to guarantee that the explanation never hides workbench
        # controls or modules while the application is in a normal window.
        outside = [
            QRect(window_rect.right() + gap, window_rect.top(), coach_w, coach_h),
            QRect(window_rect.left() - gap - coach_w, window_rect.top(), coach_w, coach_h),
            QRect(window_rect.left(), window_rect.bottom() + gap, coach_w, coach_h),
            QRect(window_rect.left(), window_rect.top() - gap - coach_h, coach_w, coach_h),
        ]
        for rect in outside:
            if screen_rect.contains(rect):
                self.coach.move(rect.topLeft())
                return

        # If the window leaves no sufficiently large external strip, fall back
        # to an in-window candidate chosen to avoid the active target. Convert
        # the logical main-window candidates to global screen coordinates.
        target_global = QRect()
        target_local = self._active_target_rect_in_window()
        if not target_local.isNull() and target_local.isValid():
            tl = self.window.mapToGlobal(target_local.topLeft())
            target_global = QRect(tl, target_local.size()).adjusted(-12, -12, 12, 12)

        candidates: list[QRect] = []
        for local in self._coach_candidate_rects(coach_w, coach_h):
            global_tl = self.window.mapToGlobal(local.topLeft())
            candidates.append(QRect(global_tl, local.size()))

        best = None
        best_score = None
        for index, candidate in enumerate(candidates):
            # Clamp to the current monitor's available work area.
            x = min(max(candidate.x(), screen_rect.left()), max(screen_rect.left(), screen_rect.right() - coach_w + 1))
            y = min(max(candidate.y(), screen_rect.top()), max(screen_rect.top(), screen_rect.bottom() - coach_h + 1))
            rect = QRect(x, y, coach_w, coach_h)
            overlap_target = self._rect_overlap_area(rect, target_global) if not target_global.isNull() else 0
            overlap_window = self._rect_overlap_area(rect, window_rect)
            # Target overlap is effectively forbidden. After that, prefer the
            # smallest amount of workbench coverage.
            score = overlap_target * 1_000_000 + overlap_window + index
            if best_score is None or score < best_score:
                best_score = score
                best = rect
        if best is not None:
            self.coach.move(best.topLeft())

    def _refresh_dynamic_target(self) -> None:
        if self._step_index < 0 or self._step_index >= len(self._steps):
            return
        step = self._steps[self._step_index]
        if step.target is None:
            return
        try:
            target = step.target()
        except Exception:
            target = None
        if target is self._target:
            return
        if self._target is not None:
            try:
                self._target.removeEventFilter(self)
            except Exception:
                pass
        self._target = target
        if self._target is not None:
            try:
                self._target.installEventFilter(self)
            except Exception:
                pass

    def _sync_geometry(self) -> None:
        if self._step_index < 0 or self._step_index >= len(self._steps):
            return
        step = self._steps[self._step_index]
        self._refresh_dynamic_target()
        if step.hide_coach:
            self.highlight.hide()
            self.coach.hide()
            return
        if step.requires_windowed and self._window_is_effectively_fullscreen():
            self.highlight.hide()
            self.coach.hide()
            QTimer.singleShot(0, self._warn_if_windowed_required)
            return
        self._window_mode_notice_shown = False
        self._position_highlight(self._target)
        self._position_coach()
        if not self.coach.isVisible():
            self.coach.show()
            self.coach.raise_()

    def _window_is_effectively_fullscreen(self) -> bool:
        if self.window.isFullScreen() or self.window.isMaximized():
            return True
        screen = self.window.screen()
        if screen is None:
            app = QApplication.instance()
            screen = app.primaryScreen() if app is not None else None
        if screen is None:
            return False
        available = screen.availableGeometry()
        frame = self.window.frameGeometry()
        # Some custom/window-manager maximize states do not report
        # isMaximized(). Treat a window covering ~98% of the available desktop
        # as effectively fullscreen for tutorial automation purposes.
        if available.width() <= 0 or available.height() <= 0:
            return False
        width_ratio = frame.width() / available.width()
        height_ratio = frame.height() / available.height()
        return width_ratio >= 0.98 and height_ratio >= 0.98

    def _warn_if_windowed_required(self) -> bool:
        if self._step_index < 0 or self._step_index >= len(self._steps):
            return True
        step = self._steps[self._step_index]
        if not step.requires_windowed or not self._window_is_effectively_fullscreen():
            return True
        if self._fullscreen_warning_open or self._window_mode_notice_shown:
            return False

        self._fullscreen_warning_open = True
        self._window_mode_notice_shown = True
        try:
            QMessageBox.information(
                self.window,
                "请切换到窗口模式",
                "交互式教程需要使用窗口模式。UVAF 如果处于全屏或最大化状态，教程提示无法稳定放在窗口外侧，"
                "运行桌面自动化时还会遮住需要识别和点击的内容。\n\n"
                "请点击窗口右上角的“还原”按钮，将 UVAF 调整为窗口模式，并在桌面上留出可见区域。"
                "恢复窗口后，教程会自动继续，并重新计算提示框与黄色高亮框的位置。",
                QMessageBox.Ok,
            )
        finally:
            self._fullscreen_warning_open = False
        return False

    def _poll_step(self) -> None:
        if self._step_index < 0 or self._step_index >= len(self._steps):
            return
        predicate = self._steps[self._step_index].predicate
        if predicate is not None and predicate():
            self._advance()

    def eventFilter(self, watched, event) -> bool:
        # Keep the tutorial aligned after resizing, maximizing, scrolling,
        # layout changes or moving the window between monitors.
        if watched is self.window and event.type() in {
            QEvent.Resize,
            QEvent.Move,
            QEvent.WindowStateChange,
            QEvent.Show,
            QEvent.LayoutRequest,
        }:
            QTimer.singleShot(0, self._sync_geometry)
            return False

        if watched is self._target:
            if event.type() in {
                QEvent.Resize,
                QEvent.Move,
                QEvent.Show,
                QEvent.Hide,
                QEvent.LayoutRequest,
            }:
                QTimer.singleShot(0, self._sync_geometry)

            if self._step_index >= 0 and self._step_index < len(self._steps):
                step = self._steps[self._step_index]
                if event.type() == QEvent.MouseButtonPress and step.requires_windowed:
                    if not self._warn_if_windowed_required():
                        # Consume the whole click sequence. Without this guard,
                        # the later release event could advance the tutorial
                        # even though the Run button never actually clicked.
                        self._blocked_target_click = True
                        return True

                if event.type() == QEvent.MouseButtonRelease:
                    if self._blocked_target_click:
                        self._blocked_target_click = False
                        return True
                    if step.advance_on_click:
                        # For desktop automation, remove every tutorial overlay
                        # immediately after the user's Run click.
                        self.coach.hide()
                        self.highlight.hide()
                        QTimer.singleShot(120, self._advance)
        return False

    def _finish(self) -> None:
        self._detach_target()
        self._poll.stop()
        self.coach.hide()
        self.settings.set("tutorial.completed", True)
        self.settings.set("tutorial.skipped", False)
        result = QMessageBox.question(
            self.window,
            "基础训练完成",
            "你已经完成第一个 UVAF 流程。现在打开完整模块手册吗？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if result == QMessageBox.Yes:
            self.open_reference()
