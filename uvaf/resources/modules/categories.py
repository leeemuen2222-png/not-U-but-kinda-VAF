from ._model import CategoryDefinition

CATEGORIES = (
    CategoryDefinition("sensing", "感知", "检测画面、窗口或状态，并输出结果。", "#49A96C", False, 10),
    CategoryDefinition("action", "动作", "根据状态执行点击、键盘等操作。", "#D5A52F", False, 20),
    CategoryDefinition("control", "逻辑", "负责 ROI、条件、分支、循环和流程顺序。", "#D57A33", False, 30),
    CategoryDefinition("data", "数据", "保存、转换和比较流程中的数据。", "#4C8FC5", False, 40),
    CategoryDefinition("debug", "调试", "检查流程中的数据与运行状态。", "#6F7C8C", False, 50),
    CategoryDefinition("global", "全局设置", "连接到起始执行链后，对后续流程全局生效。", "#B85C6F", False, 60),
    CategoryDefinition("custom", "自定义模块", "当前项目中的可复用模块组合。", "#548F8B", False, 70),
    CategoryDefinition("event", "事件", "定义流程开始和触发方式。", "#8C65B3", False, 80),
)
