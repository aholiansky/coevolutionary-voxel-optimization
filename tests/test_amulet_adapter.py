from __future__ import annotations

import unittest

from mcstego.adapters.amulet import AmuletVolume
from mcstego.core.geometry import Bounds, Position


class FakeBlock:
    def __init__(self, base_name: str) -> None:
        self.base_name = base_name


class FakePalette:
    def __init__(self) -> None:
        self.blocks = [FakeBlock("stone"), FakeBlock("coal_ore")]

    def __getitem__(self, index: int) -> FakeBlock:
        return self.blocks[index]

    def get_add_block(self, block: FakeBlock) -> int:
        for index, existing in enumerate(self.blocks):
            if existing.base_name == block.base_name:
                return index
        self.blocks.append(block)
        return len(self.blocks) - 1


class FakeBlocks:
    def __init__(self) -> None:
        self.values: dict[tuple[int, int, int], int] = {}

    def __getitem__(self, key: tuple[int, int, int]) -> int:
        return self.values.get(key, 0)

    def __setitem__(self, key: tuple[int, int, int], value: int) -> None:
        self.values[key] = value


class FakeChunk:
    def __init__(self) -> None:
        self.blocks = FakeBlocks()
        self.block_palette = FakePalette()
        self.changed = False


class FakeLevel:
    def __init__(self) -> None:
        self.chunks: dict[tuple[int, int], FakeChunk] = {}

    def get_chunk(self, chunk_x: int, chunk_z: int, dimension: str) -> FakeChunk:
        self.assert_dimension = dimension
        return self.chunks.setdefault((chunk_x, chunk_z), FakeChunk())


class AmuletAdapterTests(unittest.TestCase):
    def test_negative_coordinates_use_correct_chunk_and_local_position(self) -> None:
        level = FakeLevel()
        bounds = Bounds(-16, 0, 0, 0, -16, 0)
        volume = AmuletVolume(level, bounds, block_factory=FakeBlock)
        position = Position(-1, 0, -1)

        volume.set_block(position, "coal_ore")

        chunk = level.chunks[(-1, -1)]
        self.assertEqual(chunk.blocks.values[(15, 0, 15)], 1)
        self.assertEqual(volume.get_block(position), "coal_ore")
        self.assertTrue(chunk.changed)

    def test_out_of_bounds_access_is_rejected(self) -> None:
        volume = AmuletVolume(
            FakeLevel(),
            Bounds(0, 0, 0, 0, 0, 0),
            block_factory=FakeBlock,
        )
        with self.assertRaises(IndexError):
            volume.get_block(Position(1, 0, 0))


if __name__ == "__main__":
    unittest.main()

