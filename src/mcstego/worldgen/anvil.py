from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from mcstego.worldgen.config import ChunkBounds

REGION_HEADER_BYTES = 4096
SECTOR_BYTES = 4096


def chunk_region_position(chunk_x: int, chunk_z: int) -> tuple[int, int, int, int]:
    """Return region and local coordinates using Minecraft's floor division rules."""

    return chunk_x // 32, chunk_z // 32, chunk_x % 32, chunk_z % 32


def required_region_files(bounds: ChunkBounds) -> tuple[str, ...]:
    regions = {
        (chunk_x // 32, chunk_z // 32) for chunk_x, chunk_z in bounds.coordinates()
    }
    return tuple(f"region/r.{region_x}.{region_z}.mca" for region_x, region_z in sorted(regions))


@dataclass(frozen=True, slots=True)
class RegionScan:
    expected_chunks: int
    present_chunks: int
    missing_chunks: tuple[tuple[int, int], ...]
    invalid_chunks: tuple[tuple[int, int], ...]
    inspected_region_files: tuple[str, ...]

    @property
    def complete(self) -> bool:
        return (
            self.present_chunks == self.expected_chunks
            and not self.missing_chunks
            and not self.invalid_chunks
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "expected_chunks": self.expected_chunks,
            "present_chunks": self.present_chunks,
            "complete": self.complete,
            "missing_chunks": [list(position) for position in self.missing_chunks],
            "invalid_chunks": [list(position) for position in self.invalid_chunks],
            "inspected_region_files": list(self.inspected_region_files),
        }


def _location_entry(header: bytes, local_x: int, local_z: int) -> tuple[int, int]:
    index = local_x + local_z * 32
    start = index * 4
    entry = header[start : start + 4]
    if len(entry) != 4:
        return 0, 0
    sector_offset = int.from_bytes(entry[:3], "big")
    sector_count = entry[3]
    return sector_offset, sector_count


def scan_world_region(world_path: str | Path, bounds: ChunkBounds) -> RegionScan:
    world = Path(world_path)
    by_region: dict[tuple[int, int], list[tuple[int, int, int, int]]] = {}
    for chunk_x, chunk_z in bounds.coordinates():
        region_x, region_z, local_x, local_z = chunk_region_position(chunk_x, chunk_z)
        by_region.setdefault((region_x, region_z), []).append(
            (chunk_x, chunk_z, local_x, local_z)
        )

    present = 0
    missing: list[tuple[int, int]] = []
    invalid: list[tuple[int, int]] = []
    inspected: list[str] = []
    for (region_x, region_z), chunks in sorted(by_region.items()):
        relative = Path("region") / f"r.{region_x}.{region_z}.mca"
        inspected.append(relative.as_posix())
        region_path = world / relative
        if not region_path.is_file():
            missing.extend((chunk_x, chunk_z) for chunk_x, chunk_z, _, _ in chunks)
            continue
        file_size = region_path.stat().st_size
        with region_path.open("rb") as stream:
            header = stream.read(REGION_HEADER_BYTES)
        if len(header) != REGION_HEADER_BYTES:
            invalid.extend((chunk_x, chunk_z) for chunk_x, chunk_z, _, _ in chunks)
            continue
        for chunk_x, chunk_z, local_x, local_z in chunks:
            sector_offset, sector_count = _location_entry(header, local_x, local_z)
            if sector_offset == 0 and sector_count == 0:
                missing.append((chunk_x, chunk_z))
                continue
            if (
                sector_offset < 2
                or sector_count == 0
                or sector_offset * SECTOR_BYTES >= file_size
                or (sector_offset + sector_count) * SECTOR_BYTES > file_size
            ):
                invalid.append((chunk_x, chunk_z))
                continue
            present += 1

    return RegionScan(
        expected_chunks=bounds.expected_chunks,
        present_chunks=present,
        missing_chunks=tuple(sorted(missing)),
        invalid_chunks=tuple(sorted(invalid)),
        inspected_region_files=tuple(inspected),
    )


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def world_artifact_hashes(
    world_path: str | Path,
    bounds: ChunkBounds,
) -> dict[str, str]:
    world = Path(world_path)
    relative_paths = [Path("level.dat")]
    relative_paths.extend(Path(path) for path in required_region_files(bounds))
    hashes: dict[str, str] = {}
    for relative in relative_paths:
        target = world / relative
        if not target.is_file():
            raise FileNotFoundError(f"Missing world artifact: {target}")
        hashes[relative.as_posix()] = sha256_file(target)
    return hashes
