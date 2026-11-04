from dataclasses import dataclass

from ag_ui.core import BaseEvent


@dataclass(frozen=True, slots=True)
class RenderEvent:
    seq: int
    event: BaseEvent
