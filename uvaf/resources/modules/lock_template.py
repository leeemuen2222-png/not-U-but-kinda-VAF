from ._model import ModuleDefinition
MODULE = ModuleDefinition(
    module_type="lock_template", category_key="sensing", label="锁定模板（坐标输出）",
    description="持续输出目标坐标直到模板消失。", output_type="coordinate",
    palette_order=30,
    tags=frozenset({"visual"}), simple_width=600.0,
    simple_controls="visual", settings_key="visual", settings_title="锁定模板设置", runtime_label="锁定模板",
)
