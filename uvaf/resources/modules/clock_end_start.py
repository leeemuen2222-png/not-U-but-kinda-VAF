from ._model import ModuleDefinition
MODULE = ModuleDefinition(
    module_type="clock_end_start", category_key="event", label="时钟终止后链",
    description="由对应时钟生成的一次性事件根。", palette=False,
    tags=frozenset({"event_root"}),
    complex_inputs=(), complex_outputs=("output", "output_2", "output_3"),
)
