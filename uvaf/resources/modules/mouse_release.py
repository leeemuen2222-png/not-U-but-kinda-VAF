from ._model import ModuleDefinition

MODULE = ModuleDefinition(
    module_type="mouse_release",
    category_key="action",
    label="抬起",
    description="执行所选鼠标按键的抬起动作。",
    palette_order=26,
    tags=frozenset({"action"}),
    simple_width=220.0,
    settings_key="mouse_button",
)
