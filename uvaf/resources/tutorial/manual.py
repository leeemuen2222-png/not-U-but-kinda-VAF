from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TutorialEntry:
    module_type: str
    title_zh: str
    title_en: str
    function_zh: str
    function_en: str
    settings_zh: str
    settings_en: str
    usage_zh: str
    usage_en: str


MODULE_TUTORIALS: tuple[TutorialEntry, ...] = (
    TutorialEntry(
        "start", "起始", "Start",
        "事件链的入口。只有连接到起始模块（或其他事件类模块）的链条才会被充能并执行。",
        "Entry point of an event chain. Only chains connected to Start or another event module are energized and executed.",
        "没有双击设置。简单模式只有下方连接齿；复杂模式只有输出端口，没有输入端口。",
        "No settings dialog. In Simple mode it exposes only a lower connector; in Complex mode it has outputs only and no inputs.",
        "先拖出起始，再把要执行的模块从上到下连接。不同起始模块可以并行运行。",
        "Place Start first, then connect modules below it. Separate Start modules can run in parallel.",
    ),
    TutorialEntry(
        "findtemplate", "扫描模板（坐标输出）", "Scan template (coordinate output)",
        "在当前有效识别区域内寻找模板，命中后输出模板的全局屏幕坐标。多个相同目标时优先锚点附近，否则选择最左侧。",
        "Finds a template in the active recognition region and outputs global screen coordinates. With multiple matches it prefers the one nearest the anchor, otherwise the leftmost match.",
        "可选择模板、匹配度、彩色 Ccoeff、灰度、RGBCount、HSVCount、边缘、FeatureMatch、多尺度、连续帧确认和 Feature detector。默认全部识别方法启用。",
        "Choose the template, threshold, Color Ccoeff, grayscale, RGBCount, HSVCount, edge, FeatureMatch, multiscale matching, consecutive-frame confirmation and feature detector. All methods are enabled by default.",
        "常见用法：扫描模板 → 移至 → 点击。扫描模块输出必须保持全局坐标，ROI 只限制搜索范围。",
        "Typical chain: Scan template → Move to → Click. Scan output remains global coordinates; ROI only limits the search region.",
    ),
    TutorialEntry(
        "template_count", "模板计数（单数字输出）", "Template count (number output)",
        "统计有效识别区域内指定模板出现的数量，输出一个整数。",
        "Counts how many instances of a template exist in the active recognition region and outputs an integer.",
        "视觉设置与扫描模板一致，包括模板、匹配度和全部识别方法。",
        "Uses the same visual settings as Scan template, including template, threshold and recognition methods.",
        "可以连接检测输入进行调试，也可以作为后续条件判断的数据来源。",
        "Connect it to Inspect input for debugging or use its number as data for later conditions.",
    ),
    TutorialEntry(
        "lock_template", "锁定模板（坐标输出）", "Lock template (coordinate output)",
        "启动后持续跟踪同一目标并不断输出坐标，直到进程结束、目标消失或离开 ROI。",
        "Continuously tracks the target and keeps outputting its coordinate until the process ends, the target disappears, or it leaves the ROI.",
        "视觉设置与扫描模板一致。",
        "Uses the same visual settings as Scan template.",
        "适合需要持续跟随移动目标的动作链。目标离开有效 ROI 也会被视为消失。",
        "Useful for chains that must follow a moving target. Leaving the active ROI counts as disappearance.",
    ),
    TutorialEntry(
        "scan_until_found", "持续扫描直到发现", "Scan until found",
        "持续扫描模板，直到识别到目标后输出一次坐标并完成。没有发现时不会让同一链的下一个模块提前执行。",
        "Keeps scanning until the target appears, then outputs one coordinate and completes. The next module in the same chain cannot start early.",
        "可设置模板、识别方式、匹配度以及等待上限。",
        "Configure template, recognition methods, threshold and optional wait limit.",
        "适合等待按钮、弹窗或加载完成标识出现。",
        "Useful for waiting for a button, dialog or loading-complete indicator to appear.",
    ),
    TutorialEntry(
        "move_to", "移至", "Move to",
        "读取坐标输入，把鼠标移动到目标全局坐标。",
        "Reads coordinate input and moves the mouse to the target global screen position.",
        "普通模式精准瞬移；高级模式支持四方向偏移、规定时间、像素/秒、移速偏移和随机平滑路径。规定时间为 0 时瞬移。",
        "Normal mode moves instantly. Advanced mode adds directional offsets, fixed-duration movement, pixels/sec, speed variation and randomized smooth paths. Duration 0 means instant movement.",
        "通常放在扫描模板或固定坐标之后。",
        "Usually placed after Scan template or Fixed coordinate.",
    ),
    TutorialEntry(
        "drag", "拖动", "Drag",
        "在起点按下鼠标并移动到终点后抬起。简单模式上方坐标输入默认为起点。",
        "Presses the mouse at the start point, moves to the destination and releases. In Simple mode the incoming coordinate is the start point.",
        "两种模式：坐标至坐标；坐标为起始拖动特定像素。两种模式都保留高级移动设置。复杂模式前者有起点/终点两个输入，后者只有起点输入。",
        "Two modes: coordinate-to-coordinate and drag a pixel offset from the start coordinate. Both retain advanced movement settings. In Complex mode the first has start/end inputs; the second has only a start input.",
        "适合滑块、拖拽列表、地图拖动等。",
        "Useful for sliders, sortable lists, maps and other drag interactions.",
    ),
    TutorialEntry(
        "click", "点击", "Click",
        "执行一次完整的鼠标按下→抬起动作。",
        "Performs a complete mouse press→release click.",
        "可设置点击次数；高级设置包含每次按下时长和两次点击间隔。",
        "Configure click count; advanced settings include press duration and interval between clicks.",
        "与按下/抬起模块不同，点击会自动完成完整动作。",
        "Unlike Mouse down / Mouse up, Click automatically completes the full action.",
    ),
    TutorialEntry(
        "mouse_press", "按下", "Mouse down",
        "按住指定鼠标键，不自动抬起。",
        "Presses and holds the selected mouse button without automatically releasing it.",
        "双击可选择左键、右键或中键。",
        "Double-click to choose left, right or middle mouse button.",
        "与抬起模块配合可以制作跨多个模块的按住操作。点击 Stop 时 UVAF 会强制释放鼠标键。",
        "Pair with Mouse up to keep a button held across multiple modules. Stop forcibly releases held mouse buttons.",
    ),
    TutorialEntry(
        "mouse_release", "抬起", "Mouse up",
        "抬起指定鼠标键。",
        "Releases the selected mouse button.",
        "双击可选择左键、右键或中键。",
        "Double-click to choose left, right or middle mouse button.",
        "通常与按下模块配对使用。",
        "Usually paired with Mouse down.",
    ),
    TutorialEntry(
        "keyboard_input", "键盘输入", "Keyboard input",
        "可以执行按键动作，也可以直接输入任意文本。",
        "Can perform key actions or type arbitrary text.",
        "按键模式通过录制按钮捕获真实按键；支持按下/长按、次数、间隔、时长。文本模式支持 Unicode。高级设置可随机化时长与间隔并模拟更接近真实用户的输入节奏。",
        "Key mode records a real key through a capture button and supports press/hold, count, interval and duration. Text mode supports Unicode. Advanced settings can randomize timing for more human-like input.",
        "输入文本越长，UVAF 会自动加入处理缓冲；每个模块之间仍至少有 5 ms 间隔。",
        "Longer text automatically adds a processing buffer; every module still has at least a 5 ms inter-module gap.",
    ),
    TutorialEntry(
        "launch_exe", "启动程序", "Launch program",
        "启动用户指定路径上的程序。",
        "Launches a program at the configured path.",
        "模块表面和双击设置都可选择或输入程序路径。",
        "Choose or type the program path on the module or in its settings dialog.",
        "适合在自动化流程开始时打开目标应用。",
        "Useful for opening the target application at the start of an automation.",
    ),
    TutorialEntry(
        "delay_wait", "延时等待", "Delay",
        "等待指定时长后才让同一条链继续。",
        "Waits for the configured duration before the same chain continues.",
        "默认单位为毫秒，也可选择秒、分钟、小时。",
        "Milliseconds are the default unit; seconds, minutes and hours are also available.",
        "现在同一链中的模块必须完成后才会执行下一个模块，延时用于明确需要等待的场景。",
        "Modules in the same chain already wait for completion; use Delay when an explicit pause is required.",
    ),
    TutorialEntry(
        "roi", "ROI", "ROI",
        "限制内部视觉模块的识别区域，并作为简单模式容器组织内部链。",
        "Limits recognition for visual modules inside it and acts as a Simple-mode container for internal chains.",
        "双击可设置 X/Y/W/H、左上角+大小、ROI 框选、选择锚点和建立新的锚点模板。锚点坐标系下 ROI 坐标相对锚点。",
        "Double-click to set X/Y/W/H, top-left+size, select ROI, choose anchor, or create a new anchor template. With an anchor, ROI coordinates are anchor-relative.",
        "内部模块会让容器自动扩张；ROI 不应该遮挡或删除内部模块。",
        "Internal modules expand the container automatically; ROI must not hide or delete contained modules.",
    ),
    TutorialEntry(
        "loop", "循环", "Loop",
        "重复执行内部模块指定次数，也可以无限循环。",
        "Repeats its internal chain a chosen number of times or indefinitely.",
        "次数可以输入正整数，也可以选择无限。",
        "Use a positive loop count or Infinite.",
        "每一轮内部模块严格按顺序完整执行，完成后才开始下一轮。",
        "Modules inside each iteration complete in strict order before the next iteration starts.",
    ),
    TutorialEntry(
        "loop_until", "循环…直到…", "Loop…until…",
        "上方循环任务持续重复；下方“直到”分支同时开始但只执行一次。直到分支完成时，上方循环结束。",
        "The upper task repeats while the lower Until branch starts at the same time and runs once. Completion of Until ends the upper loop.",
        "没有额外必须设置的参数，主要通过两个内部连接臂组织链条。",
        "No required extra parameters; behavior is defined by the two internal connector branches.",
        "适合一边重复操作，一边等待结束条件链完成。",
        "Useful when repeatedly doing work while a separate completion branch runs in parallel.",
    ),
    TutorialEntry(
        "logic_if", "IF…THEN…", "IF…THEN…",
        "先执行条件框中的模块得到判定，成立时执行 THEN 区域。",
        "Evaluates the condition branch first and executes THEN when the condition is true.",
        "条件框可以放视觉/数据/逻辑模块。动作模块放入条件框会被执行，但不会直接提供判定值；若只有动作模块，执行完成默认视为成立。",
        "Condition branches can contain sensing/data/logic modules. Action modules execute but do not directly provide a condition value; if actions are the only content, completion counts as true.",
        "用于根据识别结果或数值决定是否执行动作链。",
        "Use it to conditionally execute actions based on recognition or data results.",
    ),
    TutorialEntry(
        "logic_or", "OR", "OR",
        "前两个条件任意一个成立，就执行第三个分支。",
        "Executes the third branch when either of the first two conditions is true.",
        "三个内部连接区域分别是条件 A、条件 B 和执行区。",
        "Three internal branches: Condition A, Condition B and Execute.",
        "适合接受多个可替代条件。",
        "Useful when either of multiple alternative conditions is acceptable.",
    ),
    TutorialEntry(
        "logic_nor", "NOR / neither", "NOR / neither",
        "当前两个条件都不成立时执行第三个分支。",
        "Executes the third branch only when neither of the first two conditions is true.",
        "三个内部连接区域分别是条件 A、条件 B 和执行区。",
        "Three internal branches: Condition A, Condition B and Execute.",
        "适合制作“两个目标都没有出现时”的处理。",
        "Useful for handling cases where neither target is present.",
    ),
    TutorialEntry(
        "logic_and", "AND", "AND",
        "只有前两个条件同时成立时才执行第三个分支。",
        "Executes the third branch only when both conditions are true.",
        "三个内部连接区域分别是条件 A、条件 B 和执行区。",
        "Three internal branches: Condition A, Condition B and Execute.",
        "适合需要两个独立条件同时满足的操作。",
        "Useful when two independent conditions must both be satisfied.",
    ),
    TutorialEntry(
        "fixed_coordinate", "固定坐标（坐标输出）", "Fixed coordinate (coordinate output)",
        "输出用户指定的坐标。没有锚点时是全局屏幕坐标；选择锚点后，填写值是相对锚点的偏移，最终仍输出全局坐标。",
        "Outputs a configured coordinate. Without an anchor it is a global screen coordinate; with an anchor, entered values are offsets and final output is still global.",
        "可选择锚点模板（包含“空”）并填写 X/Y。",
        "Choose an anchor template (including None) and enter X/Y.",
        "适合固定按钮、桌面图标或其他位置稳定的目标。",
        "Useful for fixed buttons, desktop icons and other stable locations.",
    ),
    TutorialEntry(
        "coordinate_modify", "坐标修改", "Modify coordinate",
        "接收一个坐标，按 X/Y 偏移后输出新的坐标。",
        "Receives a coordinate, applies X/Y offsets and outputs the result.",
        "X/Y 必须显式带 + 或 -，例如 +20、-15。",
        "X/Y must explicitly include + or -, for example +20 and -15.",
        "适合点击模板中心以外的位置，或在识别坐标基础上做微调。",
        "Useful for offsetting from a recognized point or clicking away from the template center.",
    ),
    TutorialEntry(
        "inspect_input", "检测输入", "Inspect input",
        "接受任意输入并把值、类型、数据标记和 ROI 信息打印到控制台。",
        "Accepts any input and prints value, type, data tag and ROI information to the console.",
        "没有额外设置。",
        "No extra settings.",
        "调试坐标、数字输出和 ROI 传播时非常有用。",
        "Very useful for debugging coordinates, numeric outputs and ROI propagation.",
    ),
    TutorialEntry(
        "global_anchor_roi", "仅识别锚点", "Anchor-only recognition",
        "连接在起始链后会以极高优先级限制整个 Recognition Engine 的全局视野，只允许识别锚点指定 ROI 内的内容。",
        "When connected after Start, it globally restricts Recognition Engine to the ROI around the selected anchor with very high priority.",
        "选择锚点模板和 ROI；双击可使用“观看图像识别视角”检查 Recognition Engine 实际看到的区域。",
        "Choose anchor template and ROI; double-click to inspect the Recognition Engine viewport.",
        "全局设置只在连接到事件链后生效，并会持续到 Stop。全局设置下只能继续连接其他全局设置。",
        "Global settings activate only when connected to an event chain and remain active until Stop. Only other global settings may follow them.",
    ),
    TutorialEntry(
        "clock", "时钟", "Clock",
        "计时结束后触发指定行为。",
        "Triggers a configured action when the timer expires.",
        "支持结束进程、结束进程并关闭程序、执行链、终止其他事件链条并执行链。执行链会生成一次性的“时钟终止后链”事件模块。",
        "Supports stopping the process, stopping and closing the app, executing a chain, or stopping other event chains then executing a chain. Execute-chain modes create a one-use Clock end chain event module.",
        "时钟本身也必须连接在事件链上才会被充能。",
        "Clock itself must be connected to an event chain to be energized.",
    ),
    TutorialEntry(
        "clock_end_start", "时钟终止后链", "Clock end chain",
        "由对应的时钟生成的一次性事件入口，在时钟触发执行链时运行其下方链条。",
        "A one-use event entry created by its matching Clock and executed when that timer triggers an execute-chain behavior.",
        "每个时钟生成自己的编号事件模块；拖出后不再出现在模块库，删除后才会返回。",
        "Each Clock creates its own numbered event module; once placed it disappears from the palette until deleted.",
        "把时钟结束后要执行的动作连接在它下面。",
        "Connect the actions that should run after the timer below it.",
    ),
    TutorialEntry(
        "custom_module_instance", "自定义模块", "Custom module",
        "把用户框选的一组模块保存成一个独立模块，便于项目内复用。",
        "Saves a selected group of modules as one reusable project-local module.",
        "左键框选模块后使用工作台工具栏“新建为自定义模块”。模块库自定义分类中的 + 可以导入或打开自定义模块文件夹；右键已有模块可以打开位置或删除。",
        "Select modules with left-drag, then use Create custom module in the toolbar. The + item in the Custom category imports or opens the custom-module folder; right-click an existing custom module to locate or delete it.",
        "自定义模块保存于当前项目中，不会自动成为其他项目的全局模块。",
        "Custom modules are stored in the current project and are not automatically global across projects.",
    ),
)


