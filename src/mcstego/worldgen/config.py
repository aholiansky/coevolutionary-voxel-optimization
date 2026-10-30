from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


def _require_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    return value


def _require_non_empty_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    if "\n" in value or "\r" in value:
        raise ValueError(f"{name} must not contain a newline")
    return value


def _require_https_url(value: Any, name: str) -> str:
    url = _require_non_empty_string(value, name)
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError(f"{name} must be an HTTPS URL")
    return url


@dataclass(frozen=True, slots=True)
class ChunkBounds:
    min_x: int
    max_x: int
    min_z: int
    max_z: int

    def __post_init__(self) -> None:
        if self.min_x > self.max_x or self.min_z > self.max_z:
            raise ValueError("Chunk bounds must be ordered")

    @property
    def width(self) -> int:
        return self.max_x - self.min_x + 1

    @property
    def depth(self) -> int:
        return self.max_z - self.min_z + 1

    @property
    def expected_chunks(self) -> int:
        return self.width * self.depth

    @property
    def min_block_x(self) -> int:
        return self.min_x * 16

    @property
    def max_block_x(self) -> int:
        return (self.max_x + 1) * 16 - 1

    @property
    def min_block_z(self) -> int:
        return self.min_z * 16

    @property
    def max_block_z(self) -> int:
        return (self.max_z + 1) * 16 - 1

    def coordinates(self) -> tuple[tuple[int, int], ...]:
        return tuple(
            (chunk_x, chunk_z)
            for chunk_z in range(self.min_z, self.max_z + 1)
            for chunk_x in range(self.min_x, self.max_x + 1)
        )

    def to_dict(self) -> dict[str, int]:
        return {
            "min_chunk_x": self.min_x,
            "max_chunk_x": self.max_x,
            "min_chunk_z": self.min_z,
            "max_chunk_z": self.max_z,
            "min_block_x": self.min_block_x,
            "max_block_x": self.max_block_x,
            "min_block_z": self.min_block_z,
            "max_block_z": self.max_block_z,
            "expected_chunks": self.expected_chunks,
        }


@dataclass(frozen=True, slots=True)
class ToolchainConfig:
    minecraft_version: str
    java_major: int
    fabric_loader_version: str
    fabric_installer_version: str
    fabric_server_url: str
    fabric_server_filename: str
    fabric_api_version: str
    fabric_api_modrinth_version_id: str
    fabric_api_url: str
    fabric_api_filename: str
    chunky_version: str
    chunky_modrinth_version_id: str
    chunky_url: str
    chunky_filename: str


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    xms_mb: int
    xmx_mb: int
    startup_timeout_seconds: int
    generation_timeout_seconds: int
    poll_interval_seconds: int
    shutdown_timeout_seconds: int
    minimum_free_disk_gib: int


@dataclass(frozen=True, slots=True)
class PathConfig:
    runtime: Path
    worlds: Path
    runs: Path


@dataclass(frozen=True, slots=True)
class WorldgenConfig:
    schema_version: int
    cohort_id: str
    toolchain: ToolchainConfig
    bounds: ChunkBounds
    split_counts: dict[str, int]
    server_properties: dict[str, str]
    runtime: RuntimeConfig
    paths: PathConfig

    def resolved_paths(self, project_root: str | Path) -> PathConfig:
        root = Path(project_root).resolve()
        return PathConfig(
            runtime=(root / self.paths.runtime).resolve(),
            worlds=(root / self.paths.worlds).resolve(),
            runs=(root / self.paths.runs).resolve(),
        )


