from __future__ import annotations

import unittest

from mcstego.adapters.memory import InMemoryVolume
from mcstego.core.geometry import Bounds, Position, square_spiral
from mcstego.experiments.metrics import expected_post_embedding_prevalence
from mcstego.strategies.b0 import (
    B0Config,
    B0Strategy,
    CapacityError,
    ProbabilityModel,
    deterministic_hash,
)


class B0Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.bounds = Bounds(-4, 4, -1, 1, -4, 4)
        self.model = ProbabilityModel({-1: 1.0, 0: 1.0, 1: 1.0})
        self.strategy = B0Strategy(self.model)

    def test_spiral_matches_legacy_prefix(self) -> None:
        spiral = square_spiral()
        self.assertEqual(
            [next(spiral) for _ in range(10)],
            [
                (0, 0),
                (1, 0),
                (1, 1),
                (0, 1),
                (-1, 1),
                (-1, 0),
                (-1, -1),
                (0, -1),
                (1, -1),
                (2, -1),
            ],
        )

    def test_hash_retains_known_legacy_values(self) -> None:
        self.assertEqual(deterministic_hash(0, 0, 0), 0.0)
        self.assertAlmostEqual(deterministic_hash(1, 2, 3), 0.4120227151066911)
        self.assertAlmostEqual(deterministic_hash(-5, -1, 8), 0.7842687323103426)

    def test_round_trip_on_memory_volume(self) -> None:
        volume = InMemoryVolume(self.bounds, default_block="stone")
        payload = "1011001010110010"

        result = self.strategy.embed(volume, payload)

        self.assertEqual(result.written_bits, len(payload))
        self.assertEqual(self.strategy.extract(volume, len(payload)), payload)
        self.assertEqual(result.positions[0], Position(0, -1, 0))

    def test_strict_capacity_failure_is_atomic(self) -> None:
        volume = InMemoryVolume(Bounds(0, 0, 0, 0, 0, 0), default_block="stone")

        with self.assertRaises(CapacityError):
            self.strategy.embed(volume, "11")

        self.assertEqual(volume.get_block(Position(0, 0, 0)), "stone")

    def test_empty_payload_does_not_consume_a_slot(self) -> None:
        volume = InMemoryVolume(self.bounds, default_block="stone")
        result = self.strategy.embed(volume, "")
        self.assertEqual(result.positions, ())
        self.assertEqual(result.written_bits, 0)

    def test_invalid_payload_is_rejected(self) -> None:
        volume = InMemoryVolume(self.bounds)
        with self.assertRaises(ValueError):
            self.strategy.embed(volume, "10x01")

    def test_deepslate_variant_is_preserved_below_zero(self) -> None:
        volume = InMemoryVolume(Bounds(0, 0, -1, -1, 0, 0), default_block="stone")
        self.strategy.embed(volume, "1")
        self.assertEqual(volume.get_block(Position(0, -1, 0)), "deepslate_coal_ore")

    def test_historical_density_formula(self) -> None:
        p = 0.02
        actual = expected_post_embedding_prevalence(p, p)
        self.assertAlmostEqual(actual, 1.5 * p - p * p)
        self.assertGreater(actual, p)

    def test_probability_model_rejects_invalid_values(self) -> None:
        with self.assertRaises(ValueError):
            ProbabilityModel({0: 1.1})

    def test_density_multiplier_is_part_of_strategy(self) -> None:
        volume = InMemoryVolume(Bounds(-4, 4, 0, 0, -4, 4))
        no_slots = B0Strategy(
            ProbabilityModel({0: 0.0}, fallback=0.0),
            B0Config(density_multiplier=1.0),
        )
        self.assertEqual(no_slots.plan(volume, 1), ())


if __name__ == "__main__":
    unittest.main()
