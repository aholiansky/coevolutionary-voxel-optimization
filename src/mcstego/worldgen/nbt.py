from __future__ import annotations

import gzip
import io
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO

MAX_COLLECTION_LENGTH = 10_000_000


class NbtFormatError(ValueError):
    """Raised when a binary NBT document is malformed or unsupported."""


class _NbtReader:
    def __init__(self, stream: BinaryIO) -> None:
        self.stream = stream

    def _read(self, size: int) -> bytes:
        data = self.stream.read(size)
        if len(data) != size:
            raise NbtFormatError("Unexpected end of NBT input")
        return data

    def _unpack(self, fmt: str) -> Any:
        return struct.unpack(">" + fmt, self._read(struct.calcsize(">" + fmt)))[0]

    def _length(self) -> int:
        length = int(self._unpack("i"))
        if not 0 <= length <= MAX_COLLECTION_LENGTH:
            raise NbtFormatError(f"Invalid NBT collection length: {length}")
        return length

    def string(self) -> str:
        length = int(self._unpack("H"))
        try:
            return self._read(length).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise NbtFormatError("Invalid UTF-8 in NBT string") from exc

    def payload(self, tag_type: int) -> Any:
        if tag_type == 0:
            return None
        if tag_type == 1:
            return int(self._unpack("b"))
        if tag_type == 2:
            return int(self._unpack("h"))
        if tag_type == 3:
            return int(self._unpack("i"))
        if tag_type == 4:
            return int(self._unpack("q"))
        if tag_type == 5:
            return float(self._unpack("f"))
        if tag_type == 6:
            return float(self._unpack("d"))
        if tag_type == 7:
            return self._read(self._length())
        if tag_type == 8:
            return self.string()
        if tag_type == 9:
            element_type = self._read(1)[0]
            return [self.payload(element_type) for _ in range(self._length())]
        if tag_type == 10:
            compound: dict[str, Any] = {}
            while True:
                child_type = self._read(1)[0]
                if child_type == 0:
                    return compound
                child_name = self.string()
                compound[child_name] = self.payload(child_type)
        if tag_type == 11:
            return [int(self._unpack("i")) for _ in range(self._length())]
        if tag_type == 12:
            return [int(self._unpack("q")) for _ in range(self._length())]
        raise NbtFormatError(f"Unknown NBT tag type: {tag_type}")


def read_nbt(stream: BinaryIO) -> tuple[str, Any]:
    """Read one uncompressed, big-endian Java Edition NBT document."""

    reader = _NbtReader(stream)
    root_type_raw = stream.read(1)
    if len(root_type_raw) != 1:
        raise NbtFormatError("Empty NBT document")
    root_type = root_type_raw[0]
    if root_type == 0:
        raise NbtFormatError("NBT root cannot be TAG_End")
    root_name = reader.string()
    return root_name, reader.payload(root_type)


def read_nbt_bytes(data: bytes) -> tuple[str, Any]:
    """Read an uncompressed NBT document held in memory."""

    stream = io.BytesIO(data)
    result = read_nbt(stream)
    if stream.read(1):
        raise NbtFormatError("Trailing data after NBT root tag")
    return result


def read_gzip_nbt(path: str | Path) -> tuple[str, Any]:
    with gzip.open(Path(path), "rb") as stream:
        return read_nbt(stream)


@dataclass(frozen=True, slots=True)
class LevelMetadata:
    seed: int
    minecraft_version: str | None
    data_version: int | None
    level_name: str | None


def read_level_metadata(path: str | Path) -> LevelMetadata:
    """Read provenance fields from a modern Java Edition ``level.dat`` file."""

    _, root = read_gzip_nbt(path)
    if not isinstance(root, dict) or not isinstance(root.get("Data"), dict):
        raise NbtFormatError("level.dat does not contain a Data compound")
    data = root["Data"]
    worldgen = data.get("WorldGenSettings")
    seed: Any = worldgen.get("seed") if isinstance(worldgen, dict) else None
    if seed is None:
        seed = data.get("RandomSeed")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise NbtFormatError("level.dat does not contain an integer world seed")

    version = data.get("Version")
    version_name: str | None = None
    version_id: int | None = None
    if isinstance(version, dict):
        if isinstance(version.get("Name"), str):
            version_name = version["Name"]
        if isinstance(version.get("Id"), int) and not isinstance(version.get("Id"), bool):
            version_id = version["Id"]
    level_name = data.get("LevelName") if isinstance(data.get("LevelName"), str) else None
    return LevelMetadata(
        seed=seed,
        minecraft_version=version_name,
        data_version=version_id,
        level_name=level_name,
    )