OPERATIONS_ZH = (
    ("画布操作", "简单模式：左键框选模块，中键拖动画布；模块通过齿磁吸。复杂模式：点击端口选择连接，拖动时显示虚线；右键输入端口可解除连接。"),
    ("模块设置", "大多数模块双击打开设置。视觉模块统一提供模板、匹配度和识别方法。复杂模式仍使用同一套双击设置。"),
    ("项目", "工作台可保存、导入、导出、切换、关闭、删除项目并打开项目所在文件夹。每个项目拥有独立 templates 模板库、resources 资源、自定义模块和工作流。推荐为不同游戏/应用建立不同项目。首次教程会实际带你执行一次：关闭欢迎项目 → 新建项目 → 输入项目名称 → 在新项目中建立自己的自动化。"),
    ("运行", "只有事件链会启动。Run 后同一链严格等待当前模块完成再执行下一个；不同事件链可以并行。对于移至、点击、键盘输入、拖动、启动程序等会依赖 Windows 或目标应用响应的动作，建议在相邻动作之间加入短暂的“延时等待”，常见起点为 100–500 ms，再根据稳定性逐步调整。Stop 会停止全局设置、事件链，并释放可能仍按住的鼠标键。"),
    ("什么是模板", "模板是当前项目模板库中的一张参考截图。UVAF 不会理解它‘是什么应用’或‘是什么按钮’，而是比较画面中的图像特征，寻找与模板足够相似的区域。模板应尽量紧贴目标、包含稳定且有辨识度的图形，并避免时间、动画、大面积背景或会频繁改变的文字。工具栏‘快捷创建模板’可以直接在屏幕上框选并保存模板。重要：当前版本推荐模板文件名只使用英文、数字、下划线 _ 和短横线 -，不要使用中文模板名；中文路径在部分 Windows/OpenCV/识别后端组合下可能造成模板读取失败或文件损坏。推荐例如 chrome_icon、menu_ok、app01。"),
    ("如何使用模板识别", "最常见链条是：扫描模板（坐标输出） → 移至 → 延时等待 → 点击。扫描模板命中后输出全局屏幕坐标。匹配度越高越严格；漏识别时先检查模板截图，再适度降低匹配度；误识别时提高匹配度、换更独特的模板或缩小 ROI。视觉识别方法包括彩色 Ccoeff、灰度、RGBCount、HSVCount、边缘和 FeatureMatch，默认全部启用适合多数入门场景。"),
    ("什么是锚点", "锚点也是模板，但它主要用来建立相对坐标系，而不是作为最终点击目标。假设一个游戏面板会在屏幕上移动：把面板中稳定的小图标设为锚点后，ROI 或固定坐标可以写成相对锚点的偏移。面板整体移动时，这些相对区域仍会跟随。锚点适合‘整体位置会变、内部布局相对稳定’的界面。"),
    ("模板、锚点与 ROI 的关系", "普通模板回答‘目标在哪里’；锚点回答‘参考坐标系在哪里’；ROI 回答‘只允许在哪一块区域里看’。三者可以组合：先识别锚点确定参考位置，再把 ROI 放到锚点附近，最后只在 ROI 中扫描目标模板。这样通常比整屏识别更快、更稳，也更不容易误认重复目标。"),
    ("多目标选择规则", "当同一个模板在有效识别范围内出现多个候选时，有锚点的流程优先采用靠近锚点的候选；没有锚点时优先采用屏幕最左侧候选。若场景里重复图标很多，推荐配合锚点或 ROI 限定范围。"),
    ("快捷工具", "Ctrl+S 默认快捷建立模板，Ctrl+L 默认打开视觉识别系统视角；可在设置→热键中重新录制。视觉识别视角可以帮助检查 Recognition Engine 实际看到的区域和识别框。"),
    ("小工具", "鼠标坐标监视器默认读取 Windows 全局物理坐标，每 0.2 秒刷新；按 K 记录。也可选择项目模板作为锚点记录相对坐标。颜色报告工具可框选区域并统计精确 RGB/HEX。"),
)



def entry_text(entry: TutorialEntry, language: str) -> tuple[str, str, str, str]:
    if str(language).lower().startswith("zh"):
        return entry.title_zh, entry.function_zh, entry.settings_zh, entry.usage_zh
    return entry.title_en, entry.function_en, entry.settings_en, entry.usage_en
