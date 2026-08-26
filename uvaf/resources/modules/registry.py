from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from ._model import CategoryDefinition, ModuleDefinition
from .categories import CATEGORIES


@dataclass(frozen=True)
class ModuleSpec:
    category_key: str
    module_type: str
    label: str
    payload_extra: str = ""


_PACKAGE = __package__
_ROOT = Path(__file__).resolve().parent
_SKIP = {"_model", "registry", "categories", "module_ui", "runtime"}


def _discover_definitions() -> dict[str, ModuleDefinition]:
    result: dict[str, ModuleDefinition] = {}

    # Source/development mode: every .py file dropped into this directory can
    # become a built-in module without editing workspace_page.py.
    for info in pkgutil.iter_modules([str(_ROOT)]):
        name = info.name
        if name.startswith("_") or name in _SKIP:
            continue

        module = importlib.import_module(f"{_PACKAGE}.{name}")
        definition = getattr(module, "MODULE", None)
        if not isinstance(definition, ModuleDefinition):
            continue

        if definition.module_type in result:
            raise RuntimeError(
                f"Duplicate UVAF module type: {definition.module_type}"
            )

        result[definition.module_type] = definition

    return result


MODULES = _discover_definitions()
CATEGORIES_BY_KEY = {category.key: category for category in CATEGORIES}


def get_module_definition(module_type: str) -> ModuleDefinition | None:
    return MODULES.get(str(module_type))


def category_by_key(key: str) -> CategoryDefinition:
    return CATEGORIES_BY_KEY.get(str(key), CATEGORIES[0])


def module_specs_for_category(category_key: str) -> tuple[ModuleSpec, ...]:
    category_key = str(category_key)
    definitions = [
        definition
        for definition in MODULES.values()
        if definition.palette and definition.category_key == category_key
    ]
    # Discovery order follows filenames, but UI ordering should be stable. The
    # labels are only a fallback; explicit category files can later add an
    # order field without touching WorkspacePage.
    definitions.sort(key=lambda definition: definition.label)

    definitions.sort(
        key=lambda definition: (
            definition.palette_order,
            definition.label,
        )
    )

    return tuple(
        ModuleSpec(
            definition.category_key,
            definition.module_type,
            definition.label,
        )
        for definition in definitions
    )


def module_output_type(module_type: str) -> str | None:
    definition = get_module_definition(module_type)
    return definition.output_type if definition is not None else None


def module_input_type(module_type: str) -> str | None:
    definition = get_module_definition(module_type)
    return definition.input_type if definition is not None else None


def data_types_compatible(source_type: str | None, target_type: str | None) -> bool:
    if source_type is None or target_type is None:
        return True
    return source_type == target_type


def _types_with_tag(tag: str) -> frozenset[str]:
    return frozenset(
        definition.module_type
        for definition in MODULES.values()
        if tag in definition.tags
    )


VISUAL_MODULE_TYPES = _types_with_tag("visual")
ACTION_MODULE_TYPES = _types_with_tag("action")
LOGIC_CONTAINER_TYPES = _types_with_tag("logic_container")
CONDITION_LOGIC_TYPES = _types_with_tag("condition_logic")
GLOBAL_MODULE_TYPES = _types_with_tag("global")
EVENT_ROOT_MODULE_TYPES = _types_with_tag("event_root")


def settings_key_for(module_type: str) -> str | None:
    definition = get_module_definition(module_type)
    return definition.settings_key if definition is not None else None


def simple_controls_for(module_type: str) -> str | None:
    definition = get_module_definition(module_type)
    return definition.simple_controls if definition is not None else None


def simple_width_for(module_type: str, default: float = 178.0) -> float:
    definition = get_module_definition(module_type)
    return float(definition.simple_width) if definition is not None else float(default)


def logic_slots_for(module_type: str) -> tuple[str, ...]:
    definition = get_module_definition(module_type)
    return definition.logic_slots if definition is not None else ()


def condition_slots_for(module_type: str) -> tuple[int, ...]:
    definition = get_module_definition(module_type)
    return definition.condition_slots if definition is not None else ()


def complex_ports_for(module_type: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    definition = get_module_definition(module_type)
    if definition is None:
        return (
            ("input", "input_2", "input_3"),
            ("output", "output_2", "output_3"),
        )
    return definition.complex_inputs, definition.complex_outputs
