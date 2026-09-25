from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.persistence.models import ProductStructureSnapshot
from backend.app.security.crypto import canonical_json_bytes, sha256_hex


@dataclass(frozen=True)
class StructureImportResult:
    snapshot: ProductStructureSnapshot
    status: str
    warning: str | None = None


class ProductStructureProvider(Protocol):
    def load(self) -> dict[str, Any]: ...


class JsonProductStructureProvider:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load(self) -> dict[str, Any]:
        value = json.loads(self.path.read_text(encoding="utf-8"))
        required = {"assembly_id", "revision", "components", "relations"}
        missing = required - value.keys()
        if missing:
            raise ValueError(f"product structure missing fields: {', '.join(sorted(missing))}")
        if not isinstance(value["components"], list) or not isinstance(value["relations"], list):
            raise ValueError("components and relations must be arrays")
        return value


def import_structure(db: Session, provider: ProductStructureProvider) -> StructureImportResult:
    value = provider.load()
    content_hash = sha256_hex(canonical_json_bytes(value))
    exact = db.scalar(
        select(ProductStructureSnapshot).where(
            ProductStructureSnapshot.assembly_id == value["assembly_id"],
            ProductStructureSnapshot.revision == value["revision"],
            ProductStructureSnapshot.content_hash == content_hash,
        )
    )
    if exact:
        return StructureImportResult(exact, "unchanged")
    former = db.scalar(
        select(ProductStructureSnapshot)
        .where(
            ProductStructureSnapshot.assembly_id == value["assembly_id"],
            ProductStructureSnapshot.revision == value["revision"],
        )
        .order_by(ProductStructureSnapshot.created_at.desc())
        .limit(1)
    )
    snapshot = ProductStructureSnapshot(
        assembly_id=value["assembly_id"],
        revision=value["revision"],
        content_hash=content_hash,
        components=value["components"],
        relations=value["relations"],
    )
    db.add(snapshot)
    db.flush()
    return StructureImportResult(
        snapshot,
        "created",
        "REVISION_CONTENT_CHANGED" if former else None,
    )
