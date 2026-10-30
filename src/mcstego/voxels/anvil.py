from __future__ import annotations

import zlib
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from mcstego.worldgen.anvil import SECTOR_BYTES, chunk_region_position
from mcstego.worldgen.nbt import NbtFormatError, read_nbt_bytes

REGION_HEADER_BYTES = 2 * SECTOR_BYTES
BLOCKS_PER_SECTION = 16 * 16 * 16
MAX_PALETTE_SIZE = BLOCKS_PER_SECTION
MAX_DECOMPRESSED_CHUNK_BYTES = 16 * 1024 * 1024
AIR = "minecraft:air"


class ChunkFormatError(ValueError):
    """Raised when a Java Anvil chunk cannot be decoded safely."""


def canonical_block_state(value: Any) -> str:
    """Convert a block-state palette compound to a stable string."""

    if not isinstance(value, dict):
        raise ChunkFormatError("Block-state palette entry is not a compound")
    name = value.get("Name")
    if not isinstance(name, str) or not name:
        raise ChunkFormatError("Block-state palette entry has no valid Name")
    properties = value.get("Properties")
    if properties is None:
        return name
    if not isinstance(properties, dict):
        raise ChunkFormatError(f"Invalid Properties compound for {name}")
    rendered: list[str] = []
    for key, property_value in sorted(properties.items()):
        if not isinstance(key, str) or not isinstance(property_value, str):
            raise ChunkFormatError(f"Invalid block-state property for {name}")
        rendered.append(f"{key}={property_value}")
    return f"{name}[{','.join(rendered)}]" if rendered else name


def block_name(state: str) -> str:
    """Drop properties from a canonical block-state string."""

    return state.partition("[")[0]


def _require_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ChunkFormatError(f"{label} is not an integer")
    return value


def _decompress_chunk(payload: bytes, compression: int) -> bytes:
    if compression == 3:
        if len(payload) > MAX_DECOMPRESSED_CHUNK_BYTES:
            raise ChunkFormatError("Uncompressed chunk exceeds the safety limit")
        return payload
    if compression not in {1, 2}:
        if compression == 4:
            raise ChunkFormatError(
                "LZ4-compressed Anvil chunks are not supported by the dependency-free importer"
            )
        raise ChunkFormatError(f"Unsupported Anvil compression method: {compression}")

    window_bits = 16 + zlib.MAX_WBITS if compression == 1 else zlib.MAX_WBITS
    decompressor = zlib.decompressobj(window_bits)
    try:
        output = decompressor.decompress(payload, MAX_DECOMPRESSED_CHUNK_BYTES + 1)
        if len(output) > MAX_DECOMPRESSED_CHUNK_BYTES or decompressor.unconsumed_tail:
            raise ChunkFormatError("Decompressed chunk exceeds the safety limit")
        output += decompressor.flush(MAX_DECOMPRESSED_CHUNK_BYTES + 1 - len(output))
    except zlib.error as exc:
        raise ChunkFormatError("Invalid compressed Anvil chunk payload") from exc
    if len(output) > MAX_DECOMPRESSED_CHUNK_BYTES:
        raise ChunkFormatError("Decompressed chunk exceeds the safety limit")
    if not decompressor.eof:
        raise ChunkFormatError("Truncated compressed Anvil chunk payload")
    if decompressor.unused_data:
        raise ChunkFormatError("Compressed Anvil chunk contains trailing data")
    return output


