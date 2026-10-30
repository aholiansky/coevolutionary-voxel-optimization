from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from mcstego.experiments.manifest import ExperimentManifest


class ManifestTests(unittest.TestCase):
    def test_manifest_records_payload_hash_and_refuses_overwrite(self) -> None:
        payload = b"research payload"
        manifest = ExperimentManifest.create(
            strategy="B0",
            strategy_config={"density_multiplier": 1.0},
            carrier_id="seed=123/region=0,0",
            payload=payload,
            random_seed=123,
            source_revision="deadbeef",
        )

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            manifest.save(path)
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["payload_sha256"], hashlib.sha256(payload).hexdigest())
            self.assertEqual(saved["strategy"], "B0")
            with self.assertRaises(FileExistsError):
                manifest.save(path)


if __name__ == "__main__":
    unittest.main()

