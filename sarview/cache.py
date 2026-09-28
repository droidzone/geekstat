"""Local cache of sadf JSON, keyed by file size and mtime."""

from __future__ import annotations

import json
from pathlib import Path

from sarview.source import RemoteFile


class DiskCache:
    def __init__(self, root: Path, host: str):
        self.root = Path(root) / host
        self.files = self.root / "files"
        self.catalog_path = self.root / "catalog.json"

    def load_catalog(self) -> dict | None:
        return _read_json(self.catalog_path)

    def save_catalog(self, payload: dict) -> None:
        _write_json(self.catalog_path, payload)

    def lookup(self, remote: RemoteFile, timezone_name: str, offset: str) -> dict | None:
        blob = _read_json(self.files / f"{remote.name}.json")
        if not _matches(blob, remote, timezone_name, offset):
            return None
        return blob

    def put(
        self,
        remote: RemoteFile,
        timezone_name: str,
        offset: str,
        document: dict,
        sample_dates: list[str],
    ) -> None:
        _write_json(
            self.files / f"{remote.name}.json",
            {
                "size": remote.size,
                "mtime": remote.mtime,
                "timezone": timezone_name,
                "utc_offset": offset,
                "sample_dates": sample_dates,
                "document": document,
            },
        )


def _matches(blob: dict | None, remote: RemoteFile, timezone_name: str, offset: str) -> bool:
    if not isinstance(blob, dict) or not isinstance(blob.get("document"), dict):
        return False
    try:
        size = int(blob.get("size"))
        mtime = int(blob.get("mtime"))
    except (TypeError, ValueError):
        return False
    return (
        size == int(remote.size)
        and mtime == int(remote.mtime)
        and blob.get("timezone") == timezone_name
        and blob.get("utc_offset") == offset
    )


def _read_json(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return None
    return value if isinstance(value, dict) else None


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    temporary.replace(path)
