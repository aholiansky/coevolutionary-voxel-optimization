from __future__ import annotations

from typing import Protocol, runtime_checkable

from mcstego.core.geometry import Bounds, Position


@runtime_checkable
class MutableBlockVolume(Protocol):
    """Minimal carrier interface required by embedding strategies."""

    @property
    def bounds(self) -> Bounds: ...

    def get_block(self, position: Position) -> str: ...

    def set_block(self, position: Position, block_name: str) -> None: ...

