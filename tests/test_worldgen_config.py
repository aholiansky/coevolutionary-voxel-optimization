from __future__ import annotations

import unittest
from pathlib import Path

from mcstego.worldgen.config import ChunkBounds, load_worldgen_config
from mcstego.worldgen.runtime import render_server_properties

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class WorldgenConfigTests(unittest.TestCase):
    def test_shipped_pilot_configuration_is_frozen(self) -> None:
        config = load_worldgen_config(PROJECT_ROOT / "config" / "worldgen.json")

        self.assertEqual(config.cohort_id, "pilot-mc-1.21.5-v1")
        self.assertEqual(config.toolchain.minecraft_version, "1.21.5")
        self.assertEqual(config.toolchain.java_major, 21)
        self.assertEqual(config.toolchain.fabric_loader_version, "0.16.10")
        self.assertEqual(config.toolchain.fabric_api_version, "0.119.5+1.21.5")
        self.assertEqual(config.toolchain.chunky_version, "1.4.36")
        self.assertEqual(config.split_counts, {"train": 8, "validation": 2, "test": 3})
        self.assertEqual(config.bounds, ChunkBounds(-16, 15, -16, 15))
        self.assertEqual(config.bounds.expected_chunks, 1024)
        self.assertEqual(
            (
                config.bounds.min_block_x,
                config.bounds.max_block_x,
                config.bounds.min_block_z,
                config.bounds.max_block_z,
            ),
            (-256, 255, -256, 255),
        )

    def test_server_properties_are_deterministic_and_override_dynamic_fields(self) -> None:
        config = load_worldgen_config(PROJECT_ROOT / "config" / "worldgen.json")
        first = render_server_properties(config, -123, "mcstego_working_world")
        second = render_server_properties(config, -123, "mcstego_working_world")

        self.assertEqual(first, second)
        self.assertIn("level-name=mcstego_working_world\n", first)
        self.assertIn("level-seed=-123\n", first)
        self.assertIn("level-type=minecraft:normal\n", first)
        self.assertIn("generate-structures=true\n", first)
        self.assertEqual(first.splitlines(), sorted(first.splitlines()))


if __name__ == "__main__":
    unittest.main()
