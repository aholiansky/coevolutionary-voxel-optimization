from __future__ import annotations

import hashlib
import json
import queue
import re
import shutil
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from mcstego import __version__
from mcstego.worldgen.anvil import scan_world_region, world_artifact_hashes
from mcstego.worldgen.config import WorldgenConfig
from mcstego.worldgen.nbt import NbtFormatError, read_level_metadata
from mcstego.worldgen.runtime import (
    JavaRuntime,
    BootstrapResult,
    ensure_within,
    record_or_verify_runtime_jars,
    render_server_properties,
    utc_now,
    write_json_atomic,
    write_text_atomic,
)
from mcstego.worldgen.seeds import SeedEntry

MANIFEST_NAME = "mcstego-world-manifest.json"
WORKING_LEVEL_NAME = "mcstego_working_world"
NEAR_COMPLETE_CHUNK_MARGIN = 16
STALLED_CHUNK_FLUSH_SECONDS = 10.0
CHUNK_FLUSH_COOLDOWN_SECONDS = 10.0
CHUNK_FLUSH_SETTLE_SECONDS = 3.0


def _line_reports_chunky_completion(line: str) -> bool:
    folded = line.casefold()
    return "total time:" in folded and re.search(
        r"(?<!\d)100(?:[.,]0+)?%",
        folded,
    ) is not None


def _stalled_chunk_flush_due(
    *,
    present_chunks: int,
    expected_chunks: int,
    now: float,
    last_progress_at: float,
    last_flush_at: float | None,
) -> bool:
    threshold = max(0, expected_chunks - NEAR_COMPLETE_CHUNK_MARGIN)
    cooldown_elapsed = (
        last_flush_at is None or now - last_flush_at >= CHUNK_FLUSH_COOLDOWN_SECONDS
    )
    return (
        present_chunks >= threshold
        and now - last_progress_at >= STALLED_CHUNK_FLUSH_SECONDS
        and cooldown_elapsed
    )


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@dataclass(frozen=True, slots=True)
class GenerationPlan:
    world_id: str
    split: str
    seed: int
    destination: Path

    def to_dict(self, *, redact_seed: bool = False) -> dict[str, object]:
        return {
            "world_id": self.world_id,
            "split": self.split,
            "seed": "<sealed>" if redact_seed else self.seed,
            "destination": str(self.destination),
        }


def build_plans(
    config: WorldgenConfig,
    project_root: str | Path,
    split: str,
    entries: tuple[SeedEntry, ...],
    *,
    world_id: str | None = None,
) -> tuple[GenerationPlan, ...]:
    if split not in {"train", "validation", "test"}:
        raise ValueError(f"Unknown split: {split}")
    selected = tuple(entry for entry in entries if world_id is None or entry.id == world_id)
    if world_id is not None and not selected:
        raise ValueError(f"World id {world_id!r} is not present in split {split!r}")
    worlds_root = config.resolved_paths(project_root).worlds
    return tuple(
        GenerationPlan(entry.id, split, entry.seed, worlds_root / split / entry.id)
        for entry in selected
    )


