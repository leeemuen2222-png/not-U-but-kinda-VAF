from ._model import ModuleDefinition
MODULE = ModuleDefinition(
    module_type="global_anchor_roi", category_key="global", label="仅识别锚点",
    description="以锚点为中心限制 Recognition Engine 的全局视野。",
    palette_order=10,
    tags=frozenset({"global"}), simple_width=690.0,
    simple_controls="global_anchor", settings_key="global_anchor",
)
