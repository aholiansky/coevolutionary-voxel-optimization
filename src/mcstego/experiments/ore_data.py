from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

EXPECTED_COLUMNS = (
    "Y",
    "Stone",
    "Ore",
    "ScannedArea",
    "Prob_Raw",
    "Density_Raw",
    "Prob_Smooth",
    "Density_Smooth",
)


@dataclass(frozen=True, slots=True)
class OreStatsRow:
    y: int
    stone: int
    ore: int
    scanned_area: int
    probability_raw: float
    density_raw: float
    probability_smooth: float
    density_smooth: float

    @property
    def support(self) -> int:
        return self.stone + self.ore


@dataclass(frozen=True, slots=True)
class LegacyOreValidationReport:
    valid: bool
    row_count: int
    min_y: int | None
    max_y: int | None
    observed_chunk_equivalent: int | None
    total_stone: int
    total_ore: int
    overall_ore_prevalence: float | None
    errors: tuple[str, ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["errors"] = list(self.errors)
        result["warnings"] = list(self.warnings)
        return result


def _load_rows(path: str | Path) -> list[OreStatsRow]:
    with Path(path).open("r", encoding="ascii", newline="") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != EXPECTED_COLUMNS:
            raise ValueError(
                f"Unexpected CSV columns: {reader.fieldnames}; expected {EXPECTED_COLUMNS}"
            )
        rows = [
            OreStatsRow(
                y=int(row["Y"]),
                stone=int(row["Stone"]),
                ore=int(row["Ore"]),
                scanned_area=int(row["ScannedArea"]),
                probability_raw=float(row["Prob_Raw"]),
                density_raw=float(row["Density_Raw"]),
                probability_smooth=float(row["Prob_Smooth"]),
                density_smooth=float(row["Density_Smooth"]),
            )
            for row in reader
        ]
    return rows


def _load_distribution(path: str | Path) -> dict[int, tuple[float, float]]:
    with Path(path).open("r", encoding="utf-8") as stream:
        raw = json.load(stream)
    if not isinstance(raw, dict):
        raise ValueError("Distribution root must be a JSON object")

    distribution: dict[int, tuple[float, float]] = {}
    for raw_y, values in raw.items():
        if not isinstance(values, dict) or "prob" not in values or "stone_density" not in values:
            raise ValueError(f"Invalid distribution record at Y={raw_y}")
        distribution[int(raw_y)] = (float(values["prob"]), float(values["stone_density"]))
    return distribution


def _moving_average_zero_padded(values: list[float], window_size: int = 5) -> list[float]:
    if window_size <= 0 or window_size % 2 == 0:
        raise ValueError("window_size must be a positive odd number")
    radius = window_size // 2
    return [
        sum(
            values[index] if 0 <= index < len(values) else 0.0
            for index in range(i - radius, i + radius + 1)
        )
        / window_size
        for i in range(len(values))
    ]


def validate_legacy_ore_files(
    distribution_path: str | Path,
    raw_stats_path: str | Path,
) -> LegacyOreValidationReport:
    """Validate structure, formulas and legacy five-layer smoothing."""

    errors: list[str] = []
    warnings: list[str] = []

    try:
        rows = _load_rows(raw_stats_path)
    except (KeyError, TypeError, ValueError) as exc:
        return LegacyOreValidationReport(
            False, 0, None, None, None, 0, 0, None, (str(exc),), ()
        )
    try:
        distribution = _load_distribution(distribution_path)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return LegacyOreValidationReport(
            False,
            len(rows),
            min((row.y for row in rows), default=None),
            max((row.y for row in rows), default=None),
            None,
            sum(row.stone for row in rows),
            sum(row.ore for row in rows),
            None,
            (str(exc),),
            (),
        )

    ys = [row.y for row in rows]
    if len(set(ys)) != len(ys):
        errors.append("CSV contains duplicate Y coordinates")
    if ys and ys != list(range(min(ys), max(ys) + 1)):
        errors.append("CSV Y coordinates are not contiguous and ordered")
    if set(distribution) != set(ys):
        errors.append("JSON and CSV contain different Y coordinates")

    for row in rows:
        if min(row.stone, row.ore, row.scanned_area) < 0:
            errors.append(f"Negative count at Y={row.y}")
            continue
        expected_probability = row.ore / row.support if row.support else 0.0
        expected_density = row.support / row.scanned_area if row.scanned_area else 0.0
        if abs(row.probability_raw - expected_probability) > 0.00000051:
            errors.append(f"Prob_Raw does not match counts at Y={row.y}")
        if abs(row.density_raw - expected_density) > 0.00000051:
            errors.append(f"Density_Raw does not match counts at Y={row.y}")

    raw_probabilities = [row.ore / row.support if row.support else 0.0 for row in rows]
    raw_densities = [row.support / row.scanned_area if row.scanned_area else 0.0 for row in rows]
    expected_probabilities = _moving_average_zero_padded(raw_probabilities)
    expected_densities = _moving_average_zero_padded(raw_densities)

    for index, row in enumerate(rows):
        expected_probability = round(expected_probabilities[index], 6)
        expected_density = round(expected_densities[index], 6)
        if row.probability_smooth != expected_probability:
            errors.append(f"Prob_Smooth does not match legacy smoothing at Y={row.y}")
        if row.density_smooth != expected_density:
            errors.append(f"Density_Smooth does not match legacy smoothing at Y={row.y}")
        json_values = distribution.get(row.y)
        if json_values != (row.probability_smooth, row.density_smooth):
            errors.append(f"JSON does not match CSV smoothed values at Y={row.y}")

    by_y = {row.y: row for row in rows}
    bottom_spike = by_y.get(-63)
    if bottom_spike and bottom_spike.ore > 0:
        later_ore_heights = [row.y for row in rows if row.y > -63 and row.ore > 0]
        if later_ore_heights and later_ore_heights[0] - bottom_spike.y > 10:
            warnings.append(
                f"Isolated ore spike at Y=-63 ({bottom_spike.ore} blocks); "
                f"the next non-zero layer is Y={later_ore_heights[0]}. Source world is needed "
                "to determine whether this is natural terrain, prior embedding or another artifact."
            )

    low_support_high_probability = [
        row for row in rows if 0 < row.support < 1_000 and row.probability_raw > 0.05
    ]
    for row in low_support_high_probability:
        warnings.append(
            f"High raw probability at Y={row.y} ({row.probability_raw:.6f}) is based on "
            f"only {row.support} carrier blocks."
        )

    zero_support_smoothed = [
        row.y for row in rows if row.support == 0 and row.probability_smooth > 0
    ]
    if zero_support_smoothed:
        warnings.append(
            "Five-layer smoothing assigns positive probability to layers with zero carrier "
            f"support: {zero_support_smoothed}."
        )

    scan_areas = {row.scanned_area for row in rows}
    chunk_equivalent = None
    if len(scan_areas) == 1:
        only_area = next(iter(scan_areas))
        if only_area % 256 == 0:
            chunk_equivalent = only_area // 256
    else:
        warnings.append("ScannedArea varies between Y layers")

    total_stone = sum(row.stone for row in rows)
    total_ore = sum(row.ore for row in rows)
    total_support = total_stone + total_ore
    return LegacyOreValidationReport(
        valid=not errors,
        row_count=len(rows),
        min_y=min(ys) if ys else None,
        max_y=max(ys) if ys else None,
        observed_chunk_equivalent=chunk_equivalent,
        total_stone=total_stone,
        total_ore=total_ore,
        overall_ore_prevalence=total_ore / total_support if total_support else None,
        errors=tuple(errors),
        warnings=tuple(warnings),
    )