class _ServerProcess:
    def __init__(
        self,
        command: list[str],
        cwd: Path,
        log_path: Path,
        *,
        startup_timeout_seconds: int,
        shutdown_timeout_seconds: int,
    ) -> None:
        self.command = command
        self.cwd = cwd
        self.log_path = log_path
        self.startup_timeout_seconds = startup_timeout_seconds
        self.shutdown_timeout_seconds = shutdown_timeout_seconds
        self.process: subprocess.Popen[str] | None = None
        self.ready = threading.Event()
        self.chunky_seen = threading.Event()
        self.chunky_finished = threading.Event()
        self.lines: queue.Queue[str] = queue.Queue()
        self.tail: deque[str] = deque(maxlen=80)
        self._reader_thread: threading.Thread | None = None

    def start(self) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.process = subprocess.Popen(
            self.command,
            cwd=self.cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        self._reader_thread = threading.Thread(target=self._read_output, daemon=True)
        self._reader_thread.start()

    def _read_output(self) -> None:
        assert self.process is not None and self.process.stdout is not None
        with self.log_path.open("a", encoding="utf-8", newline="\n") as log:
            for line in self.process.stdout:
                clean = line.rstrip("\r\n")
                log.write(clean + "\n")
                log.flush()
                self.tail.append(clean)
                self.lines.put(clean)
                print(clean, flush=True)
                folded = clean.casefold()
                if "done (" in folded and "for help" in folded:
                    self.ready.set()
                if "chunky" in folded:
                    self.chunky_seen.set()
                if _line_reports_chunky_completion(clean):
                    self.chunky_finished.set()

    def wait_ready(self) -> None:
        assert self.process is not None
        deadline = time.monotonic() + self.startup_timeout_seconds
        while not self.ready.wait(timeout=0.25):
            if self.process.poll() is not None:
                raise RuntimeError(
                    "Minecraft server exited before becoming ready. Last output:\n"
                    + "\n".join(self.tail)
                )
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    "Minecraft server startup timed out. Last output:\n" + "\n".join(self.tail)
                )

    def send(self, command: str) -> None:
        if "\n" in command or "\r" in command:
            raise ValueError("Server command must be one line")
        if self.process is None or self.process.poll() is not None or self.process.stdin is None:
            raise RuntimeError(f"Cannot send command to stopped server: {command}")
        self.process.stdin.write(command + "\n")
        self.process.stdin.flush()

    def wait(self) -> int:
        assert self.process is not None
        try:
            code = self.process.wait(timeout=self.shutdown_timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError(
                "Minecraft server did not stop within the configured timeout"
            ) from exc
        if self._reader_thread is not None:
            self._reader_thread.join(timeout=5)
        return code

    def emergency_stop(self) -> None:
        if self.process is None or self.process.poll() is not None:
            return
        try:
            self.send("chunky pause")
            self.send("save-all flush")
            self.send("stop")
            self.process.wait(timeout=min(60, self.shutdown_timeout_seconds))
        except (BrokenPipeError, OSError, RuntimeError, subprocess.TimeoutExpired):
            self.process.terminate()
            try:
                self.process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=10)


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def _load_toolchain_lock(path: Path) -> dict[str, Any]:
    lock = _load_json(path)
    if lock.get("schema_version") != 1:
        raise RuntimeError("Unsupported toolchain lock schema")
    return lock


def _write_world_manifest(
    world_path: Path,
    *,
    config: WorldgenConfig,
    plan: GenerationPlan,
    java: JavaRuntime,
    bootstrap: BootstrapResult,
    server_properties: str,
    started_at: str,
    completed_at: str,
) -> Path:
    scan = scan_world_region(world_path, config.bounds)
    if not scan.complete:
        raise RuntimeError(
            f"Cannot finalize {plan.world_id}: only {scan.present_chunks}/"
            f"{scan.expected_chunks} target chunks are valid"
        )
    level = read_level_metadata(world_path / "level.dat")
    if level.seed != plan.seed:
        raise RuntimeError(
            f"World seed mismatch for {plan.world_id}: level.dat={level.seed}, plan={plan.seed}"
        )
    if level.minecraft_version != config.toolchain.minecraft_version:
        raise RuntimeError(
            f"Minecraft version mismatch for {plan.world_id}: "
            f"level.dat={level.minecraft_version!r}, "
            f"expected={config.toolchain.minecraft_version!r}"
        )

    lock = _load_toolchain_lock(bootstrap.lock_path)
    artifact_hashes = world_artifact_hashes(world_path, config.bounds)
    manifest = {
        "schema_version": 1,
        "world_id": plan.world_id,
        "cohort_id": config.cohort_id,
        "split": plan.split,
        "seed": plan.seed,
        "immutable_cover": True,
        "minecraft": {
            "edition": "java",
            "version": level.minecraft_version,
            "data_version": level.data_version,
            "level_name": level.level_name,
        },
        "toolchain": {
            "fabric_loader_version": config.toolchain.fabric_loader_version,
            "fabric_installer_version": config.toolchain.fabric_installer_version,
            "fabric_api_version": config.toolchain.fabric_api_version,
            "fabric_api_modrinth_version_id": (
                config.toolchain.fabric_api_modrinth_version_id
            ),
            "chunky_version": config.toolchain.chunky_version,
            "chunky_modrinth_version_id": config.toolchain.chunky_modrinth_version_id,
            "locked_artifacts": lock.get("artifacts"),
            "resolved_runtime_jars": lock.get("resolved_runtime_jars"),
        },
        "java": {
            "major": java.major,
            "version_output": java.version_output,
        },
        "analysis_region": config.bounds.to_dict(),
        "region_scan": scan.to_dict(),
        "server_properties_sha256": hashlib.sha256(server_properties.encode("utf-8")).hexdigest(),
        "artifact_sha256": artifact_hashes,
        "generation": {
            "started_at": started_at,
            "completed_at": completed_at,
            "duration_seconds": round(
                (_parse_timestamp(completed_at) - _parse_timestamp(started_at)).total_seconds(),
                3,
            ),
            "status": "complete",
        },
        "mcstego_version": __version__,
    }
    return write_json_atomic(world_path / MANIFEST_NAME, manifest)


