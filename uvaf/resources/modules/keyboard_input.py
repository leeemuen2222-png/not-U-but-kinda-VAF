from ._model import ModuleDefinition
MODULE = ModuleDefinition(
    module_type="keyboard_input", category_key="action", label="键盘输入",
    description="执行按键或文本输入。",
    palette_order=40,
    tags=frozenset({"action"}), simple_width=360.0, settings_key="keyboard_input",
)
