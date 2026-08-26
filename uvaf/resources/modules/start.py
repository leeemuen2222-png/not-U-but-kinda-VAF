from ._model import ModuleDefinition
MODULE = ModuleDefinition(
    module_type="start", category_key="event", label="起始",
    description="运行时为连接在其后的执行链充能。",
    palette_order=10,
    tags=frozenset({"event_root"}),
    complex_inputs=(), complex_outputs=("output", "output_2", "output_3"),
)
