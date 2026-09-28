"""Turn sadf JSON into one dict per original sample."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone, tzinfo

_PARTITION = re.compile(r"^((?:sd|vd|xvd|hd)[a-z])\d+$")
_NVME_PARTITION = re.compile(r"^(nvme\d+n\d+)p\d+$")
_VIRTUAL_DISK = ("loop", "ram", "fd", "sr", "zram")


@dataclass
class ParsedSadf:
    samples: list[dict]
    restarts: list[dict]


def parse_sadf(document: dict, zone: tzinfo) -> ParsedSadf:
    hosts = ((document or {}).get("sysstat") or {}).get("hosts") or []
    samples: list[dict] = []
    restarts: list[dict] = []
    if isinstance(hosts, dict):
        hosts = [hosts]
    for host in hosts:
        if not isinstance(host, dict):
            continue
        cpu_count = host.get("number-of-cpus")
        try:
            cpu_count = int(cpu_count) if cpu_count is not None else None
        except (TypeError, ValueError):
            cpu_count = None
        for item in host.get("restarts") or []:
            restart = _restart(item, zone)
            if restart:
                restarts.append(restart)
        for record in host.get("statistics") or []:
            sample = _sample(record, zone, cpu_count)
            if sample:
                samples.append(sample)
    return ParsedSadf(samples=samples, restarts=restarts)


def prune_idle(samples: list[dict]) -> tuple[list[dict], list[str], list[str]]:
    """Drop devices that never moved, unless that would leave the series empty."""
    samples, idle_disks = _prune_group(
        samples, "disk", ("read_kb_s", "write_kb_s", "util_pct", "tps")
    )
    samples, idle_ifaces = _prune_group(samples, "net", ("rx_kb_s", "tx_kb_s"))
    return samples, idle_disks, idle_ifaces


def _sample(record: dict, zone: tzinfo, cpu_count: int | None) -> dict | None:
    if not isinstance(record, dict):
        return None
    stamp = _timestamp(record.get("timestamp") or {}, zone)
    if stamp is None:
        return None
    interval = _float((record.get("timestamp") or {}).get("interval"))
    if interval == 0:
        return None
    cpu = _cpu(record.get("cpu-load") or record.get("cpu_load"))
    memory = record.get("memory") if isinstance(record.get("memory"), dict) else {}
    swap_block = record.get("swap") if isinstance(record.get("swap"), dict) else {}
    queue = record.get("queue") if isinstance(record.get("queue"), dict) else {}
    mem = {
        "used_kb": _kb(memory, "memused", "kbmemused"),
        "free_kb": _kb(memory, "memfree", "kbmemfree"),
        "avail_kb": _kb(memory, "avail", "kbavail", "kbmemavail"),
        "used_pct": _pct(memory, "memused-percent", "%memused"),
    }
    swap = {
        "used_kb": _kb(memory, "swpused", "kbswpused") if _has(memory, "swpused", "kbswpused") else _kb(swap_block, "swpused", "kbswpused"),
        "free_kb": _kb(memory, "swpfree", "kbswpfree") if _has(memory, "swpfree", "kbswpfree") else _kb(swap_block, "swpfree", "kbswpfree"),
        "used_pct": _pct(memory, "swpused-percent", "%swpused")
        if _has(memory, "swpused-percent", "%swpused")
        else _pct(swap_block, "swpused-percent", "%swpused"),
    }
    load = {
        "l1": _float(_first(queue, "ldavg-1")),
        "l5": _float(_first(queue, "ldavg-5")),
        "l15": _float(_first(queue, "ldavg-15")),
    }
    disk = _disks(record.get("disk") or record.get("disk-device") or [])
    net = _ifaces(record.get("network"))
    if cpu is None and all(value is None for value in (*mem.values(), *swap.values(), *load.values())) and not disk and not net:
        return None
    epoch, iso, local_date = stamp
    return {
        "epoch": epoch,
        "iso": iso,
        "local_date": local_date,
        "interval": interval,
        "cpu_count": cpu_count,
        "cpu": cpu or {key: None for key in ("user", "nice", "system", "iowait", "steal", "idle")},
        "mem": mem,
        "swap": swap,
        "load": load,
        "disk": disk,
        "net": net,
    }


def _cpu(entries: object) -> dict | None:
    if not isinstance(entries, list) or not entries:
        return None
    chosen = None
    individuals: list[dict] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        label = str(entry.get("cpu", "")).lower()
        if label == "all":
            chosen = entry
            break
        if label not in {"", "-1"}:
            individuals.append(entry)
    if chosen is None and individuals:
        chosen = _average_cpu(individuals)
    if chosen is None:
        return None
    user = _metric(chosen, "usr", "user")
    nice = _metric(chosen, "nice") or 0.0
    iowait = _metric(chosen, "iowait") or 0.0
    steal = _metric(chosen, "steal") or 0.0
    idle = _metric(chosen, "idle")
    # sadf -u ALL splits classic %system into sys + irq + soft.
    if "sys" in chosen:
        system = round(
            float(chosen.get("sys") or 0) + float(chosen.get("irq") or 0) + float(chosen.get("soft") or 0),
            2,
        )
    else:
        system = _metric(chosen, "system", "sys")
    return {
        "user": user,
        "nice": round(nice, 2),
        "system": system,
        "iowait": round(iowait, 2),
        "steal": round(steal, 2),
        "idle": idle,
    }


def _average_cpu(entries: list[dict]) -> dict:
    keys = ("usr", "user", "nice", "sys", "system", "iowait", "steal", "irq", "soft", "idle")
    averaged: dict = {"cpu": "all"}
    for key in keys:
        values = [float(entry[key]) for entry in entries if key in entry and entry[key] is not None]
        if values:
            averaged[key] = sum(values) / len(values)
    return averaged


def _disks(entries: object) -> dict:
    if isinstance(entries, dict):
        entries = [entries]
    if not isinstance(entries, list):
        return {}
    devices: dict[str, dict] = {}
    names: list[str] = []
    parsed: list[tuple[str, dict]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = str(_first(entry, "disk-device", "disk", "dev") or "")
        if not name or name.startswith(_VIRTUAL_DISK):
            continue
        parsed.append((name, entry))
        names.append(name)
    present = set(names)
    for name, entry in parsed:
        if _is_partition(name, present):
            continue
        devices[name] = {
            "read_kb_s": _rate(entry, "rkB", "rkB/s", "kB_rd/s"),
            "write_kb_s": _rate(entry, "wkB", "wkB/s", "kB_wr/s"),
            "util_pct": _pct(entry, "util-percent", "%util"),
            "tps": _float(_first(entry, "tps")),
        }
    return devices


def _ifaces(network: object) -> dict:
    entries: list = []
    if isinstance(network, dict):
        raw = network.get("net-dev") or network.get("net_dev") or []
        if isinstance(raw, list):
            entries = raw
    elif isinstance(network, list):
        entries = network
    ifaces: dict[str, dict] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = str(_first(entry, "iface", "interface") or "")
        if not name or name == "lo" or name.startswith("lo"):
            continue
        ifaces[name] = {
            "rx_kb_s": _rate(entry, "rxkB", "rxkB/s"),
            "tx_kb_s": _rate(entry, "txkB", "txkB/s"),
        }
    return ifaces


def _is_partition(name: str, present: set[str]) -> bool:
    match = _PARTITION.fullmatch(name) or _NVME_PARTITION.fullmatch(name)
    return bool(match and match.group(1) in present)


def _timestamp(raw: dict, zone: tzinfo) -> tuple[float, str, str] | None:
    if not isinstance(raw, dict) or "date" not in raw or "time" not in raw:
        return None
    text = str(raw["time"])
    if len(text) == 5:
        text = text + ":00"
    try:
        naive = datetime.strptime(f"{raw['date']} {text}", "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    if int(raw.get("utc") or 0) == 1:
        aware = naive.replace(tzinfo=timezone.utc).astimezone(zone)
    else:
        aware = naive.replace(tzinfo=zone)
    return aware.timestamp(), aware.isoformat(timespec="seconds"), aware.date().isoformat()


def _restart(item: object, zone: tzinfo) -> dict | None:
    if not isinstance(item, dict):
        return None
    raw = item.get("timestamp") if isinstance(item.get("timestamp"), dict) else item
    stamp = _timestamp(raw, zone)
    if stamp is None:
        return None
    epoch, iso, local_date = stamp
    return {"epoch": epoch, "iso": iso, "local_date": local_date}


def _prune_group(samples: list[dict], group: str, fields: tuple[str, ...]) -> tuple[list[dict], list[str]]:
    names: list[str] = []
    seen: set[str] = set()
    for sample in samples:
        for name in sample.get(group, {}):
            if name not in seen:
                seen.add(name)
                names.append(name)
    active: list[str] = []
    idle: list[str] = []
    for name in names:
        busy = False
        for sample in samples:
            device = sample.get(group, {}).get(name) or {}
            if any((device.get(field) or 0) != 0 for field in fields):
                busy = True
                break
        (active if busy else idle).append(name)
    idle.sort()
    if not active:
        return samples, []
    for sample in samples:
        bucket = sample.get(group)
        if isinstance(bucket, dict):
            for name in idle:
                bucket.pop(name, None)
    return samples, idle


def _metric(entry: dict, *keys: str) -> float | None:
    value = _first(entry, *keys)
    if value is None:
        return None
    return round(float(value), 2)


def _rate(entry: dict, *keys: str) -> float | None:
    value = _float(_first(entry, *keys))
    if value is None:
        return None
    return round(value, 2)


def _pct(entry: dict, *keys: str) -> float | None:
    value = _float(_first(entry, *keys))
    if value is None:
        return None
    return round(value, 2)


def _kb(entry: dict, *keys: str):
    value = _float(_first(entry, *keys))
    if value is None:
        return None
    if value.is_integer():
        return int(value)
    return value


def _has(entry: dict, *keys: str) -> bool:
    return _first(entry, *keys) is not None


def _first(entry: dict, *keys: str):
    for key in keys:
        if key in entry and entry[key] is not None:
            return entry[key]
    return None


def _float(value) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
