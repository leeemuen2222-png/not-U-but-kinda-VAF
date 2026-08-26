from ._model import ModuleDefinition
MODULE = ModuleDefinition(
    module_type="coordinate_modify", category_key="data", label="坐标修改（坐标输出）",
    description="对输入坐标添加 X/Y 偏移并输出。",
    palette_order=20,
    input_type="coordinate", output_type="coordinate", simple_width=440.0,
    simple_controls="coordinate_modify", settings_key="coordinate_modify",
)
