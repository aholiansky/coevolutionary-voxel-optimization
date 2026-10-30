from __future__ import annotations

import math
import struct
import tempfile
import unittest
import zlib
from pathlib import Path

from mcstego.voxels.anvil import (
    AnvilWorldReader,
    ChunkFormatError,
    ChunkSection,
    canonical_block_state,
    decode_chunk_nbt,
)


def _name(value: str) -> bytes:
    encoded = value.encode("utf-8")
    return struct.pack(">H", len(encoded)) + encoded


def _tag(tag_type: int, name: str, payload: bytes) -> bytes:
    return bytes([tag_type]) + _name(name) + payload


def _string(value: str) -> bytes:
    return _name(value)


def _signed_long(value: int) -> int:
    return value if value < 1 << 63 else value - (1 << 64)


def _chunk_nbt(chunk_x: int, chunk_z: int, section_y: int = -4) -> bytes:
    air = _tag(8, "Name", _string("minecraft:air")) + b"\x00"
    stone = (
        _tag(8, "Name", _string("minecraft:stone"))
        + _tag(
            10,
            "Properties",
            _tag(8, "axis", _string("y"))
            + _tag(8, "waterlogged", _string("false"))
            + b"\x00",
        )
        + b"\x00"
    )
    palette = struct.pack(">i", 2) + air + stone
    alternating_word = sum(1 << (index * 4) for index in range(1, 16, 2))
    packed = [_signed_long(alternating_word)] * 256
    packed_payload = struct.pack(">i", len(packed)) + b"".join(
        struct.pack(">q", value) for value in packed
    )
    block_states = (
        _tag(9, "palette", bytes([10]) + palette)
        + _tag(12, "data", packed_payload)
        + b"\x00"
    )
    section = (
        _tag(1, "Y", struct.pack(">b", section_y))
        + _tag(10, "block_states", block_states)
        + b"\x00"
    )
    sections = bytes([10]) + struct.pack(">i", 1) + section
    root = (
        _tag(3, "DataVersion", struct.pack(">i", 4325))
        + _tag(3, "xPos", struct.pack(">i", chunk_x))
        + _tag(3, "zPos", struct.pack(">i", chunk_z))
        + _tag(8, "Status", _string("minecraft:full"))
        + _tag(9, "sections", sections)
        + b"\x00"
    )
    return _tag(10, "", root)


def _write_region(world: Path, chunk_x: int, chunk_z: int, raw_nbt: bytes) -> None:
    region_x, region_z = chunk_x // 32, chunk_z // 32
    local_x, local_z = chunk_x % 32, chunk_z % 32
    compressed = zlib.compress(raw_nbt)
    stored = len(compressed) + 1
    sectors = math.ceil((stored + 4) / 4096)
    header = bytearray(8192)
    location_index = (local_x + local_z * 32) * 4
    header[location_index : location_index + 4] = (2).to_bytes(3, "big") + bytes([sectors])
    body = stored.to_bytes(4, "big") + b"\x02" + compressed
    body += b"\x00" * (sectors * 4096 - len(body))
    region = world / "region"
    region.mkdir(parents=True)
    (world / "level.dat").write_bytes(b"placeholder")
    (region / f"r.{region_x}.{region_z}.mca").write_bytes(bytes(header) + body)


class VoxelAnvilTests(unittest.TestCase):
    def test_canonical_block_state_sorts_properties(self) -> None:
        state = canonical_block_state(
            {
                "Name": "minecraft:oak_log",
                "Properties": {"waterlogged": "false", "axis": "y"},
            }
        )
        self.assertEqual(state, "minecraft:oak_log[axis=y,waterlogged=false]")

    def test_decodes_modern_padded_palette_data(self) -> None:
        chunk = decode_chunk_nbt(_chunk_nbt(0, 0), expected_chunk_x=0, expected_chunk_z=0)

        self.assertEqual(chunk.min_block_y, -64)
        self.assertEqual(chunk.block_state(0, -64, 0), "minecraft:air")
        self.assertEqual(
            chunk.block_state(1, -64, 0),
            "minecraft:stone[axis=y,waterlogged=false]",
        )
        self.assertEqual(chunk.block_state(15, -64, 0), "minecraft:stone[axis=y,waterlogged=false]")
        self.assertEqual(chunk.block_state(0, -64, 1), "minecraft:air")

    def test_rejects_out_of_palette_index(self) -> None:
        section = ChunkSection(
            section_y=0,
            palette=("minecraft:air", "minecraft:stone"),
            packed_data=(2,) + (0,) * 255,
        )

        with self.assertRaisesRegex(ChunkFormatError, "exceeds palette size"):
            section.block_state(0, 0, 0)

    def test_reads_negative_chunk_coordinates_from_region(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            world = Path(directory)
            _write_region(world, -1, -1, _chunk_nbt(-1, -1))
            reader = AnvilWorldReader(world)

            self.assertEqual(reader.block_state(-16, -64, -16), "minecraft:air")
            self.assertEqual(
                reader.block_state(-15, -64, -16),
                "minecraft:stone[axis=y,waterlogged=false]",
            )


if __name__ == "__main__":
    unittest.main()
