from ._model import ModuleDefinition
MODULE = ModuleDefinition(
    module_type="loop_until", category_key="control", label="循环…直到…",
    description="循环任务与直到分支同时启动，直到分支完成后结束循环。",
    palette_order=30,
    tags=frozenset({"logic_container"}),
    logic_slots=("循环任务（重复）", "直到"),
    complex_outputs=("output", "output_2", "output_3", "branch_a_output", "branch_b_output"),
)
