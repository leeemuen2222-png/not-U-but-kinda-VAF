from __future__ import annotations

from dataclasses import dataclass, field
from typing import FrozenSet, Tuple


STANDARD_COMPLEX_INPUTS = ("input", "input_2", "input_3")
STANDARD_COMPLEX_OUTPUTS = ("output", "output_2", "output_3")


@dataclass(frozen=True)
class CategoryDefinition:
    key: str
    title: str
    description: str
    color: str
    translucent: bool = True
    order: int = 0


@dataclass(frozen=True)
class ModuleDefinition:
    module_type: str
    category_key: str
    label: str
    description: str = ""
    palette: bool = True
    palette_order: int = 1000
    settings_title: str | None = None
    runtime_label: str | None = None

    input_type: str | None = None
    output_type: str | None = None

    tags: FrozenSet[str] = field(default_factory=frozenset)

    # Simple-mode presentation/configuration.
    simple_width: float = 178.0
    simple_controls: str | None = None
    settings_key: str | None = None

    # Logic-container metadata.
    logic_slots: Tuple[str, ...] = ()
    condition_slots: Tuple[int, ...] = ()

    # Complex-mode ports.
    complex_inputs: Tuple[str, ...] = STANDARD_COMPLEX_INPUTS
    complex_outputs: Tuple[str, ...] = STANDARD_COMPLEX_OUTPUTS

    @property
    def is_visual(self) -> bool:
        return "visual" in self.tags

    @property
    def is_action(self) -> bool:
        return "action" in self.tags

    @property
    def is_logic_container(self) -> bool:
        return "logic_container" in self.tags

    @property
    def is_condition_logic(self) -> bool:
        return "condition_logic" in self.tags

    @property
    def is_global(self) -> bool:
        return "global" in self.tags

    @property
    def is_event_root(self) -> bool:
        return "event_root" in self.tags
