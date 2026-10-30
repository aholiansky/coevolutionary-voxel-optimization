from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Mapping

from mcstego.core.geometry import Position, spiral_positions_in_bounds
from mcstego.core.volume import MutableBlockVolume

VALID_BLOCKS = frozenset(
    {
        "stone",
        "deepslate",
        "andesite",
        "diorite",
        "granite",
        "tuff",
        "coal_ore",
        "deepslate_coal_ore",
    }
)
COAL_BLOCKS = frozenset({"coal_ore", "deepslate_coal_ore"})


class CapacityError(RuntimeError):
    """The carrier does not contain enough deterministic B0 slots."""


def deterministic_hash(x: int, y: int, z: int) -> float:
    """Coordinate hash retained byte-for-byte from the engineering baseline."""

    value = (x * 374_761_393) ^ (y * 668_265_263) ^ (z * 432_352_741)
    value = (value ^ (value >> 13)) * 1_274_126_177
    return (value & 0xFFFFFFF) / 0xFFFFFFF


@dataclass(frozen=True, slots=True)
class ProbabilityModel:
    probabilities: Mapping[int, float]
    fallback: float = 0.005

    def __post_init__(self) -> None:
        if not 0.0 <= self.fallback <= 1.0:
            raise ValueError("fallback must be in [0, 1]")
        for y, probability in self.probabilities.items():
            if not isinstance(y, int):
                raise TypeError("probability model keys must be integer Y coordinates")
            if not 0.0 <= probability <= 1.0:
                raise ValueError(f"probability at Y={y} is outside [0, 1]")

    def get_probability(self, y: int) -> float:
        return float(self.probabilities.get(y, self.fallback))

    @classmethod
    def from_json(cls, path: str | Path, *, fallback: float = 0.005) -> ProbabilityModel:
        with Path(path).open("r", encoding="utf-8") as stream:
            raw = json.load(stream)
        probabilities = {
            int(y): float(value["prob"] if isinstance(value, dict) else value)
            for y, value in raw.items()
        }
        return cls(probabilities, fallback=fallback)


@dataclass(frozen=True, slots=True)
class B0Config:
    density_multiplier: float = 1.0
    center_x: int = 0
    center_z: int = 0

    def __post_init__(self) -> None:
        if self.density_multiplier < 0:
            raise ValueError("density_multiplier cannot be negative")


@dataclass(frozen=True, slots=True)
class Mutation:
    position: Position
    bit: int
    before: str
    after: str


@dataclass(frozen=True, slots=True)
class EmbeddingResult:
    requested_bits: int
    written_bits: int
    positions: tuple[Position, ...]
    mutations: tuple[Mutation, ...]

    @property
    def changed_blocks(self) -> int:
        return len(self.mutations)


def _normalise_bits(bits: str | Iterable[int]) -> tuple[int, ...]:
    if isinstance(bits, str):
        if set(bits) - {"0", "1"}:
            raise ValueError("bit string may contain only '0' and '1'")
        return tuple(int(bit) for bit in bits)

    normalised = tuple(int(bit) for bit in bits)
    if any(bit not in (0, 1) for bit in normalised):
        raise ValueError("bits may contain only 0 and 1")
    return normalised


class B0Strategy:
    """Historical probabilistic baseline, detached from Minecraft I/O."""

    def __init__(self, model: ProbabilityModel, config: B0Config | None = None) -> None:
        self.model = model
        self.config = config or B0Config()

    def iter_candidate_positions(self, volume: MutableBlockVolume) -> Iterator[Position]:
        bounds = volume.bounds
        for y in range(bounds.min_y, bounds.max_y + 1):
            probability = min(
                1.0,
                self.model.get_probability(y) * self.config.density_multiplier,
            )
            if probability <= 0.0:
                continue

            positions = spiral_positions_in_bounds(
                bounds,
                center_x=self.config.center_x,
                center_z=self.config.center_z,
                y=y,
            )
            for position in positions:
                if deterministic_hash(position.x, position.y, position.z) >= probability:
                    continue
                if volume.get_block(position) in VALID_BLOCKS:
                    yield position

    def plan(self, volume: MutableBlockVolume, bit_count: int) -> tuple[Position, ...]:
        if bit_count < 0:
            raise ValueError("bit_count cannot be negative")
        if bit_count == 0:
            return ()

        selected: list[Position] = []
        for position in self.iter_candidate_positions(volume):
            selected.append(position)
            if len(selected) == bit_count:
                break
        return tuple(selected)

    def embed(
        self,
        volume: MutableBlockVolume,
        bits: str | Iterable[int],
        *,
        strict: bool = True,
    ) -> EmbeddingResult:
        payload = _normalise_bits(bits)
        positions = self.plan(volume, len(payload))

        if strict and len(positions) != len(payload):
            raise CapacityError(
                f"B0 capacity is {len(positions)} bits, payload requires {len(payload)} bits"
            )

        mutations: list[Mutation] = []
        for bit, position in zip(payload, positions, strict=False):
            before = volume.get_block(position)
            is_deep = "deepslate" in before or position.y < 0
            if bit:
                after = "deepslate_coal_ore" if is_deep else "coal_ore"
            else:
                after = "deepslate" if is_deep else "stone"

            if before != after:
                volume.set_block(position, after)
                mutations.append(Mutation(position, bit, before, after))

        return EmbeddingResult(
            requested_bits=len(payload),
            written_bits=len(positions),
            positions=positions,
            mutations=tuple(mutations),
        )

    def extract(self, volume: MutableBlockVolume, bit_count: int) -> str:
        positions = self.plan(volume, bit_count)
        if len(positions) != bit_count:
            raise CapacityError(
                f"B0 carrier contains {len(positions)} readable bits, expected {bit_count}"
            )
        return "".join(
            "1" if volume.get_block(position) in COAL_BLOCKS else "0"
            for position in positions
        )
