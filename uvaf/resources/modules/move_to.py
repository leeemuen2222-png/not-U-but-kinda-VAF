from ._model import ModuleDefinition
MODULE = ModuleDefinition(
    module_type="move_to", category_key="action", label="移至",
    description="把鼠标移动到输入坐标。", input_type="coordinate", output_type="coordinate",
    palette_order=10,
    tags=frozenset({"action"}), settings_key="move_to",
)
