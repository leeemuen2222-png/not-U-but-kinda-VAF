from ._model import ModuleDefinition
MODULE = ModuleDefinition(
    module_type="logic_and", category_key="control", label="AND（同时满足）",
    description="前两个判定都成立时执行第三分支。",
    palette_order=70,
    tags=frozenset({"logic_container", "condition_logic"}),
    logic_slots=("条件 A", "条件 B", "两者均满足后执行"), condition_slots=(0, 1),
    complex_outputs=("output", "output_2", "output_3", "branch_a_output", "branch_b_output", "branch_c_output"),
)
