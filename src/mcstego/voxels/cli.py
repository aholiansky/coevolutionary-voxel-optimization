from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from mcstego.voxels.anvil import AnvilWorldReader
from mcstego.voxels.cube import (
    extract_cube,
    load_cube,
    source_metadata,
    validate_extraction_bounds,
    verify_world_source,
    write_cube,
)
from mcstego.worldgen.anvil import sha256_file


def _print_json(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def _representative_chunk(manifest: dict[str, object]) -> tuple[int, int]:
    analysis = manifest.get("analysis_region")
    if not isinstance(analysis, dict):
        raise ValueError("World manifest contains no analysis region")
    minimum_x = analysis.get("min_chunk_x")
    maximum_x = analysis.get("max_chunk_x")
    minimum_z = analysis.get("min_chunk_z")
    maximum_z = analysis.get("max_chunk_z")
    if not all(isinstance(value, int) for value in (minimum_x, maximum_x, minimum_z, maximum_z)):
        raise ValueError("World manifest contains invalid chunk bounds")
    assert isinstance(minimum_x, int)
    assert isinstance(maximum_x, int)
    assert isinstance(minimum_z, int)
    assert isinstance(maximum_z, int)
    chunk_x = 0 if minimum_x <= 0 <= maximum_x else minimum_x
    chunk_z = 0 if minimum_z <= 0 <= maximum_z else minimum_z
    return chunk_x, chunk_z


def _cmd_inspect(args: argparse.Namespace) -> int:
    world = Path(args.world).resolve()
    manifest = verify_world_source(world)
    reader = AnvilWorldReader(world)
    chunk = tuple(args.chunk) if args.chunk is not None else _representative_chunk(manifest)
    summary = reader.chunk_summary(chunk[0], chunk[1])
    _print_json(
        {
            "analysis_region": manifest.get("analysis_region"),
            "artifact_count": len(manifest["artifact_sha256"]),
            "cohort_id": manifest.get("cohort_id"),
            "immutable_cover_verified": True,
            "manifest_sha256": manifest["_manifest_sha256"],
            "minecraft": manifest.get("minecraft"),
            "representative_chunk": summary,
            "split": manifest.get("split"),
            "world_id": manifest.get("world_id"),
        }
    )
    return 0


def _shape(args: argparse.Namespace) -> tuple[int, int, int]:
    if args.size is not None:
        if args.size <= 0:
            raise ValueError("--size must be positive")
        return args.size, args.size, args.size
    if args.shape is None:
        raise ValueError("Provide --size N or --shape X Y Z")
    result = tuple(args.shape)
    if any(size <= 0 for size in result):
        raise ValueError("Every --shape dimension must be positive")
    return result


def _cmd_extract(args: argparse.Namespace) -> int:
    world = Path(args.world).resolve()
    output = Path(args.output).resolve()
    if output == world or output.is_relative_to(world):
        raise ValueError("Output must be outside the immutable source world directory")
    manifest = verify_world_source(world)
    reader = AnvilWorldReader(world)
    origin = tuple(args.origin)
    shape = _shape(args)
    validate_extraction_bounds(reader, manifest, origin, shape)
    cube = extract_cube(
        reader,
        origin=origin,
        shape=shape,
        state_mode=args.state_mode,
        source=source_metadata(manifest),
    )
    metadata = write_cube(output, cube, overwrite=args.overwrite)
    counts = cube.state_counts()
    top_states = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:20]
    _print_json(
        {
            "artifact": str(output),
            "artifact_sha256": sha256_file(output),
            "format": metadata["format"],
            "origin": list(cube.origin),
            "palette_entries": len(cube.palette),
            "shape": list(cube.shape),
            "source_verified": True,
            "state_mode": cube.state_mode,
            "top_states": [{"count": count, "state": state} for state, count in top_states],
            "voxel_count": cube.voxel_count,
        }
    )
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    artifact = Path(args.artifact).resolve()
    cube = load_cube(artifact)
    _print_json(
        {
            "artifact": str(artifact),
            "artifact_sha256": sha256_file(artifact),
            "origin": list(cube.origin),
            "palette_entries": len(cube.palette),
            "shape": list(cube.shape),
            "source": cube.source,
            "state_mode": cube.state_mode,
            "valid": True,
            "voxel_count": cube.voxel_count,
        }
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="voxel_import",
        description="Read-only Java Anvil to deterministic MCVX importer",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect = subparsers.add_parser(
        "inspect",
        help="Verify an immutable generated world and inspect one chunk",
    )
    inspect.add_argument("--world", required=True, help="Generated world directory")
    inspect.add_argument("--chunk", nargs=2, type=int, metavar=("X", "Z"))
    inspect.set_defaults(handler=_cmd_inspect)

    extract = subparsers.add_parser(
        "extract",
        help="Extract one verified voxel cube without modifying the source world",
    )
    extract.add_argument("--world", required=True, help="Generated world directory")
    extract.add_argument("--output", required=True, help="Destination .mcvx path")
    extract.add_argument("--origin", nargs=3, type=int, required=True, metavar=("X", "Y", "Z"))
    dimensions = extract.add_mutually_exclusive_group(required=True)
    dimensions.add_argument("--size", type=int, help="Cubic side length")
    dimensions.add_argument("--shape", nargs=3, type=int, metavar=("X", "Y", "Z"))
    extract.add_argument("--state-mode", choices=("full", "name"), default="full")
    extract.add_argument("--overwrite", action="store_true")
    extract.set_defaults(handler=_cmd_extract)

    verify = subparsers.add_parser(
        "verify",
        help="Validate checksums and structure of an MCVX file",
    )
    verify.add_argument("--artifact", required=True, help="MCVX artifact path")
    verify.set_defaults(handler=_cmd_verify)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except KeyboardInterrupt:
        print("ERROR: interrupted", file=sys.stderr)
        return 130
    except Exception as exc:  # noqa: BLE001 - CLI boundary prints a concise failure
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
