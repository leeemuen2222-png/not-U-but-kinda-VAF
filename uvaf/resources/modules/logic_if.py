from ._model import ModuleDefinition
MODULE = ModuleDefinition(
    module_type="logic_if", category_key="control", label="IF…THEN…",
    description="判定条件成立后执行 THEN 分支。",
    palette_order=40,
    tags=frozenset({"logic_container", "condition_logic"}),
    logic_slots=("IF · 判定", "THEN · 执行"), condition_slots=(0,),
    complex_outputs=("output", "output_2", "output_3", "branch_a_output", "branch_b_output"),
)
