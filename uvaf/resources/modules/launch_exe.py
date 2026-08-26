from ._model import ModuleDefinition
MODULE = ModuleDefinition(
    module_type="launch_exe", category_key="action", label="启动程序",
    description="启动指定路径的程序。",
    palette_order=50,
    tags=frozenset({"action"}), simple_width=520.0,
    simple_controls="launch_exe", settings_key="launch_exe",
)
