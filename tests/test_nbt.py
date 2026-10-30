from __future__ import annotations

import gzip
import struct
import tempfile
import unittest
from pathlib import Path

from mcstego.worldgen.nbt import read_level_metadata, read_nbt_bytes


def _name(value: str) -> bytes:
    encoded = value.encode("utf-8")
    return struct.pack(">H", len(encoded)) + encoded


def _tag(tag_type: int, name: str, payload: bytes) -> bytes:
    return bytes([tag_type]) + _name(name) + payload


def _string(value: str) -> bytes:
    return _name(value)


class NbtTests(unittest.TestCase):
    def test_reads_uncompressed_nbt_bytes(self) -> None:
        document = _tag(10, "root", _tag(3, "answer", struct.pack(">i", 42)) + b"\x00")

        name, root = read_nbt_bytes(document)

        self.assertEqual(name, "root")
        self.assertEqual(root, {"answer": 42})

    def test_reads_modern_level_dat_provenance(self) -> None:
        version = (
            _tag(8, "Name", _string("1.21.5"))
            + _tag(3, "Id", struct.pack(">i", 4321))
            + b"\x00"
        )
        worldgen = _tag(4, "seed", struct.pack(">q", -123456789)) + b"\x00"
        data = (
            _tag(8, "LevelName", _string("mcstego_working_world"))
            + _tag(10, "Version", version)
            + _tag(10, "WorldGenSettings", worldgen)
            + b"\x00"
        )
        document = _tag(10, "", _tag(10, "Data", data) + b"\x00")

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "level.dat"
            with gzip.open(path, "wb") as stream:
                stream.write(document)
            metadata = read_level_metadata(path)

        self.assertEqual(metadata.seed, -123456789)
        self.assertEqual(metadata.minecraft_version, "1.21.5")
        self.assertEqual(metadata.data_version, 4321)
        self.assertEqual(metadata.level_name, "mcstego_working_world")


if __name__ == "__main__":
    unittest.main()
