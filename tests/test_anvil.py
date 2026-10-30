from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from mcstego.worldgen.anvil import (
    SECTOR_BYTES,
    chunk_region_position,
    scan_world_region,
)
from mcstego.worldgen.config import ChunkBounds


def _write_region(path: Path, chunks: list[tuple[int, int]]) -> None:
    data = bytearray((2 + len(chunks)) * SECTOR_BYTES)
    for number, (local_x, local_z) in enumerate(chunks, start=2):
        index = local_x + local_z * 32
        start = index * 4
        data[start : start + 3] = number.to_bytes(3, "big")
        data[start + 3] = 1
        data[number * SECTOR_BYTES : number * SECTOR_BYTES + 5] = b"chunk"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


class AnvilRegionTests(unittest.TestCase):
    def test_negative_chunk_coordinates_use_floor_division(self) -> None:
        self.assertEqual(chunk_region_position(-1, -1), (-1, -1, 31, 31))
        self.assertEqual(chunk_region_position(-32, -32), (-1, -1, 0, 0))
        self.assertEqual(chunk_region_position(-33, -33), (-2, -2, 31, 31))

    def test_scan_requires_every_chunk_in_the_target_rectangle(self) -> None:
        bounds = ChunkBounds(0, 1, 0, 1)
        with tempfile.TemporaryDirectory() as directory:
            world = Path(directory)
            region = world / "region" / "r.0.0.mca"
            _write_region(region, [(0, 0), (1, 0), (0, 1), (1, 1)])

            complete = scan_world_region(world, bounds)
            self.assertTrue(complete.complete)
            self.assertEqual(complete.present_chunks, 4)

            data = bytearray(region.read_bytes())
            missing_index = 1 + 1 * 32
            data[missing_index * 4 : missing_index * 4 + 4] = b"\x00\x00\x00\x00"
            region.write_bytes(data)
            incomplete = scan_world_region(world, bounds)
            self.assertFalse(incomplete.complete)
            self.assertEqual(incomplete.missing_chunks, ((1, 1),))

    def test_scan_rejects_location_pointing_outside_region_file(self) -> None:
        bounds = ChunkBounds(0, 0, 0, 0)
        with tempfile.TemporaryDirectory() as directory:
            world = Path(directory)
            region = world / "region" / "r.0.0.mca"
            _write_region(region, [(0, 0)])
            data = bytearray(region.read_bytes())
            data[0:3] = (200).to_bytes(3, "big")
            region.write_bytes(data)

            scan = scan_world_region(world, bounds)
            self.assertFalse(scan.complete)
            self.assertEqual(scan.invalid_chunks, ((0, 0),))


if __name__ == "__main__":
    unittest.main()
