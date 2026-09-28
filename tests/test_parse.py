import json
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from sarview.parse import parse_sadf, prune_idle

ZONE = ZoneInfo("Asia/Kolkata")
FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "one_sample.json").read_text())


class ParseTests(unittest.TestCase):
    def test_live_sadf_sample_keeps_original_values(self):
        parsed = parse_sadf(FIXTURE, ZONE)
        self.assertEqual(len(parsed.samples), 1)
        sample = parsed.samples[0]
        self.assertEqual(sample["iso"], "2026-09-28T08:25:07+05:30")
        expected = datetime(2026, 9, 28, 8, 25, 7, tzinfo=ZONE).timestamp()
        self.assertEqual(sample["epoch"], expected)
        self.assertEqual(sample["interval"], 306)
        self.assertEqual(sample["cpu_count"], 2)
        self.assertEqual(sample["cpu"]["user"], 10.26)
        self.assertEqual(sample["cpu"]["nice"], 0.86)
        self.assertEqual(sample["cpu"]["system"], 2.28)
        self.assertEqual(sample["cpu"]["iowait"], 0.16)
        self.assertEqual(sample["cpu"]["steal"], 0.09)
        self.assertEqual(sample["cpu"]["idle"], 86.35)
        self.assertEqual(sample["mem"]["used_kb"], 1323784)
        self.assertEqual(sample["mem"]["free_kb"], 1291792)
        self.assertEqual(sample["mem"]["avail_kb"], 2338728)
        self.assertEqual(sample["mem"]["used_pct"], 33.01)
        self.assertEqual(sample["swap"]["used_kb"], 0)
        self.assertEqual(sample["swap"]["free_kb"], 507900)
        self.assertEqual(sample["swap"]["used_pct"], 0.0)
        self.assertEqual(sample["load"], {"l1": 0.02, "l5": 0.22, "l15": 0.16})
        self.assertNotIn("loop0", sample["disk"])
        self.assertNotIn("sda1", sample["disk"])
        self.assertEqual(sample["disk"]["sda"]["read_kb_s"], 134.25)
        self.assertEqual(sample["disk"]["sda"]["write_kb_s"], 477.22)
        self.assertNotIn("lo", sample["net"])
        self.assertEqual(sample["net"]["eth0"], {"rx_kb_s": 2.39, "tx_kb_s": 1.96})

    def test_utc_timestamp_converts_into_kolkata(self):
        document = _document(
            [
                {
                    "timestamp": {"date": "2026-09-27", "time": "23:50:01", "utc": 1, "interval": 600},
                    "cpu-load": [{"cpu": "all", "user": 3.5, "nice": 0, "system": 1, "iowait": 0.2, "steal": 0, "idle": 95.3}],
                }
            ]
        )
        sample = parse_sadf(document, ZONE).samples[0]
        self.assertEqual(sample["iso"], "2026-09-28T05:20:01+05:30")
        self.assertEqual(sample["local_date"], "2026-09-28")
        self.assertEqual(sample["interval"], 600)
        self.assertEqual(sample["cpu"]["system"], 1.0)

    def test_classic_system_is_not_added_twice(self):
        document = _document(
            [
                {
                    "timestamp": {"date": "2026-09-28", "time": "08:00:00", "utc": 0, "interval": 300},
                    "cpu-load": [{"cpu": "all", "user": 10, "nice": 0, "system": 2.28, "iowait": 0.1, "steal": 0, "idle": 87.62}],
                }
            ]
        )
        cpu = parse_sadf(document, ZONE).samples[0]["cpu"]
        self.assertEqual(cpu["system"], 2.28)
        self.assertEqual(cpu["user"], 10.0)

    def test_kb_field_aliases_and_restart(self):
        document = _document(
            [
                {
                    "timestamp": {"date": "2026-09-28", "time": "01:00:00", "utc": 0, "interval": 300},
                    "memory": {"kbmemused": 2048, "kbmemfree": 1024, "kbavail": 1500, "%memused": 66.6},
                    "swap": {"kbswpused": 10, "kbswpfree": 90, "%swpused": 10},
                }
            ]
        )
        document["sysstat"]["hosts"][0]["restarts"] = [{"date": "2026-09-28", "time": "00:05:00", "utc": 0}]
        parsed = parse_sadf(document, ZONE)
        memory = parsed.samples[0]["mem"]
        self.assertEqual(memory["used_kb"], 2048)
        self.assertEqual(memory["avail_kb"], 1500)
        self.assertEqual(parsed.samples[0]["swap"]["used_pct"], 10.0)
        self.assertEqual(parsed.restarts[0]["iso"], "2026-09-28T00:05:00+05:30")

    def test_idle_device_is_removed_only_when_another_disk_is_active(self):
        samples, idle_disks, idle_ifaces = prune_idle(parse_sadf(FIXTURE, ZONE).samples)
        self.assertEqual(idle_disks, ["sdb"])
        self.assertEqual(idle_ifaces, [])
        self.assertIn("sda", samples[0]["disk"])
        self.assertNotIn("sdb", samples[0]["disk"])

    def test_ten_minute_sample_is_not_split(self):
        document = _document(
            [
                {
                    "timestamp": {"date": "2026-09-28", "time": "08:00:01", "utc": 0, "interval": 600},
                    "cpu-load": [{"cpu": "all", "usr": 1, "sys": 1, "idle": 98}],
                },
                {
                    "timestamp": {"date": "2026-09-28", "time": "08:10:01", "utc": 0, "interval": 600},
                    "cpu-load": [{"cpu": "all", "usr": 9, "sys": 1, "idle": 90}],
                },
            ]
        )
        samples = parse_sadf(document, ZONE).samples
        self.assertEqual([sample["interval"] for sample in samples], [600, 600])
        self.assertEqual([sample["cpu"]["user"] for sample in samples], [1.0, 9.0])


def _document(statistics):
    return {
        "sysstat": {
            "hosts": [
                {
                    "number-of-cpus": 2,
                    "statistics": statistics,
                }
            ]
        }
    }


if __name__ == "__main__":
    unittest.main()
