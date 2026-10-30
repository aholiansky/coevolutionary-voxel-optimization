from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from mcstego.worldgen.config import WorldgenConfig, load_worldgen_config
from mcstego.worldgen.generator import build_plans, generate_worlds, verify_plans
from mcstego.worldgen.runtime import (
    bootstrap_runtime,
    doctor_report,
    find_java,
    write_json_atomic,
)
from mcstego.worldgen.seeds import (
    PublicSeedRegistry,
    entries_for_split,
    load_private_test_registry,
    load_public_registry,
    unlock_test_entries,
)


def _absolute(root: Path, path: str | Path) -> Path:
    candidate = Path(path)
    return candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()


def _load_inputs(args: argparse.Namespace) -> tuple[Path, WorldgenConfig, PublicSeedRegistry]:
    root = Path(args.project_root).resolve()
    config = load_worldgen_config(_absolute(root, args.config))
    seeds = load_public_registry(
        _absolute(root, args.seeds),
        expected_cohort_id=config.cohort_id,
        expected_counts=config.split_counts,
    )
    return root, config, seeds


def _split_entries(
    args: argparse.Namespace,
    root: Path,
    registry: PublicSeedRegistry,
):
    if args.split != "test":
        return entries_for_split(registry, args.split)
    if not getattr(args, "unlock_test_set", False):
        raise PermissionError(
            "Test split is sealed. Add --unlock-test-set and provide --test-key only for "
            "the final evaluation."
        )
    test_key = getattr(args, "test_key", None)
    if not test_key:
        raise PermissionError("The sealed test split requires --test-key PATH")
    private = load_private_test_registry(
        _absolute(root, test_key),
        expected_cohort_id=registry.cohort_id,
    )
    return entries_for_split(registry, "test", private_test_registry=private)


