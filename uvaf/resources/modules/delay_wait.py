from ._model import ModuleDefinition
MODULE = ModuleDefinition(
    module_type="delay_wait", category_key="action", label="延时等待",
    description="暂停当前执行链指定时间。",
    palette_order=60,
    tags=frozenset({"action"}), simple_width=360.0,
    simple_controls="delay_wait", settings_key="delay_wait",
)
