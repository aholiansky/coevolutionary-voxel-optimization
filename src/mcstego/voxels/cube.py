from __future__ import annotations

import hashlib
import json
import os
import struct
import tempfile
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Iterator

from mcstego.voxels.anvil import AIR, AnvilWorldReader
from mcstego.worldgen.anvil import sha256_file
from mcstego.worldgen.nbt import read_level_metadata

FORMAT_NAME = "mcstego-voxel-cube"
SCHEMA_VERSION = 1
METADATA_NAME = "metadata.json"
PALETTE_NAME = "palette.json"
VOXELS_NAME = "voxels.u16le"
ARCHIVE_ENTRIES = (METADATA_NAME, PALETTE_NAME, VOXELS_NAME)
MAX_VOXELS = 16_777_216
MAX_METADATA_BYTES = 1024 * 1024
MAX_PALETTE_BYTES = 16 * 1024 * 1024
FIXED_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


class VoxelFormatError(ValueError):
    """Raised when source provenance or an MCVX artifact is invalid."""


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _json_object(data: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VoxelFormatError(f"Invalid {label} JSON") from exc
    if not isinstance(value, dict):
        raise VoxelFormatError(f"{label} must be a JSON object")
    return value


def _safe_world_artifact(world: Path, name: str) -> Path:
    relative = PurePosixPath(name)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise VoxelFormatError(f"Unsafe artifact path in world manifest: {name!r}")
    target = world.joinpath(*relative.parts).resolve()
    if not target.is_relative_to(world):
        raise VoxelFormatError(f"Artifact escapes the world directory: {name!r}")
    return target


def verify_world_source(world_path: str | Path) -> dict[str, Any]:
    """Verify a generated immutable cover and return its manifest."""

    world = Path(world_path).resolve()
    manifest_path = world / "mcstego-world-manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Missing world manifest: {manifest_path}")
    manifest_bytes = manifest_path.read_bytes()
    manifest = _json_object(manifest_bytes, "world manifest")
    if manifest.get("schema_version") != 1:
        raise VoxelFormatError("Unsupported world manifest schema")
    if manifest.get("immutable_cover") is not True:
        raise VoxelFormatError("Voxel import requires a manifest marked immutable_cover=true")
    if not isinstance(manifest.get("world_id"), str) or not manifest["world_id"]:
        raise VoxelFormatError("World manifest contains no valid world_id")
    if not isinstance(manifest.get("cohort_id"), str) or not manifest["cohort_id"]:
        raise VoxelFormatError("World manifest contains no valid cohort_id")
    if manifest.get("split") not in {"train", "validation", "test"}:
        raise VoxelFormatError("World manifest contains an invalid split")
    if isinstance(manifest.get("seed"), bool) or not isinstance(manifest.get("seed"), int):
        raise VoxelFormatError("World manifest contains no valid seed")
    generation = manifest.get("generation")
    region_scan = manifest.get("region_scan")
    if not isinstance(generation, dict) or generation.get("status") != "complete":
        raise VoxelFormatError("World manifest does not describe completed generation")
    if not isinstance(region_scan, dict) or region_scan.get("complete") is not True:
        raise VoxelFormatError("World manifest does not describe a complete region scan")
    artifacts = manifest.get("artifact_sha256")
    if not isinstance(artifacts, dict) or not artifacts:
        raise VoxelFormatError("World manifest contains no artifact hashes")
    for name, expected_hash in sorted(artifacts.items()):
        if not isinstance(name, str) or not isinstance(expected_hash, str):
            raise VoxelFormatError("Invalid artifact hash entry in world manifest")
        invalid_hash = len(expected_hash) != 64 or any(
            character not in "0123456789abcdef" for character in expected_hash
        )
        if invalid_hash:
            raise VoxelFormatError(f"Invalid SHA-256 value for {name}")
        target = _safe_world_artifact(world, name)
        if not target.is_file():
            raise FileNotFoundError(f"Missing immutable cover artifact: {target}")
        actual_hash = sha256_file(target)
        if actual_hash != expected_hash:
            raise VoxelFormatError(
                f"Immutable cover hash mismatch for {name}: {actual_hash} != {expected_hash}"
            )

    level = read_level_metadata(world / "level.dat")
    if level.seed != manifest.get("seed"):
        raise VoxelFormatError("level.dat seed does not match the world manifest")
    minecraft = manifest.get("minecraft")
    if not isinstance(minecraft, dict):
        raise VoxelFormatError("World manifest contains no Minecraft metadata")
    if level.minecraft_version != minecraft.get("version"):
        raise VoxelFormatError("level.dat version does not match the world manifest")
    if level.data_version != minecraft.get("data_version"):
        raise VoxelFormatError("level.dat data version does not match the world manifest")
    manifest["_manifest_sha256"] = _sha256_bytes(manifest_bytes)
    return manifest


