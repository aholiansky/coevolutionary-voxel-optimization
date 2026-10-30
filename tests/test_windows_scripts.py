from pathlib import Path
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class WindowsScriptCompatibilityTests(unittest.TestCase):
    def test_powershell_entrypoints_are_ascii_safe(self) -> None:
        scripts = sorted((PROJECT_ROOT / "windows").rglob("*.ps1"))
        self.assertTrue(scripts)
        for script in scripts:
            try:
                script.read_bytes().decode("ascii")
            except UnicodeDecodeError as exc:
                self.fail(
                    f"{script.relative_to(PROJECT_ROOT)} is not ASCII-safe for "
                    f"Windows PowerShell 5.1: {exc}"
                )


if __name__ == "__main__":
    unittest.main()
