from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from mcstego.worldgen.config import load_worldgen_config
from mcstego.worldgen.runtime import bootstrap_runtime

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _fake_download(url: str, target: str | Path) -> Path:
    destination = Path(target)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w") as archive:
        if "Chunky" in destination.name:
            archive.writestr(
                "fabric.mod.json",
                json.dumps({"id": "chunky", "version": "1.4.36"}),
            )
        elif "fabric-api" in destination.name:
            archive.writestr(
                "fabric.mod.json",
                json.dumps({"id": "fabric-api", "version": "0.119.5+1.21.5"}),
            )
        else:
            archive.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\n")
    return destination


class WorldgenRuntimeTests(unittest.TestCase):
    def test_bootstrap_downloads_locks_and_copies_exact_toolchain(self) -> None:
        config = load_worldgen_config(PROJECT_ROOT / "config" / "worldgen.json")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch("mcstego.worldgen.runtime.download_file", side_effect=_fake_download):
                result = bootstrap_runtime(config, root, accept_eula=True)

            self.assertTrue(result.launcher_path.is_file())
            self.assertTrue(result.fabric_api_path.is_file())
            self.assertTrue(result.chunky_path.is_file())
            self.assertIn("eula=true", (result.server_directory / "eula.txt").read_text())
            lock = json.loads(result.lock_path.read_text(encoding="utf-8"))
            self.assertEqual(
                set(lock["artifacts"]),
                {"fabric_server", "fabric_api", "chunky"},
            )
            self.assertTrue(
                all(len(artifact["sha256"]) == 64 for artifact in lock["artifacts"].values())
            )

            with patch("mcstego.worldgen.runtime.download_file") as download:
                second = bootstrap_runtime(config, root)
            download.assert_not_called()
            self.assertEqual(second.lock_path, result.lock_path)


if __name__ == "__main__":
    unittest.main()
