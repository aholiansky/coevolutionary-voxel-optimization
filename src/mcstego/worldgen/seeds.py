from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

COMMITMENT_DOMAIN = "mcstego-test-seed-commitment-v1"
MIN_SEED = -(1 << 63)
MAX_SEED = (1 << 63) - 1


@dataclass(frozen=True, slots=True)
class SeedEntry:
    id: str
    seed: int


@dataclass(frozen=True, slots=True)
class TestCommitment:
    id: str
    commitment_sha256: str


@dataclass(frozen=True, slots=True)
class PrivateTestEntry:
    id: str
    seed: int
    nonce_hex: str


@dataclass(frozen=True, slots=True)
class PublicSeedRegistry:
    schema_version: int
    cohort_id: str
    commitment_scheme: str
    train: tuple[SeedEntry, ...]
    validation: tuple[SeedEntry, ...]
    test: tuple[TestCommitment, ...]


@dataclass(frozen=True, slots=True)
class PrivateTestRegistry:
    schema_version: int
    cohort_id: str
    test: tuple[PrivateTestEntry, ...]


def _load_json_object(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    with source.open("r", encoding="utf-8") as stream:
        raw = json.load(stream)
    if not isinstance(raw, dict):
        raise ValueError(f"JSON root must be an object: {source}")
    return raw


def _validate_id(value: Any, expected_prefix: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(rf"{expected_prefix}-\d{{3}}", value):
        raise ValueError(f"Invalid {expected_prefix} seed id: {value!r}")
    return value


def _validate_seed(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    if not MIN_SEED <= value <= MAX_SEED:
        raise ValueError(f"{name} is outside the signed 64-bit Minecraft seed range")
    return value


def _seed_entries(raw: Any, prefix: str) -> tuple[SeedEntry, ...]:
    if not isinstance(raw, list):
        raise ValueError(f"{prefix} must be a list")
    entries: list[SeedEntry] = []
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"{prefix}[{index}] must be an object")
        entries.append(
            SeedEntry(
                id=_validate_id(item.get("id"), prefix),
                seed=_validate_seed(item.get("seed"), f"{prefix}[{index}].seed"),
            )
        )
    return tuple(entries)


def test_seed_commitment(entry: PrivateTestEntry) -> str:
    payload = (
        f"{COMMITMENT_DOMAIN}\0{entry.id}\0{entry.seed}\0{entry.nonce_hex}"
    ).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def load_public_registry(
    path: str | Path,
    *,
    expected_cohort_id: str | None = None,
    expected_counts: dict[str, int] | None = None,
) -> PublicSeedRegistry:
    raw = _load_json_object(path)
    if raw.get("schema_version") != 1:
        raise ValueError("Unsupported public seed registry schema")
    cohort_id = raw.get("cohort_id")
    if not isinstance(cohort_id, str) or not cohort_id:
        raise ValueError("Invalid public seed cohort_id")
    if expected_cohort_id is not None and cohort_id != expected_cohort_id:
        raise ValueError(
            f"Seed cohort mismatch: registry={cohort_id}, config={expected_cohort_id}"
        )
    if raw.get("commitment_scheme") != COMMITMENT_DOMAIN:
        raise ValueError("Unsupported test seed commitment scheme")

    train = _seed_entries(raw.get("train"), "train")
    validation = _seed_entries(raw.get("validation"), "validation")
    raw_test = raw.get("test")
    if not isinstance(raw_test, list):
        raise ValueError("test must be a list")
    test: list[TestCommitment] = []
    for index, item in enumerate(raw_test, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"test[{index}] must be an object")
        identifier = _validate_id(item.get("id"), "test")
        digest = item.get("commitment_sha256")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError(f"Invalid test commitment for {identifier}")
        if "seed" in item:
            raise ValueError("Public test records must not expose seeds")
        test.append(TestCommitment(identifier, digest))

    identifiers = [entry.id for entry in train + validation] + [entry.id for entry in test]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("Seed registry contains duplicate ids")
    public_seeds = [entry.seed for entry in train + validation]
    if len(public_seeds) != len(set(public_seeds)):
        raise ValueError("Training and validation splits contain duplicate seeds")

    registry = PublicSeedRegistry(
        schema_version=1,
        cohort_id=cohort_id,
        commitment_scheme=COMMITMENT_DOMAIN,
        train=train,
        validation=validation,
        test=tuple(test),
    )
    if expected_counts is not None:
        actual = {
            "train": len(registry.train),
            "validation": len(registry.validation),
            "test": len(registry.test),
        }
        if actual != expected_counts:
            raise ValueError(
                f"Seed split counts differ: registry={actual}, config={expected_counts}"
            )
    return registry


def load_private_test_registry(
    path: str | Path,
    *,
    expected_cohort_id: str | None = None,
) -> PrivateTestRegistry:
    raw = _load_json_object(path)
    if raw.get("schema_version") != 1:
        raise ValueError("Unsupported private test seed registry schema")
    cohort_id = raw.get("cohort_id")
    if not isinstance(cohort_id, str) or not cohort_id:
        raise ValueError("Invalid private seed cohort_id")
    if expected_cohort_id is not None and cohort_id != expected_cohort_id:
        raise ValueError(
            f"Private seed cohort mismatch: registry={cohort_id}, config={expected_cohort_id}"
        )
    raw_test = raw.get("test")
    if not isinstance(raw_test, list):
        raise ValueError("Private test list is missing")
    entries: list[PrivateTestEntry] = []
    for index, item in enumerate(raw_test, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"test[{index}] must be an object")
        identifier = _validate_id(item.get("id"), "test")
        nonce = item.get("nonce_hex")
        if not isinstance(nonce, str) or not re.fullmatch(r"[0-9a-f]{64}", nonce):
            raise ValueError(f"Invalid nonce for {identifier}")
        entries.append(
            PrivateTestEntry(
                id=identifier,
                seed=_validate_seed(item.get("seed"), f"test[{index}].seed"),
                nonce_hex=nonce,
            )
        )
    if len({entry.id for entry in entries}) != len(entries):
        raise ValueError("Private test registry contains duplicate ids")
    if len({entry.seed for entry in entries}) != len(entries):
        raise ValueError("Private test registry contains duplicate seeds")
    return PrivateTestRegistry(1, cohort_id, tuple(entries))


def unlock_test_entries(
    public: PublicSeedRegistry,
    private: PrivateTestRegistry,
) -> tuple[SeedEntry, ...]:
    """Verify commitments and return test seeds only after an explicit private-file load."""

    if public.cohort_id != private.cohort_id:
        raise ValueError("Public and private seed cohorts differ")
    public_by_id = {entry.id: entry for entry in public.test}
    private_by_id = {entry.id: entry for entry in private.test}
    if set(public_by_id) != set(private_by_id):
        raise ValueError("Public commitments and private test ids differ")

    unlocked: list[SeedEntry] = []
    for identifier in (entry.id for entry in public.test):
        private_entry = private_by_id[identifier]
        actual = test_seed_commitment(private_entry)
        expected = public_by_id[identifier].commitment_sha256
        if actual != expected:
            raise ValueError(f"Commitment mismatch for {identifier}")
        unlocked.append(SeedEntry(identifier, private_entry.seed))

    public_seeds = {entry.seed for entry in public.train + public.validation}
    test_seeds = {entry.seed for entry in unlocked}
    if public_seeds.intersection(test_seeds):
        raise ValueError("A test seed also occurs in train or validation")
    return tuple(unlocked)


def entries_for_split(
    registry: PublicSeedRegistry,
    split: str,
    *,
    private_test_registry: PrivateTestRegistry | None = None,
) -> tuple[SeedEntry, ...]:
    if split == "train":
        return registry.train
    if split == "validation":
        return registry.validation
    if split == "test":
        if private_test_registry is None:
            raise PermissionError("Test seeds require the separate private registry")
        return unlock_test_entries(registry, private_test_registry)
    raise ValueError(f"Unknown split: {split}")
