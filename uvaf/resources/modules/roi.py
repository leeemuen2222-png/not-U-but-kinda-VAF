from ._model import ModuleDefinition
MODULE = ModuleDefinition(
    module_type="roi", category_key="control", label="ROI",
    description="限制内部模块的识别与执行范围。",
    palette_order=10,
    tags=frozenset({"logic_container"}), settings_key="roi",
    complex_inputs=("input", "input_2", "input_3", "inner_input"),
    complex_outputs=("output", "output_2", "output_3", "inner_output"),
)
