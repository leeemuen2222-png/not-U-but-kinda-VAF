from ._model import ModuleDefinition

MODULE = ModuleDefinition(
    module_type="mouse_press",
    category_key="action",
    label="按下",
    description="执行所选鼠标按键的按下动作，不自动抬起。",
    palette_order=25,
    tags=frozenset({"action"}),
    simple_width=220.0,
    settings_key="mouse_button",
)
