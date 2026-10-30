from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class ExperimentManifest:
    """Minimum provenance required to reproduce one embedding run."""

    strategy: str
    strategy_config: dict[str, Any]
    carrier_id: str
    payload_sha256: str
    random_seed: int | None = None
    source_revision: str | None = None
    run_id: str = field(default_factory=lambda: uuid4().hex)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
    schema_version: int = 1

    @classmethod
    def create(
        cls,
        *,
        strategy: str,
        strategy_config: dict[str, Any],
        carrier_id: str,
        payload: bytes,
        random_seed: int | None = None,
        source_revision: str | None = None,
    ) -> ExperimentManifest:
        return cls(
            strategy=strategy,
            strategy_config=dict(strategy_config),
            carrier_id=carrier_id,
            payload_sha256=hashlib.sha256(payload).hexdigest(),
            random_seed=random_seed,
            source_revision=source_revision,
        )

    def save(self, path: str | Path, *, overwrite: bool = False) -> Path:
        target = Path(path)
        if target.exists() and not overwrite:
            raise FileExistsError(f"Refusing to overwrite experiment manifest: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return target

