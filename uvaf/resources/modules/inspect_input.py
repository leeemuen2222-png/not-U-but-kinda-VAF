from ._model import ModuleDefinition
MODULE = ModuleDefinition(
    module_type="inspect_input", category_key="debug", label="检测输入",
    description="打印任意输入到控制台并透传。",
    palette_order=10,
)
