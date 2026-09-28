"""Assemble a local day from cached or freshly decoded sa files."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from sarview.cache import DiskCache
from sarview.errors import SarviewError
from sarview.parse import parse_sadf, prune_idle
from sarview.source import Probe, RemoteFile
from sarview.tz import covered_local_dates, offset_minutes, resolve_zone
from sarview.validate import validate_date
from sarview.window import filter_samples


@dataclass
class Catalog:
    timezone: str
    utc_offset: str
    hostname: str
    files: list[RemoteFile]
    dates: list[str]
    warnings: list[str]
    fetched_at: float
    zone: object
    from_cache: bool = False
    checked_server: bool = False


class MonitorService:
    def __init__(self, source, cache: DiskCache, catalog_ttl: int = 120, now=None, log=None):
        self.source = source
        self.cache = cache
        self.catalog_ttl = catalog_ttl
        self._now = now or time.time
        self._log = log or (lambda message: print(message, flush=True))
        self._lock = threading.RLock()
        self._catalog: Catalog | None = None
        self._probed_now = False

    def get_catalog(self, refresh: bool = False) -> Catalog:
        with self._lock:
            return self._catalog_locked(refresh)

    def get_day(
        self,
        day: str,
        refresh: bool = False,
        start: str | None = None,
        end: str | None = None,
    ) -> dict:
        with self._lock:
            day = validate_date(day)
            catalog = self._catalog_locked(refresh)
            if day not in catalog.dates:
                raise SarviewError(f"no sysstat data for {day}", status=404)
            needed = [remote for remote in catalog.files if day in self._dates_for(remote, catalog)]
            documents: dict[str, dict] = {}
            origins: dict[str, str] = {}
            to_fetch: list[RemoteFile] = []
            for remote in needed:
                cached = self.cache.lookup(remote, catalog.timezone, catalog.utc_offset)
                if cached is None:
                    to_fetch.append(remote)
                    continue
                documents[remote.name] = cached["document"]
                origins[remote.name] = "cache"
                self._log(f"cache hit {remote.name}")
            network = "none"
            if to_fetch:
                names = [remote.name for remote in to_fetch]
                self._log(f"ssh sadf {' '.join(names)}")
                fetched = self.source.fetch_files(names)
                for remote in to_fetch:
                    document = fetched[remote.name]
                    parsed = parse_sadf(document, catalog.zone)
                    sample_dates = sorted({sample["local_date"] for sample in parsed.samples})
                    self.cache.put(remote, catalog.timezone, catalog.utc_offset, document, sample_dates)
                    documents[remote.name] = document
                    origins[remote.name] = "ssh"
                network = "decode"
            elif self._probed_now and getattr(self.source, "remote", False):
                network = "catalog"
            if not getattr(self.source, "remote", False):
                network = "demo"
            groups = []
            restarts = []
            for remote in needed:
                parsed = parse_sadf(documents[remote.name], catalog.zone)
                groups.append((remote.name, parsed.samples))
                restarts.extend(parsed.restarts)
            merged = _merge(groups)
            day_samples = [sample for sample in merged if sample["local_date"] == day]
            day_samples, idle_disks, idle_ifaces = prune_idle(day_samples)
            if start or end:
                if not (start and end):
                    raise SarviewError("start and end must be set together")
                day_samples = filter_samples(day_samples, catalog.zone, start, end)
            visible_restarts = [item for item in restarts if item["local_date"] == day]
            return {
                "host": getattr(self.source, "host", catalog.hostname),
                "hostname": catalog.hostname,
                "timezone": catalog.timezone,
                "utc_offset": catalog.utc_offset,
                "offset_minutes": offset_minutes(catalog.zone, day),
                "date": day,
                "network": network,
                "catalog_age_seconds": max(0, int(self._now() - catalog.fetched_at)),
                "files": [{"name": remote.name, "source": origins.get(remote.name, "cache")} for remote in needed],
                "idle_disks": idle_disks,
                "idle_ifaces": idle_ifaces,
                "restarts": visible_restarts,
                "warnings": catalog.warnings,
                "samples": day_samples,
            }

    def _catalog_locked(self, refresh: bool) -> Catalog:
        self._probed_now = False
        if not refresh and self._catalog is not None:
            age = self._now() - self._catalog.fetched_at
            if 0 <= age <= self.catalog_ttl:
                return self._catalog
        if not refresh:
            saved = self.cache.load_catalog()
            catalog = self._catalog_from_disk(saved)
            if catalog is not None:
                self._catalog = catalog
                self._log("catalog from local cache")
                return catalog
        self._probed_now = True
        self._log(f"ssh catalog {getattr(self.source, 'host', '')}".strip())
        probe = self.source.probe()
        catalog = self._from_probe(probe, checked_server=True)
        self.cache.save_catalog(self._catalog_dict(catalog))
        self._catalog = catalog
        return catalog

    def _catalog_from_disk(self, saved: dict | None) -> Catalog | None:
        if not saved:
            return None
        try:
            age = self._now() - float(saved["fetched_at"])
        except (KeyError, TypeError, ValueError):
            return None
        if age < 0 or age > self.catalog_ttl:
            return None
        try:
            return self._from_parts(
                timezone_name=saved["timezone"],
                offset=saved["utc_offset"],
                hostname=saved["hostname"],
                files=[RemoteFile(**item) for item in saved["files"]],
                warnings=list(saved.get("warnings") or []),
                fetched_at=float(saved["fetched_at"]),
                from_cache=True,
                checked_server=False,
            )
        except (KeyError, TypeError, SarviewError):
            return None

    def _from_probe(self, probe: Probe, checked_server: bool) -> Catalog:
        return self._from_parts(
            timezone_name=probe.timezone,
            offset=probe.utc_offset,
            hostname=probe.hostname,
            files=list(probe.files),
            warnings=list(probe.warnings),
            fetched_at=self._now(),
            from_cache=False,
            checked_server=checked_server,
        )

    def _from_parts(
        self,
        timezone_name: str,
        offset: str,
        hostname: str,
        files: list[RemoteFile],
        warnings: list[str],
        fetched_at: float,
        from_cache: bool,
        checked_server: bool,
    ) -> Catalog:
        zone_name, zone = resolve_zone(timezone_name, offset)
        dates: set[str] = set()
        catalog = Catalog(
            timezone=zone_name,
            utc_offset=offset,
            hostname=hostname,
            files=files,
            dates=[],
            warnings=warnings,
            fetched_at=fetched_at,
            zone=zone,
            from_cache=from_cache,
            checked_server=checked_server,
        )
        for remote in files:
            dates |= self._dates_for(remote, catalog)
        catalog.dates = sorted(dates)
        return catalog

    def _dates_for(self, remote: RemoteFile, catalog: Catalog) -> set[str]:
        cached = self.cache.lookup(remote, catalog.timezone, catalog.utc_offset)
        sample_dates = cached.get("sample_dates") if cached else None
        if isinstance(sample_dates, list) and sample_dates:
            return {str(day) for day in sample_dates}
        return covered_local_dates(
            remote.file_date,
            remote.file_timezone,
            remote.mtime,
            remote.name,
            catalog.zone,
        )

    def _catalog_dict(self, catalog: Catalog) -> dict:
        return {
            "fetched_at": catalog.fetched_at,
            "timezone": catalog.timezone,
            "utc_offset": catalog.utc_offset,
            "hostname": catalog.hostname,
            "warnings": catalog.warnings,
            "files": [
                {
                    "name": remote.name,
                    "size": remote.size,
                    "mtime": remote.mtime,
                    "file_date": remote.file_date,
                    "file_timezone": remote.file_timezone,
                }
                for remote in catalog.files
            ],
        }

    def catalog_payload(self, refresh: bool = False) -> dict:
        catalog = self.get_catalog(refresh=refresh)
        network = "demo"
        if getattr(self.source, "remote", False):
            network = "catalog" if catalog.checked_server else "none"
        return {
            "host": getattr(self.source, "host", catalog.hostname),
            "hostname": catalog.hostname,
            "timezone": catalog.timezone,
            "utc_offset": catalog.utc_offset,
            "dates": catalog.dates,
            "files": [remote.name for remote in catalog.files],
            "warnings": catalog.warnings,
            "network": network,
            "catalog_age_seconds": max(0, int(self._now() - catalog.fetched_at)),
        }


def _merge(groups: list[tuple[str, list[dict]]]) -> list[dict]:
    ranked = sorted(groups, key=lambda item: _rank(item[0]))
    chosen: dict[int, dict] = {}
    for _name, samples in ranked:
        for sample in samples:
            chosen[int(round(sample["epoch"]))] = sample
    return [chosen[key] for key in sorted(chosen)]


def _rank(name: str) -> tuple[int, int]:
    base = name.split(".", 1)[0]
    dated = 1 if len(base) == 10 else 0
    plain = 0 if name.endswith((".xz", ".gz", ".bz2")) else 1
    return dated, plain
