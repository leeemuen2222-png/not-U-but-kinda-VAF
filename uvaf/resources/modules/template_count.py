from ._model import ModuleDefinition
MODULE = ModuleDefinition(
    module_type="template_count", category_key="sensing", label="模板计数（单数字输出）",
    description="统计识别范围内模板数量。", output_type="number",
    palette_order=20,
    tags=frozenset({"visual"}), simple_width=600.0,
    simple_controls="visual", settings_key="visual", settings_title="模板计数设置", runtime_label="模板计数",
)