@dataclass(frozen=True, slots=True)
class ChunkSection:
    section_y: int
    palette: tuple[str, ...]
    packed_data: tuple[int, ...]

    def __post_init__(self) -> None:
        palette_size = len(self.palette)
        if not 1 <= palette_size <= MAX_PALETTE_SIZE:
            raise ChunkFormatError(f"Invalid block-state palette size: {palette_size}")
        if len(set(self.palette)) != palette_size:
            raise ChunkFormatError("Block-state palette contains duplicate entries")

        if palette_size == 1:
            if self.packed_data:
                raise ChunkFormatError("Single-entry palette unexpectedly contains packed data")
            return
        bits = max(4, (palette_size - 1).bit_length())
        values_per_long = 64 // bits
        expected_longs = (BLOCKS_PER_SECTION + values_per_long - 1) // values_per_long
        if len(self.packed_data) != expected_longs:
            raise ChunkFormatError(
                f"Invalid packed block-state length: {len(self.packed_data)}, "
                f"expected {expected_longs}"
            )

    def palette_index(self, local_x: int, local_y: int, local_z: int) -> int:
        if not all(0 <= coordinate < 16 for coordinate in (local_x, local_y, local_z)):
            raise ValueError("Local block coordinates must be in range 0..15")
        if len(self.palette) == 1:
            return 0
        bits = max(4, (len(self.palette) - 1).bit_length())
        values_per_long = 64 // bits
        linear_index = (local_y * 16 + local_z) * 16 + local_x
        packed = self.packed_data[linear_index // values_per_long] & 0xFFFFFFFFFFFFFFFF
        palette_index = (packed >> ((linear_index % values_per_long) * bits)) & ((1 << bits) - 1)
        if palette_index >= len(self.palette):
            raise ChunkFormatError(
                f"Packed palette index {palette_index} exceeds palette size {len(self.palette)}"
            )
        return palette_index

    def block_state(self, local_x: int, local_y: int, local_z: int) -> str:
        return self.palette[self.palette_index(local_x, local_y, local_z)]


@dataclass(frozen=True, slots=True)
class ChunkData:
    chunk_x: int
    chunk_z: int
    data_version: int
    status: str
    sections: dict[int, ChunkSection]
    min_section_y: int
    max_section_y: int

    @property
    def min_block_y(self) -> int:
        return self.min_section_y * 16

    @property
    def max_block_y(self) -> int:
        return self.max_section_y * 16 + 15

    def block_state(self, block_x: int, block_y: int, block_z: int) -> str:
        if block_x // 16 != self.chunk_x or block_z // 16 != self.chunk_z:
            raise ValueError("Block coordinate does not belong to this chunk")
        if not self.min_block_y <= block_y <= self.max_block_y:
            raise ValueError(
                f"Y={block_y} lies outside chunk range {self.min_block_y}..{self.max_block_y}"
            )
        section_y = block_y // 16
        section = self.sections.get(section_y)
        if section is None:
            section = ChunkSection(section_y=section_y, palette=(AIR,), packed_data=())
        return section.block_state(block_x % 16, block_y % 16, block_z % 16)


def decode_chunk_nbt(
    raw_nbt: bytes,
    *,
    expected_chunk_x: int,
    expected_chunk_z: int,
) -> ChunkData:
    try:
        _, root = read_nbt_bytes(raw_nbt)
    except NbtFormatError as exc:
        raise ChunkFormatError("Invalid NBT document in Anvil chunk") from exc
    if not isinstance(root, dict):
        raise ChunkFormatError("Anvil chunk root is not a compound")
    if isinstance(root.get("Level"), dict):
        root = root["Level"]

    chunk_x = _require_int(root.get("xPos"), "Chunk xPos")
    chunk_z = _require_int(root.get("zPos"), "Chunk zPos")
    if (chunk_x, chunk_z) != (expected_chunk_x, expected_chunk_z):
        raise ChunkFormatError(
            f"Chunk coordinate mismatch: location is ({expected_chunk_x}, {expected_chunk_z}), "
            f"NBT says ({chunk_x}, {chunk_z})"
        )
    data_version = _require_int(root.get("DataVersion"), "Chunk DataVersion")
    status = root.get("Status")
    if not isinstance(status, str):
        raise ChunkFormatError("Chunk Status is missing or invalid")
    raw_sections = root.get("sections", root.get("Sections"))
    if not isinstance(raw_sections, list) or not raw_sections:
        raise ChunkFormatError("Chunk contains no section list")

    sections: dict[int, ChunkSection] = {}
    all_section_y: list[int] = []
    for raw_section in raw_sections:
        if not isinstance(raw_section, dict):
            raise ChunkFormatError("Chunk section is not a compound")
        section_y = _require_int(raw_section.get("Y"), "Section Y")
        if section_y in all_section_y:
            raise ChunkFormatError(f"Duplicate chunk section Y={section_y}")
        all_section_y.append(section_y)
        raw_states = raw_section.get("block_states")
        if raw_states is None:
            continue
        if not isinstance(raw_states, dict):
            raise ChunkFormatError(f"Invalid block_states compound in section Y={section_y}")
        raw_palette = raw_states.get("palette")
        if not isinstance(raw_palette, list) or not raw_palette:
            raise ChunkFormatError(f"Missing block-state palette in section Y={section_y}")
        palette = tuple(canonical_block_state(entry) for entry in raw_palette)
        raw_data = raw_states.get("data", [])
        if not isinstance(raw_data, list) or any(
            isinstance(item, bool) or not isinstance(item, int) for item in raw_data
        ):
            raise ChunkFormatError(f"Invalid packed block-state data in section Y={section_y}")
        sections[section_y] = ChunkSection(section_y, palette, tuple(raw_data))

    return ChunkData(
        chunk_x=chunk_x,
        chunk_z=chunk_z,
        data_version=data_version,
        status=status,
        sections=sections,
        min_section_y=min(all_section_y),
        max_section_y=max(all_section_y),
    )


class AnvilWorldReader:
    """Read blocks from the overworld of a modern Java Edition save."""

    def __init__(self, world_path: str | Path, *, cache_size: int = 64) -> None:
        if cache_size < 1:
            raise ValueError("cache_size must be positive")
        self.world_path = Path(world_path).resolve()
        self.region_path = self.world_path / "region"
        if not (self.world_path / "level.dat").is_file():
            raise FileNotFoundError(f"Missing level.dat: {self.world_path / 'level.dat'}")
        if not self.region_path.is_dir():
            raise FileNotFoundError(f"Missing overworld region directory: {self.region_path}")
        self.cache_size = cache_size
        self._cache: OrderedDict[tuple[int, int], ChunkData] = OrderedDict()

    def _region_file(self, chunk_x: int, chunk_z: int) -> Path:
        region_x, region_z, _, _ = chunk_region_position(chunk_x, chunk_z)
        return self.region_path / f"r.{region_x}.{region_z}.mca"

    def _read_compressed_chunk(self, chunk_x: int, chunk_z: int) -> tuple[int, bytes]:
        _, _, local_x, local_z = chunk_region_position(chunk_x, chunk_z)
        path = self._region_file(chunk_x, chunk_z)
        if not path.is_file():
            raise FileNotFoundError(f"Missing region file for chunk ({chunk_x}, {chunk_z}): {path}")
        file_size = path.stat().st_size
        if file_size < REGION_HEADER_BYTES:
            raise ChunkFormatError(f"Truncated Anvil region header: {path}")
        location_index = local_x + local_z * 32
        with path.open("rb") as stream:
            stream.seek(location_index * 4)
            location = stream.read(4)
            if len(location) != 4:
                raise ChunkFormatError(f"Cannot read Anvil location entry: {path}")
            sector_offset = int.from_bytes(location[:3], "big")
            sector_count = location[3]
            if sector_offset == 0 and sector_count == 0:
                raise KeyError(f"Chunk ({chunk_x}, {chunk_z}) is absent from {path.name}")
            if sector_offset < 2 or sector_count == 0:
                raise ChunkFormatError(f"Invalid Anvil location for chunk ({chunk_x}, {chunk_z})")
            start = sector_offset * SECTOR_BYTES
            allocation_end = (sector_offset + sector_count) * SECTOR_BYTES
            if start + 5 > file_size or allocation_end > file_size:
                raise ChunkFormatError(
                    f"Anvil location exceeds region file for chunk ({chunk_x}, {chunk_z})"
                )
            stream.seek(start)
            length_bytes = stream.read(4)
            length = int.from_bytes(length_bytes, "big")
            if length < 1 or length > sector_count * SECTOR_BYTES - 4:
                raise ChunkFormatError(f"Invalid stored length for chunk ({chunk_x}, {chunk_z})")
            compression_byte = stream.read(1)
            if len(compression_byte) != 1:
                raise ChunkFormatError(f"Missing compression byte for chunk ({chunk_x}, {chunk_z})")
            encoded_compression = compression_byte[0]
            external = bool(encoded_compression & 0x80)
            compression = encoded_compression & 0x7F
            payload = stream.read(length - 1)
            if len(payload) != length - 1:
                raise ChunkFormatError(f"Truncated payload for chunk ({chunk_x}, {chunk_z})")

        if external:
            if payload:
                raise ChunkFormatError("External Anvil chunk has an unexpected inline payload")
            external_path = self.region_path / f"c.{chunk_x}.{chunk_z}.mcc"
            if not external_path.is_file():
                raise FileNotFoundError(f"Missing external chunk payload: {external_path}")
            if external_path.stat().st_size > MAX_DECOMPRESSED_CHUNK_BYTES:
                raise ChunkFormatError(
                    f"External chunk payload exceeds safety limit: {external_path}"
                )
            payload = external_path.read_bytes()
        return compression, payload

    def load_chunk(self, chunk_x: int, chunk_z: int) -> ChunkData:
        key = (chunk_x, chunk_z)
        cached = self._cache.pop(key, None)
        if cached is not None:
            self._cache[key] = cached
            return cached
        compression, payload = self._read_compressed_chunk(chunk_x, chunk_z)
        raw_nbt = _decompress_chunk(payload, compression)
        chunk = decode_chunk_nbt(
            raw_nbt,
            expected_chunk_x=chunk_x,
            expected_chunk_z=chunk_z,
        )
        self._cache[key] = chunk
        if len(self._cache) > self.cache_size:
            self._cache.popitem(last=False)
        return chunk

    def block_state(self, block_x: int, block_y: int, block_z: int, *, mode: str = "full") -> str:
        if mode not in {"full", "name"}:
            raise ValueError("mode must be 'full' or 'name'")
        chunk = self.load_chunk(block_x // 16, block_z // 16)
        state = chunk.block_state(block_x, block_y, block_z)
        return state if mode == "full" else block_name(state)

    def iter_block_states(
        self,
        origin: tuple[int, int, int],
        shape: tuple[int, int, int],
        *,
        mode: str = "full",
    ) -> Iterator[str]:
        origin_x, origin_y, origin_z = origin
        size_x, size_y, size_z = shape
        if any(size <= 0 for size in shape):
            raise ValueError("Every shape dimension must be positive")
        for block_x in range(origin_x, origin_x + size_x):
            for block_y in range(origin_y, origin_y + size_y):
                for block_z in range(origin_z, origin_z + size_z):
                    yield self.block_state(block_x, block_y, block_z, mode=mode)

    def chunk_summary(self, chunk_x: int, chunk_z: int) -> dict[str, object]:
        chunk = self.load_chunk(chunk_x, chunk_z)
        states = {state for section in chunk.sections.values() for state in section.palette}
        return {
            "chunk": [chunk_x, chunk_z],
            "data_version": chunk.data_version,
            "status": chunk.status,
            "section_y": [chunk.min_section_y, chunk.max_section_y],
            "block_y": [chunk.min_block_y, chunk.max_block_y],
            "section_count": chunk.max_section_y - chunk.min_section_y + 1,
            "distinct_palette_states": len(states),
        }
