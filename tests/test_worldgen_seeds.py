from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from mcstego.worldgen.seeds import (
    COMMITMENT_DOMAIN,
    PrivateTestEntry,
    entries_for_split,
    load_private_test_registry,
    load_public_registry,
    test_seed_commitment,
    unlock_test_entries,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class WorldgenSeedTests(unittest.TestCase):
    def test_shipped_public_registry_has_disjoint_expected_splits(self) -> None:
        registry = load_public_registry(
            PROJECT_ROOT / "config" / "seeds.public.json",
            expected_cohort_id="pilot-mc-1.21.5-v1",
            expected_counts={"train": 8, "validation": 2, "test": 3},
        )

        public_seeds = [entry.seed for entry in registry.train + registry.validation]
        self.assertEqual(len(public_seeds), len(set(public_seeds)))
        self.assertEqual(entries_for_split(registry, "train"), registry.train)
        self.assertEqual(entries_for_split(registry, "validation"), registry.validation)
        with self.assertRaises(PermissionError):
            entries_for_split(registry, "test")

    def test_private_file_must_match_public_commitments(self) -> None:
        private_entry = PrivateTestEntry(
            id="test-001",
            seed=-42,
            nonce_hex="ab" * 32,
        )
        public_data = {
            "schema_version": 1,
            "cohort_id": "synthetic-cohort",
            "commitment_scheme": COMMITMENT_DOMAIN,
            "train": [{"id": "train-001", "seed": 1}],
            "validation": [{"id": "validation-001", "seed": 2}],
            "test": [
                {
                    "id": "test-001",
                    "commitment_sha256": test_seed_commitment(private_entry),
                }
            ],
        }
        private_data = {
            "schema_version": 1,
            "cohort_id": "synthetic-cohort",
            "test": [
                {
                    "id": private_entry.id,
                    "seed": private_entry.seed,
                    "nonce_hex": private_entry.nonce_hex,
                }
            ],
        }

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            public_path = root / "public.json"
            private_path = root / "private.json"
            public_path.write_text(json.dumps(public_data), encoding="utf-8")
            private_path.write_text(json.dumps(private_data), encoding="utf-8")
            public = load_public_registry(public_path)
            private = load_private_test_registry(private_path)

            self.assertEqual(unlock_test_entries(public, private)[0].seed, -42)

            private_data["test"][0]["seed"] = -43
            private_path.write_text(json.dumps(private_data), encoding="utf-8")
            altered = load_private_test_registry(private_path)
            with self.assertRaisesRegex(ValueError, "Commitment mismatch"):
                unlock_test_entries(public, altered)


if __name__ == "__main__":
    unittest.main()
