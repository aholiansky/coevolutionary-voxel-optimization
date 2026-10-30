from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from mcstego.worldgen.anvil import sha256_file
from mcstego.worldgen.config import WorldgenConfig

USER_AGENT = "MCStego-Worldgen/0.2 (+research reproducibility)"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def write_json_atomic(path: str | Path, value: Any) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=target.name + ".",
        suffix=".tmp",
        dir=target.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return target


def write_text_atomic(path: str | Path, value: str) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=target.name + ".",
        suffix=".tmp",
        dir=target.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return target


def ensure_within(path: str | Path, parent: str | Path) -> Path:
    candidate = Path(path).resolve()
    root = Path(parent).resolve()
    if candidate == root or not candidate.is_relative_to(root):
        raise ValueError(f"Unsafe path outside dedicated directory: {candidate}")
    return candidate


def download_file(url: str, target: str | Path) -> Path:
    destination = Path(target)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".download")
    temporary.unlink(missing_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=120) as response, temporary.open("wb") as out:
            shutil.copyfileobj(response, out, length=1024 * 1024)
        if temporary.stat().st_size == 0:
            raise RuntimeError(f"Downloaded an empty file from {url}")
        os.replace(temporary, destination)
    except (OSError, urllib.error.URLError) as exc:
        temporary.unlink(missing_ok=True)
        raise RuntimeError(f"Cannot download {url}: {exc}") from exc
    return destination