def source_metadata(manifest: dict[str, Any]) -> dict[str, Any]:
    minecraft = manifest.get("minecraft")
    artifacts = manifest.get("artifact_sha256")
    if not isinstance(minecraft, dict) or not isinstance(artifacts, dict):
        raise VoxelFormatError("Incomplete verified world manifest")
    return {
        "artifact_sha256": dict(sorted(artifacts.items())),
        "cohort_id": manifest.get("cohort_id"),
        "manifest": "mcstego-world-manifest.json",
        "manifest_sha256": manifest.get("_manifest_sha256"),
        "minecraft": {
            "data_version": minecraft.get("data_version"),
            "edition": minecraft.get("edition"),
            "version": minecraft.get("version"),
        },
        "seed": manifest.get("seed"),
        "split": manifest.get("split"),
        "world_id": manifest.get("world_id"),
    }


def _positive_triplet(value: object, label: str) -> tuple[int, int, int]:
    if not isinstance(value, list) or len(value) != 3:
        raise VoxelFormatError(f"{label} must contain exactly three integers")
    if any(isinstance(item, bool) or not isinstance(item, int) for item in value):
        raise VoxelFormatError(f"{label} must contain exactly three integers")
    result = (value[0], value[1], value[2])
    if label == "shape" and any(item <= 0 for item in result):
        raise VoxelFormatError("Every shape dimension must be positive")
    return result


@dataclass(frozen=True, slots=True)
class VoxelCube:
    origin: tuple[int, int, int]
    shape: tuple[int, int, int]
    palette: tuple[str, ...]
    voxels: bytes
    state_mode: str = "full"
    source: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if len(self.origin) != 3 or any(
            isinstance(item, bool) or not isinstance(item, int) for item in self.origin
        ):
            raise VoxelFormatError("origin must contain exactly three integers")
        if len(self.shape) != 3 or any(
            isinstance(item, bool) or not isinstance(item, int) or item <= 0
            for item in self.shape
        ):
            raise VoxelFormatError("shape must contain exactly three positive integers")
        if self.voxel_count > MAX_VOXELS:
            raise VoxelFormatError(f"Cube exceeds the safety limit of {MAX_VOXELS} voxels")
        if len(self.voxels) != self.voxel_count * 2:
            raise VoxelFormatError("Voxel payload length does not match shape and uint16 dtype")
        if not self.palette or self.palette[0] != AIR:
            raise VoxelFormatError(f"Local palette id 0 must be {AIR}")
        if len(self.palette) > 65_536 or len(set(self.palette)) != len(self.palette):
            raise VoxelFormatError("Local palette is too large or contains duplicate states")
        if self.palette != (AIR, *sorted(set(self.palette) - {AIR})):
            raise VoxelFormatError("Local palette is not in canonical order")
        if any(not isinstance(state, str) or not state for state in self.palette):
            raise VoxelFormatError("Local palette contains an invalid state")
        if self.state_mode not in {"full", "name"}:
            raise VoxelFormatError("state_mode must be 'full' or 'name'")
        if not isinstance(self.source, dict):
            raise VoxelFormatError("source must be a metadata object")
        for palette_id in self.iter_ids():
            if palette_id >= len(self.palette):
                raise VoxelFormatError(
                    f"Voxel palette id {palette_id} exceeds palette size {len(self.palette)}"
                )

    @property
    def voxel_count(self) -> int:
        return self.shape[0] * self.shape[1] * self.shape[2]

    def iter_ids(self) -> Iterator[int]:
        return (item[0] for item in struct.iter_unpack("<H", self.voxels))

    def palette_id(self, local_x: int, local_y: int, local_z: int) -> int:
        size_x, size_y, size_z = self.shape
        if not (0 <= local_x < size_x and 0 <= local_y < size_y and 0 <= local_z < size_z):
            raise IndexError("Local voxel coordinate lies outside the cube")
        index = (local_x * size_y + local_y) * size_z + local_z
        return struct.unpack_from("<H", self.voxels, index * 2)[0]

    def block_state(self, local_x: int, local_y: int, local_z: int) -> str:
        return self.palette[self.palette_id(local_x, local_y, local_z)]

    def state_counts(self) -> dict[str, int]:
        counts = Counter(self.iter_ids())
        return {self.palette[index]: counts[index] for index in sorted(counts)}


