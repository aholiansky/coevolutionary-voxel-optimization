from __future__ import annotations

import hashlib
import unittest
from pathlib import Path

from mcstego.experiments.ore_data import validate_legacy_ore_files
from mcstego.strategies.b0 import ProbabilityModel


class LegacyOreDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data_directory = Path(__file__).resolve().parents[1] / "data" / "legacy"
        cls.distribution_path = cls.data_directory / "ore_distribution.json"
        cls.raw_stats_path = cls.data_directory / "ore_stats_raw.csv"

    def test_source_files_are_bit_exact(self) -> None:
        self.assertEqual(
            hashlib.sha256(self.distribution_path.read_bytes()).hexdigest(),
            "a35a7636d270138e9222d170467a2abb951cd1f96a76ae4e033afbd4f58002a3",
        )
        self.assertEqual(
            hashlib.sha256(self.raw_stats_path.read_bytes()).hexdigest(),
            "39743c820569b81bc1a5f16f7840f6710bb763ce3de52cb010ed6698817d51bb",
        )

    def test_json_and_csv_are_mathematically_consistent(self) -> None:
        report = validate_legacy_ore_files(self.distribution_path, self.raw_stats_path)
        self.assertTrue(report.valid, report.errors)
        self.assertEqual(report.row_count, 384)
        self.assertEqual((report.min_y, report.max_y), (-64, 319))
        self.assertEqual(report.observed_chunk_equivalent, 9_489)
        self.assertEqual(report.total_ore, 471_281)
        self.assertEqual(report.errors, ())
        self.assertGreaterEqual(len(report.warnings), 3)

    def test_probability_model_loads_legacy_distribution(self) -> None:
        model = ProbabilityModel.from_json(self.distribution_path)
        self.assertEqual(model.get_probability(-64), 0.002895)
        self.assertEqual(model.get_probability(113), 0.025531)
        self.assertEqual(model.get_probability(319), 0.0)


if __name__ == "__main__":
    unittest.main()

