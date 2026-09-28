"""Built-in day used by --demo and the tests. No SSH."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sarview.source import Probe, RemoteFile

ZONE = ZoneInfo("Asia/Kolkata")
DAY = "2026-09-28"


def build_demo() -> tuple[Probe, dict[str, dict]]:
    end = datetime(2026, 9, 28, 9, 0, tzinfo=ZONE)
    remote = RemoteFile(
        name="sa20260928",
        size=100,
        mtime=int(end.timestamp()),
        file_date="2026-09-28",
        file_timezone="UTC",
    )
    probe = Probe(
        timezone="Asia/Kolkata",
        utc_offset="+0530",
        hostname="demo",
        files=[remote],
    )
    return probe, {"sa20260928": _document()}


def _document() -> dict:
    start = datetime(2026, 9, 28, 7, 0, 0)
    statistics = []
    for index in range(25):
        current = start + timedelta(minutes=5 * index)
        spike = current.hour == 8 and current.minute in (5, 10, 15)
        user = 72.0 if spike else 4.0
        system = 8.0 if spike else 1.0
        iowait = 18.0 if spike else 0.2
        steal = 0.2
        nice = 0.1
        idle = round(100 - user - system - iowait - steal - nice, 2)
        used_pct = 88.0 if spike else 30.0
        total_kb = 4 * 1024 * 1024
        used_kb = int(round(total_kb * used_pct / 100))
        avail_kb = int(round(total_kb * (0.20 if spike else 0.80)))
        swap_total = 512 * 1024
        swap_used = 64 * 1024 if spike else 0
        statistics.append(
            {
                "timestamp": {
                    "date": DAY,
                    "time": current.strftime("%H:%M:%S"),
                    "utc": 0,
                    "interval": 300,
                },
                "cpu-load": [
                    {
                        "cpu": "all",
                        "usr": user,
                        "nice": nice,
                        "sys": system,
                        "iowait": iowait,
                        "steal": steal,
                        "irq": 0.0,
                        "soft": 0.0,
                        "idle": idle,
                    }
                ],
                "memory": {
                    "memfree": total_kb - used_kb,
                    "avail": avail_kb,
                    "memused": used_kb,
                    "memused-percent": used_pct,
                    "swpfree": swap_total - swap_used,
                    "swpused": swap_used,
                    "swpused-percent": round(100 * swap_used / swap_total, 2),
                },
                "queue": {
                    "ldavg-1": 3.5 if spike else 0.2,
                    "ldavg-5": 2.4 if spike else 0.15,
                    "ldavg-15": 1.2 if spike else 0.1,
                },
                "disk": [
                    {
                        "disk-device": "loop0",
                        "tps": 0,
                        "rkB": 0,
                        "wkB": 0,
                        "util-percent": 0,
                    },
                    {
                        "disk-device": "sda",
                        "tps": 400 if spike else 20,
                        "rkB": 8000 if spike else 100,
                        "wkB": 12000 if spike else 200,
                        "util-percent": 72 if spike else 1.2,
                    },
                    {
                        "disk-device": "sdb",
                        "tps": 0,
                        "rkB": 0,
                        "wkB": 0,
                        "util-percent": 0,
                    },
                ],
                "network": {
                    "net-dev": [
                        {"iface": "lo", "rxkB": 5, "txkB": 5},
                        {
                            "iface": "eth0",
                            "rxkB": 4000 if spike else 10,
                            "txkB": 1500 if spike else 8,
                        },
                    ]
                },
            }
        )
    return {
        "sysstat": {
            "hosts": [
                {
                    "nodename": "demo",
                    "number-of-cpus": 2,
                    "file-date": DAY,
                    "timezone": "UTC",
                    "statistics": statistics,
                    "restarts": [{"date": DAY, "time": "07:30:00", "utc": 0}],
                }
            ]
        }
    }


class DemoSource:
    remote = False
    host = "demo"

    def __init__(self):
        self.probe_result, self.docs = build_demo()

    def probe(self) -> Probe:
        return self.probe_result

    def fetch_files(self, names: list[str]) -> dict[str, dict]:
        missing = [name for name in names if name not in self.docs]
        if missing:
            from sarview.errors import SarviewError

            raise SarviewError(f"demo data has no {', '.join(missing)}", status=404)
        return {name: self.docs[name] for name in names}