def extract_cube(
    reader: AnvilWorldReader,
    *,
    origin: tuple[int, int, int],
    shape: tuple[int, int, int],
    state_mode: str = "full",
    source: dict[str, Any] | None = None,
) -> VoxelCube:
    voxel_count = shape[0] * shape[1] * shape[2]
    if any(size <= 0 for size in shape):
        raise ValueError("Every shape dimension must be positive")
    if voxel_count > MAX_VOXELS:
        raise ValueError(f"Requested cube exceeds the safety limit of {MAX_VOXELS} voxels")
    states = list(reader.iter_block_states(origin, shape, mode=state_mode))
    if len(states) != voxel_count:
        raise VoxelFormatError(
            f"Reader yielded {len(states)} states for a requested {voxel_count}-voxel cube"
        )
    palette = (AIR, *sorted(set(states) - {AIR}))
    if len(palette) > 65_536:
        raise VoxelFormatError("Extracted cube has more than 65,536 distinct states")
    ids = {state: index for index, state in enumerate(palette)}
    payload = bytearray(voxel_count * 2)
    for index, state in enumerate(states):
        struct.pack_into("<H", payload, index * 2, ids[state])
    return VoxelCube(
        origin=origin,
        shape=shape,
        palette=palette,
        voxels=bytes(payload),
        state_mode=state_mode,
        source={} if source is None else source,
    )


