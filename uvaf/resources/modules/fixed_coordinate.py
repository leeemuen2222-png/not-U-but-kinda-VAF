from ._model import ModuleDefinition
MODULE = ModuleDefinition(
    module_type="fixed_coordinate", category_key="data", label="固定坐标（坐标输出）",
    description="输出固定全局坐标，或基于锚点计算后的全局坐标。",
    palette_order=10,
    output_type="coordinate", simple_width=430.0, settings_key="fixed_coordinate",
)
