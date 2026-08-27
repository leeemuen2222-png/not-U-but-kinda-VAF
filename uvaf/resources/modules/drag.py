from ._model import ModuleDefinition

MODULE = ModuleDefinition(
    module_type="drag",
    category_key="action",
    label="拖动",
    description="以上方坐标输入作为拖动起点，并拖动到终点坐标或按指定像素偏移。",
    palette_order=20,
    input_type="coordinate",
    output_type="coordinate",
    tags=frozenset({"action"}),
    simple_width=360.0,
    settings_key="drag",
    complex_inputs=("input", "input_2"),
    complex_input_hints=("起点坐标", "终点坐标"),
)
