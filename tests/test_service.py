import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from sarview.cache import DiskCache
from sarview.demo import DemoSource
from sarview.service import MonitorService
from sarview.source import Probe, RemoteFile
from sarview.window import filter_samples

ZONE = ZoneInfo("Asia/Kolkata")


class WindowTests(unittest.TestCase):
    def test_minute_window_keeps_each_raw_sample(self):
        samples = [
            _at(7, 59, 59, 1),
            _at(8, 0, 1, 2),
            _at(8, 5, 0, 3),
            _at(8, 15, 7, 4),
            _at(8, 16, 0, 5),
        ]
        chosen = filter_samples(samples, ZONE, "08:00:00", "08:15:00")
        self.assertEqual([sample["cpu"]["user"] for sample in chosen], [2, 3, 4])
        self.assertIs(chosen[0], samples[1])
        self.assertIs(chosen[2], samples[3])
        exact = filter_samples(samples, ZONE, "08:00:00", "08:15:06")
        self.assertEqual([sample["cpu"]["user"] for sample in exact], [2, 3])


class ServiceTests(unittest.TestCase):
    def test_demo_window_is_not_aggregated(self):
        with tempfile.TemporaryDirectory() as directory:
            service = _service(DemoSource(), directory)
            day = service.get_day("2026-09-28", start="08:00:00", end="08:15:00")
        self.assertEqual(day["timezone"], "Asia/Kolkata")
        self.assertEqual(day["offset_minutes"], 330)
        self.assertEqual([sample["cpu"]["user"] for sample in day["samples"]], [4.0, 72.0, 72.0, 72.0])
        self.assertTrue(all(sample["interval"] == 300 for sample in day["samples"]))
        self.assertNotIn("loop0", day["samples"][0]["disk"])
        self.assertNotIn("sdb", day["samples"][0]["disk"])
        self.assertIn("sda", day["samples"][0]["disk"])
        self.assertNotIn("lo", day["samples"][0]["net"])
        self.assertIn("eth0", day["samples"][0]["net"])
        self.assertEqual(day["restarts"][0]["iso"], "2026-09-28T07:30:00+05:30")

    def test_cache_avoids_a_second_decode(self):
        clock = {"t": 1_000_000.0}
        source = CountingSource(DemoSource())
        with tempfile.TemporaryDirectory() as directory:
            cache = DiskCache(Path(directory), "myopip")
            first = _service(source, cache, clock)
            first.get_day("2026-09-28")
            self.assertEqual(source.probes, 1)
            self.assertEqual(source.fetches, 1)

            clock["t"] += 10
            second = _service(source, cache, clock)
            cached = second.get_day("2026-09-28")
            self.assertEqual(source.probes, 1)
            self.assertEqual(source.fetches, 1)
            self.assertEqual(cached["network"], "none")

            clock["t"] += 500
            third = _service(source, cache, clock)
            checked = third.get_day("2026-09-28")
            self.assertEqual(source.probes, 2)
            self.assertEqual(source.fetches, 1)
            self.assertEqual(checked["network"], "catalog")

            source.inner.probe_result.files[0].mtime += 5
            clock["t"] += 500
            fourth = _service(source, cache, clock)
            refreshed = fourth.get_day("2026-09-28")
            self.assertEqual(source.fetches, 2)
            self.assertEqual(refreshed["network"], "decode")

    def test_utc_file_splits_across_kolkata_dates(self):
        mtime = int(datetime(2026, 9, 28, 5, 20, 1, tzinfo=ZONE).timestamp())
        remote = RemoteFile("sa27", 10, mtime, "2026-09-27", "UTC")
        document = {
            "sysstat": {
                "hosts": [
                    {
                        "number-of-cpus": 1,
                        "statistics": [
                            _stat("2026-09-27", "12:00:00", 1, 22),
                            _stat("2026-09-27", "23:50:01", 1, 11),
                        ],
                    }
                ]
            }
        }
        source = FixedSource(Probe("Asia/Kolkata", "+0530", "myopip", [remote]), {"sa27": document})
        with tempfile.TemporaryDirectory() as directory:
            service = _service(source, directory)
            morning = service.get_day("2026-09-28")
            previous = service.get_day("2026-09-27")
        self.assertEqual([sample["cpu"]["user"] for sample in morning["samples"]], [11.0])
        self.assertEqual(morning["samples"][0]["iso"], "2026-09-28T05:20:01+05:30")
        self.assertEqual([sample["cpu"]["user"] for sample in previous["samples"]], [22.0])

    def test_dated_filename_wins_a_duplicate_timestamp(self):
        mtime = int(datetime(2026, 9, 28, 10, 0, tzinfo=ZONE).timestamp())
        older = RemoteFile("sa28", 1, mtime, "2026-09-28", "UTC")
        newer = RemoteFile("sa20260928", 2, mtime, "2026-09-28", "UTC")
        source = FixedSource(
            Probe("Asia/Kolkata", "+0530", "myopip", [newer, older]),
            {
                "sa28": _host(_stat("2026-09-28", "08:25:07", 0, 1)),
                "sa20260928": _host(_stat("2026-09-28", "08:25:07", 0, 9)),
            },
        )
        with tempfile.TemporaryDirectory() as directory:
            day = _service(source, directory).get_day("2026-09-28")
        self.assertEqual(len(day["samples"]), 1)
        self.assertEqual(day["samples"][0]["cpu"]["user"], 9.0)


class CountingSource:
    remote = True
    host = "myopip"

    def __init__(self, inner):
        self.inner = inner
        self.probes = 0
        self.fetches = 0

    def probe(self):
        self.probes += 1
        return self.inner.probe()

    def fetch_files(self, names):
        self.fetches += 1
        return self.inner.fetch_files(names)


class FixedSource:
    remote = True
    host = "myopip"

    def __init__(self, probe, documents):
        self._probe = probe
        self._documents = documents

    def probe(self):
        return self._probe

    def fetch_files(self, names):
        return {name: self._documents[name] for name in names}


def _service(source, cache, clock=None):
    if isinstance(cache, (str, Path)):
        cache = DiskCache(Path(cache), getattr(source, "host", "demo"))
    now = (lambda: clock["t"]) if clock else None
    return MonitorService(source, cache, catalog_ttl=120, now=now, log=lambda *_args, **_kwargs: None)


def _at(hour, minute, second, user):
    moment = datetime(2026, 9, 28, hour, minute, second, tzinfo=ZONE)
    return {"epoch": moment.timestamp(), "iso": moment.isoformat(), "cpu": {"user": user}}


def _stat(day, time, utc, user):
    return {
        "timestamp": {"date": day, "time": time, "utc": utc, "interval": 300},
        "cpu-load": [{"cpu": "all", "usr": user, "nice": 0, "sys": 1, "iowait": 0, "steal": 0, "idle": 99}],
        "memory": {"memfree": 10, "avail": 20, "memused": 30, "memused-percent": 75, "swpfree": 5, "swpused": 0, "swpused-percent": 0},
        "queue": {"ldavg-1": 0.1, "ldavg-5": 0.2, "ldavg-15": 0.3},
        "disk": [{"disk-device": "sda", "rkB": 1, "wkB": 2, "util-percent": 1, "tps": 1}],
        "network": {"net-dev": [{"iface": "eth0", "rxkB": 3, "txkB": 4}, {"iface": "lo", "rxkB": 1, "txkB": 1}]},
    }


def _host(statistic):
    return {"sysstat": {"hosts": [{"number-of-cpus": 2, "statistics": [statistic]}]}}


if __name__ == "__main__":
    unittest.main()