def _print_json(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def _cmd_doctor(args: argparse.Namespace) -> int:
    root, config, _ = _load_inputs(args)
    report = doctor_report(
        config,
        root,
        java_path=args.java,
        crystal_path=args.crystal_path,
    )
    output = _absolute(root, args.output)
    write_json_atomic(output, report)
    _print_json(report)
    return 0 if report["ready"] else 2


def _cmd_registry(args: argparse.Namespace) -> int:
    root, config, registry = _load_inputs(args)
    result: dict[str, object] = {
        "valid": True,
        "cohort_id": config.cohort_id,
        "counts": {
            "train": len(registry.train),
            "validation": len(registry.validation),
            "test": len(registry.test),
        },
        "test_commitments_verified": False,
    }
    if args.test_key:
        private = load_private_test_registry(
            _absolute(root, args.test_key),
            expected_cohort_id=registry.cohort_id,
        )
        unlocked = unlock_test_entries(registry, private)
        result["test_commitments_verified"] = True
        result["verified_test_ids"] = [entry.id for entry in unlocked]
    _print_json(result)
    return 0


def _cmd_bootstrap(args: argparse.Namespace) -> int:
    root, config, _ = _load_inputs(args)
    java = find_java(
        config.toolchain.java_major,
        explicit=args.java,
        crystal_path=args.crystal_path,
    )
    result = bootstrap_runtime(config, root, accept_eula=args.accept_eula)
    _print_json(
        {
            "ready": True,
            "cohort_id": config.cohort_id,
            "java_major": java.major,
            "server_directory": str(result.server_directory),
            "toolchain_lock": str(result.lock_path),
        }
    )
    return 0


def _cmd_plan(args: argparse.Namespace) -> int:
    root, config, registry = _load_inputs(args)
    entries = _split_entries(args, root, registry)
    plans = build_plans(config, root, args.split, entries, world_id=args.world_id)
    _print_json(
        {
            "cohort_id": config.cohort_id,
            "split": args.split,
            "world_count": len(plans),
            "analysis_region": config.bounds.to_dict(),
            "plans": [
                plan.to_dict(redact_seed=args.split == "test") for plan in plans
            ],
        }
    )
    return 0


def _cmd_generate(args: argparse.Namespace) -> int:
    root, config, registry = _load_inputs(args)
    entries = _split_entries(args, root, registry)
    plans = build_plans(config, root, args.split, entries, world_id=args.world_id)
    java = find_java(
        config.toolchain.java_major,
        explicit=args.java,
        crystal_path=args.crystal_path,
    )
    bootstrap = bootstrap_runtime(config, root, accept_eula=False)
    results = generate_worlds(
        config,
        plans,
        java=java,
        bootstrap=bootstrap,
        project_root=root,
    )
    _print_json(
        {
            "cohort_id": config.cohort_id,
            "split": args.split,
            "generated": sum(item["status"] == "generated" for item in results),
            "skipped": sum(item["status"] == "skipped" for item in results),
            "valid": all(item["valid"] for item in results),
        }
    )
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    root, config, registry = _load_inputs(args)
    entries = _split_entries(args, root, registry)
    plans = build_plans(config, root, args.split, entries, world_id=args.world_id)
    reports = verify_plans(config, plans, verify_hashes=not args.skip_hashes)
    summary = {
        "cohort_id": config.cohort_id,
        "split": args.split,
        "valid": all(report["valid"] for report in reports),
        "worlds": reports,
    }
    if args.output:
        write_json_atomic(_absolute(root, args.output), summary)
    _print_json(summary)
    return 0 if summary["valid"] else 3


def _add_split_arguments(parser: argparse.ArgumentParser, *, allow_test: bool = True) -> None:
    parser.add_argument("--split", choices=("train", "validation", "test"), required=True)
    parser.add_argument("--world-id", help="Process just one id from the selected split")
    if allow_test:
        parser.add_argument("--unlock-test-set", action="store_true")
        parser.add_argument("--test-key", help="Path to the separate private test seed file")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="worldgen",
        description="Reproducible Minecraft Java world generation for MCStego",
    )
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--config", default="config/worldgen.json")
    parser.add_argument("--seeds", default="config/seeds.public.json")
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor = subparsers.add_parser(
        "doctor",
        help="Check local prerequisites without launching Minecraft",
    )
    doctor.add_argument("--java", help="Explicit path to java/java.exe")
    doctor.add_argument("--crystal-path", default=r"C:\Apps\Crystal-Launcher")
    doctor.add_argument("--output", default="runs/worldgen/doctor.json")
    doctor.set_defaults(handler=_cmd_doctor)

    registry = subparsers.add_parser("registry", help="Validate public split metadata")
    registry.add_argument("--test-key", help="Optionally verify sealed test commitments")
    registry.set_defaults(handler=_cmd_registry)

    bootstrap = subparsers.add_parser("bootstrap", help="Download and lock the headless toolchain")
    bootstrap.add_argument("--java", help="Explicit path to java/java.exe")
    bootstrap.add_argument("--crystal-path", default=r"C:\Apps\Crystal-Launcher")
    bootstrap.add_argument("--accept-eula", action="store_true")
    bootstrap.set_defaults(handler=_cmd_bootstrap)

    plan = subparsers.add_parser("plan", help="Print the immutable world-generation plan")
    _add_split_arguments(plan)
    plan.set_defaults(handler=_cmd_plan)

    generate = subparsers.add_parser("generate", help="Generate or safely resume a split")
    _add_split_arguments(generate)
    generate.add_argument("--java", help="Explicit path to java/java.exe")
    generate.add_argument("--crystal-path", default=r"C:\Apps\Crystal-Launcher")
    generate.set_defaults(handler=_cmd_generate)

    verify = subparsers.add_parser("verify", help="Verify completeness, seed and checksums")
    _add_split_arguments(verify)
    verify.add_argument("--skip-hashes", action="store_true")
    verify.add_argument("--output", help="Optional JSON report path")
    verify.set_defaults(handler=_cmd_verify)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except KeyboardInterrupt:
        print(
            "ERROR: interrupted; the working world was retained for a safe resume",
            file=sys.stderr,
        )
        return 130
    except Exception as exc:  # noqa: BLE001 - CLI boundary prints a concise failure
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
