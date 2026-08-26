from ._model import ModuleDefinition
MODULE = ModuleDefinition(
    module_type="clock", category_key="global", label="时钟",
    description="持续计时并在结束后执行指定行为。",
    palette_order=20,
    tags=frozenset({"global"}), simple_width=360.0, settings_key="clock",
)