def _copy_verified(source: Path, target: Path, expected_sha256: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if not target.is_file() or sha256_file(target) != expected_sha256:
            raise RuntimeError(f"Existing runtime artifact differs from the lock: {target}")
        return
    shutil.copy2(source, target)
    if sha256_file(target) != expected_sha256:
        target.unlink(missing_ok=True)
        raise RuntimeError(f"Copied artifact failed checksum verification: {target}")


def _validate_jar_file(path: Path) -> None:
    try:
        with zipfile.ZipFile(path) as archive:
            if not archive.namelist() or archive.testzip() is not None:
                raise RuntimeError(f"JAR archive failed integrity checking: {path}")
    except (OSError, zipfile.BadZipFile) as exc:
        raise RuntimeError(f"Artifact is not a valid JAR archive: {path}") from exc


def _validate_fabric_mod_jar(path: Path, expected_id: str, expected_version: str) -> None:
    _validate_jar_file(path)
    try:
        with zipfile.ZipFile(path) as archive:
            metadata = json.loads(archive.read("fabric.mod.json"))
    except (KeyError, OSError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Artifact is not a valid Fabric mod: {path}") from exc
    if metadata.get("id") != expected_id or metadata.get("version") != expected_version:
        raise RuntimeError(
            "Fabric mod metadata mismatch: "
            f"id={metadata.get('id')!r}, version={metadata.get('version')!r}"
        )


@dataclass(frozen=True, slots=True)
class BootstrapResult:
    server_directory: Path
    launcher_path: Path
    fabric_api_path: Path
    chunky_path: Path
    lock_path: Path


def bootstrap_runtime(
    config: WorldgenConfig,
    project_root: str | Path,
    *,
    accept_eula: bool = False,
) -> BootstrapResult:
    paths = config.resolved_paths(project_root)
    runtime_root = paths.runtime
    downloads = runtime_root / "downloads"
    server = runtime_root / "server"
    lock_path = runtime_root / "toolchain.lock.json"
    downloads.mkdir(parents=True, exist_ok=True)
    server.mkdir(parents=True, exist_ok=True)

    tool = config.toolchain
    declared = {
        "fabric_server": {
            "version": (
                f"mc-{tool.minecraft_version}/loader-{tool.fabric_loader_version}/"
                f"installer-{tool.fabric_installer_version}"
            ),
            "url": tool.fabric_server_url,
            "filename": tool.fabric_server_filename,
        },
        "chunky": {
            "version": tool.chunky_version,
            "modrinth_version_id": tool.chunky_modrinth_version_id,
            "url": tool.chunky_url,
            "filename": tool.chunky_filename,
        },
        "fabric_api": {
            "version": tool.fabric_api_version,
            "modrinth_version_id": tool.fabric_api_modrinth_version_id,
            "url": tool.fabric_api_url,
            "filename": tool.fabric_api_filename,
        },
    }

    existing_lock: dict[str, Any] | None = None
    if lock_path.exists():
        with lock_path.open("r", encoding="utf-8") as stream:
            existing_lock = json.load(stream)
        if existing_lock.get("schema_version") != 1:
            raise RuntimeError("Unsupported toolchain lock schema")
        if existing_lock.get("cohort_id") != config.cohort_id:
            raise RuntimeError("Toolchain lock belongs to a different cohort")
        for name, fields in declared.items():
            locked = existing_lock.get("artifacts", {}).get(name)
            if not isinstance(locked, dict):
                raise RuntimeError(f"Toolchain lock does not contain {name}")
            for field, value in fields.items():
                if locked.get(field) != value:
                    raise RuntimeError(f"Frozen toolchain field changed: {name}.{field}")

    resolved_artifacts: dict[str, dict[str, Any]] = {}
    for name, fields in declared.items():
        destination = downloads / str(fields["filename"])
        if not destination.exists():
            download_file(str(fields["url"]), destination)
        digest = sha256_file(destination)
        if existing_lock is not None:
            expected = existing_lock["artifacts"][name].get("sha256")
            if digest != expected:
                raise RuntimeError(
                    f"Checksum mismatch for {destination.name}: {digest} != {expected}"
                )
        resolved_artifacts[name] = {
            **fields,
            "sha256": digest,
            "size_bytes": destination.stat().st_size,
        }

    chunky_download = downloads / tool.chunky_filename
    fabric_api_download = downloads / tool.fabric_api_filename
    _validate_jar_file(downloads / tool.fabric_server_filename)
    _validate_fabric_mod_jar(chunky_download, "chunky", tool.chunky_version)
    _validate_fabric_mod_jar(fabric_api_download, "fabric-api", tool.fabric_api_version)
    launcher_target = server / tool.fabric_server_filename
    fabric_api_target = server / "mods" / tool.fabric_api_filename
    chunky_target = server / "mods" / tool.chunky_filename
    _copy_verified(
        downloads / tool.fabric_server_filename,
        launcher_target,
        resolved_artifacts["fabric_server"]["sha256"],
    )
    _copy_verified(
        fabric_api_download,
        fabric_api_target,
        resolved_artifacts["fabric_api"]["sha256"],
    )
    _copy_verified(
        chunky_download,
        chunky_target,
        resolved_artifacts["chunky"]["sha256"],
    )

    if existing_lock is None:
        write_json_atomic(
            lock_path,
            {
                "schema_version": 1,
                "cohort_id": config.cohort_id,
                "created_at": utc_now(),
                "artifacts": resolved_artifacts,
                "resolved_runtime_jars": None,
            },
        )

    eula_path = server / "eula.txt"
    accepted = False
    if eula_path.exists():
        accepted = any(
            line.strip().lower() == "eula=true"
            for line in eula_path.read_text(encoding="utf-8", errors="replace").splitlines()
        )
    if not accepted:
        if not accept_eula:
            raise PermissionError(
                "Mojang EULA has not been accepted. Re-run bootstrap with --accept-eula "
                "after reading https://aka.ms/MinecraftEULA"
            )
        write_text_atomic(
            eula_path,
            "# Accepted explicitly by the user for the local MCStego generator.\n"
            "eula=true\n",
        )

    return BootstrapResult(server, launcher_target, fabric_api_target, chunky_target, lock_path)


def record_or_verify_runtime_jars(server_directory: str | Path, lock_path: str | Path) -> None:
    server = Path(server_directory)
    lock_file = Path(lock_path)
    with lock_file.open("r", encoding="utf-8") as stream:
        lock = json.load(stream)
    inventory = {
        path.relative_to(server).as_posix(): sha256_file(path)
        for path in sorted(server.rglob("*.jar"))
        if path.is_file()
    }
    if not inventory:
        raise RuntimeError("No runtime JAR files were found after server startup")
    frozen = lock.get("resolved_runtime_jars")
    if frozen is None:
        lock["resolved_runtime_jars"] = inventory
        lock["runtime_resolved_at"] = utc_now()
        write_json_atomic(lock_file, lock)
        return
    if frozen != inventory:
        missing = sorted(set(frozen) - set(inventory))
        added = sorted(set(inventory) - set(frozen))
        changed = sorted(
            path for path in set(frozen).intersection(inventory) if frozen[path] != inventory[path]
        )
        raise RuntimeError(
            "Resolved Minecraft runtime differs from the lock "
            f"(missing={missing}, added={added}, changed={changed})"
        )


def render_server_properties(config: WorldgenConfig, seed: int, level_name: str) -> str:
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{2,63}", level_name):
        raise ValueError(f"Unsafe level name: {level_name!r}")
    if isinstance(seed, bool) or not -(1 << 63) <= seed <= (1 << 63) - 1:
        raise ValueError("Minecraft seed must be a signed 64-bit integer")
    properties = dict(config.server_properties)
    properties["level-name"] = level_name
    properties["level-seed"] = str(seed)
    return "".join(f"{key}={properties[key]}\n" for key in sorted(properties))


def _java_major(version_output: str) -> int | None:
    match = re.search(r'(?:java|openjdk) version "(?P<version>[^"\s]+)', version_output)
    if match is None:
        match = re.search(r"openjdk (?P<version>\d+(?:\.\d+)*)", version_output)
    if match is None:
        return None
    first = match.group("version").split(".")[0]
    if first == "1":
        parts = match.group("version").split(".")
        first = parts[1] if len(parts) > 1 else first
    return int(first) if first.isdigit() else None


def _deduplicate_paths(paths: Iterable[Path]) -> tuple[Path, ...]:
    seen: set[str] = set()
    result: list[Path] = []
    for path in paths:
        key = os.path.normcase(str(path.resolve()))
        if key not in seen:
            seen.add(key)
            result.append(path)
    return tuple(result)


def java_candidates(
    *,
    explicit: str | Path | None = None,
    crystal_path: str | Path | None = None,
) -> tuple[Path, ...]:
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    java_home = os.environ.get("JAVA_HOME")
    if java_home:
        candidates.append(Path(java_home) / "bin" / ("java.exe" if os.name == "nt" else "java"))
    discovered = shutil.which("java")
    if discovered:
        candidates.append(Path(discovered))
    if crystal_path:
        crystal = Path(crystal_path)
        if crystal.is_dir():
            executable = "java.exe" if os.name == "nt" else "java"
            for path in crystal.rglob(executable):
                if path.parent.name.lower() == "bin":
                    candidates.append(path)
                if len(candidates) >= 30:
                    break
    return _deduplicate_paths(path for path in candidates if path.is_file())


@dataclass(frozen=True, slots=True)
class JavaRuntime:
    path: Path
    major: int
    version_output: str


def inspect_java(path: str | Path) -> JavaRuntime | None:
    try:
        result = subprocess.run(
            [str(path), "-version"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    output = "\n".join(part.strip() for part in (result.stderr, result.stdout) if part.strip())
    major = _java_major(output)
    if result.returncode != 0 or major is None:
        return None
    return JavaRuntime(Path(path).resolve(), major, output)


def find_java(
    required_major: int,
    *,
    explicit: str | Path | None = None,
    crystal_path: str | Path | None = None,
) -> JavaRuntime:
    primary = [
        runtime
        for candidate in java_candidates(explicit=explicit, crystal_path=None)
        if (runtime := inspect_java(candidate)) is not None
    ]
    for runtime in primary:
        if runtime.major == required_major:
            return runtime
    crystal_candidates = java_candidates(explicit=None, crystal_path=crystal_path)
    known = {os.path.normcase(str(item.path)) for item in primary}
    from_crystal = [
        runtime
        for candidate in crystal_candidates
        if os.path.normcase(str(candidate.resolve())) not in known
        and (runtime := inspect_java(candidate)) is not None
    ]
    for runtime in from_crystal:
        if runtime.major == required_major:
            return runtime
    inspected = primary + from_crystal
    available = ", ".join(f"Java {item.major} at {item.path}" for item in inspected) or "none"
    raise RuntimeError(f"Java {required_major} is required; detected: {available}")


def _total_memory_bytes() -> int | None:
    if os.name == "nt":
        try:
            import ctypes

            class MemoryStatus(ctypes.Structure):
                _fields_ = [
                    ("length", ctypes.c_ulong),
                    ("memory_load", ctypes.c_ulong),
                    ("total_physical", ctypes.c_ulonglong),
                    ("available_physical", ctypes.c_ulonglong),
                    ("total_page_file", ctypes.c_ulonglong),
                    ("available_page_file", ctypes.c_ulonglong),
                    ("total_virtual", ctypes.c_ulonglong),
                    ("available_virtual", ctypes.c_ulonglong),
                    ("available_extended_virtual", ctypes.c_ulonglong),
                ]

            status = MemoryStatus()
            status.length = ctypes.sizeof(MemoryStatus)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return int(status.total_physical)
        except (AttributeError, OSError):
            return None
    try:
        return int(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES"))
    except (AttributeError, OSError, ValueError):
        return None


def doctor_report(
    config: WorldgenConfig,
    project_root: str | Path,
    *,
    java_path: str | Path | None = None,
    crystal_path: str | Path | None = None,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    paths = config.resolved_paths(root)
    checks: list[dict[str, Any]] = []

    python_ok = sys.version_info >= (3, 10)
    checks.append(
        {
            "name": "python",
            "status": "pass" if python_ok else "fail",
            "detail": platform.python_version(),
        }
    )
    try:
        java = find_java(
            config.toolchain.java_major,
            explicit=java_path,
            crystal_path=crystal_path,
        )
        checks.append(
            {
                "name": "java",
                "status": "pass",
                "detail": f"Java {java.major}",
                "path": str(java.path),
                "version_output": java.version_output,
            }
        )
    except RuntimeError as exc:
        checks.append({"name": "java", "status": "fail", "detail": str(exc)})

    paths.runtime.mkdir(parents=True, exist_ok=True)
    free_bytes = shutil.disk_usage(paths.runtime).free
    required_bytes = config.runtime.minimum_free_disk_gib * (1 << 30)
    checks.append(
        {
            "name": "disk",
            "status": "pass" if free_bytes >= required_bytes else "warn",
            "free_gib": round(free_bytes / (1 << 30), 2),
            "recommended_minimum_gib": config.runtime.minimum_free_disk_gib,
        }
    )
    memory = _total_memory_bytes()
    memory_status = (
        "pass"
        if memory is None or memory >= config.runtime.xmx_mb * (1 << 20)
        else "fail"
    )
    checks.append(
        {
            "name": "memory",
            "status": memory_status,
            "total_gib": round(memory / (1 << 30), 2) if memory is not None else None,
            "configured_xmx_mb": config.runtime.xmx_mb,
        }
    )
    crystal = Path(crystal_path) if crystal_path else None
    checks.append(
        {
            "name": "crystal_launcher",
            "status": "pass" if crystal is not None and crystal.is_dir() else "warn",
            "path": str(crystal) if crystal is not None else None,
            "detail": "optional; generator does not depend on the launcher",
        }
    )
    return {
        "schema_version": 1,
        "created_at": utc_now(),
        "cohort_id": config.cohort_id,
        "platform": platform.platform(),
        "project_root": str(root),
        "checks": checks,
        "ready": all(check["status"] != "fail" for check in checks),
    }
