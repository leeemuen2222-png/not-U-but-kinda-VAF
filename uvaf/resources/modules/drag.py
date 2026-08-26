from ._model import ModuleDefinition
MODULE = ModuleDefinition(
    module_type="drag", category_key="action", label="拖动",
    description="从起始点按下鼠标并移动到结束点后松开。",
    palette_order=20,
    tags=frozenset({"action"}), simple_width=360.0, settings_key="drag",
)
