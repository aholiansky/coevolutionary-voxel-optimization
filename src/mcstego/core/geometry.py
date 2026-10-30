from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator


@dataclass(frozen=True, order=True, slots=True)
class Position:
    x: int
    y: int
    z: int


@dataclass(frozen=True, slots=True)
class Bounds:
    """Inclusive voxel bounds."""

    min_x: int
    max_x: int
    min_y: int
    max_y: int
    min_z: int
    max_z: int

    def __post_init__(self) -> None:
        if self.min_x > self.max_x or self.min_y > self.max_y or self.min_z > self.max_z:
            raise ValueError("Bounds minimum cannot exceed maximum")

    def contains(self, position: Position) -> bool:
        return (
            self.min_x <= position.x <= self.max_x
            and self.min_y <= position.y <= self.max_y
            and self.min_z <= position.z <= self.max_z
        )

    @property
    def voxel_count(self) -> int:
        return (
            (self.max_x - self.min_x + 1)
            * (self.max_y - self.min_y + 1)
            * (self.max_z - self.min_z + 1)
        )


def square_spiral() -> Iterator[tuple[int, int]]:
    """Yield offsets in the same leg-based square spiral used by legacy B0."""

    x = z = 0
    yield x, z
    leg = 1
    direction = 0
    moves = ((1, 0), (0, 1), (-1, 0), (0, -1))

    while True:
        for _ in range(2):
            dx, dz = moves[direction]
            for _ in range(leg):
                x += dx
                z += dz
                yield x, z
            direction = (direction + 1) % 4
        leg += 1


def spiral_positions_in_bounds(
    bounds: Bounds,
    *,
    center_x: int,
    center_z: int,
    y: int,
) -> Iterator[Position]:
    """Yield every X/Z position in bounds once, in legacy spiral order."""

    max_radius = max(
        abs(bounds.min_x - center_x),
        abs(bounds.max_x - center_x),
        abs(bounds.min_z - center_z),
        abs(bounds.max_z - center_z),
    )
    maximum_steps = (2 * max_radius + 1) ** 2
    yielded = 0

    for x_offset, z_offset in square_spiral():
        if yielded >= maximum_steps:
            return
        yielded += 1
        position = Position(center_x + x_offset, y, center_z + z_offset)
        if bounds.contains(position):
            yield position