def validate_extraction_bounds(
    reader: AnvilWorldReader,
    manifest: dict[str, Any],
    origin: tuple[int, int, int],
    shape: tuple[int, int, int],
) -> None:
    analysis = manifest.get("analysis_region")
    if not isinstance(analysis, dict):
        raise VoxelFormatError("World manifest contains no analysis region")
    end = tuple(origin[index] + shape[index] - 1 for index in range(3))
    for axis, minimum_key, maximum_key, coordinate_index in (
        ("X", "min_block_x", "max_block_x", 0),
        ("Z", "min_block_z", "max_block_z", 2),
    ):
        minimum = analysis.get(minimum_key)
        maximum = analysis.get(maximum_key)
        if not isinstance(minimum, int) or not isinstance(maximum, int):
            raise VoxelFormatError(f"Invalid {axis} bounds in world manifest")
        if origin[coordinate_index] < minimum or end[coordinate_index] > maximum:
            raise ValueError(
                f"Requested {axis} range {origin[coordinate_index]}..{end[coordinate_index]} "
                f"exceeds verified analysis range {minimum}..{maximum}"
            )

    minecraft = manifest.get("minecraft")
    expected_data_version = minecraft.get("data_version") if isinstance(minecraft, dict) else None
    for chunk_x in range(origin[0] // 16, end[0] // 16 + 1):
        for chunk_z in range(origin[2] // 16, end[2] // 16 + 1):
            chunk = reader.load_chunk(chunk_x, chunk_z)
            if chunk.status != "minecraft:full":
                raise VoxelFormatError(
                    f"Chunk ({chunk_x}, {chunk_z}) has non-final status {chunk.status!r}"
                )
            if chunk.data_version != expected_data_version:
                raise VoxelFormatError(
                    f"Chunk ({chunk_x}, {chunk_z}) data version {chunk.data_version} "
                    f"does not match manifest {expected_data_version}"
                )
            if origin[1] < chunk.min_block_y or end[1] > chunk.max_block_y:
                raise ValueError(
                    f"Requested Y range {origin[1]}..{end[1]} exceeds chunk "
                    f"({chunk_x}, {chunk_z}) range {chunk.min_block_y}..{chunk.max_block_y}"
                )


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=FIXED_ZIP_TIMESTAMP)
    info.compress_type = zipfile.ZIP_STORED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    return info


def cube_metadata(cube: VoxelCube, palette_bytes: bytes | None = None) -> dict[str, Any]:
    if palette_bytes is None:
        palette_bytes = _canonical_json(list(cube.palette))
    return {
        "axes": ["x", "y", "z"],
        "dtype": "uint16",
        "endianness": "little",
        "format": FORMAT_NAME,
        "linear_index": "((x * size_y) + y) * size_z + z",
        "local_palette": True,
        "origin": list(cube.origin),
        "palette": {
            "air_id": 0,
            "entry_count": len(cube.palette),
            "file": PALETTE_NAME,
            "sha256": _sha256_bytes(palette_bytes),
        },
        "schema_version": SCHEMA_VERSION,
        "shape": list(cube.shape),
        "source": cube.source,
        "state_mode": cube.state_mode,
        "voxel_count": cube.voxel_count,
        "voxels": {
            "file": VOXELS_NAME,
            "sha256": _sha256_bytes(cube.voxels),
        },
    }


def write_cube(path: str | Path, cube: VoxelCube, *, overwrite: bool = False) -> dict[str, Any]:
    """Write an MCVX archive atomically with stable entry order and timestamps."""

    target = Path(path).resolve()
    if target.exists() and not overwrite:
        raise FileExistsError(f"Refusing to overwrite existing artifact: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    palette_bytes = _canonical_json(list(cube.palette))
    metadata = cube_metadata(cube, palette_bytes)
    metadata_bytes = _canonical_json(metadata)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{target.name}.", suffix=".tmp", dir=target.parent, delete=False
        ) as stream:
            temporary = Path(stream.name)
        with zipfile.ZipFile(temporary, "w", allowZip64=True) as archive:
            archive.writestr(_zip_info(METADATA_NAME), metadata_bytes)
            archive.writestr(_zip_info(PALETTE_NAME), palette_bytes)
            archive.writestr(_zip_info(VOXELS_NAME), cube.voxels)
        os.replace(temporary, target)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return metadata


def load_cube(path: str | Path) -> VoxelCube:
    artifact = Path(path)
    with zipfile.ZipFile(artifact, "r") as archive:
        names = archive.namelist()
        if names != list(ARCHIVE_ENTRIES) or len(set(names)) != len(names):
            raise VoxelFormatError(
                f"MCVX entries must be exactly {', '.join(ARCHIVE_ENTRIES)} in canonical order"
            )
        info = {item.filename: item for item in archive.infolist()}
        if info[METADATA_NAME].file_size > MAX_METADATA_BYTES:
            raise VoxelFormatError("MCVX metadata exceeds the safety limit")
        if info[PALETTE_NAME].file_size > MAX_PALETTE_BYTES:
            raise VoxelFormatError("MCVX palette exceeds the safety limit")
        if info[VOXELS_NAME].file_size > MAX_VOXELS * 2:
            raise VoxelFormatError("MCVX voxel payload exceeds the safety limit")
        metadata_bytes = archive.read(METADATA_NAME)
        palette_bytes = archive.read(PALETTE_NAME)
        voxel_bytes = archive.read(VOXELS_NAME)

    metadata = _json_object(metadata_bytes, "MCVX metadata")
    if metadata.get("format") != FORMAT_NAME or metadata.get("schema_version") != SCHEMA_VERSION:
        raise VoxelFormatError("Unsupported MCVX format or schema")
    if metadata.get("axes") != ["x", "y", "z"]:
        raise VoxelFormatError("Unsupported MCVX axis order")
    if metadata.get("dtype") != "uint16" or metadata.get("endianness") != "little":
        raise VoxelFormatError("Unsupported MCVX voxel encoding")
    if metadata.get("linear_index") != "((x * size_y) + y) * size_z + z":
        raise VoxelFormatError("Unsupported MCVX linear index order")
    if metadata.get("local_palette") is not True:
        raise VoxelFormatError("MCVX schema requires a local palette")
    origin = _positive_triplet(metadata.get("origin"), "origin")
    shape = _positive_triplet(metadata.get("shape"), "shape")
    try:
        palette_value = json.loads(palette_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VoxelFormatError("Invalid MCVX palette JSON") from exc
    if not isinstance(palette_value, list) or any(
        not isinstance(state, str) for state in palette_value
    ):
        raise VoxelFormatError("MCVX palette must be a JSON array of strings")
    palette = tuple(palette_value)
    palette_metadata = metadata.get("palette")
    voxels_metadata = metadata.get("voxels")
    if not isinstance(palette_metadata, dict) or not isinstance(voxels_metadata, dict):
        raise VoxelFormatError("MCVX payload metadata is incomplete")
    if palette_metadata.get("file") != PALETTE_NAME or voxels_metadata.get("file") != VOXELS_NAME:
        raise VoxelFormatError("MCVX payload filenames do not match the schema")
    if palette_metadata.get("sha256") != _sha256_bytes(palette_bytes):
        raise VoxelFormatError("MCVX palette checksum mismatch")
    if voxels_metadata.get("sha256") != _sha256_bytes(voxel_bytes):
        raise VoxelFormatError("MCVX voxel checksum mismatch")
    if palette_metadata.get("entry_count") != len(palette) or palette_metadata.get("air_id") != 0:
        raise VoxelFormatError("MCVX palette metadata does not match the palette")
    source = metadata.get("source")
    if not isinstance(source, dict):
        raise VoxelFormatError("MCVX source metadata must be an object")
    cube = VoxelCube(
        origin=origin,
        shape=shape,
        palette=palette,
        voxels=voxel_bytes,
        state_mode=metadata.get("state_mode", ""),
        source=source,
    )
    if metadata.get("voxel_count") != cube.voxel_count:
        raise VoxelFormatError("MCVX voxel_count does not match shape")
    return cube
