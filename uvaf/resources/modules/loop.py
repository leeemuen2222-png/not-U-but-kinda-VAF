from ._model import ModuleDefinition
MODULE = ModuleDefinition(
    module_type="loop", category_key="control", label="循环",
    description="重复执行内部模块指定次数或无限循环。",
    palette_order=20,
    tags=frozenset({"logic_container"}), settings_key="loop",
    logic_slots=("循环体",),
    complex_outputs=("output", "output_2", "output_3", "body_output"),
)
