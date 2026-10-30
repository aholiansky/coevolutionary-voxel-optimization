from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from mcstego.voxels.cube import extract_cube, load_cube, write_cube


class _FakeReader:
    def iter_block_states(self, origin, shape, *, mode="full"):
        del origin, shape, mode
        yield from (
            "minecraft:stone",
            "minecraft:air",
            "minecraft:coal_ore",
            "minecraft:stone",
            "minecraft:air",
            "minecraft:coal_ore",
            "minecraft:stone",
            "minecraft:air",
        )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class VoxelCubeTests(unittest.TestCase):
    def test_axis_order_palette_and_round_trip(self) -> None:
        cube = extract_cube(
            _FakeReader(),  # type: ignore[arg-type]
            origin=(-4, -64, 8),
            shape=(2, 2, 2),
            source={"world_id": "train-001"},
        )
        self.assertEqual(
            cube.palette,
            ("minecraft:air", "minecraft:coal_ore", "minecraft:stone"),
        )
        self.assertEqual(cube.block_state(0, 0, 0), "minecraft:stone")
        self.assertEqual(cube.block_state(0, 0, 1), "minecraft:air")
        self.assertEqual(cube.block_state(1, 1, 1), "minecraft:air")

        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "first.mcvx"
            second = Path(directory) / "second.mcvx"
            write_cube(first, cube)
            write_cube(second, cube)
            restored = load_cube(first)

            self.assertEqual(_sha256(first), _sha256(second))
            self.assertEqual(restored, cube)

    def test_refuses_implicit_overwrite(self) -> None:
        cube = extract_cube(
            _FakeReader(),  # type: ignore[arg-type]
            origin=(0, 0, 0),
            shape=(2, 2, 2),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cube.mcvx"
            write_cube(path, cube)
            with self.assertRaises(FileExistsError):
                write_cube(path, cube)


if __name__ == "__main__":
    unittest.main()