def verify_generated_world(
    world_path: str | Path,
    config: WorldgenConfig,
    *,
    expected_plan: GenerationPlan | None = None,
    verify_hashes: bool = True,
) -> dict[str, Any]:
    world = Path(world_path)
    errors: list[str] = []
    manifest_path = world / MANIFEST_NAME
    manifest: dict[str, Any] | None = None
    if not manifest_path.is_file():
        errors.append(f"Missing {MANIFEST_NAME}")
    else:
        try:
            manifest = _load_json(manifest_path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"Cannot read manifest: {exc}")

    scan = scan_world_region(world, config.bounds)
    if not scan.complete:
        errors.append(
            f"Target region is incomplete: {scan.present_chunks}/"
            f"{scan.expected_chunks} valid chunks"
        )

    level = None
    try:
        level = read_level_metadata(world / "level.dat")
    except (OSError, NbtFormatError) as exc:
        errors.append(f"Cannot read level.dat: {exc}")

    if manifest is not None:
        if manifest.get("schema_version") != 1:
            errors.append("Unsupported world manifest schema")
        if manifest.get("cohort_id") != config.cohort_id:
            errors.append("World manifest cohort differs from config")
        if level is not None and manifest.get("seed") != level.seed:
            errors.append("Manifest seed differs from level.dat")
        if level is not None and level.minecraft_version != config.toolchain.minecraft_version:
            errors.append(
                f"Minecraft version is {level.minecraft_version!r}, "
                f"expected {config.toolchain.minecraft_version!r}"
            )
        if expected_plan is not None:
            for field, expected in (
                ("world_id", expected_plan.world_id),
                ("split", expected_plan.split),
                ("seed", expected_plan.seed),
            ):
                if manifest.get(field) != expected:
                    errors.append(
                        f"Manifest {field}={manifest.get(field)!r}, expected={expected!r}"
                    )
        if verify_hashes and isinstance(manifest.get("artifact_sha256"), dict):
            try:
                current = world_artifact_hashes(world, config.bounds)
                if current != manifest["artifact_sha256"]:
                    errors.append("World artifact checksums differ from the frozen cover")
            except OSError as exc:
                errors.append(f"Cannot hash world artifacts: {exc}")
        elif verify_hashes:
            errors.append("Manifest does not contain artifact checksums")

    return {
        "world_path": str(world.resolve()),
        "world_id": manifest.get("world_id") if manifest else world.name,
        "valid": not errors,
        "errors": errors,
        "region_scan": scan.to_dict(),
        "seed": level.seed if level is not None else None,
        "minecraft_version": level.minecraft_version if level is not None else None,
    }


