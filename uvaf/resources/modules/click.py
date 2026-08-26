from ._model import ModuleDefinition
MODULE = ModuleDefinition(
    module_type="click", category_key="action", label="点击",
    description="执行完整的按下和松开点击动作。",
    palette_order=30,
    tags=frozenset({"action"}), settings_key="click",
)
