from __future__ import annotations

from dataclasses import dataclass, field

from mcstego.core.geometry import Bounds, Position


@dataclass(slots=True)
class InMemoryVolume:
    """Finite carrier with a uniform base block and sparse modifications."""

    bounds: Bounds
    default_block: str = "stone"
    overrides: dict[Position, str] = field(default_factory=dict)

    def get_block(self, position: Position) -> str:
        if not self.bounds.contains(position):
            raise IndexError(f"Position outside volume: {position}")
        return self.overrides.get(position, self.default_block)

    def set_block(self, position: Position, block_name: str) -> None:
        if not self.bounds.contains(position):
            raise IndexError(f"Position outside volume: {position}")
        if block_name == self.default_block:
            self.overrides.pop(position, None)
        else:
            self.overrides[position] = block_name

    def clone(self) -> InMemoryVolume:
        return InMemoryVolume(self.bounds, self.default_block, dict(self.overrides))

    def count(self, block_names: set[str] | frozenset[str]) -> int:
        """Count matching blocks without materialising the full dense volume."""

        default_count = self.bounds.voxel_count if self.default_block in block_names else 0
        for block in self.overrides.values():
            if self.default_block in block_names:
                if block not in block_names:
                    default_count -= 1
            elif block in block_names:
                default_count += 1
        return default_count

