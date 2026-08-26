from ._model import ModuleDefinition
MODULE = ModuleDefinition(
    module_type="scan_until_found", category_key="sensing", label="持续扫描模板直到发现（坐标输出）",
    description="持续扫描直到发现模板，然后输出一次全局坐标。", output_type="coordinate",
    palette_order=40,
    tags=frozenset({"visual"}), simple_width=600.0,
    simple_controls="visual", settings_key="visual", settings_title="视觉识别设置", runtime_label="持续扫描直到发现",
)