def _load_object(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def _validate_filename(value: Any, name: str) -> str:
    filename = _require_non_empty_string(value, name)
    if filename in {".", ".."} or Path(filename).name != filename:
        raise ValueError(f"{name} must be a plain filename")
    return filename


def _validate_relative_path(value: Any, name: str) -> Path:
    raw = _require_non_empty_string(value, name)
    path = Path(raw)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{name} must be a project-relative path without '..'")
    return path


def load_worldgen_config(path: str | Path) -> WorldgenConfig:
    """Load and strictly validate the frozen world-generation configuration."""

    source = Path(path)
    raw = _load_object(source)
    schema_version = _require_int(raw.get("schema_version"), "schema_version")
    if schema_version != 1:
        raise ValueError(f"Unsupported worldgen schema version: {schema_version}")

    cohort_id = _require_non_empty_string(raw.get("cohort_id"), "cohort_id")
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{2,63}", cohort_id):
        raise ValueError("cohort_id contains unsupported characters")

    tool = raw.get("toolchain")
    if not isinstance(tool, dict):
        raise ValueError("toolchain must be an object")
    toolchain = ToolchainConfig(
        minecraft_version=_require_non_empty_string(
            tool.get("minecraft_version"), "toolchain.minecraft_version"
        ),
        java_major=_require_int(tool.get("java_major"), "toolchain.java_major"),
        fabric_loader_version=_require_non_empty_string(
            tool.get("fabric_loader_version"), "toolchain.fabric_loader_version"
        ),
        fabric_installer_version=_require_non_empty_string(
            tool.get("fabric_installer_version"), "toolchain.fabric_installer_version"
        ),
        fabric_server_url=_require_https_url(
            tool.get("fabric_server_url"), "toolchain.fabric_server_url"
        ),
        fabric_server_filename=_validate_filename(
            tool.get("fabric_server_filename"), "toolchain.fabric_server_filename"
        ),
        fabric_api_version=_require_non_empty_string(
            tool.get("fabric_api_version"), "toolchain.fabric_api_version"
        ),
        fabric_api_modrinth_version_id=_require_non_empty_string(
            tool.get("fabric_api_modrinth_version_id"),
            "toolchain.fabric_api_modrinth_version_id",
        ),
        fabric_api_url=_require_https_url(
            tool.get("fabric_api_url"), "toolchain.fabric_api_url"
        ),
        fabric_api_filename=_validate_filename(
            tool.get("fabric_api_filename"), "toolchain.fabric_api_filename"
        ),
        chunky_version=_require_non_empty_string(
            tool.get("chunky_version"), "toolchain.chunky_version"
        ),
        chunky_modrinth_version_id=_require_non_empty_string(
            tool.get("chunky_modrinth_version_id"),
            "toolchain.chunky_modrinth_version_id",
        ),
        chunky_url=_require_https_url(tool.get("chunky_url"), "toolchain.chunky_url"),
        chunky_filename=_validate_filename(
            tool.get("chunky_filename"), "toolchain.chunky_filename"
        ),
    )
    if toolchain.java_major < 17:
        raise ValueError("toolchain.java_major is implausibly old")

    region = raw.get("region")
    if not isinstance(region, dict):
        raise ValueError("region must be an object")
    bounds = ChunkBounds(
        min_x=_require_int(region.get("min_chunk_x"), "region.min_chunk_x"),
        max_x=_require_int(region.get("max_chunk_x"), "region.max_chunk_x"),
        min_z=_require_int(region.get("min_chunk_z"), "region.min_chunk_z"),
        max_z=_require_int(region.get("max_chunk_z"), "region.max_chunk_z"),
    )
    declared_chunks = _require_int(region.get("expected_chunks"), "region.expected_chunks")
    if declared_chunks != bounds.expected_chunks:
        raise ValueError(
            f"region.expected_chunks={declared_chunks}, calculated={bounds.expected_chunks}"
        )

    raw_splits = raw.get("split_counts")
    if not isinstance(raw_splits, dict) or set(raw_splits) != {
        "train",
        "validation",
        "test",
    }:
        raise ValueError("split_counts must contain exactly train, validation and test")
    split_counts = {
        name: _require_int(raw_splits[name], f"split_counts.{name}")
        for name in ("train", "validation", "test")
    }
    if any(count <= 0 for count in split_counts.values()):
        raise ValueError("All split counts must be positive")

    raw_properties = raw.get("server_properties")
    if not isinstance(raw_properties, dict) or not raw_properties:
        raise ValueError("server_properties must be a non-empty object")
    server_properties: dict[str, str] = {}
    for key, value in raw_properties.items():
        if not isinstance(key, str) or not re.fullmatch(r"[a-z0-9-]+", key):
            raise ValueError(f"Invalid server property name: {key!r}")
        if not isinstance(value, (str, int, bool)):
            raise ValueError(f"Invalid server property value for {key}")
        normalized = str(value).lower() if isinstance(value, bool) else str(value)
        if "\n" in normalized or "\r" in normalized:
            raise ValueError(f"Newline in server property {key}")
        server_properties[key] = normalized
    forbidden = {"level-name", "level-seed"}.intersection(server_properties)
    if forbidden:
        raise ValueError(f"Dynamic properties must not be frozen in config: {sorted(forbidden)}")

    runtime = raw.get("runtime")
    if not isinstance(runtime, dict):
        raise ValueError("runtime must be an object")
    runtime_config = RuntimeConfig(
        xms_mb=_require_int(runtime.get("xms_mb"), "runtime.xms_mb"),
        xmx_mb=_require_int(runtime.get("xmx_mb"), "runtime.xmx_mb"),
        startup_timeout_seconds=_require_int(
            runtime.get("startup_timeout_seconds"), "runtime.startup_timeout_seconds"
        ),
        generation_timeout_seconds=_require_int(
            runtime.get("generation_timeout_seconds"), "runtime.generation_timeout_seconds"
        ),
        poll_interval_seconds=_require_int(
            runtime.get("poll_interval_seconds"), "runtime.poll_interval_seconds"
        ),
        shutdown_timeout_seconds=_require_int(
            runtime.get("shutdown_timeout_seconds"), "runtime.shutdown_timeout_seconds"
        ),
        minimum_free_disk_gib=_require_int(
            runtime.get("minimum_free_disk_gib"), "runtime.minimum_free_disk_gib"
        ),
    )
    if runtime_config.xms_mb <= 0 or runtime_config.xmx_mb < runtime_config.xms_mb:
        raise ValueError("runtime memory limits are inconsistent")
    if min(
        runtime_config.startup_timeout_seconds,
        runtime_config.generation_timeout_seconds,
        runtime_config.poll_interval_seconds,
        runtime_config.shutdown_timeout_seconds,
    ) <= 0:
        raise ValueError("runtime timeouts and polling interval must be positive")

    paths = raw.get("paths")
    if not isinstance(paths, dict):
        raise ValueError("paths must be an object")
    path_config = PathConfig(
        runtime=_validate_relative_path(paths.get("runtime"), "paths.runtime"),
        worlds=_validate_relative_path(paths.get("worlds"), "paths.worlds"),
        runs=_validate_relative_path(paths.get("runs"), "paths.runs"),
    )

    return WorldgenConfig(
        schema_version=schema_version,
        cohort_id=cohort_id,
        toolchain=toolchain,
        bounds=bounds,
        split_counts=split_counts,
        server_properties=server_properties,
        runtime=runtime_config,
        paths=path_config,
    )