def _active_world_state(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return _load_json(path)


def _prepare_working_world(
    server: Path,
    plan: GenerationPlan,
) -> tuple[Path, Path, bool]:
    working = ensure_within(server / WORKING_LEVEL_NAME, server)
    active_path = ensure_within(server / "mcstego-active-world.json", server)
    active = _active_world_state(active_path)
    expected = {
        "schema_version": 1,
        "world_id": plan.world_id,
        "split": plan.split,
        "seed": plan.seed,
        "level_name": WORKING_LEVEL_NAME,
    }
    if active is not None:
        if working.exists() and not working.is_dir():
            raise RuntimeError(
                "Incomplete runtime state is inconsistent. Preserve the runtime directory and "
                "inspect mcstego-active-world.json before retrying."
            )
        for key, value in expected.items():
            if active.get(key) != value:
                raise RuntimeError(
                    f"Working world belongs to {active.get('world_id')!r}, not {plan.world_id!r}; "
                    "it will not be overwritten automatically."
                )
        return working, active_path, working.is_dir()
    if working.exists():
        raise RuntimeError(
            "A working world exists without mcstego-active-world.json and will not be "
            "overwritten automatically."
        )
    write_json_atomic(active_path, {**expected, "started_at": utc_now()})
    return working, active_path, False


def _run_one_world(
    config: WorldgenConfig,
    plan: GenerationPlan,
    *,
    java: JavaRuntime,
    bootstrap: BootstrapResult,
    paths_root: Path,
) -> dict[str, Any]:
    destination = plan.destination.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        report = verify_generated_world(destination, config, expected_plan=plan)
        if report["valid"]:
            active_path = bootstrap.server_directory / "mcstego-active-world.json"
            working = bootstrap.server_directory / WORKING_LEVEL_NAME
            if active_path.is_file() and not working.exists():
                active = _active_world_state(active_path)
                if active is not None and active.get("world_id") == plan.world_id:
                    active_path.unlink()
            print(f"[skip] {plan.world_id}: verified world already exists", flush=True)
            return {"status": "skipped", **report}
        raise RuntimeError(
            f"Destination exists but is not a valid frozen world: {destination}; "
            f"errors={report['errors']}"
        )

    working, active_path, resumed = _prepare_working_world(bootstrap.server_directory, plan)
    active = _active_world_state(active_path) or {}
    started_at = str(active.get("started_at") or utc_now())
    properties = render_server_properties(config, plan.seed, WORKING_LEVEL_NAME)
    write_text_atomic(bootstrap.server_directory / "server.properties", properties)

    logs = paths_root / "logs"
    log_path = logs / f"{plan.world_id}.log"
    command = [
        str(java.path),
        f"-Xms{config.runtime.xms_mb}M",
        f"-Xmx{config.runtime.xmx_mb}M",
        "-Dfile.encoding=UTF-8",
        "-Djava.awt.headless=true",
        "-jar",
        str(bootstrap.launcher_path),
        "nogui",
    ]
    server = _ServerProcess(
        command,
        bootstrap.server_directory,
        log_path,
        startup_timeout_seconds=config.runtime.startup_timeout_seconds,
        shutdown_timeout_seconds=config.runtime.shutdown_timeout_seconds,
    )
    try:
        print(
            f"[start] {plan.world_id} split={plan.split} resumed={str(resumed).lower()}",
            flush=True,
        )
        server.start()
        server.wait_ready()
        record_or_verify_runtime_jars(bootstrap.server_directory, bootstrap.lock_path)
        if not server.chunky_seen.wait(timeout=15):
            server.send("chunky selection")
            if not server.chunky_seen.wait(timeout=10):
                raise RuntimeError("Chunky did not announce itself in the server console")

        if resumed:
            server.send(f"chunky continue {WORKING_LEVEL_NAME}")
            time.sleep(1)
        server.send(f"chunky world {WORKING_LEVEL_NAME}")
        server.send("chunky shape square")
        server.send(
            "chunky corners "
            f"{config.bounds.min_block_x} {config.bounds.min_block_z} "
            f"{config.bounds.max_block_x} {config.bounds.max_block_z}"
        )
        server.send("chunky quiet 5")
        server.send("chunky start")

        deadline = time.monotonic() + config.runtime.generation_timeout_seconds
        last_present = -1
        max_present = -1
        last_progress_at = time.monotonic()
        last_flush_at: float | None = None
        while True:
            if server.process is None or server.process.poll() is not None:
                raise RuntimeError(
                    "Minecraft server exited during chunk generation. Last output:\n"
                    + "\n".join(server.tail)
                )
            now = time.monotonic()
            scan = scan_world_region(working, config.bounds)
            if scan.present_chunks > max_present:
                max_present = scan.present_chunks
                last_progress_at = now
            if scan.present_chunks != last_present:
                print(
                    f"[chunks] {plan.world_id}: {scan.present_chunks}/"
                    f"{scan.expected_chunks} valid",
                    flush=True,
                )
                last_present = scan.present_chunks
            if scan.complete:
                break
            if server.chunky_finished.is_set():
                print(
                    f"[chunky] {plan.world_id}: task complete; flushing cached chunks",
                    flush=True,
                )
                break
            if _stalled_chunk_flush_due(
                present_chunks=scan.present_chunks,
                expected_chunks=scan.expected_chunks,
                now=now,
                last_progress_at=last_progress_at,
                last_flush_at=last_flush_at,
            ):
                print(
                    f"[flush] {plan.world_id}: progress stalled near completion; "
                    "forcing chunk save",
                    flush=True,
                )
                server.send("save-all flush")
                last_flush_at = now
                time.sleep(CHUNK_FLUSH_SETTLE_SECONDS)
                continue
            if now >= deadline:
                raise TimeoutError(
                    f"Generation timed out for {plan.world_id} at "
                    f"{scan.present_chunks}/{scan.expected_chunks} chunks"
                )
            time.sleep(config.runtime.poll_interval_seconds)

        server.send(f"chunky pause {WORKING_LEVEL_NAME}")
        time.sleep(1)
        server.send("save-all flush")
        time.sleep(CHUNK_FLUSH_SETTLE_SECONDS)
        server.send("stop")
        exit_code = server.wait()
        if exit_code != 0:
            raise RuntimeError(f"Minecraft server exited with code {exit_code}")
    except BaseException:
        server.emergency_stop()
        raise

    final_scan = scan_world_region(working, config.bounds)
    print(
        f"[saved] {plan.world_id}: {final_scan.present_chunks}/"
        f"{final_scan.expected_chunks} valid after server shutdown",
        flush=True,
    )
    if not final_scan.complete:
        raise RuntimeError(
            f"Chunky finished but the saved region is incomplete for {plan.world_id}: "
            f"{final_scan.present_chunks}/{final_scan.expected_chunks} valid; "
            f"missing={list(final_scan.missing_chunks[:16])}; "
            f"invalid={list(final_scan.invalid_chunks[:16])}"
        )

    completed_at = utc_now()
    _write_world_manifest(
        working,
        config=config,
        plan=plan,
        java=java,
        bootstrap=bootstrap,
        server_properties=properties,
        started_at=started_at,
        completed_at=completed_at,
    )
    shutil.move(str(working), str(destination))
    active_path.unlink(missing_ok=True)
    report = verify_generated_world(destination, config, expected_plan=plan)
    if not report["valid"]:
        raise RuntimeError(f"Post-move verification failed for {plan.world_id}: {report['errors']}")
    print(f"[complete] {plan.world_id}: {destination}", flush=True)
    return {"status": "generated", **report}


def generate_worlds(
    config: WorldgenConfig,
    plans: tuple[GenerationPlan, ...],
    *,
    java: JavaRuntime,
    bootstrap: BootstrapResult,
    project_root: str | Path,
) -> list[dict[str, Any]]:
    run_root = config.resolved_paths(project_root).runs
    run_root.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    for plan in plans:
        result = _run_one_world(
            config,
            plan,
            java=java,
            bootstrap=bootstrap,
            paths_root=run_root,
        )
        results.append(result)
        write_json_atomic(
            run_root / "generation-status.json",
            {
                "schema_version": 1,
                "updated_at": utc_now(),
                "cohort_id": config.cohort_id,
                "results": results,
            },
        )
    return results


def verify_plans(
    config: WorldgenConfig,
    plans: tuple[GenerationPlan, ...],
    *,
    verify_hashes: bool = True,
) -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    for plan in plans:
        reports.append(
            verify_generated_world(
                plan.destination,
                config,
                expected_plan=plan,
                verify_hashes=verify_hashes,
            )
        )
    return reports
