from ._model import ModuleDefinition
MODULE = ModuleDefinition(
    module_type="findtemplate", category_key="sensing", label="扫描模板（坐标输出）",
    description="扫描一次模板并输出全局坐标。", output_type="coordinate",
    palette_order=10,
    tags=frozenset({"visual"}), simple_width=600.0,
    simple_controls="visual", settings_key="visual", settings_title="扫描模板设置", runtime_label="扫描模板",
)
