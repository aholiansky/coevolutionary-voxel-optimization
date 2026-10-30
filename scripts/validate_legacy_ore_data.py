from __future__ import annotations

import json
from pathlib import Path

from mcstego.experiments.ore_data import validate_legacy_ore_files


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    data_directory = project_root / "data" / "legacy"
    report = validate_legacy_ore_files(
        data_directory / "ore_distribution.json",
        data_directory / "ore_stats_raw.csv",
    )
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    return 0 if report.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())

