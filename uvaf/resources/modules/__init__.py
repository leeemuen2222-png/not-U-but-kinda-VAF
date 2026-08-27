"""UVAF built-in module registry.

Each built-in module lives in its own Python file in this directory. The
workspace imports metadata from this package instead of maintaining a second
hard-coded module catalog inside ``workspace_page.py``.
"""

from ._model import CategoryDefinition as BlockCategory, ModuleDefinition
from .registry import (
    ACTION_MODULE_TYPES,
    CATEGORIES,
    CONDITION_LOGIC_TYPES,
    EVENT_ROOT_MODULE_TYPES,
    GLOBAL_MODULE_TYPES,
    LOGIC_CONTAINER_TYPES,
    MODULES,
    VISUAL_MODULE_TYPES,
    ModuleSpec,
    category_by_key,
    complex_ports_for,
    complex_input_hints_for,
    condition_slots_for,
    data_types_compatible,
    get_module_definition,
    logic_slots_for,
    module_input_type,
    module_output_type,
    module_specs_for_category,
    settings_key_for,
    simple_controls_for,
    simple_width_for,
)

__all__ = [
    "ACTION_MODULE_TYPES",
    "BlockCategory",
    "CATEGORIES",
    "CONDITION_LOGIC_TYPES",
    "EVENT_ROOT_MODULE_TYPES",
    "GLOBAL_MODULE_TYPES",
    "LOGIC_CONTAINER_TYPES",
    "MODULES",
    "ModuleDefinition",
    "ModuleSpec",
    "VISUAL_MODULE_TYPES",
    "category_by_key",
    "complex_ports_for",
    "complex_input_hints_for",
    "condition_slots_for",
    "data_types_compatible",
    "get_module_definition",
    "logic_slots_for",
    "module_input_type",
    "module_output_type",
    "module_specs_for_category",
    "settings_key_for",
    "simple_controls_for",
    "simple_width_for",
]
