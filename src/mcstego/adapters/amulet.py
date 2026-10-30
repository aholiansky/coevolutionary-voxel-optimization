from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from mcstego.core.geometry import Bounds, Position


def _default_block_factory(block_name: str) -> Any:
    try:
        import amulet
    except ImportError as exc:  # pragma: no cover - depends on optional package
        raise RuntimeError(
            "Amulet adapter requires the optional 'amulet-core' dependency"
        ) from exc
    return amulet.Block.from_string_blockstate(f"minecraft:{block_name}")


@dataclass(slots=True)
class AmuletVolume:
    """Bounded view over an already opened Amulet level."""

    level: Any
    bounds: Bounds
    dimension: str = "minecraft:overworld"
    block_factory: Callable[[str], Any] = field(default=_default_block_factory, repr=False)

    def _chunk_and_local(self, position: Position) -> tuple[Any, int, int]:
        if not self.bounds.contains(position):
            raise IndexError(f"Position outside volume: {position}")
        chunk = self.level.get_chunk(position.x >> 4, position.z >> 4, self.dimension)
        return chunk, position.x % 16, position.z % 16

    def get_block(self, position: Position) -> str:
        chunk, local_x, local_z = self._chunk_and_local(position)
        block_id = chunk.blocks[local_x, position.y, local_z]
        return chunk.block_palette[block_id].base_name

    def set_block(self, position: Position, block_name: str) -> None:
        chunk, local_x, local_z = self._chunk_and_local(position)
        block = self.block_factory(block_name)
        block_id = chunk.block_palette.get_add_block(block)
        chunk.blocks[local_x, position.y, local_z] = block_id
        chunk.changed = True


@contextmanager
def open_amulet_world(
    world_path: str,
    bounds: Bounds,
    *,
    dimension: str = "minecraft:overworld",
    save: bool = False,
) -> Iterator[AmuletVolume]:
    """Open and always close a world; saving must be explicitly requested."""

    try:
        import amulet
    except ImportError as exc:  # pragma: no cover - depends on optional package
        raise RuntimeError(
            "Opening a Minecraft world requires the optional 'amulet-core' dependency"
        ) from exc

    level = amulet.load_level(world_path)
    try:
        yield AmuletVolume(level, bounds, dimension)
        if save:
            level.save()
    finally:
        level.close()

